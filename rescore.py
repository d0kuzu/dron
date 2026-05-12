"""Re-score raw API data locally (no API calls needed)."""
import json
import sys
sys.path.insert(0, ".")
from main import build_report, render_text_summary, write_json

with open("raw_api_data.json", encoding="utf-8") as f:
    raw = json.load(f)

opps = raw.get("opportunitiesData", [])
print(f"Loaded {len(opps)} raw opportunities")

report, excluded = build_report(opps, api_key="", out_desc="")
write_json("sam_matches.json", report)
write_json("sam_excluded.json", excluded)

summary = render_text_summary(report, top_n=25)
with open("sam_matches.txt", "w", encoding="utf-8") as f:
    f.write(summary)

summary_ex = render_text_summary(excluded, top_n=100, is_excluded=True)
with open("sam_excluded.txt", "w", encoding="utf-8") as f:
    f.write(summary_ex)

print(summary)
m = len(report["opportunities"])
e = len(excluded["opportunities"])
print(f"\nSaved {m} matched, {e} excluded")
