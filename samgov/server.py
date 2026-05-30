from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
BOT_SCRIPT = BASE_DIR / "bot" / "samgov_bot.py"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "samgov_tenders.txt"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
SCRIPT_TIMEOUT_SECONDS = 300


class SamGovHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_POST(self):
        if self.path != "/api/run-bot":
            self.send_json_error(404, "Endpoint not found.")
            return

        if not BOT_SCRIPT.exists():
            self.send_json_error(500, f"Script not found: {BOT_SCRIPT}")
            return

        OUTPUT_DIR.mkdir(exist_ok=True)
        if OUTPUT_FILE.exists():
            OUTPUT_FILE.unlink()

        try:
            result = subprocess.run(
                [sys.executable, str(BOT_SCRIPT), str(OUTPUT_FILE)],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=SCRIPT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            self.send_json_error(504, "Python script timed out.")
            return

        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip() or "Unknown script error."
            self.send_json_error(500, details)
            return

        if not OUTPUT_FILE.exists():
            self.send_json_error(500, "Script finished, but TXT file was not created.")
            return

        data = OUTPUT_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="samgov_tenders.txt"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json_error(self, status_code: int, message: str):
        data = json.dumps({"message": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    server = ThreadingHTTPServer((HOST, PORT), SamGovHandler)
    print(f"SAM.gov Tender Bot is running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
