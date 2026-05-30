from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


def build_report() -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""SAM.gov tender report
Generated: {now}

This is a placeholder report.

Replace bot/samgov_bot.py with your real SAM.gov parser or API client.
The web page will download whatever text this script writes to the output path.
"""


def main() -> None:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/samgov_tenders.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_report(), encoding="utf-8")


if __name__ == "__main__":
    main()
