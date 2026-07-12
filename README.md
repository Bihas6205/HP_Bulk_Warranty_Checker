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

## Setup

To finally run the scrapper program, run the below command:
```bash
# xvfb-run -a python hp_warranty_checker.py

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
   python hp_warranty_checker.py
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

## License

MIT
