#!/usr/bin/env python3
"""Genie Fail Streak — Claude Code `PostToolUse` / `PostToolUseFailure` hook:
track consecutive failures of the same command fingerprint and warn once at 2.

Events (official, fix 0324/9777): Bash failure only emits `PostToolUseFailure`
with `error` string (often starts with `Exit code N`), **no** `tool_response`.
Success only emits `PostToolUse`. The two are mutually exclusive.

State: `$GENIE_STATE_DIR/fail-<session_id>.json` (default `~/.genie/state`),
atomic write via temp file + os.replace. session_id sanitized to `[A-Za-z0-9_-]`.
Cleanup: remove `fail-*.json` with mtime > 7 days on every run.
Failure policy: fail OPEN — any exception → no output, exit 0.
"""
import json
import os
import re
import sys
import tempfile
import time


DEFAULT_STATE_DIR = os.path.expanduser("~/.genie/state")
EXCLUDED_COMMANDS = frozenset(("grep", "rg", "test", "[", "diff", "cmp"))
FINGERPRINT_SKIP_PREFIXES = ("sudo",)
WARNING_MESSAGE = (
    "Genie: the same kind of command ({fp}) failed twice in a row. "
    "Stop. Re-read the error text, state your hypothesis in one sentence, "
    "then try once more. If it fails a third time, change approach or ask the user."
)


def _sanitize_session_id(sid):
    if not isinstance(sid, str):
        return "unknown"
    return re.sub(r"[^A-Za-z0-9_-]", "", sid) or "unknown"


def _extract_fingerprint(command):
    if not command or not isinstance(command, str):
        return None
    tokens = command.strip().split()
    if not tokens:
        return None

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if "=" in tok and not tok.startswith("-"):
            i += 1
            continue
        if tok in FINGERPRINT_SKIP_PREFIXES:
            i += 1
            continue
        break

    if i >= len(tokens):
        return None

    first = tokens[i]
    if i + 1 < len(tokens):
        second = tokens[i + 1]
        if not second.startswith("-"):
            return first + " " + second
    return first


def _is_excluded_failure(command, error):
    fp = _extract_fingerprint(command)
    if not fp:
        return False
    first_token = fp.split()[0]
    if first_token not in EXCLUDED_COMMANDS:
        return False
    return "Exit code 1" in error


def _state_path(state_dir, session_id):
    safe_sid = _sanitize_session_id(session_id)
    return os.path.join(state_dir, f"fail-{safe_sid}.json")


def _load_state(state_dir, session_id):
    path = _state_path(state_dir, session_id)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"counts": {}, "warned": {}}


def _save_state(state_dir, session_id, state):
    path = _state_path(state_dir, session_id)
    os.makedirs(state_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=state_dir, delete=False, prefix=".fail-", suffix=".tmp"
    ) as tf:
        json.dump(state, tf)
        tmp_name = tf.name
    try:
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except Exception:
            pass
        raise


def _cleanup_old_files(state_dir):
    try:
        cutoff = time.time() - 7 * 86400
        for entry in os.scandir(state_dir):
            if not entry.name.startswith("fail-") or not entry.name.endswith(".json"):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    os.unlink(entry.path)
            except Exception:
                pass
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read() or "{}"
        data = json.loads(raw)
    except Exception:
        return  # fail open

    tool_name = data.get("tool_name")
    if tool_name != "Bash":
        return

    hook_event = data.get("hook_event_name")
    session_id = data.get("session_id")
    tool_input = data.get("tool_input") or {}
    command = tool_input.get("command")
    error = data.get("error")

    if not session_id or not command:
        return

    state_dir = os.environ.get("GENIE_STATE_DIR", DEFAULT_STATE_DIR)

    try:
        _cleanup_old_files(state_dir)
        state = _load_state(state_dir, session_id)
        fp = _extract_fingerprint(command)
        if not fp:
            return

        counts = state.setdefault("counts", {})
        warned = state.setdefault("warned", {})

        if hook_event == "PostToolUseFailure":
            if _is_excluded_failure(command, error or ""):
                return
            counts[fp] = counts.get(fp, 0) + 1
            if counts[fp] >= 2 and not warned.get(fp):
                warned[fp] = True
                _save_state(state_dir, session_id, state)
                out = {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUseFailure",
                        "additionalContext": WARNING_MESSAGE.format(fp=fp),
                    }
                }
                json.dump(out, sys.stdout, ensure_ascii=False)
                return
            _save_state(state_dir, session_id, state)
        elif hook_event == "PostToolUse":
            if fp in counts:
                counts[fp] = 0
                warned.pop(fp, None)
                _save_state(state_dir, session_id, state)
    except Exception:
        return  # fail open


if __name__ == "__main__":
    main()