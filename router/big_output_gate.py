#!/usr/bin/env python3
"""Genie Big Output Gate — Claude Code `PostToolUse` hook: warn when a tool
result is big enough that it should have been filtered before printing.

A 5,000-line test log lands in context whole; the next request re-sends it.
The fix is upstream of the model: `| head`, `rg -m`, `jq`, `--max-count` --
print the needed rows, not the file. This hook cannot un-spend the tokens of
the result that just landed, so it warns for the next call.

Never blocks: a warning is context, not a veto (fail_streak.py's precedent).
Threshold: GENIE_BIG_OUTPUT_LINES, default 200. Fails OPEN on any error.
"""
import json
import os
import sys
from datetime import datetime, timezone

DEFAULT_LIMIT = 200

WARNING = (
    "Genie: {tool} returned {lines} lines (over the ~{limit}-line budget). "
    "That whole result now sits in context and is re-sent every request. "
    "Next time filter at the source -- head, rg -m, jq, --max-count, a "
    "script that prints only the needed rows."
)


def _text_of(resp):
    """tool_response -> its text. Bash gives {stdout, stderr}; other tools give
    a string or any JSON -- fall back to the serialized size rather than miss."""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        parts = [v for k, v in resp.items()
                 if k in ("stdout", "stderr", "output", "content", "text",
                          "result", "error", "message") and isinstance(v, str)]
        if parts:
            return "\n".join(parts)
    return json.dumps(resp, ensure_ascii=False)


def _limit():
    try:
        return int(os.environ.get("GENIE_BIG_OUTPUT_LINES") or DEFAULT_LIMIT)
    except ValueError:
        return DEFAULT_LIMIT


def _shadow_enabled():
    return os.environ.get("GENIE_BIG_OUTPUT_SHADOW") in ("1", "true", "yes", "on")


def _shadow_log_path():
    return os.environ.get(
        "GENIE_BIG_OUTPUT_SHADOW_LOG",
        os.path.expanduser("~/.claude/guard-state/big-output-shadow.jsonl"))


def _write_shadow(data, lines, limit):
    """Write metadata only. Never log tool input or tool_response content."""
    path = _shadow_log_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "tool": data.get("tool_name") or "tool",
        "lines": lines,
        "limit": limit,
        "session_id": data.get("session_id"),
    }
    with open(path, "a", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", "replace") or "{}"
        data = json.loads(raw)
        if not isinstance(data, dict):
            return
        text = _text_of(data.get("tool_response"))
        if not text:
            return
        lines = text.count("\n") + 1
        limit = _limit()
        if lines <= limit:
            return
        if _shadow_enabled():
            _write_shadow(data, lines, limit)
            return
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": WARNING.format(
                    tool=data.get("tool_name") or "tool",
                    lines=lines, limit=limit),
            }
        }
        json.dump(out, sys.stdout, ensure_ascii=False)
    except Exception:
        return  # fail open


if __name__ == "__main__":
    main()
