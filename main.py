#!/usr/bin/env python3
"""
SAM.gov monitoring agent for drone opportunities.

Features:
- Pull opportunities from SAM.gov Opportunities v2 API.
- Match and score opportunities against AIRIS 3 requirements.
- Prioritize target departments/agencies (DOT, NCDOT, USDA Forest, DOI, Public Safety).
- Emphasize Small Business set-asides.
- Export JSON and optional text summary.
- Optionally push matched opportunities to Telegram.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Tuple

# ---------------------------------------------------------------------------
# Configuration system
# ---------------------------------------------------------------------------
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drone_config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "drone_specs": {
        "max_payload_kg": 10.5,
    },
    "search": {
        "naics_codes": "336411,334511,541715,423860",
        "procurement_types": ["p", "o", "k"],
        "sam_search_urls": [
            "https://api.sam.gov/opportunities/v2/search",
            "https://api.sam.gov/prod/opportunities/v2/search",
        ],
    },
    "keywords": {
        "target_departments": [
            "ncdot", "department of transportation", " dot ",
            "usda forest service", "forest service",
            "department of interior", "bureau of land management",
            "national park service", "police", "fire department",
            "public safety", "first responder",
            "dept of defense", "army", "navy", "air force",
            "marine corps", "homeland security", "dhs",
        ],
        "rfp_topics": [
            "drone", "uav", "uas", "unmanned aircraft",
            "drone as first responder", "dfr", "drone delivery",
            "last mile", "payload delivery", "forest", "wildfire",
            "inspection", "vtol", "vertical take-off", "surveillance",
            "reconnaissance", "bvlos", "beyond visual line of sight",
            "long range", "suas",
        ],
        "negative": [
            "c-suas", "counter-uas", "counter uas", "counter-unmanned",
            "anti-drone", "anti drone", "drone shield", "droneshield",
            "defeat uas", "detect and defeat",
            "3d print", "3d printer",
            "repair parts", "spare parts", "replacement parts",
        ],
        "components_only": ["components", "parts", "accessories", "kits"],
    },
    "competitors": {
        "brands": [
            "skydio", "dji", "draganfly", "autel", "parrot",
            "freefly", "wingtra", "sensfly", "ebee", "matrice",
            "mavic", "phantom", "inspire", "agras",
        ],
        "or_equal_patterns": [r"\bor equal\b", r"\bor equivalent\b", r"\bor similar\b"],
    },
    "patterns": {
        "payload": [
            r"\b\d{1,3}\s?kg\b", r"\b\d{1,3}\s?lb(s)?\b",
            r"heavy\s?lift", r"delivery\s?box",
            r"cargo\s?capacity", r"payload\s?capacity",
        ],
        "winch": [r"\bwinch\b", r"\bgravity release\b", r"\bdrop( system)?\b"],
        "parachute": [r"\bparachute\b", r"\brecovery system\b"],
        "comms": [r"\blte\b", r"\b900\s?mhz\b", r"\bcommand and control\b", r"\bc2\b"],
    },
    "scoring_weights": {
        "topic_keyword": 2,
        "target_department": 3,
        "ideal_payload_match": 5,
        "payload_partial_match": 2,
        "generic_heavy_lift": 2,
        "winch_delivery": 3,
        "parachute": 4,
        "comms": 2,
        "brand_or_equal": 2,
        "brand_exclusive_penalty": -3,
        "vtol": 3,
        "bvlos": 2,
        "surveillance": 2,
        "small_business": 3,
        "negative_keyword_penalty": -5,
        "components_only_penalty": -3,
    },
    "small_biz_codes": [
        "SBA", "SBP", "8A", "8AN", "HZC", "HZS",
        "SDVOSBC", "SDVOSBS", "WOSB", "WOSBSS",
        "EDWOSB", "EDWOSBSS",
    ],
    "match_thresholds": {
        "high_min_score": 8,
        "medium_min_score": 7,
        "likely_relevant_min_score": 7,
    },
}


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Recursively merge *override* into a copy of *base*."""
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def load_config(path: str | None = None) -> Dict[str, Any]:
    """Load config from *path* (default: ``CONFIG_PATH``), merging over defaults."""
    path = path or CONFIG_PATH
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            return _deep_merge(DEFAULT_CONFIG, user_cfg)
        except Exception as exc:
            print(f"Warning: failed to load {path}, using defaults: {exc}", file=sys.stderr)
    return copy.deepcopy(DEFAULT_CONFIG)


