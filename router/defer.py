"""Deferred Stop-gate notes.

A Stop hook that answers `decision: block` (or even `additionalContext`) adds a
round the user can see: the assistant comes back with a "one more thing"
message. On a phone that reads as the agent stalling. The gates keep their
judgment but hand the note over here; the next UserPromptSubmit
(genie_router.py) drains it into additionalContext, which only the model sees.

Keyed by Claude Code `session_id`. No id -> the caller falls back to blocking,
so a host without session ids keeps the old guarantee. GENIE_DONE_GATE=block
restores blocking everywhere.
"""
import os
import re

HEADER = ("deferred from last turn's Stop gates (the user was not interrupted; "
          "act on these now, do not mention them):")


def _path(session_id):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id or ""))
    if not sid:
        return None
    state_dir = os.environ.get("GENIE_STATE_DIR", os.path.expanduser("~/.genie/state"))
    return os.path.join(state_dir, "defer-%s.txt" % sid)


def legacy_block():
    return os.environ.get("GENIE_DONE_GATE") == "block"


def write(session_id, source, text):
    """Append one note. False when it could not be stored (caller should block)."""
    path = _path(session_id)
    if not path or legacy_block():
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (source, str(text).strip()))
    except OSError:
        return False
    return True


def drain(session_id):
    """Notes stored for this session, header included; "" when none. Deletes the file."""
    path = _path(session_id)
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            body = fh.read().strip()
        os.remove(path)
    except OSError:
        return ""
    return HEADER + "\n" + body if body else ""
