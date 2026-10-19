#!/usr/bin/env python3
"""Self-check for the wheel gate. Run: python3 router/test_wheel_gate.py

Two halves, both load-bearing:
  * MUST BLOCK -- a gate that lets the first new file through is the rule we
    already had, which route.log shows never fired.
  * MUST PASS  -- a gate that blocks ordinary work gets switched off by hand
    within a day, and then there is no gate at all. Edits to existing files,
    notes, un-armed sessions, stale flags and the third attempt all go through.

Run as a subprocess: the real contract is stdin -> stdout -> exit code.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "wheel_gate.py")
sys.path.insert(0, HERE)
import wheel_gate  # noqa: E402  (same dir, used for open_gate/gate_path)


def run(payload, state_dir, env_extra=None):
    """-> (parsed stdout or None, exit code)."""
    env = dict(os.environ, GENIE_STATE_DIR=state_dir)
    env.pop("GENIE_WHEEL_GATE", None)
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, GATE], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=20)
    out = p.stdout.strip()
    return (json.loads(out) if out else None), p.returncode


def call(tool, inp, sid="s1"):
    return {"hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": inp, "session_id": sid}


def denied(res):
    return bool(res) and res.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def arm(state_dir, sid="s1"):
    os.environ["GENIE_STATE_DIR"] = state_dir
    wheel_gate.open_gate(sid)


def main():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as td:
        new_file = os.path.join(td, "thing.py")
        existing = os.path.join(td, "already.py")
        with open(existing, "w") as f:
            f.write("x = 1\n")

        # ── MUST PASS: nothing armed, nothing blocked ──
        state = os.path.join(td, "s_unarmed")
        res, rc = run(call("Write", {"file_path": new_file}), state)
        check("un-armed session must not be blocked", not denied(res) and rc == 0)

        # ── MUST BLOCK ──
        state = os.path.join(td, "s_armed")
        arm(state)
        res, _ = run(call("Write", {"file_path": new_file}), state)
        check("armed + new file must block", denied(res))
        arm(state + "2")
        res, _ = run(call("ExitPlanMode", {"plan": "do it"}), state + "2")
        check("armed + ExitPlanMode must block", denied(res))

        # ── MUST PASS: surgical and doc work ──
        state = os.path.join(td, "s_pass")
        arm(state)
        res, _ = run(call("Write", {"file_path": existing}), state)
        check("existing file must not block", not denied(res))
        res, _ = run(call("Edit", {"file_path": new_file}), state)
        check("Edit must not block", not denied(res))
        res, _ = run(call("Write", {"file_path": os.path.join(td, "notes.md")}), state)
        check("new .md must not block", not denied(res))

        # ── the search itself clears the gate ──
        state = os.path.join(td, "s_clear")
        arm(state)
        res, _ = run(call("Bash", {"command": "python3 ~/dev/wheel/skills/wheel/scripts/wheel_registry.py find x"}), state)
        check("registry lookup must not block", not denied(res))
        res, _ = run(call("Write", {"file_path": new_file}), state)
        check("after the lookup the gate is open", not denied(res))

        state = os.path.join(td, "s_skill")
        arm(state)
        run(call("Skill", {"skill": "wheel", "args": "Quick"}), state)
        res, _ = run(call("Write", {"file_path": new_file}), state)
        check("running the wheel skill clears the gate", not denied(res))

        # A lookalike command must NOT count as having searched.
        state = os.path.join(td, "s_fake")
        arm(state)
        run(call("Bash", {"command": "echo I already know the wheel answer"}), state)
        res, _ = run(call("Write", {"file_path": new_file}), state)
        check("talking about wheel does not clear the gate", denied(res))

        # ── escape valve: blocks twice, third attempt goes through ──
        state = os.path.join(td, "s_valve")
        arm(state)
        r1, _ = run(call("Write", {"file_path": new_file}), state)
        r2, _ = run(call("Write", {"file_path": new_file}), state)
        r3, _ = run(call("Write", {"file_path": new_file}), state)
        check("escape valve: deny, deny, then pass",
              denied(r1) and denied(r2) and not denied(r3))

        # ── kill switch ──
        state = os.path.join(td, "s_off")
        arm(state)
        res, _ = run(call("Write", {"file_path": new_file}), state,
                     {"GENIE_WHEEL_GATE": "0"})
        check("GENIE_WHEEL_GATE=0 disables the gate", not denied(res))

        # ── stale flag (resumed session) ──
        state = os.path.join(td, "s_stale")
        arm(state)
        path = wheel_gate.gate_path("s1")
        os.utime(path, (0, 0))
        res, _ = run(call("Write", {"file_path": new_file}), state)
        check("flag older than 6h is stale", not denied(res))

        # ── fail open on garbage ──
        env = dict(os.environ, GENIE_STATE_DIR=state)
        p = subprocess.run([sys.executable, GATE], input="not json",
                           capture_output=True, text=True, env=env, timeout=20)
        check("unparseable stdin fails open", p.returncode == 0 and not p.stdout.strip())

    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("wheel gate self-check: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
