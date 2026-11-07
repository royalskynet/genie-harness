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
    env = dict(os.environ, GENIE_STATE_DIR=state_dir,
               GENIE_PREFS=os.path.join(state_dir, "no-prefs.json"))  # defaults: research on
    env.pop("GENIE_WHEEL_GATE", None)
    env.pop("GENIE_WHEEL_FIRST", None)
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

        # ── un-armed session: the first new file blocks once, then never again ──
        state = os.path.join(td, "s_unarmed")
        r1, rc = run(call("Write", {"file_path": new_file}), state)
        r2, _ = run(call("Write", {"file_path": new_file}), state)
        check("un-armed: first new file blocks once", denied(r1) and rc == 0)
        check("un-armed: second attempt passes", not denied(r2))
        state = os.path.join(td, "s_unarmed_looked")
        run(call("Bash", {"command": "grep -iF x ~/.wheel/registry.tsv"}), state)
        res, _ = run(call("Write", {"file_path": new_file}), state)
        check("un-armed after a registry lookup must not block", not denied(res))
        res, _ = run(call("Write", {"file_path": new_file}), os.path.join(td, "s_first_off"),
                     {"GENIE_WHEEL_FIRST": "0"})
        check("GENIE_WHEEL_FIRST=0 turns off the un-armed block", not denied(res))
        off = os.path.join(td, "prefs-off.json")
        with open(off, "w") as f:
            json.dump({"blocks": {"research": "off"}}, f)
        res, _ = run(call("Write", {"file_path": new_file}), os.path.join(td, "s_research_off"),
                     {"GENIE_PREFS": off})
        check("research=off turns off the un-armed block", not denied(res))
        res, _ = run(call("ExitPlanMode", {"plan": "x"}), os.path.join(td, "s_unarmed_plan"))
        check("un-armed ExitPlanMode must not block", not denied(res))

        # ── other ways to create a file (armed) ──
        def armed_denies(name, tool, inp, cwd=""):
            st = os.path.join(td, "s_" + name)
            arm(st)
            payload = call(tool, inp)
            payload["cwd"] = cwd
            res, _ = run(payload, st)
            return denied(res)
        check("apply_patch Add File must block",
              armed_denies("ap_add", "apply_patch", {"command": "*** Begin Patch\n*** Add File: %s\n+x\n*** End Patch" % new_file}))
        check("apply_patch Update File must not block",
              not armed_denies("ap_upd", "apply_patch", {"command": "*** Begin Patch\n*** Update File: %s\n@@\n-x\n+y\n*** End Patch" % existing}))
        check("heredoc into a new file must block",
              armed_denies("hd_new", "Bash", {"command": "cat > %s <<'EOF'\nprint(1)\nEOF" % new_file}))
        check("relative heredoc path resolves against cwd",
              armed_denies("hd_rel", "Bash", {"command": "tee thing.py <<EOF\nx\nEOF"}, td))
        check("heredoc into an existing file must not block",
              not armed_denies("hd_old", "Bash", {"command": "cat > already.py <<EOF\nx\nEOF"}, td))
        check("plain redirect (no heredoc) must not block",
              not armed_denies("redir", "Bash", {"command": "echo x > %s 2>&1" % new_file}))
        check("new test file must not block",
              not armed_denies("testf", "Write", {"file_path": os.path.join(td, "tests", "test_x.py")}))

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

        # ── ds-claude work order: skipped only while ds-claude is installed ──
        order = os.path.join(td, "repo", "task", "verify.sh")
        home = os.path.join(td, "home")
        state = os.path.join(td, "s_ds_absent")
        arm(state)
        res, _ = run(call("Write", {"file_path": order}), state, {"HOME": home})
        check("task/verify.sh without ds-claude must block", denied(res))
        os.makedirs(os.path.join(home, ".claude", "skills", "ds-claude"))
        open(os.path.join(home, ".claude", "skills", "ds-claude", "SKILL.md"), "w").close()
        state = os.path.join(td, "s_ds_present")
        arm(state)
        res, _ = run(call("Write", {"file_path": order}), state, {"HOME": home})
        check("task/verify.sh with ds-claude must not block", not denied(res))
        res, _ = run(call("Write", {"file_path": new_file}), state, {"HOME": home})
        check("ds-claude installed still gates other new files", denied(res))

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