# Load config at module level so every function can access it.
_CFG = load_config()

# ---------------------------------------------------------------------------
# Convenience accessors (kept as module-level for minimal diff to the rest of the code)
# ---------------------------------------------------------------------------
SAM_SEARCH_URL_DEFAULTS: Tuple[str, ...] = tuple(_CFG["search"]["sam_search_urls"])
DEFAULT_PTYPES = tuple(_CFG["search"]["procurement_types"])

TARGET_DEPARTMENT_KEYWORDS = _CFG["keywords"]["target_departments"]
RFP_TOPIC_KEYWORDS = _CFG["keywords"]["rfp_topics"]

KNOWN_COMPETITOR_BRANDS = _CFG["competitors"]["brands"]
OR_EQUAL_PATTERNS = _CFG["competitors"]["or_equal_patterns"]

NEGATIVE_KEYWORDS = _CFG["keywords"]["negative"]
COMPONENTS_ONLY_KEYWORDS = _CFG["keywords"]["components_only"]

PAYLOAD_PATTERNS = _CFG["patterns"]["payload"]
WINCH_PATTERNS = _CFG["patterns"]["winch"]
PARACHUTE_PATTERNS = _CFG["patterns"]["parachute"]
COMMS_PATTERNS = _CFG["patterns"]["comms"]

DEFAULT_NAICS_CODES = _CFG["search"]["naics_codes"]

SMALL_BIZ_CODES = set(_CFG["small_biz_codes"])


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.lower()
    return str(value).lower()


def date_mmddyyyy(days_back: int = 30) -> Tuple[str, str]:
    today = dt.date.today()
    start = today - dt.timedelta(days=days_back)
    return start.strftime("%m/%d/%Y"), today.strftime("%m/%d/%Y")


def to_query_string(pairs: List[Tuple[str, str]]) -> str:
    """Build query string; repeats keys are preserved (ptype=p&ptype=o&...)."""
    return urllib.parse.urlencode([(k, v) for k, v in pairs if v is not None and v != ""])


def redact_url(u: str) -> str:
    """Remove api_key from URLs printed in logs or errors."""
    return re.sub(r"([?&])api_key=[^&]*", r"\1api_key=***", u)


def effective_https_proxy(cli_value: str | None) -> str | None:
    """HTTPS proxy URL; CLI wins, else standard env vars (urllib does not apply these alone)."""
    if cli_value and cli_value.strip():
        return cli_value.strip()
    for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        v = os.getenv(key)
        if v and v.strip():
            return v.strip()
    return None


def _url_open(req: urllib.request.Request, *, timeout: int, proxy_url: str | None):
    """Like urlopen(); uses HTTP(S) CONNECT proxy when proxy_url is set."""
    if proxy_url:
        proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(proxy_handler)
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)
def fetch_json(url: str, timeout: int = 35, *, proxy_url: str | None = None) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    safe = redact_url(url)
    try:
        with _url_open(req, timeout=timeout, proxy_url=proxy_url) as resp:
            data = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        snippet = ""
        try:
            snippet = e.read().decode("utf-8", errors="replace")[:800].strip()
        except Exception:
            pass
        extra = f" Body: {snippet}" if snippet else ""
        raise RuntimeError(f"{e.code} {e.reason}: {safe}{extra}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {safe} — {e.reason}") from e
    return json.loads(data)


def fetch_description(url: str, api_key: str, timeout: int = 25, *, proxy_url: str | None = None) -> str:
    """Fetch the full description text from the SAM notice description API."""
    if not url or not url.startswith("http"):
        return ""
    # Append api_key if missing
    sep = "&" if "?" in url else "?"
    if "api_key=" not in url:
        url = f"{url}{sep}api_key={api_key}"

    try:
        data = fetch_json(url, timeout=timeout, proxy_url=proxy_url)
        # Description API usually returns a JSON with a 'description' field
        return normalize_text(data.get("description", ""))
    except Exception:
        return ""


def contains_any_regex(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE | re.DOTALL) for pattern in patterns)


def contains_any_keyword(text: str, keywords: Iterable[str]) -> bool:
    return any(k in text for k in keywords)


