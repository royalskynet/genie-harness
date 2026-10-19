#!/usr/bin/env python3
"""Genie Wheel Gate — Claude Code `PreToolUse` hook: on a turn that needs prior
art, block the first new file and the plan hand-off until the wheel skill ran.

Why a hook and not a rule: wheel-first lived only in the router's `DO:` line,
which is emitted at conf=high. In one measured route.log that was 49 of the
last 300 turns, and `build_request` at conf=high was 0 of them -- so the rule
read as written and never fired. A rule the model can skip is not a gate.
Shape: a flag file the router sets, cleared by the lookup itself rather than
by a claim that it happened.

Two gated tools, for the two things wheel exists to catch:
  Write of a file that does not exist yet -> about to build.
  ExitPlanMode                            -> about to decide.
Editing an existing file is never gated: surgical changes need no prior art.

Blocks once, then gets out of the way. A PreToolUse hook that only
writes additionalContext has no force at all -- the model's prose is already
out -- so this returns permissionDecision deny. It also has an escape valve:
after 2 denies in a session the gate opens, so a misjudged turn cannot lock the
session. Flag older than 6h is stale (a resumed session), killed by
GENIE_WHEEL_GATE=0, and fails OPEN on any exception like every other hook here.
"""
import json
import os
import re
import sys
import time

DEFAULT_STATE_DIR = os.path.expanduser("~/.genie/state")
STALE_SECONDS = 6 * 3600
MAX_DENIES = 2
# Doc files are how thinking gets written down; blocking a note is noise, and
# ExitPlanMode already covers the decision those notes lead to.
DOC_SUFFIXES = (".md", ".txt", ".rst")
# The wheel skill's step 0 is its own registry lookup, so the command that
# proves a search happened is the one the skill always runs first.
RAN_WHEEL_CMD = re.compile(r"wheel_registry\.py|\.wheel/registry\.tsv")
REASON = (
    "Genie wheel gate: this turn is about building or choosing, and no prior-art "
    "search has run yet. Run the wheel skill first (Claude Code: /wheel, Codex: "
    "$wheel), then redo this. If you already know wheel has nothing to add, say so "
    "in one line and try again -- the gate opens after the second block."
)


def state_dir():
    return os.environ.get("GENIE_STATE_DIR", DEFAULT_STATE_DIR)


def gate_path(session_id):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id or "")) or "unknown"
    return os.path.join(state_dir(), "wheel-%s" % sid)


def open_gate(session_id):
    """Called by the router: this turn needs prior art before building."""
    path = gate_path(session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):  # keep the deny count of an open gate
            with open(path, "w") as f:
                f.write("0")
        else:
            os.utime(path, None)
    except Exception:
        pass


def clear_gate(session_id):
    try:
        os.unlink(gate_path(session_id))
    except Exception:
        pass


def ran_wheel(tool_name, tool_input):
    """True when this call *is* a prior-art search, not a claim of one."""
    if tool_name == "Bash":
        return bool(RAN_WHEEL_CMD.search(str(tool_input.get("command") or "")))
    if tool_name in ("Skill", "SlashCommand"):
        text = " ".join(str(v) for v in tool_input.values() if isinstance(v, str))
        return "wheel" in text.lower()
    return False


def is_gated(tool_name, tool_input):
    if tool_name == "ExitPlanMode":
        return True
    if tool_name != "Write":
        return False
    path = str(tool_input.get("file_path") or "")
    if not path or path.lower().endswith(DOC_SUFFIXES):
        return False
    return not os.path.exists(os.path.expanduser(path))


def deny_count(path):
    try:
        with open(path) as f:
            return int(f.read().strip() or 0)
    except Exception:
        return 0


def hook(raw):
    """-> the JSON to print, or "" to stay out of the way."""
    if os.environ.get("GENIE_WHEEL_GATE") == "0":
        return ""
    try:
        data = json.loads(raw or "{}")
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    tool_name = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    session_id = data.get("session_id")

    if ran_wheel(tool_name, tool_input):
        clear_gate(session_id)
        return ""
    if not is_gated(tool_name, tool_input):
        return ""

    path = gate_path(session_id)
    try:
        mtime = os.stat(path).st_mtime
    except Exception:
        return ""  # no gate open for this session
    if time.time() - mtime > STALE_SECONDS:
        clear_gate(session_id)
        return ""

    n = deny_count(path) + 1
    if n > MAX_DENIES:
        clear_gate(session_id)  # escape valve: never lock a session
        return ""
    try:
        with open(path, "w") as f:
            f.write(str(n))
    except Exception:
        return ""  # cannot count denies -> do not deny
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": REASON,
    }}, ensure_ascii=False)


def main():
    try:
        out = hook(sys.stdin.read())
    except Exception:
        out = ""  # fail open
    if out:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
