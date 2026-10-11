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

# Commands that look at the world without exercising the change. Clearing the
# gate on these made `ls` after an edit count as having run it, which is the
# whole failure the gate exists to catch: evidence that cannot fail is not
# evidence. Kept deliberately narrow -- grep/sed/awk/jq/test are assertions as
# often as they are sightseeing, so they still count as a run.
NOOP_CMDS = {"cd", "ls", "pwd", "echo", "printf", "date", "which", "command",
             "true", "clear", "cat", "head", "tail", "wc", "open", "mkdir",
             "touch", "tree", "file"}
# `git <sub>` that only reports. `git status` after an edit is the classic
# "I ran something" that proves nothing about the change.
NOOP_GIT_SUBS = {"status", "diff", "log", "show", "branch", "remote"}


def counts_as_run(command):
    """True when a Bash command could actually exercise the change.

    Every segment must be a look-only command for the whole line to be
    discounted: `ls && pytest` runs the tests. Unparseable means it counts,
    like every other fail-open path in this hook.
    """
    text = str(command or "").strip()
    if not text:
        return False
    for seg in text.replace("&&", "\n").replace("||", "\n").replace(";", "\n").replace("|", "\n").split("\n"):
        words = seg.split()
        # Skip leading VAR=value env assignments.
        while words and "=" in words[0] and not words[0].startswith("-"):
            words = words[1:]
        if not words:
            continue
        head = words[0].rsplit("/", 1)[-1]
        if head == "git":
            if len(words) > 1 and words[1] in NOOP_GIT_SUBS:
                continue
            return True
        if head in NOOP_CMDS:
            continue
        return True
    return False


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
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if counts_as_run(inp.get("command")):
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
