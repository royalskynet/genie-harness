#!/usr/bin/env python3
"""Genie Done Gate — Claude Code `Stop` hook: "did you actually run it?"

Genie's `AGENTS.md` says 「做完實際跑一次，貼真的輸出」. That instruction is cheap
to write and easy to forget: the model edits a file, describes what the fix
would do, and stops. The user gets a confident report about code that has never
executed. This hook is the mechanical half of that promise.

What it blocks: after the user's last message, the assistant edited a real code
file and then ran nothing. Not "the tests are probably fine" — nothing.

What it deliberately does not block, because a gate that cries wolf gets
disabled:
  * Markdown and plain-text edits. Prose has nothing to execute, and asking for
    a test run after a README typo is the fastest way to make a user turn the
    whole thing off.
  * The `stop_hook_active` re-entry. Claude Code sets it when a Stop hook is
    already blocking; looping on ourselves would hang the session.
  * Edits made before the user's last message. Those belong to a previous turn
    and were already the subject of whatever the user asked next.

Failure policy: fail OPEN, like `guard_dangerous.py`. A missing transcript, a
half-written JSONL line, a content shape this script has never seen — all of it
prints nothing and exits 0. This gate must never be the reason a session ends
badly.

Claude Code only. Codex has no equivalent `Stop` event in this plugin, so on
Codex this script simply never runs.
"""
import json
import os
import sys

# Tools that change a file. NotebookEdit uses `notebook_path`; the rest use
# `file_path`.
EDIT_TOOLS = frozenset(("Write", "Edit", "MultiEdit", "NotebookEdit"))
PATH_KEYS = ("file_path", "notebook_path")

# Prose is not runnable, so it is exempt.
DOC_EXT = (".md", ".txt")

REASON = ("You changed files but ran nothing after the last change. Run it once "
          "and show the real output, or say plainly why it cannot be run.")


def _content_of(line):
    """The `message.content` value, or None if this line is not shaped like one."""
    if not isinstance(line, dict):
        return None
    msg = line.get("message")
    if not isinstance(msg, dict):
        return None
    return msg.get("content")


def _is_user_message(content):
    """True for a message the human typed, not for a tool result coming back.

    Claude Code writes both as `type == "user"`. Tool results arrive as a list
    whose items are `tool_result` blocks; treating those as user turns would
    reset the scan window on every single tool call and the gate would never
    see anything.
    """
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_result"
                       for b in content)
    return False


def _iter_tool_uses(lines, start):
    """Yield every `tool_use` block from assistant lines at/after `start`."""
    for line in lines[start:]:
        if not isinstance(line, dict) or line.get("type") != "assistant":
            continue
        content = _content_of(line)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield block


def _is_code_edit(block):
    """True when this tool_use changed something that could be executed."""
    if block.get("name") not in EDIT_TOOLS:
        return False
    tool_input = block.get("input")
    path = None
    if isinstance(tool_input, dict):
        for key in PATH_KEYS:
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                path = value
                break
    if path is None:
        return True  # an edit we cannot identify is an edit
    return not path.lower().endswith(DOC_EXT)


def needs_run(path):
    """True when the transcript ends with code edits and no run after them."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            raw_lines = fh.read().splitlines()
    except Exception:
        return False

    lines = []
    for raw in raw_lines:
        if not raw.strip():
            continue
        try:
            lines.append(json.loads(raw))
        except Exception:
            continue  # a half-flushed line must not disable the gate

    last_user = None
    for i, line in enumerate(lines):
        if isinstance(line, dict) and line.get("type") == "user" \
                and _is_user_message(_content_of(line)):
            last_user = i
    if last_user is None:
        return False  # nothing to judge; fail open

    edits = 0
    ran_after_last_edit = False
    for block in _iter_tool_uses(lines, last_user + 1):
        if block.get("name") == "Bash":
            if edits:
                ran_after_last_edit = True
        elif _is_code_edit(block):
            edits += 1
            ran_after_last_edit = False
    return bool(edits) and not ran_after_last_edit


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        if not isinstance(data, dict):
            return
        if data.get("stop_hook_active"):
            return  # already blocked this turn; do not loop
        transcript = data.get("transcript_path")
        if not isinstance(transcript, str) or not transcript:
            return
        if needs_run(os.path.expanduser(transcript)):
            json.dump({"decision": "block", "reason": REASON}, sys.stdout)
    except Exception:
        return  # fail open


if __name__ == "__main__":
    main()