"""
app.py
======
Small Flask web UI for the HP Bulk Warranty Checker, built to run inside
GitHub Codespaces. Serves a single page where you upload your serials
file, start the batch, watch live progress, and download results.

Run with:  python app.py
Then open the forwarded port (Codespaces will prompt you / show it in
the "Ports" tab).
"""

import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

import warranty_engine as engine

app = Flask(__name__)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

INPUT_PATH = DATA_DIR / "serials.xlsx"
OUTPUT_XLSX = DATA_DIR / "warranty_results.xlsx"
OUTPUT_CSV = DATA_DIR / "warranty_results.csv"

# Shared job state, guarded by a lock since the background thread and the
# Flask request threads both touch it.
state_lock = threading.Lock()
state = {
    "running": False,
    "finished": False,
    "total": 0,
    "done": 0,
    "logs": [],
    "rows": [],
    "error": None,
}
stop_event = threading.Event()
worker_thread = None


def add_log(line: str):
    with state_lock:
        state["logs"].append(line)
        state["logs"] = state["logs"][-300:]  # keep it bounded


def on_progress(update: dict):
    with state_lock:
        state["total"] = update["total"]
        state["done"] = update["done"]
        state["rows"].append(update["last_row"])


def run_job():
    with state_lock:
        state["running"] = True
        state["finished"] = False
        state["error"] = None
        state["rows"] = []
        state["logs"] = []
        state["done"] = 0
        state["total"] = 0
    stop_event.clear()
    try:
        engine.run_batch(
            str(INPUT_PATH), str(OUTPUT_XLSX), str(OUTPUT_CSV),
            on_progress=on_progress, on_log=add_log,
            should_stop=stop_event.is_set,
        )
    except Exception as e:
        add_log(f"FATAL ERROR: {e}")
        with state_lock:
            state["error"] = str(e)
    finally:
        with state_lock:
            state["running"] = False
            state["finished"] = True


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f or f.filename == "":
        return jsonify({"ok": False, "error": "No file selected."}), 400
    if not f.filename.lower().endswith((".xlsx", ".csv")):
        return jsonify({"ok": False, "error": "Please upload an .xlsx or .csv file."}), 400
    suffix = ".csv" if f.filename.lower().endswith(".csv") else ".xlsx"
    save_path = DATA_DIR / f"serials{suffix}"
    f.save(save_path)
    global INPUT_PATH
    INPUT_PATH = save_path
    return jsonify({"ok": True, "filename": f.filename})


@app.route("/api/start", methods=["POST"])
def start():
    global worker_thread
    if not INPUT_PATH.exists():
        return jsonify({"ok": False, "error": "Upload a serials file first."}), 400
    with state_lock:
        if state["running"]:
            return jsonify({"ok": False, "error": "A batch is already running."}), 400
    worker_thread = threading.Thread(target=run_job, daemon=True)
    worker_thread.start()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop():
    stop_event.set()
    return jsonify({"ok": True})


@app.route("/api/status")
def status():
    with state_lock:
        return jsonify(dict(state))


@app.route("/api/download/<fmt>")
def download(fmt):
    if fmt == "xlsx" and OUTPUT_XLSX.exists():
        return send_file(OUTPUT_XLSX, as_attachment=True)
    if fmt == "csv" and OUTPUT_CSV.exists():
        return send_file(OUTPUT_CSV, as_attachment=True)
    return jsonify({"ok": False, "error": "No results file yet."}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
