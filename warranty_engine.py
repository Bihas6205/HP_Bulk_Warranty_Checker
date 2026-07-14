"""
warranty_engine.py
===================
Core scraping logic for the HP Bulk Warranty Checker, refactored out of
hp_warranty_checker.py so it can be driven by the web UI (app.py) instead
of only running as a standalone CLI script.

Changes from the original CLI version, specifically for running inside
GitHub Codespaces (a headless container with no monitor):

  - HEADLESS is always True. There is no display to show a Chrome window
    on, so Playwright runs Chromium in headless mode.
  - The original script paused on `input()` when it hit a CAPTCHA, so a
    human could solve it in the visible browser. That's not possible
    headless, and it would freeze the web server. Instead, if a CAPTCHA
    or block is detected, we wait 25s (in case it was a transient bot
    check) and try to read the page again. If it still looks blocked, we
    log a note on that row and move to the next serial rather than
    hanging forever.
  - WARRANTY_URL defaults to the India region (support.hp.com/in-en/...),
    which requires explicitly clicking the country dropdown and selecting
    "India" even though it visually appears selected by default.
  - Progress is reported through a callback instead of print(), so the
    Flask app can push live updates to the browser.
"""

import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

WARRANTY_URL = "https://support.hp.com/in-en/check-warranty"
MIN_DELAY, MAX_DELAY = 8, 15
HEADLESS = True  # must stay True in Codespaces - no display available

DATE_PATTERN = (
    r"("
    r"[A-Z][a-z]+ \d{1,2},? \d{4}"
    r"|\d{1,2} [A-Z][a-z]+,? \d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r")"
)