def build_record_text(record: Dict[str, Any]) -> str:
    fields = [
        record.get("title"),
        record.get("fullParentPathName"),
        record.get("type"),
        record.get("baseType"),
        record.get("typeOfSetAsideDescription"),
        record.get("typeOfSetAside"),
        record.get("classificationCode"),
        record.get("naicsCode"),
        record.get("solicitationNumber"),
    ]
    # Some records have useful text in POC fullName
    for poc in (record.get("pointOfContact") or []):
        fields.append(poc.get("fullName"))

    return normalize_text(" | ".join([f for f in fields if f]))


def has_target_department(text: str) -> bool:
    return contains_any_keyword(text, TARGET_DEPARTMENT_KEYWORDS)


def has_topic_keyword(text: str) -> bool:
    return contains_any_keyword(text, RFP_TOPIC_KEYWORDS)


def score_record(record: Dict[str, Any], full_description: str = "") -> Dict[str, Any]:
    text = build_record_text(record)
    if full_description:
        text = f"{text} | {full_description}"

    sw = _CFG["scoring_weights"]
    thresholds = _CFG["match_thresholds"]
    reasons: List[str] = []
    score = 0

    # Negative keyword check (counter-drone, spare parts, etc.)
    if any(neg in text for neg in NEGATIVE_KEYWORDS):
        score += sw["negative_keyword_penalty"]
        reasons.append("Negative keyword (counter-UAS / parts / 3D print) - penalty")

    # Softer penalty for "components only" orders
    title_lower = normalize_text(record.get("title"))
    if any(kw in title_lower for kw in COMPONENTS_ONLY_KEYWORDS):
        if not any(pos in title_lower for pos in ["system", "complete", "drone", "aircraft"]):
            score += sw["components_only_penalty"]
            reasons.append("Title suggests components/parts only, not a complete system")

    if has_topic_keyword(text):
        score += sw["topic_keyword"]
        reasons.append("Drone/DFR/delivery keyword")

    if has_target_department(text):
        score += sw["target_department"]
        reasons.append("Target department/agency match")

    # 3. Payload analysis (Advanced logic)
    found_weights_kg: List[float] = []
    # Extract kg
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s?kg\b", text):
        found_weights_kg.append(float(match.group(1)))
    # Extract lbs and convert to kg (1 lb = 0.453 kg)
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s?lb(s)?\b", text):
        found_weights_kg.append(float(match.group(1)) * 0.453)

    max_drone_cap = _CFG["drone_specs"]["max_payload_kg"]
    if found_weights_kg:
        has_fit = any(w <= max_drone_cap for w in found_weights_kg)
        has_exceed = any(w > max_drone_cap for w in found_weights_kg)

        if has_fit:
            if has_exceed:
                score += sw["payload_partial_match"]
                reasons.append(f"Payload match found (<={max_drone_cap}kg), but also found requirements exceeding capacity (Penalty applied)")
            else:
                score += sw["ideal_payload_match"]
                reasons.append(f"Ideal Payload match (<={max_drone_cap}kg)")
        # If ONLY exceed, we don't add points (handled by default score=0)
    elif "heavy lift" in text or "cargo" in text:
        # Fallback for generic terms without numbers
        score += sw["generic_heavy_lift"]
        reasons.append("Generic Heavy Lift/Cargo keyword match")

    if contains_any_regex(text, WINCH_PATTERNS) or "delivery box" in text:
        score += sw["winch_delivery"]
        reasons.append("Winch / delivery system requirement")

    parachute = contains_any_regex(text, PARACHUTE_PATTERNS)
    if parachute:
        score += sw["parachute"]
        reasons.append("Parachute requirement (High Match cue)")

    if contains_any_regex(text, COMMS_PATTERNS):
        score += sw["comms"]
        reasons.append("LTE / 900MHz / C2 communication cue")

    # Brand-name and 'or equal' analysis
    has_brand = any(brand in text for brand in KNOWN_COMPETITOR_BRANDS)
    has_or_equal = contains_any_regex(text, OR_EQUAL_PATTERNS)
    if has_brand:
        if has_or_equal:
            score += sw["brand_or_equal"]
            reasons.append("Brand name mentioned with 'or equal' — open to alternatives")
        else:
            score += sw["brand_exclusive_penalty"]
            reasons.append("Specific brand required (no 'or equal') — penalty applied")

    # Technical Capability Matching (AIRIS 3 Strengths)
    if "vtol" in text or "vertical take-off" in text:
        score += sw["vtol"]
        reasons.append("VTOL requirement match")
    
    if any(kw in text for kw in ["bvlos", "beyond visual line of sight", "long range"]):
        score += sw["bvlos"]
        reasons.append("BVLOS / Long-range capability match")

    if any(kw in text for kw in ["surveillance", "reconnaissance", "rsta", "monitoring"]):
        score += sw["surveillance"]
        reasons.append("Surveillance/Reconnaissance mission match")

    set_aside_code = normalize_text(record.get("typeOfSetAside"))
    set_aside_desc = normalize_text(record.get("typeOfSetAsideDescription"))
    small_biz = (
        record.get("typeOfSetAside") in SMALL_BIZ_CODES
        or "small business" in set_aside_desc
        or "set-aside" in set_aside_desc
    )
    if small_biz:
        score += sw["small_business"]
        reasons.append("Small Business set-aside")

    match_level = "Low"
    if parachute and score >= thresholds["high_min_score"]:
        match_level = "High"
    elif score >= thresholds["medium_min_score"]:
        match_level = "Medium"

    # Logic change: if it's explicitly a drone/UAV topic, we lower the bar for score/department.
    topic_match = has_topic_keyword(text)
    likely_relevant = topic_match and (has_target_department(text) or score >= thresholds["likely_relevant_min_score"])

    return {
        "score": score,
        "match_level": match_level,
        "small_business": small_biz,
        "likely_relevant": likely_relevant,
        "topic_match": topic_match,
        "reasons": reasons,
        "found_weights_kg": found_weights_kg,
    }


