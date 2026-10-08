#!/usr/bin/env python3
"""Genie route extension: parse user routing table, match keywords, eligibility."""
import json
import os
import re
from pathlib import Path


def load_config(host: str):
    """Load route extension config. Returns None if disabled/invalid/host not in hosts."""
    path_env = os.environ.get("GENIE_ROUTE_EXT")
    if path_env == "0":
        return None
    config_path = Path(path_env) if path_env else Path.home() / ".genie" / "route_ext.json"
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    hosts = data.get("hosts", [])
    if host not in hosts:
        return None
    return data


def parse_routes(md: str, heading: str):
    """Parse routing table from markdown. Returns list of {when, action, kw}."""
    pattern = rf"^## {re.escape(heading)}\b"
    start = re.search(pattern, md, re.MULTILINE)
    if not start:
        return []
    rows = []
    for line in md[start.end():].split("\n"):
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        cells = re.split(r"(?<!\\)\|", line)[1:-1]
        cells = [c.strip() for c in cells]
        if len(cells) < 2:
            continue
        if re.match(r"^-+$", cells[0]) or cells[0] == "情境":
            continue
        when = cells[0]
        action = cells[1].replace("\\|", "|") if len(cells) > 1 else ""
        kw = cells[2].replace("\\|", "|") if len(cells) > 2 else ""
        rows.append({"when": when, "action": action, "kw": kw})
    return rows


def match(routes, text: str):
    """Match text against routes. Returns (row, m, strong) or (None, 0, False)."""
    for row in routes:
        kw = row.get("kw", "")
        if not kw:
            continue
        segments = [s for s in kw.split("|") if s]
        matched = []
        for seg in segments:
            try:
                if re.compile(seg, re.I).search(text):
                    matched.append(seg)
            except re.error:
                continue
        m = len(matched)
        if m:
            strong = m >= 2 or (len(text) < 25 and "\n" not in text)
            return row, m, strong
    return None, 0, False


def eligible(text: str) -> bool:
    """Check if text is eligible for routing extension."""
    if not text:
        return False
    if text.startswith("/"):
        return False
    if len(text) < 12:
        return False
    bare = re.sub(r"^(\[allow-[a-z]+\]\s*)+", "", text, flags=re.I).strip()
    if len(bare) < 12:
        return False
    if re.match(r"^(繼續|接著|接上|續做|continue)", bare, re.I) and len(bare) < 40:
        return False
    if re.match(r"^\S+$", bare) and re.match(r"^(https?://|~?/|[0-9a-f]{8}-[0-9a-f]{4}-)", bare, re.I):
        return False
    return True


def is_fix_row(row: dict) -> bool:
    """Check if row is a fixindex row."""
    return "fixindex find" in row.get("action", "")