def read_serials(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Input file '{path}' not found.")
    df = pd.read_csv(p) if p.suffix.lower() == ".csv" else pd.read_excel(p)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "serial number" not in df.columns:
        raise SystemExit(
            f"Couldn't find a 'Serial Number' column. Found: {list(df.columns)}"
        )
    df["serial number"] = df["serial number"].astype(str).str.strip().str.upper()
    df = df[df["serial number"].ne("") & df["serial number"].ne("NAN")]
    return df.reset_index(drop=True)


def extract_dates(page_text: str) -> dict:
    result = {"start_date": None, "end_date": None, "status": None}
    start_m = re.search(r"[Ss]tart\s*[Dd]ate\s*:?\s*" + DATE_PATTERN, page_text)
    end_m = re.search(r"[Ee]nd\s*[Dd]ate\s*:?\s*" + DATE_PATTERN, page_text)
    if start_m:
        result["start_date"] = start_m.group(1)
    if end_m:
        result["end_date"] = end_m.group(1)
    if re.search(r"expired", page_text, re.I):
        result["status"] = "Expired"
    elif re.search(r"active|in warranty|covered", page_text, re.I):
        result["status"] = "Active"
    return result


def select_india_region(page, log):
    """HP shows India as the apparent default but won't register it unless
    you explicitly open the country dropdown and click it."""
    try:
        page.locator("#country-region, [id*='country']").first.click(timeout=4000)
        page.locator("#India, text=India").first.click(timeout=4000)
    except PWTimeout:
        log("Country dropdown not found/needed - continuing.")
    except Exception:
        pass


def expand_result_accordion(page, log):
    """Warranty dates are often hidden inside a collapsed accordion panel
    that has to be expanded before the text is visible in the DOM/inner_text."""
    try:
        panels = page.locator(
            "[class*='accordion'] button, [class*='accordion-header'], "
            "[aria-expanded='false']"
        )
        count = min(panels.count(), 5)
        for i in range(count):
            try:
                panels.nth(i).click(timeout=2000)
                time.sleep(0.3)
            except Exception:
                continue
    except Exception:
        pass


def lookup_serial(page, serial: str, product_number, log) -> dict:
    row = {
        "Serial Number": serial,
        "Product": "",
        "Warranty Start Date": "",
        "Warranty End Date": "",
        "Status": "",
        "Notes": "",
        "Checked At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    page.goto(WARRANTY_URL, wait_until="domcontentloaded", timeout=60000)

    try:
        page.locator(
            "button:has-text('Reject'), button:has-text('Decline'), "
            "#onetrust-reject-all-handler"
        ).first.click(timeout=4000)
    except PWTimeout:
        pass

    select_india_region(page, log)

    input_box = None
    for sel in [
        "#inputtextpfinder",
        "input[name='serialNumber']",
        "input[placeholder*='erial']",
        "input[type='text']",
    ]:
        loc = page.locator(sel).first
        if loc.count() > 0 and loc.is_visible():
            input_box = loc
            break
    if input_box is None:
        row["Notes"] = "Could not find serial input box (page layout changed or bot-blocked)"
        try:
            page.screenshot(path=f"debug_{serial}.png")
        except Exception:
            pass
        return row

    input_box.fill(serial)
    time.sleep(random.uniform(0.5, 1.5))

    for sel in ["#FindMyProduct", "button:has-text('Submit')", "button:has-text('Check')"]:
        try:
            page.locator(sel).first.click(timeout=3000)
            break
        except PWTimeout:
            continue

    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PWTimeout:
        pass
    time.sleep(3)

    expand_result_accordion(page, log)
    body_text = page.inner_text("body")

    # recycled serial -> needs Product Number too
    if "product number" in body_text.lower() and "cannot be identified" in body_text.lower():
        pn = None if product_number in (None, "", "nan", "NAN") else product_number
        if isinstance(pn, float) and pd.isna(pn):
            pn = None
        if pn:
            try:
                page.locator("input").nth(1).fill(str(pn))
                page.locator("button:has-text('Submit')").first.click()
                page.wait_for_load_state("networkidle", timeout=30000)
                time.sleep(3)
                expand_result_accordion(page, log)
                body_text = page.inner_text("body")
            except Exception:
                row["Notes"] = "Product number step failed"
                return row
        else:
            row["Notes"] = "HP asked for a Product Number (recycled serial) - add it to the input file"
            return row

    # CAPTCHA / bot block: headless-safe handling (no input(), can't wait forever)
    if re.search(r"captcha|access denied|verify you are", body_text, re.I):
        log(f"  CAPTCHA/block detected for {serial}. Waiting 25s and retrying once...")
        time.sleep(25)
        try:
            page.reload(wait_until="domcontentloaded", timeout=60000)
            body_text = page.inner_text("body")
        except Exception:
            pass
        if re.search(r"captcha|access denied|verify you are", body_text, re.I):
            row["Notes"] = "Blocked by CAPTCHA/bot-check - could not complete headless. Retry later or from a residential IP."
            try:
                page.screenshot(path=f"debug_{serial}.png")
            except Exception:
                pass
            return row

    parsed = extract_dates(body_text)
    row["Warranty Start Date"] = parsed["start_date"] or ""
    row["Warranty End Date"] = parsed["end_date"] or ""
    row["Status"] = parsed["status"] or ""

    try:
        heading = page.locator("h1, h2").first.inner_text(timeout=3000).strip()
        if heading and "warranty" not in heading.lower():
            row["Product"] = heading
    except Exception:
        pass

    if not parsed["start_date"] and not parsed["end_date"]:
        row["Notes"] = "No dates found - see debug screenshot"
        try:
            page.screenshot(path=f"debug_{serial}.png")
        except Exception:
            pass

    return row


def run_batch(input_path: str, output_xlsx: str, output_csv: str,
              on_progress, on_log, should_stop):
    """
    Runs the full batch. Designed to be called from a background thread.

    on_progress(dict)  - called after every serial with the running state
    on_log(str)        - called with human-readable log lines
    should_stop() -> bool - checked between serials to allow a clean stop
    """
    df = read_serials(input_path)
    serials = df["serial number"].tolist()
    product_numbers = (
        df["product number"].tolist()
        if "product number" in df.columns
        else [None] * len(serials)
    )

    on_log(f"Loaded {len(serials)} serial numbers from {Path(input_path).name}")

    results = []
    done_serials = set()
    if Path(output_xlsx).exists():
        prev = pd.read_excel(output_xlsx)
        results = prev.to_dict("records")
        done_serials = set(prev["Serial Number"].astype(str))
        on_log(f"Resuming - {len(done_serials)} serials already done.")

    def save():
        out_df = pd.DataFrame(results)
        out_df.to_excel(output_xlsx, index=False)
        out_df.to_csv(output_csv, index=False)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="en-IN")
        page = context.new_page()

        total = len(serials)
        for i, serial in enumerate(serials, 1):
            if should_stop():
                on_log("Stop requested - halting after current progress was saved.")
                break
            if serial in done_serials:
                continue

            on_log(f"[{i}/{total}] Checking {serial} ...")
            try:
                row = lookup_serial(page, serial, product_numbers[i - 1], on_log)
            except Exception as e:
                row = {
                    "Serial Number": serial, "Product": "",
                    "Warranty Start Date": "", "Warranty End Date": "",
                    "Status": "", "Notes": f"Error: {e}",
                    "Checked At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }

            on_log(f"  -> {row['Warranty End Date'] or row['Notes'] or 'done'}")
            results.append(row)
            save()

            on_progress({
                "total": total,
                "done": len(results),
                "last_row": row,
            })

            if i < total and not should_stop():
                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        browser.close()

    on_log("Batch finished.")
    return results