def get_ui_link(record: Dict[str, Any]) -> str:
    ui_link = record.get("uiLink")
    if ui_link:
        return ui_link
    notice_id = record.get("noticeId")
    if notice_id:
        return f"https://sam.gov/opp/{notice_id}/view"
    return "https://sam.gov/search"
def summarize_department(record: Dict[str, Any]) -> str:
    org = record.get("fullParentPathName") or ""
    org_l = normalize_text(org)
    if "ncdot" in org_l or "north carolina department of transportation" in org_l:
        return "NCDOT"
    if "department of transportation" in org_l or " dot " in f" {org_l} ":
        return "DOT"
    if "forest service" in org_l or "usda" in org_l:
        return "USDA / Forest"
    if "department of interior" in org_l or "interior" in org_l:
        return "Department of Interior"
    if "police" in org_l or "fire" in org_l or "public safety" in org_l:
        return "Public Safety"
    return org.split(">")[0].strip() if org else "Unknown Department"


def _search_query_pairs(
    *,
    api_key: str,
    posted_from: str,
    posted_to: str,
    limit: int,
    offset: int,
    ncode: str,
) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = [
        ("api_key", api_key),
        ("postedFrom", posted_from),
        ("postedTo", posted_to),
        ("limit", str(limit)),
        ("offset", str(offset)),
    ]
    if ncode:
        pairs.append(("ncode", ncode))
    for pt in DEFAULT_PTYPES:
        pairs.append(("ptype", pt))
    return pairs


def search_opportunities(
    api_key: str,
    days_back: int,
    limit: int,
    offset: int,
    ncode: str,
    *,
    search_urls: List[str],
    proxy_url: str | None = None,
) -> Dict[str, Any]:
    posted_from, posted_to = date_mmddyyyy(days_back)
    qs = _search_query_pairs(
        api_key=api_key,
        posted_from=posted_from,
        posted_to=posted_to,
        limit=limit,
        offset=offset,
        ncode=ncode.strip(),
    )
    query_string = to_query_string(qs)
    errors: List[str] = []

    for base in search_urls:
        url = f"{base.rstrip('/')}?{query_string}"
        try:
            return fetch_json(url, proxy_url=proxy_url)
        except Exception as exc:  # noqa: BLE001 — collect and try next base URL
            errors.append(f"{base}: {exc}")

    hint = (
        "Could not reach SAM.gov opportunities search. If every attempt is HTTP 404 with an empty body, "
        "try from a US-based network/VPN or a small cloud VM in the US — some regions cannot route to api.sam.gov. "
        "If you have a US HTTP/HTTPS proxy, set HTTPS_PROXY or pass --https-proxy. "
        "Many consumer VPNs only tunnel the browser unless you enable full-tunnel / system proxy. "
        "Alpha (api-alpha.sam.gov) needs a key from alpha.sam.gov. "
        "Verify the key under SAM.gov -> Account Details (password required to view)."
    )
    raise RuntimeError(f"{hint}\nAttempts:\n" + "\n".join(errors))


