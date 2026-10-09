#!/usr/bin/env python3
"""Self-check for the fail streak hook. Run: python3 router/test_fail_streak.py

Tests the PostToolUse / PostToolUseFailure hook that tracks consecutive
failures of the same command fingerprint and warns once at 2.

Every test runs in a tempdir with tempfile, so tests never depend on a real
Claude Code session's shape drifting underneath them. Run as a subprocess:
the real contract is stdin → stdout → exit code.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "fail_streak.py")


def make_payload(event, session_id="s1", command="npm run build", error=None):
    payload = {
        "hook_event_name": event,
        "tool_name": "Bash",
        "session_id": session_id,
        "tool_input": {"command": command},
    }
    if error is not None:
        payload["error"] = error
    return json.dumps(payload)


def run(payload, env=None, state_dir=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    if state_dir:
        e["GENIE_STATE_DIR"] = state_dir
    return subprocess.run(
        [sys.executable, HOOK],
        input=payload,
        capture_output=True,
        text=True,
        env=e,
        cwd=tempfile.gettempdir(),
    )


def has_warning(output):
    try:
        data = json.loads(output.strip())
        return (
            data.get("hookSpecificOutput", {}).get("hookEventName") == "PostToolUseFailure"
            and "failed twice" in data.get("hookSpecificOutput", {}).get("additionalContext", "")
        )
    except Exception:
        return False


def main():
    fails = []

    with tempfile.TemporaryDirectory() as tmp:
        # 1. Two consecutive failures → injection
        p1 = run(make_payload("PostToolUseFailure", "s1", "npm run build", "Exit code 1\nboom"), state_dir=tmp)
        if p1.returncode != 0 or p1.stdout.strip():
            fails.append("FAIL 1a: first failure should produce no output")
        p2 = run(make_payload("PostToolUseFailure", "s1", "npm run build", "Exit code 1\nboom"), state_dir=tmp)
        if p2.returncode != 0 or not has_warning(p2.stdout):
            fails.append("FAIL 1b: second failure should inject warning")

        # 2. Only inject once (3rd time no output)
        p3 = run(make_payload("PostToolUseFailure", "s1", "npm run build", "Exit code 1\nboom"), state_dir=tmp)
        if p3.returncode != 0 or p3.stdout.strip():
            fails.append("FAIL 2: third failure should not inject again")

        # 3. Success in between resets count
        p4 = run(make_payload("PostToolUseFailure", "s2", "pytest", "Exit code 1\ntest failed"), state_dir=tmp)
        if p4.returncode != 0 or p4.stdout.strip():
            fails.append("FAIL 3a: first failure for s2")
        p5 = run(make_payload("PostToolUse", "s2", "pytest"), state_dir=tmp)
        if p5.returncode != 0 or p5.stdout.strip():
            fails.append("FAIL 3b: success should produce no output")
        p6 = run(make_payload("PostToolUseFailure", "s2", "pytest", "Exit code 1\ntest failed"), state_dir=tmp)
        if p6.returncode != 0 or p6.stdout.strip():
            fails.append("FAIL 3c: after success, first failure again should not warn")
        p7 = run(make_payload("PostToolUseFailure", "s2", "pytest", "Exit code 1\ntest failed"), state_dir=tmp)
        if p7.returncode != 0 or not has_warning(p7.stdout):
            fails.append("FAIL 3d: second failure after reset should warn")

        # 4. Different fingerprints don't add up
        p8 = run(make_payload("PostToolUseFailure", "s3", "git push origin", "Exit code 1\nfailed"), state_dir=tmp)
        if p8.returncode != 0 or p8.stdout.strip():
            fails.append("FAIL 4a: first fingerprint failure")
        p9 = run(make_payload("PostToolUseFailure", "s3", "git pull origin", "Exit code 1\nfailed"), state_dir=tmp)
        if p9.returncode != 0 or p9.stdout.strip():
            fails.append("FAIL 4b: different fingerprint should not accumulate")
        p10 = run(make_payload("PostToolUseFailure", "s3", "git push origin", "Exit code 1\nfailed"), state_dir=tmp)
        if p10.returncode != 0 or not has_warning(p10.stdout):
            fails.append("FAIL 4c: second failure of same fingerprint should warn")

        # 5. grep exit 1 doesn't count
        p11 = run(make_payload("PostToolUseFailure", "s4", "grep pattern file.txt", "Exit code 1\n"), state_dir=tmp)
        if p11.returncode != 0 or p11.stdout.strip():
            fails.append("FAIL 5a: grep exit 1 should not count")
        p12 = run(make_payload("PostToolUseFailure", "s4", "grep pattern file.txt", "Exit code 1\n"), state_dir=tmp)
        if p12.returncode != 0 or p12.stdout.strip():
            fails.append("FAIL 5b: second grep exit 1 should not count")
        p13 = run(make_payload("PostToolUseFailure", "s4", "grep pattern file.txt", "Exit code 1\n"), state_dir=tmp)
        if p13.returncode != 0 or p13.stdout.strip():
            fails.append("FAIL 5c: third grep exit 1 should not count")

        # Also test rg, test, [, diff, cmp
        for cmd in ["rg pattern", "test -f file", "[ -f file ]", "diff a b", "cmp a b"]:
            p = run(make_payload("PostToolUseFailure", "s4", cmd, "Exit code 1\n"), state_dir=tmp)
            if p.returncode != 0 or p.stdout.strip():
                fails.append(f"FAIL 5x: {cmd} exit 1 should not count")

        # 6. Bad JSON → no output, rc=0
        p14 = run("not json", state_dir=tmp)
        if p14.returncode != 0 or p14.stdout.strip() or p14.stderr.strip():
            fails.append("FAIL 6: bad JSON should fail open (rc=0, no output)")

        # 7. Non-Bash ignored
        p15 = run(json.dumps({"hook_event_name": "PostToolUseFailure", "tool_name": "Write", "session_id": "s5"}), state_dir=tmp)
        if p15.returncode != 0 or p15.stdout.strip():
            fails.append("FAIL 7: non-Bash tool should be ignored")

    # 8. 7-day old files cleaned up
    with tempfile.TemporaryDirectory() as tmp:
        old_file = os.path.join(tmp, "fail-old.json")
        with open(old_file, "w") as fh:
            json.dump({"counts": {"foo": 1}}, fh)
        old_time = time.time() - 8 * 86400
        os.utime(old_file, (old_time, old_time))

        new_file = os.path.join(tmp, "fail-new.json")
        with open(new_file, "w") as fh:
            json.dump({"counts": {"bar": 1}}, fh)

        p = run(make_payload("PostToolUseFailure", "cleanup", "npm run build", "Exit code 1\n"), state_dir=tmp)
        if p.returncode != 0:
            fails.append("FAIL 8a: cleanup run should succeed")

        if os.path.exists(old_file):
            fails.append("FAIL 8b: old file should have been deleted")
        if not os.path.exists(new_file):
            fails.append("FAIL 8c: new file should not have been deleted")

    # 9. Hook registered in claude/hooks.json
    hooks_path = os.path.join(os.path.dirname(HERE), "claude", "hooks.json")
    try:
        with open(hooks_path, encoding="utf-8") as fh:
            hooks_data = json.load(fh)
        hooks = hooks_data.get("hooks", {})
        if "PostToolUseFailure" not in hooks:
            fails.append("FAIL 9: PostToolUseFailure not in claude/hooks.json")
        if "PostToolUse" not in hooks:
            fails.append("FAIL 9: PostToolUse not in claude/hooks.json")
        for event in ("PostToolUseFailure", "PostToolUse"):
            if event in hooks:
                cmds = json.dumps(hooks[event])
                if "fail_streak.py" not in cmds:
                    fails.append(f"FAIL 9: {event} hook does not reference fail_streak.py")
                if "${CLAUDE_PLUGIN_ROOT}" not in cmds:
                    fails.append(f"FAIL 9: {event} hook is not plugin-root relative")
                if "matcher" not in str(hooks[event]):
                    fails.append(f"FAIL 9: {event} hook missing matcher")
    except Exception as e:
        fails.append(f"FAIL 9: could not read claude/hooks.json: {e}")

    total_cases = 15  # approximate count
    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  all cases: 2-fail injection, single warn, reset on success, "
          "fingerprint isolation, excluded commands, bad JSON safe, "
          "non-Bash ignored, 7-day cleanup, hooks registered")


if __name__ == "__main__":
    main()