#!/usr/bin/env python3
"""Self-check for the shadow reply audit (Codex and Claude Code hosts). Run: python3 router/test_reply_audit.py

What must hold, and why:
  * NEVER BLOCKS -- shadow mode exists to measure precision first; any stdout or a
    non-zero exit would turn a measurement into an unvetted gate.
  * PREFILTER -- replies without a hedge phrase never reach the judge (cost, privacy).
  * NO GUESSING -- a missing judge or unparsable judge output is logged "unjudged",
    never counted as a pass or a violation, or the precision numbers lie.
  * NO RECURSION -- the judge is itself a Claude Code run; its own Stop must not audit.
A fake `claude` stands in for the judge, so the tests cost nothing and run offline.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "reply_audit.py")
HEDGED = "結論是 A。不過也不能排除是 B，兩者都有可能。"
PLAIN = "結論是 A，證據強：log 第 12 行直接寫出原因。"
FAILS = []


def fake_judge(tmp, body):
    path = os.path.join(tmp, "claude")
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)
    return path


def run(payload, tmp, judge=None, extra_env=None, host="claude"):
    log = os.path.join(tmp, "audit.jsonl")
    env = dict(os.environ, GENIE_AUDIT_LOG=log, GENIE_AUDIT_FOREGROUND="1")
    env["GENIE_AUDIT_" + host.upper()] = judge or "/nonexistent/" + host
    env.pop("GENIE_REPLY_AUDIT_CHILD", None)
    env.pop("GENIE_REPLY_AUDIT", None)
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, HOOK, "--host", host], input=json.dumps(payload), env=env,
                       capture_output=True, text=True, timeout=30)
    rows = []
    if os.path.exists(log):
        with open(log) as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
    return p, rows


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + detail))
    if not cond:
        FAILS.append(name)


def main():
    verdict = '{"violation": true, "rule": "R4", "quote": "不能排除是 B", "why": "no evidence for B"}'
    with tempfile.TemporaryDirectory() as tmp:
        judge = fake_judge(tmp, "echo 'sure:'; echo '%s'" % verdict)
        p, rows = run({"last_assistant_message": PLAIN, "session_id": "s"}, tmp, judge)
        check("plain reply: not logged, judge not called", rows == [], str(rows))
        check("plain reply: silent exit 0", p.returncode == 0 and p.stdout == "", p.stdout)

    with tempfile.TemporaryDirectory() as tmp:
        judge = fake_judge(tmp, "echo 'sure:'; echo '%s'" % verdict)
        p, rows = run({"last_assistant_message": HEDGED, "session_id": "s"}, tmp, judge)
        ok = len(rows) == 1 and rows[0]["verdict"].get("rule") == "R4"
        check("hedged reply: judged and logged", ok, str(rows))
        check("hedged reply: never blocks (no stdout, exit 0)",
              p.returncode == 0 and p.stdout == "", repr(p.stdout))
        check("hedged reply: hit phrase recorded", ok and "不能排除" in rows[0]["hits"][0], str(rows))

    with tempfile.TemporaryDirectory() as tmp:
        _, rows = run({"last_assistant_message": HEDGED}, tmp)
        check("no claude binary: logged as unjudged",
              len(rows) == 1 and rows[0]["verdict"] == "unjudged" and rows[0]["judge"] is None, str(rows))

    with tempfile.TemporaryDirectory() as tmp:
        judge = fake_judge(tmp, "echo 'I think it is fine'")
        _, rows = run({"last_assistant_message": HEDGED}, tmp, judge)
        check("garbage judge output: unjudged, not a guess",
              len(rows) == 1 and rows[0]["verdict"] == "unjudged", str(rows))

    with tempfile.TemporaryDirectory() as tmp:
        judge = fake_judge(tmp, "echo '{\"violation\": \"maybe\"}'")
        _, rows = run({"last_assistant_message": HEDGED}, tmp, judge)
        check("non-bool violation: unjudged", len(rows) == 1 and rows[0]["verdict"] == "unjudged", str(rows))

    with tempfile.TemporaryDirectory() as tmp:
        judge = fake_judge(tmp, "echo '%s'" % verdict)
        for name, payload, env in [
            ("judge child run: skipped (no recursion)", {"last_assistant_message": HEDGED},
             {"GENIE_REPLY_AUDIT_CHILD": "1"}),
            ("GENIE_REPLY_AUDIT=0: skipped", {"last_assistant_message": HEDGED},
             {"GENIE_REPLY_AUDIT": "0"}),
            ("stop_hook_active: skipped", {"last_assistant_message": HEDGED, "stop_hook_active": True}, {}),
            ("missing message: skipped", {"session_id": "s"}, {}),
        ]:
            p, rows = run(payload, tmp, judge, env)
            check(name, rows == [] and p.returncode == 0 and p.stdout == "", str(rows))

    # Codex is the main host: the judge must be the user's own codex, locked read-only.
    with tempfile.TemporaryDirectory() as tmp:
        argv = os.path.join(tmp, "argv.txt")
        judge = fake_judge(tmp, 'printf "%%s\\n" "$@" > %s; echo \'%s\'' % (argv, verdict))
        p, rows = run({"last_assistant_message": HEDGED}, tmp, judge, host="codex")
        args = open(argv).read().split("\n") if os.path.exists(argv) else []
        check("codex host: judged by codex exec",
              len(rows) == 1 and rows[0]["judge"] == "codex" and args[:1] == ["exec"], str(rows))
        check("codex host: judge sandbox is read-only",
              "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only", str(args[:6]))
        check("codex host: never blocks", p.returncode == 0 and p.stdout == "", p.stdout)

    # Real mode: `codex exec` kills a hook still running when it exits, so the hook must return
    # at once and leave the judge to a detached child that still writes the log afterwards.
    with tempfile.TemporaryDirectory() as tmp:
        judge = fake_judge(tmp, "sleep 2; echo '%s'" % verdict)
        t0 = time.time()
        p, rows = run({"last_assistant_message": HEDGED}, tmp, judge, {"GENIE_AUDIT_FOREGROUND": ""})
        took = time.time() - t0
        check("detached: hook returns before the judge finishes",
              took < 1.5 and rows == [] and p.returncode == 0 and p.stdout == "", "%.1fs %s" % (took, rows))
        for _ in range(40):
            _, rows = run({"session_id": "poll"}, tmp)  # no message: reads the log, writes nothing
            if rows:
                break
            time.sleep(0.25)
        check("detached: judge child still logs after the hook exited",
              len(rows) == 1 and rows[0]["verdict"].get("rule") == "R4", str(rows))

    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run([sys.executable, HOOK], input="not json", capture_output=True, text=True,
                           env=dict(os.environ, GENIE_AUDIT_LOG=os.path.join(tmp, "a.jsonl")))
        check("bad stdin: fails open", p.returncode == 0 and p.stdout == "", p.stderr)

    print("%d failed" % len(FAILS) if FAILS else "all passed")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