def build_report(opps: List[Dict[str, Any]], api_key: str = "", out_desc: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    analyzed_matched: List[Dict[str, Any]] = []
    analyzed_excluded: List[Dict[str, Any]] = []
    dept_map: Dict[str, int] = {}
    descriptions_log: List[str] = []

    for rec in opps:
        # 1. Quick pre-score to see if we should bother fetching description
        scoring = score_record(rec)
        desc_url = rec.get("description")
        full_text = ""

        # If it's a topic match but lacks info, try to fetch full description
        if scoring["topic_match"] and desc_url and api_key:
            print(f"Fetching full description for: {rec.get('title')[:60]}...")
            full_text = fetch_description(desc_url, api_key, proxy_url=None)
            if full_text:
                print(f"  [OK] Fetched {len(full_text)} chars of description")
                descriptions_log.append(f"TITLE: {rec.get('title')}\nURL: {desc_url}\nTEXT: {full_text}\n" + "="*40 + "\n")
                scoring = score_record(rec, full_description=full_text)
            else:
                print(f"  [FAIL] Could not fetch description text from {desc_url[:50]}...")

        dept = summarize_department(rec)
        dept_map[dept] = dept_map.get(dept, 0) + 1

        item_data = {
            "notice_id": rec.get("noticeId"),
            "title": rec.get("title"),
            "agency": rec.get("fullParentPathName"),
            "department_bucket": dept,
            "posted_date": rec.get("postedDate"),
            "response_deadline": rec.get("responseDeadLine"),
            "type": rec.get("type"),
            "set_aside": rec.get("typeOfSetAsideDescription") or rec.get("typeOfSetAside"),
            "match_analysis": {
                "total_score": scoring["score"],
                "match_level": scoring["match_level"],
                "reasons": scoring["reasons"],
                "detected_weights_kg": [round(w, 2) for w in scoring["found_weights_kg"]],
                "is_small_business": scoring["small_business"]
            },
            "sam_link": get_ui_link(rec),
            "full_description": full_text,
            "raw_api_data": rec
        }

        if not scoring["likely_relevant"]:
            if scoring["topic_match"]:
                analyzed_excluded.append(item_data)
            continue

        analyzed_matched.append(item_data)
    for lst in [analyzed_matched, analyzed_excluded]:
        lst.sort(
            key=lambda x: (
                0 if x["match_analysis"]["match_level"] == "High" else 1 if x["match_analysis"]["match_level"] == "Medium" else 2,
                -x["match_analysis"]["total_score"],
                x.get("posted_date") or "",
            )
        )

    departments_ranked = sorted(dept_map.items(), key=lambda x: x[1], reverse=True)

    if out_desc and descriptions_log:
        with open(out_desc, "w", encoding="utf-8") as f:
            f.write("\n".join(descriptions_log))
        print(f"Saved {len(descriptions_log)} full descriptions to {out_desc}")
    
    matched_report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "matched_count": len(analyzed_matched),
        "departments": [{"name": name, "opportunity_count": count} for name, count in departments_ranked],
        "opportunities": analyzed_matched,
    }
    excluded_report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "excluded_count": len(analyzed_excluded),
        "opportunities": analyzed_excluded,
    }
    return matched_report, excluded_report


def render_text_summary(report: Dict[str, Any], top_n: int = 25, is_excluded: bool = False) -> str:
    lines = []
    status_label = "EXCLUDED (REJECTED)" if is_excluded else "ACCEPTED (MATCHED)"
    
    lines.append("=" * 60)
    lines.append(f"SAM.GOV DRONE ANALYSIS REPORT - {status_label}")
    lines.append(f"Generated at: {report.get('generated_at')}")
    lines.append(f"Total {status_label.lower()} opportunities: {len(report.get('opportunities', []))}")
    lines.append("=" * 60 + "\n")

    opps = report.get("opportunities", []) or []
    for i, opp in enumerate(opps[:top_n], 1):
        m = opp.get("match_analysis", {})
        score = m.get("total_score", 0)
        level = m.get("match_level", "Unknown")
        reasons = "; ".join(m.get("reasons", []))
        
        lines.append(f"{i}. [{level}] {opp.get('title')} | SCORE: {score}")
        lines.append(f"   Agency:   {opp.get('agency')}")
        lines.append(f"   Deadline: {opp.get('response_deadline')}")
        lines.append(f"   Link:     {opp.get('sam_link')}")
        lines.append(f"   Status:   {'[REJECTED]' if is_excluded else '[ACCEPTED]'}")
        lines.append(f"   Analysis: {reasons}")
        
        desc = opp.get("full_description", "").strip()
        if desc:
            # Shorten description for report if it's too long
            clean_desc = desc[:1000] + ("..." if len(desc) > 1000 else "")
            lines.append(f"   Description Preview:\n      {clean_desc}")
        
        lines.append("-" * 40)

    return "\n".join(lines)


