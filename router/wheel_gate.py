#!/usr/bin/env python3
"""Genie Wheel Gate — Claude Code `PreToolUse` hook: on a turn that needs prior
art, block the first new file and the plan hand-off until the wheel skill ran.

Why a hook and not a rule: wheel-first lived only in the router's `DO:` line,
which is emitted at conf=high. In one measured route.log that was 49 of the
last 300 turns, and `build_request` at conf=high was 0 of them -- so the rule
read as written and never fired. A rule the model can skip is not a gate.
Shape: a flag file the router sets, cleared by the lookup itself rather than
by a claim that it happened.

Gated calls, for the two things wheel exists to catch:
  a file that does not exist yet -> about to build. Claude Code `Write`, Codex
    `apply_patch` (`*** Add File:`), or a shell heredoc into a new path
    (`cat > x <<EOF`) -- a gate that watches one tool is routed around.
  ExitPlanMode                   -> about to decide.
Editing an existing file is never gated: surgical changes need no prior art.
Neither are notes or tests: a test is not a wheel.

Un-armed sessions get one block too: the first new file in a session that has
not looked up prior art at all. The router arms the gate only on conf=high or
L2, and one measured route.log had 358 of its last 400 turns at conf=low, so
most building happened with no gate. That block is a fact (no lookup ran in
this session), not a guess about intent, and it fires once per session.
ponytail: adding a whole subsystem inside an existing file is still not
caught; catching it needs a diff-size signal, add one if route.log shows it.

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
# ds-claude writes a work order under task/ and dispatches it; the order is not
# product code, so its verify script is not what this gate exists to catch.
# Only while ds-claude is installed, so other repos' task/ dirs stay gated.
DS_CLAUDE_SKILL = "~/.claude/skills/ds-claude/SKILL.md"
DS_CLAUDE_ORDER = re.compile(r"(?:^|/)task/verify\.sh$")
RAN_WHEEL_CMD = re.compile(r"wheel_registry\.py|\.wheel/registry\.tsv")
ADD_FILE = re.compile(r"^\*\*\* Add File: *(.+?) *$", re.M)
# `cat > path <<EOF` / `tee path <<EOF`: a heredoc written to a file is a new
# file by another name. A plain redirect without a heredoc is usually a log.
HEREDOC = re.compile(r"<<-?\s*['\"]?\w")
REDIRECT = re.compile(r"(?:(?<![0-9&>])>(?![>&])|\btee\s+(?:-a\s+)?)\s*['\"]?([^\s'\";|&<>]+)")
TEST_PATH = re.compile(r"(?:^|/)(?:tests?/|test_[^/]*$|[^/]*[._]test\.[^/]*$)")
REASON_FIRST = (
    "Genie wheel gate: first new file in this session and no prior-art search "
    "has run yet. Run the wheel skill Quick first (Claude Code: /wheel, Codex: "
    "$wheel), or check ~/.wheel/registry.tsv for an earlier decision. If wheel "
    "has nothing to add, say so in one line and try again -- this blocks once."
)
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


def seen_path(session_id):
    return gate_path(session_id) + ".seen"


def mark_seen(session_id):
    """This session looked up prior art, or was already told to once."""
    path = seen_path(session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("1")
    except Exception:
        pass


def fresh(path):
    try:
        return time.time() - os.stat(path).st_mtime <= STALE_SECONDS
    except Exception:
        return False


def research_off():
    """Nobody looks for prior art (research off, not handed to a tool): the
    router never arms, so the un-armed block must not either. Same test as the
    router's wheel_ref. Unreadable prefs -> treat as off (fail open)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import prefs
        res = prefs.resolve(None, persist=False)
        return not res.get("handed_off", {}).get("research") \
            and res.get("blocks", {}).get("research") == "off"
    except Exception:
        return True


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


def strings(value):
    """Every string inside a tool input: hosts name the patch field differently."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def new_paths(tool_name, tool_input):
    """-> paths this call would create (may not all be new; is_new decides)."""
    if tool_name == "Write":
        return [str(tool_input.get("file_path") or "")]
    if tool_name == "Bash":
        # only the line that opens the heredoc: its body is data (a commit
        # message with <a@b.com> is not a redirect)
        cmd = str(tool_input.get("command") or "")
        return [p for line in cmd.splitlines() if HEREDOC.search(line)
                for p in REDIRECT.findall(line)]
    if tool_name == "apply_patch" or tool_name.endswith("apply_patch"):
        return [p for s in strings(tool_input) for p in ADD_FILE.findall(s)]
    return []


def is_new(path, cwd):
    if not path or path.lower().endswith(DOC_SUFFIXES) or TEST_PATH.search(path):
        return False
    full = os.path.expanduser(path)
    if not os.path.isabs(full) and cwd:
        full = os.path.join(cwd, full)
    if DS_CLAUDE_ORDER.search(full) and os.path.exists(os.path.expanduser(DS_CLAUDE_SKILL)):
        return False
    return not os.path.exists(full)


def is_gated(tool_name, tool_input, cwd=""):
    if tool_name == "ExitPlanMode":
        return True
    return any(is_new(p, cwd) for p in new_paths(tool_name, tool_input))


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
        mark_seen(session_id)
        return ""
    if not is_gated(tool_name, tool_input, str(data.get("cwd") or "")):
        return ""

    path = gate_path(session_id)
    try:
        mtime = os.stat(path).st_mtime
    except Exception:
        # no gate armed: block the session's first new file once
        if tool_name == "ExitPlanMode" or os.environ.get("GENIE_WHEEL_FIRST") == "0" \
                or fresh(seen_path(session_id)) or research_off():
            return ""
        mark_seen(session_id)
        if not fresh(seen_path(session_id)):
            return ""  # cannot remember the block -> do not block
        return deny(REASON_FIRST)
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
    mark_seen(session_id)
    return deny(REASON)


def deny(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False)


def main():
    try:
        out = hook(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except Exception:
        out = ""  # fail open
    if out:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
