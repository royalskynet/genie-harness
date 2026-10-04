#!/usr/bin/env python3
"""Self-check for the Stop done gate. Run: python3 router/test_done_gate.py

Two halves and both matter equally:
  * MUST BLOCK -- the gate is worthless if unrun edits walk through.
  * MUST PASS  -- a gate that blocks a beginner's normal work gets disabled by
    hand within a day, and then nobody has a gate at all. Prose edits, pure
    questions, and the `stop_hook_active` re-entry are all exempt on purpose.

Every transcript here is built from scratch in a tempdir with tempfile, so the
tests never depend on a real Claude Code session's shape drifting underneath
them. Run as a subprocess: the real contract is stdin → stdout → exit code.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "done_gate.py")


def user(text="fix it", as_list=False):
    """A real human turn: `content` is a string, or a list with no tool_result."""
    if as_list:
        return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}
    return {"type": "user", "message": {"content": text}}


def tool_result(text="ok"):
    """A tool result coming back as `type == "user"` -- NOT a human turn."""
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "content": text}]}}


def assistant(*blocks):
    return {"type": "assistant", "message": {"content": list(blocks)}}


def edit(path, name="Edit", key="file_path"):
    return {"type": "tool_use", "name": name, "input": {key: path}}


def bash(command="pytest"):
    return {"type": "tool_use", "name": "Bash", "input": {"command": command}}


def write_transcript(directory, lines, name="t.jsonl"):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write((line if isinstance(line, str) else json.dumps(line)) + "\n")
    return path


def run(payload):
    return subprocess.run([sys.executable, GATE], input=payload,
                          capture_output=True, text=True,
                          cwd=tempfile.gettempdir())


def call(transcript_path, active=False):
    return run(json.dumps({"transcript_path": transcript_path,
                           "stop_hook_active": active}))


# --- must block: code changed, nothing run after the last change -------------
MUST_BLOCK = [
    ("edited .py, never ran", [user(), assistant(edit("app.py"))]),
    ("wrote .py, never ran", [user(), assistant(edit("app.py", name="Write"))]),
    ("MultiEdit .ts, never ran", [user(), assistant(edit("a.ts", name="MultiEdit"))]),
    ("NotebookEdit uses notebook_path",
     [user(), assistant(edit("nb.ipynb", name="NotebookEdit", key="notebook_path"))]),
    ("bash ran BEFORE the edit, not after",
     [user(), assistant(bash(), edit("app.py"))]),
    ("two edits, no run after either",
     [user(), assistant(edit("a.py"), edit("b.js"))]),
    ("ran, then edited again",
     [user(), assistant(bash(), edit("a.py"), bash(), edit("b.py"))]),
    ("no path on the edit at all", [user(), assistant(edit(None))]),
    ("user turn is a content list",
     [user(as_list=True), assistant(edit("a.py"))]),
]

# --- must pass: nothing to run, or already handled --------------------------
MUST_PASS = [
    ("pure question, no tools", [user(), assistant({"type": "text", "text": "run pytest"}),
                                 assistant({"type": "text", "text": "all 12 passed"})]),
    ("only .md edited", [user(), assistant(edit("README.md", name="Write"))]),
    ("only .txt edited", [user(), assistant(edit("notes.txt"))]),
    ("ran bash after the edit", [user(), assistant(edit("a.py"), bash("pytest"))]),
    ("edit from a previous turn only",
     [user("first"), assistant(edit("a.py")), user("wait, why?"),
      assistant({"type": "text", "text": "because..."})]),
    ("tool_result is not a user turn",
     [user(), assistant(edit("a.py")), tool_result(), assistant(bash("pytest"))]),
    ("doc edit then code edit", [user(), assistant(edit("README.md"), edit("a.py"), bash())]),
    ("only reads, no edits", [user(), assistant({"type": "tool_use", "name": "Read",
                                                 "input": {"file_path": "a.py"}})]),
    ("stop_hook_active re-entry", [user(), assistant(edit("a.py"))]),
    ("no user message at all", [assistant(edit("a.py"))]),
    ("half-written last line",
     [user(), assistant(edit("a.py"), bash()), '{"type":"assist']),
    ("empty transcript", []),
]

# Any truthy `stop_hook_active` counts as a re-entry. Claude Code sets it so a
# blocking Stop hook cannot loop on itself, so it is checked for truthiness, not
# `is True`: a hook that re-blocks on a re-entry hangs the session.
REENTRY_VALUES = [True, "true", 1, "yes"]

# --- malformed stdin must fail open, never block, never crash ---------------
MALFORMED = [
    "",
    "not json",
    "{}",
    "[]",
    '{"transcript_path": null}',
    '{"transcript_path": ""}',
    '{"transcript_path": 123}',
    '{"transcript_path": "/nonexistent/transcript.jsonl"}',
]


def check_block_cases(tmp, fails):
    for i, (label, lines) in enumerate(MUST_BLOCK):
        path = write_transcript(tmp, lines, "block%d.jsonl" % i)
        p = call(path)
        if p.returncode != 0:
            fails.append("NOT BLOCKED (rc=%d): %s -> %r" % (p.returncode, label, p.stderr.strip()[:70]))
            continue
        try:
            out = json.loads(p.stdout)
        except Exception:
            fails.append("NOT BLOCKED (unparseable output): %s -> %r" % (label, p.stdout[:80]))
            continue
        if out.get("decision") != "block" or not out.get("reason"):
            fails.append("NOT BLOCKED: %s -> %r" % (label, p.stdout[:90]))


def check_pass_cases(tmp, fails):
    for i, (label, lines) in enumerate(MUST_PASS):
        active = label == "stop_hook_active re-entry"
        path = write_transcript(tmp, lines, "pass%d.jsonl" % i)
        p = call(path, active=active)
        if p.returncode != 0 or p.stdout.strip():
            fails.append("FALSE POSITIVE: %s -> rc=%d %r" % (label, p.returncode, p.stdout.strip()[:90]))


def check_reentry(tmp, fails):
    """The same unrun edit must pass for every truthy re-entry flag."""
    path = write_transcript(tmp, [user(), assistant(edit("a.py"))], "reentry.jsonl")
    for value in REENTRY_VALUES:
        p = run(json.dumps({"transcript_path": path, "stop_hook_active": value}))
        if p.returncode != 0 or p.stdout.strip():
            fails.append("RE-ENTRY LOOP RISK: stop_hook_active=%r blocked -> rc=%d %r"
                         % (value, p.returncode, p.stdout.strip()[:70]))


def check_malformed(tmp, fails):
    for junk in MALFORMED:
        p = run(junk)
        if p.returncode != 0 or p.stdout.strip():
            fails.append("MALFORMED INPUT NOT SAFE: %r rc=%d out=%r" % (junk, p.returncode, p.stdout[:60]))


def check_hook_registered(fails):
    """A5 in test_repo.py only reads the Codex hooks.json; this one is Claude-only."""
    path = os.path.join(os.path.dirname(HERE), "claude", "hooks.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        cmds = json.dumps(data["hooks"]["Stop"])
    except Exception as e:
        fails.append("claude/hooks.json has no usable Stop hook: %r" % e)
        return
    if "done_gate.py" not in cmds:
        fails.append("claude/hooks.json Stop hook does not reference done_gate.py")
    if "${CLAUDE_PLUGIN_ROOT}" not in cmds:
        fails.append("claude/hooks.json Stop hook is not plugin-root relative")


def main():
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        check_block_cases(tmp, fails)
        check_pass_cases(tmp, fails)
        check_reentry(tmp, fails)
        check_malformed(tmp, fails)
    check_hook_registered(fails)

    total = (len(MUST_BLOCK) + len(MUST_PASS) + len(MALFORMED) + len(REENTRY_VALUES))
    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  %d cases: %d must-block, %d must-pass, %d re-entry, %d malformed-input, "
          "hook registered" % (total, len(MUST_BLOCK), len(MUST_PASS),
                              len(REENTRY_VALUES), len(MALFORMED)))


if __name__ == "__main__":
    main()