def proxy_hint(proxy_url: str | None) -> str:
    if not proxy_url:
        return "none (direct)"
    parsed = urllib.parse.urlparse(proxy_url)
    if parsed.username:
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://***@{host}{port}"
    return proxy_url


def run_diagnose(
    *,
    api_key: str | None,
    proxy_url: str | None,
    search_urls: List[str],
) -> int:
    """Same network path as normal runs: helps verify VPN/proxy applies to Python."""
    print("=== sam_drone_agent.py — network diagnose ===")
    print(f"HTTPS proxy: {proxy_hint(proxy_url)}")

    try:
        geo = fetch_json("https://ipinfo.io/json", timeout=18, proxy_url=proxy_url)
        ip = geo.get("ip", "?")
        cc = geo.get("country", "?")
        org = (geo.get("org") or "")[:120]
        print(f"Exit for this Python process: IP={ip}  country={cc}  org={org}")
        if cc != "US":
            print(
                "Note: SAM production API often fails (e.g. empty 404) when exit is not US. "
                "Use US VPN with full tunnel, or HTTPS_PROXY to a US proxy, or run on a US cloud VM.",
            )
    except Exception as exc:  # noqa: BLE001
        print(f"ipinfo.io check failed (still can try SAM): {exc}")

    if not api_key:
        print("SAM check skipped — set SAM_API_KEY or pass --api-key.")
        return 0
    posted_from, posted_to = date_mmddyyyy(7)
    qs = to_query_string(
        _search_query_pairs(
            api_key=api_key,
            posted_from=posted_from,
            posted_to=posted_to,
            limit=1,
            offset=0,
            ncode="",
        )
    )
    print("SAM search (limit=1, no NAICS filter, diagnose only):")
    any_ok = False
    for base in search_urls:
        url = f"{base.rstrip('/')}?{qs}"
        try:
            payload = fetch_json(url, timeout=35, proxy_url=proxy_url)
            n = payload.get("totalRecords")
            got = len(payload.get("opportunitiesData") or [])
            print(f"  OK  {base} → totalRecords={n} rows_in_page={got}")
            any_ok = True
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {base} → {exc}")
    return 0 if any_ok else 1


