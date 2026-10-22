#!/usr/bin/env python3
"""Self-check for deferred Stop-gate notes (defer.py). Run: python3 router/test_defer.py

A Stop hook that blocks adds a visible round. With a session id the gates now
park the note and the next UserPromptSubmit hands it to the model instead.
Four things must hold, or the user is interrupted again or the note is lost:
  * done_gate / blame_gate with a session id: stdout empty, note on disk.
  * genie_router on the next prompt: note rides in additionalContext, file gone.
  * no session id: the old block answer, unchanged.
  * GENIE_DONE_GATE=block: the old block answer even with a session id.
Run as subprocesses: the contract is stdin -> stdout -> files under GENIE_STATE_DIR.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DONE = os.path.join(HERE, "done_gate.py")
BLAME = os.path.join(HERE, "blame_gate.py")
ROUTER = os.path.join(HERE, "genie_router.py")
SID = "defer-selftest-1"


def run(script, payload, env, *args):
    e = dict(os.environ)
    e.update(env)
    return subprocess.run([sys.executable, script, *args], input=json.dumps(payload),
                          capture_output=True, text=True, env=e, cwd=tempfile.gettempdir())


def unrun_edit_transcript(directory):
    """One user turn, one .py edit, nothing run after: done_gate must speak."""
    path = os.path.join(directory, "t.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "user", "message": {"content": "fix it"}}) + "\n")
        fh.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "app.py"}}]}}) + "\n")
    return path


def blocked(p):
    try:
        return json.loads(p.stdout).get("decision") == "block"
    except ValueError:
        return False


def main():
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        state = os.path.join(tmp, "state")
        env = {"GENIE_STATE_DIR": state}
        env.pop("GENIE_DONE_GATE", None)
        note = os.path.join(state, "defer-%s.txt" % SID)
        tp = unrun_edit_transcript(tmp)

        # 1. done_gate defers: silent on stdout, note on disk.
        p = run(DONE, {"transcript_path": tp, "session_id": SID}, env)
        if p.returncode != 0 or p.stdout.strip():
            fails.append("done_gate did not stay silent: rc=%s out=%r" % (p.returncode, p.stdout[:80]))
        if not os.path.exists(note) or "[done_gate]" not in open(note, encoding="utf-8").read():
            fails.append("done_gate wrote no note")

        # 2. blame_gate appends to the same note.
        p = run(BLAME, {"last_assistant_message": "It failed because of a timeout.",
                        "session_id": SID}, env)
        if p.returncode != 0 or p.stdout.strip():
            fails.append("blame_gate did not stay silent: rc=%s out=%r" % (p.returncode, p.stdout[:80]))
        body = open(note, encoding="utf-8").read() if os.path.exists(note) else ""
        if "[blame_gate]" not in body or "[done_gate]" not in body:
            fails.append("blame_gate note missing or overwrote done_gate: %r" % body[:120])

        # 3. next prompt drains the note into additionalContext and deletes the file.
        p = run(ROUTER, {"prompt": "好，繼續", "session_id": SID}, env, "--host", "claude")
        try:
            ctx = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
        except (ValueError, KeyError, TypeError):
            ctx = ""
        if "deferred from last turn" not in ctx or "[done_gate]" not in ctx or "[blame_gate]" not in ctx:
            fails.append("router did not inject the deferred notes: %r" % p.stdout[:200])
        if os.path.exists(note):
            fails.append("router left the note file behind")
        # Drained once: a second prompt must not repeat it.
        p = run(ROUTER, {"prompt": "好，繼續", "session_id": SID}, env, "--host", "claude")
        if "deferred from last turn" in p.stdout:
            fails.append("router injected the same note twice")

        # 4. other sessions never see this session's note.
        run(DONE, {"transcript_path": tp, "session_id": SID}, env)
        p = run(ROUTER, {"prompt": "hi", "session_id": "someone-else"}, env, "--host", "claude")
        if "deferred from last turn" in p.stdout:
            fails.append("note leaked across sessions")

        # 5. no session id -> the old block answer.
        if not blocked(run(DONE, {"transcript_path": tp}, env)):
            fails.append("done_gate without session id did not block")
        if not blocked(run(BLAME, {"last_assistant_message": "The model is too weak."}, env)):
            fails.append("blame_gate without session id did not block")

        # 6. GENIE_DONE_GATE=block restores blocking even with a session id.
        legacy = dict(env, GENIE_DONE_GATE="block")
        if not blocked(run(DONE, {"transcript_path": tp, "session_id": SID}, legacy)):
            fails.append("GENIE_DONE_GATE=block did not restore blocking")

    if fails:
        print("FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("PASS  defer: 2 gates park, router drains once, no cross-session leak, "
          "no-sid and GENIE_DONE_GATE=block still block")
    return 0


if __name__ == "__main__":
    sys.exit(main())
