#!/usr/bin/env python3
"""Genie Done Gate — Claude Code `Stop` hook: block once when the assistant
edited a code file after the user's last message and ran nothing afterwards.

Exempt: .md/.txt edits, `stop_hook_active` re-entry, earlier turns.
Fails OPEN like guard_dangerous.py. Claude Code only (Codex has no Stop hook here).
"""
import json
import sys

EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
REASON = ("You changed files but ran nothing after the last change. Run it once "
          "and show the real output, or say plainly why it cannot be run.")


def needs_run(path):
    lines = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                line = json.loads(raw)
            except ValueError:
                continue  # half-flushed line must not disable the gate
            if isinstance(line, dict) and isinstance(line.get("message"), dict):
                lines.append((line.get("type"), line["message"].get("content")))

    # A typed user turn; tool results also arrive as type=user, as a list of tool_result.
    def typed(c):
        return isinstance(c, str) or (isinstance(c, list) and not any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in c))

    users = [i for i, (t, c) in enumerate(lines) if t == "user" and typed(c)]
    if not users:
        return False
    pending = False  # a code edit with no Bash after it
    for t, c in lines[users[-1] + 1:]:
        if t != "assistant" or not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            if b.get("name") == "Bash":
                pending = False
            elif b.get("name") in EDIT_TOOLS:
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                p = inp.get("file_path") or inp.get("notebook_path") or ""
                if not str(p).lower().endswith((".md", ".txt")):
                    pending = True  # unknown path counts as code
    return pending


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        if data.get("stop_hook_active") or not data.get("transcript_path"):
            return
        if needs_run(data["transcript_path"]):
            json.dump({"decision": "block", "reason": REASON}, sys.stdout)
    except Exception:
        return  # fail open


if __name__ == "__main__":
    main()