def send_telegram(token: str, chat_id: str, text: str, *, proxy_url: str | None = None) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:4000]})
    req = urllib.request.Request(
        url,
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with _url_open(req, timeout=30, proxy_url=proxy_url) as _:
        return


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SAM.gov drone opportunity monitoring agent")
    p.add_argument("--api-key", default=os.getenv("SAM_API_KEY"), help="SAM.gov API key")
    p.add_argument("--days-back", type=int, default=30, help="Date window in days (default: 30)")
    p.add_argument("--limit", type=int, default=200, help="Records per request (max 1000)")
    p.add_argument("--offset", type=int, default=0, help="Offset for pagination")
    p.add_argument("--ncode", default=DEFAULT_NAICS_CODES, help="NAICS codes, comma-separated (default: multiple drone-related codes)")
    p.add_argument("--out-json", default="sam_matches.json", help="Output JSON report path")
    p.add_argument("--out-raw", default="", help="Save raw un-filtered API response to this JSON file")
    p.add_argument("--out-desc", default="descriptions_debug.txt", help="Save all fetched descriptions to this file")
    p.add_argument("--out-txt", default="sam_matches.txt", help="Output text report path")
    p.add_argument("--telegram-token", default=os.getenv("TELEGRAM_BOT_TOKEN"), help="Telegram bot token")
    p.add_argument("--telegram-chat-id", default=os.getenv("TELEGRAM_CHAT_ID"), help="Telegram chat ID")
    p.add_argument("--telegram", action="store_true", help="Send top results to Telegram")
    p.add_argument(
        "--sam-search-url",
        default=os.getenv("SAM_SEARCH_URL", "").strip(),
        help="Override opportunities search base URL (default: try official production URLs). "
        "Example: https://api.sam.gov/opportunities/v2/search",
    )
    p.add_argument(
        "--https-proxy",
        default=os.getenv("HTTPS_PROXY", os.getenv("https_proxy", "")).strip(),
        help="HTTP(S) proxy for SAM and Telegram (or set HTTPS_PROXY / https_proxy in the environment).",
    )
    p.add_argument(
        "--diagnose",
        action="store_true",
        help="Print egress IP/country and test SAM URLs (same proxy as agent), then exit.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    search_urls = [args.sam_search_url] if args.sam_search_url else list(SAM_SEARCH_URL_DEFAULTS)
    proxy_url = effective_https_proxy(args.https_proxy)

    if args.diagnose:
        return run_diagnose(api_key=args.api_key, proxy_url=proxy_url, search_urls=search_urls)

    if not args.api_key:
        print("Error: provide --api-key or set SAM_API_KEY", file=sys.stderr)
        return 2

    try:
        naics_codes = [c.strip() for c in args.ncode.split(",") if c.strip()]
        if not naics_codes:
            naics_codes = [""]  # Empty string = no NAICS filter

        all_opportunities: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for ncode in naics_codes:
            label = ncode or "ALL"
            print(f"Searching NAICS={label}...", end=" ")
            try:
                raw = search_opportunities(
                    api_key=args.api_key,
                    days_back=args.days_back,
                    limit=max(1, min(args.limit, 1000)),
                    offset=max(0, args.offset),
                    ncode=ncode,
                    search_urls=search_urls,
                    proxy_url=proxy_url,
                )
                batch = raw.get("opportunitiesData", []) or []
                new_count = 0
                for opp in batch:
                    nid = opp.get("noticeId")
                    if nid and nid not in seen_ids:
                        seen_ids.add(nid)
                        all_opportunities.append(opp)
                        new_count += 1
                print(f"found {len(batch)} records ({new_count} new)")
            except Exception as e:
                print(f"FAILED: {e}")

        if not all_opportunities:
            print("No opportunities found from any NAICS code.", file=sys.stderr)
            return 1

        print(f"\nTotal unique opportunities: {len(all_opportunities)}")
        opportunities = all_opportunities
    except Exception as e:
        print(f"SAM API request failed: {e}", file=sys.stderr)
        return 1

    if args.out_raw:
        write_json(args.out_raw, {"totalRecords": len(opportunities), "opportunitiesData": opportunities})
        print(f"Raw API data saved to {args.out_raw} ({len(opportunities)} records total)")

    report, excluded = build_report(opportunities, api_key=args.api_key, out_desc=args.out_desc)
    write_json(args.out_json, report)
    write_json("sam_excluded.json", excluded)

    summary = render_text_summary(report, top_n=25)
    with open(args.out_txt, "w", encoding="utf-8") as f:
        f.write(summary + "\n")

    summary_excluded = render_text_summary(excluded, top_n=100, is_excluded=True)
    with open("sam_excluded.txt", "w", encoding="utf-8") as f:
        f.write(summary_excluded + "\n")

    print(summary)
    print(f"\nSaved {len(report['opportunities'])} matched and {len(excluded['opportunities'])} excluded opportunities.")

    if args.telegram:
        if not args.telegram_token or not args.telegram_chat_id:
            print("Telegram enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing.", file=sys.stderr)
            return 2
        top = report.get("opportunities", [])[:10]
        if top:
            message_lines = ["Found matching SAM.gov opportunities:"]
            for item in top:
                analysis = item.get("match_analysis", {})
                message_lines.append(
                    f"- [{analysis.get('match_level')}] {item['department_bucket']}: {item['title']}\n{item['sam_link']}"
                )
            send_telegram(
                args.telegram_token, args.telegram_chat_id, "\n\n".join(message_lines), proxy_url=proxy_url
            )
        else:
            send_telegram(
                args.telegram_token,
                args.telegram_chat_id,
                "No matching opportunities found this run.",
                proxy_url=proxy_url,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())