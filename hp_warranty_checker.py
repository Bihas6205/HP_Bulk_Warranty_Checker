"""
HP Warranty Bulk Checker (original CLI version)
================================================
NOTE: There's now a web UI for this (app.py + warranty_engine.py) built to
run inside GitHub Codespaces headlessly, with live progress in the browser
instead of a visible Chrome window. See README.md "Web UI (Codespaces)".
This file is kept as-is for anyone who wants to run it headful, locally,
with the original CLI/manual CAPTCHA-solving flow.
========================
Reads laptop serial numbers from an Excel file, looks each one up on
HP's warranty page using a real automated browser (Playwright), and
writes the warranty start/end dates to a results Excel file.

HOW IT WORKS (the big picture):
  1. pandas reads your input Excel  ->  a list of serial numbers
  2. Playwright opens a real Chrome window (visible, so HP's bot
     detection is less suspicious and YOU can solve a CAPTCHA if one
     appears)
  3. For each serial: type it in, submit, wait for the result page,
     and pull the dates out of the page text
  4. Results are saved to Excel after EVERY serial, so if the script
     crashes at #57 of 400, you keep the first 56 rows.

USAGE:
  1. Put your serials in serials.xlsx (column name: "Serial Number",
     optional column: "Product Number" for recycled serials)
  2. pip install pandas openpyxl playwright
     playwright install chromium
  3. python hp_warranty_checker.py
"""

import random
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

# ----------------------------- CONFIG ---------------------------------
INPUT_FILE = "serials.xlsx"          # your input file (.xlsx or .csv)
OUTPUT_FILE = "warranty_results.xlsx"
WARRANTY_URL = "https://support.hp.com/us-en/check-warranty"
# Change to your region if needed, e.g. "https://support.hp.com/in-en/check-warranty"

MIN_DELAY, MAX_DELAY = 8, 15   # seconds to wait between lookups.
# Why the random delay? Hitting a site every 2 seconds like a machine
# is the #1 way to get blocked. Random 8-15s looks like a bored human.

HEADLESS = False  # Keep False! Visible browser = fewer bot blocks,
                  # and you can manually solve a CAPTCHA if one pops up.
# -----------------------------------------------------------------------


def read_serials(path: str) -> pd.DataFrame:
    """Load serials from Excel/CSV into a DataFrame."""
    p = Path(path)
    if not p.exists():
        raise SystemExit(
            f"Input file '{path}' not found. Create it with a column "
            f"named 'Serial Number' (one serial per row)."
        )
    df = pd.read_csv(p) if p.suffix.lower() == ".csv" else pd.read_excel(p)
    # Normalise column names: " serial number " -> "serial number"
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "serial number" not in df.columns:
        raise SystemExit(
            f"Couldn't find a 'Serial Number' column. Found: {list(df.columns)}"
        )
    df["serial number"] = df["serial number"].astype(str).str.strip().str.upper()
    df = df[df["serial number"].ne("") & df["serial number"].ne("NAN")]
    return df.reset_index(drop=True)


# --- Date extraction ----------------------------------------------------
# Instead of relying on fragile CSS selectors (HP changes their HTML
# often), we grab ALL the visible text of the result page and use
# regular expressions to find lines like:
#     "Coverage start date  October 12, 2024"
#     "End date: 2027-10-11"
# This survives most website redesigns.

DATE_PATTERN = (
    r"("
    r"[A-Z][a-z]+ \d{1,2},? \d{4}"      # October 12, 2024
    r"|\d{1,2} [A-Z][a-z]+,? \d{4}"     # 12 October 2024
    r"|\d{4}-\d{2}-\d{2}"               # 2024-10-12
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"   # 12/10/2024
    r")"
)

def extract_dates(page_text: str) -> dict:
    """Pull start/end dates + status out of the raw page text."""
    result = {"start_date": None, "end_date": None, "status": None, "product": None}

    start_m = re.search(r"[Ss]tart\s*[Dd]ate\s*:?\s*" + DATE_PATTERN, page_text)
    end_m = re.search(r"[Ee]nd\s*[Dd]ate\s*:?\s*" + DATE_PATTERN, page_text)
    if start_m:
        result["start_date"] = start_m.group(1)
    if end_m:
        result["end_date"] = end_m.group(1)

    # Warranty status keywords
    if re.search(r"expired", page_text, re.I):
        result["status"] = "Expired"
    elif re.search(r"active|in warranty|covered", page_text, re.I):
        result["status"] = "Active"

    return result


