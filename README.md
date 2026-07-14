# HP Warranty Bulk Checker

Check HP laptop/desktop warranty **start and end dates in bulk** from a list of
serial numbers, and get the results in an Excel file.

HP's public warranty page only lets you check one serial at a time (or ~20 via
their multi-product page). This tool automates the lookup using
[Playwright](https://playwright.dev/python/) — a real Chrome browser driven by
Python — and writes everything to `warranty_results.xlsx`.

## Features
- 📥 Reads serials from a simple Excel file
- 📤 Outputs Serial, Product, Warranty Start Date, End Date, Status to Excel
- 💾 **Crash-safe** — saves after every serial; re-running resumes where it stopped
- 🤖 Human-like random delays (8–15 s) to avoid bot-blocking
- 🧩 Handles HP's "recycled serial" case (asks for Product Number)
- 🖼️ Saves a debug screenshot for any serial it couldn't parse

## Web UI (GitHub Codespaces)

There's a browser-based UI on top of the same scraper (`app.py` +
`warranty_engine.py`), built specifically to run inside a Codespace: it
runs Chromium headless (no monitor needed), shows live progress in a
table, and lets you download the results when it's done.

**1. Open the Codespace**
- On the repo page, click the green **Code** button → **Codespaces** tab → **Create codespace on main**.
- Wait for it to finish building (~1-2 min). You'll land in a VS Code-in-browser with a terminal at the bottom.

**2. Install dependencies** (in the Codespace terminal)
```bash
pip install -r requirements.txt
playwright install --with-deps chromium
```
`--with-deps` also installs the system libraries Chromium needs — skip it and headless Chromium will fail to launch on a bare container.

**3. Start the server**
```bash
python app.py
```
You'll see `Running on http://127.0.0.1:5000`.

**4. Open the UI in your browser**
- Codespaces auto-detects port 5000 and shows a popup: click **Open in Browser**.
- If you miss the popup: go to the **Ports** tab (next to Terminal), find port `5000`, and click the globe icon.

**5. Use it**
- Click **Choose serials.xlsx / .csv**, pick your file (needs a `Serial Number` column, optional `Product Number` column), click **Upload**.
- Click **Start batch**. Rows fill in live as each serial is checked (expect ~10-15s per serial — that delay is intentional, don't rush it).
- Click **Stop** any time to pause; progress is saved after every row, so starting again resumes where you left off.
- When done (or partway through), click **Download .xlsx** or **Download .csv**.

**Notes specific to running headless in a Codespace:**
- There's no visible browser window, so if HP shows a CAPTCHA the tool can't pause for you to solve it. It waits 25s and retries once, then logs a note on that row ("Blocked by CAPTCHA/bot-check") and moves on — re-run those specific serials later if that happens a lot.
- Cloud/datacenter IPs (which is what a Codespace runs on) get flagged for CAPTCHAs more often than a home connection. If you see a lot of blocked rows, that's why.
- The uploaded file and results are stored in a `data/` folder inside the Codespace (not committed to git). Download your results before you delete/stop the Codespace, or they're gone with it.

## Setup (original CLI script)

```bash
# clone the repo, then:
cd hp-warranty-checker
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Usage

1. Copy `serials.example.xlsx` to `serials.xlsx` and fill in your serial
   numbers (keep the column name **Serial Number**). The **Product Number**
   column is only needed if HP reports a serial as recycled.
2. If you're not in the US, edit `WARRANTY_URL` at the top of the script,
   e.g. `https://support.hp.com/in-en/check-warranty` for India.
3. Run:
   ```bash
   xvfb-run -a python hp_warranty_checker.py
   ```
4. A Chrome window opens and works through your list. **Stay nearby** — if a
   CAPTCHA appears, solve it in the browser and press Enter in the terminal.
5. Results land in `warranty_results.xlsx`.

⏱️ Expect roughly 10–15 seconds per serial (the delay is intentional —
don't reduce it much or HP will block your IP).

## Troubleshooting

| Problem | Fix |
|---|---|
| Notes says "HP asked for a Product Number" | That serial is recycled — add its product number in the Product Number column and re-run |
| "Could not find serial input box" on every row | HP changed their page HTML. Open the `debug_*.png` screenshot, inspect the input field with Chrome DevTools, and add its selector to the list in `lookup_serial()` |
| Constant CAPTCHAs | Run from a home/office network (never a cloud VM / VPN datacenter IP), and increase `MIN_DELAY` / `MAX_DELAY` |

## Notes & fair use

- Run this from a normal residential/office connection at reasonable volume.
  It drives HP's own public warranty page the same way a human would, just
  without the typing.
- For large-scale or recurring business use, the proper solution is the
  official **HP Warranty API** (developers.hp.com, partner approval required)
  or **HP CMSL** for managed fleets.
- This project is not affiliated with or endorsed by HP.