def lookup_serial(page, serial: str, product_number: str | None) -> dict:
    """Look up ONE serial number and return a result dict."""
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

    # Cookie banner: decline non-essential cookies if the banner shows up.
    try:
        page.locator(
            "button:has-text('Reject'), button:has-text('Decline'), "
            "#onetrust-reject-all-handler"
        ).first.click(timeout=4000)
    except PWTimeout:
        pass  # no banner — fine

    # Find the serial number input box. We try a few likely selectors
    # because HP renames IDs from time to time.
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
        page.screenshot(path=f"debug_{serial}.png")
        return row

    input_box.fill(serial)
    time.sleep(random.uniform(0.5, 1.5))  # tiny human-like pause

    # Submit (button text/id also varies)
    for sel in ["#FindMyProduct", "button:has-text('Submit')", "button:has-text('Check')"]:
        try:
            page.locator(sel).first.click(timeout=3000)
            break
        except PWTimeout:
            continue

    # Wait for the result content to load
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PWTimeout:
        pass
    time.sleep(3)  # give client-side rendering a moment

    body_text = page.inner_text("body")

    # Case: recycled serial needs a product number too
    if "product number" in body_text.lower() and "cannot be identified" in body_text.lower():
        if product_number:
            try:
                page.locator("input").nth(1).fill(product_number)
                page.locator("button:has-text('Submit')").first.click()
                page.wait_for_load_state("networkidle", timeout=30000)
                time.sleep(3)
                body_text = page.inner_text("body")
            except Exception:
                row["Notes"] = "Product number step failed"
                return row
        else:
            row["Notes"] = "HP asked for a Product Number (recycled serial) — add it to the input file"
            return row

    # Possible CAPTCHA / bot block: pause and let the human solve it
    if re.search(r"captcha|access denied|verify you are", body_text, re.I):
        print(f"\n  ⚠️  CAPTCHA or block detected for {serial}.")
        input("  Solve it in the browser window, then press Enter here to continue... ")
        time.sleep(2)
        body_text = page.inner_text("body")

    parsed = extract_dates(body_text)
    row["Warranty Start Date"] = parsed["start_date"] or ""
    row["Warranty End Date"] = parsed["end_date"] or ""
    row["Status"] = parsed["status"] or ""

    # Try to grab the product name from the page heading
    try:
        heading = page.locator("h1, h2").first.inner_text(timeout=3000).strip()
        if heading and "warranty" not in heading.lower():
            row["Product"] = heading
    except Exception:
        pass

    if not parsed["start_date"] and not parsed["end_date"]:
        row["Notes"] = "No dates found — see screenshot"
        page.screenshot(path=f"debug_{serial}.png")

    return row


def main():
    df = read_serials(INPUT_FILE)
    serials = df["serial number"].tolist()
    product_numbers = (
        df["product number"].astype(str).str.strip().tolist()
        if "product number" in df.columns
        else [None] * len(serials)
    )
    print(f"Loaded {len(serials)} serial numbers from {INPUT_FILE}")

    # Resume support: skip serials already in the output file
    done = set()
    results = []
    if Path(OUTPUT_FILE).exists():
        prev = pd.read_excel(OUTPUT_FILE)
        results = prev.to_dict("records")
        done = set(prev["Serial Number"].astype(str))
        print(f"Resuming — {len(done)} serials already done.")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        page = context.new_page()

        for i, serial in enumerate(serials, 1):
            if serial in done:
                continue
            pn = product_numbers[i - 1]
            pn = None if pn in (None, "", "nan", "NAN") else pn
            print(f"[{i}/{len(serials)}] Checking {serial} ...", end=" ", flush=True)

            try:
                row = lookup_serial(page, serial, pn)
            except Exception as e:
                row = {
                    "Serial Number": serial, "Product": "",
                    "Warranty Start Date": "", "Warranty End Date": "",
                    "Status": "", "Notes": f"Error: {e}",
                    "Checked At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            print(row["Warranty End Date"] or row["Notes"] or "done")

            results.append(row)
            # Save after EVERY lookup — crash-safe progress
            pd.DataFrame(results).to_excel(OUTPUT_FILE, index=False)

            if i < len(serials):
                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        browser.close()

    print(f"\n✅ Done. Results saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
