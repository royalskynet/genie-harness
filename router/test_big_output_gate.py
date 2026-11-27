#!/usr/bin/env python3
"""Self-check for big_output_gate.py. Run: python3 router/test_big_output_gate.py

Two halves:
  * MUST WARN -- a result over the line budget produces an additionalContext
    note naming the count, for dict (Bash {stdout}) and plain-string responses.
  * MUST PASS -- results inside the budget, an env-raised/lowered budget,
    empty or malformed payloads all stay silent, exit 0 (fail open).

Run as a subprocess: the real contract is stdin -> stdout -> exit code.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "big_output_gate.py")
ROOT = os.path.dirname(HERE)


def run(payload, env_extra=None):
    """-> (parsed stdout or None, exit code)."""
    env = dict(os.environ)
    env.pop("GENIE_BIG_OUTPUT_LINES", None)
    env.pop("GENIE_BIG_OUTPUT_SHADOW", None)
    env.pop("GENIE_BIG_OUTPUT_SHADOW_LOG", None)
    env.update(env_extra or {})
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([sys.executable, GATE], input=raw,
                       capture_output=True, text=True, env=env, timeout=20)
    out = p.stdout.strip()
    return (json.loads(out) if out else None), p.returncode


def call(tool, response):
    return {"hook_event_name": "PostToolUse", "tool_name": tool,
            "session_id": "s1", "tool_input": {}, "tool_response": response}


def warned(res):
    return bool(res) and bool(
        res.get("hookSpecificOutput", {}).get("additionalContext"))


def main():
    fails = []

    res, rc = run(call("Bash", {"stdout": "line\n" * 250, "stderr": ""}))
    if rc != 0 or not warned(res):
        fails.append("FAIL 1: 250-line stdout produced no warning (rc=%d)" % rc)
    else:
        ctx = res["hookSpecificOutput"]["additionalContext"]
        if not re.search(r"returned \d+ lines", ctx):
            fails.append("FAIL 1: warning does not name the line count: %s"
                         % ctx[:120])

    res, rc = run(call("Bash", {"stdout": "ok\n" * 50}))
    if rc != 0 or res is not None:
        fails.append("FAIL 2: 50-line output should stay silent")

    res, rc = run(call("Read", "x\n" * 10), {"GENIE_BIG_OUTPUT_LINES": "5"})
    if not warned(res):
        fails.append("FAIL 3: GENIE_BIG_OUTPUT_LINES=5 should flag 11 lines")

    res, rc = run(call("Read", "x\n" * 10), {"GENIE_BIG_OUTPUT_LINES": "50"})
    if res is not None:
        fails.append("FAIL 3b: budget 50 should not flag 11 lines")

    res, rc = run(call("WebFetch", "body\n" * 300))
    if not warned(res):
        fails.append("FAIL 4: plain-string tool_response not measured")

    with tempfile.TemporaryDirectory() as td:
        logp = os.path.join(td, "shadow.jsonl")
        res, rc = run(call("Bash", {"stdout": "shadow-secret\n" * 250}),
                      {"GENIE_BIG_OUTPUT_SHADOW": "1",
                       "GENIE_BIG_OUTPUT_SHADOW_LOG": logp})
        if rc != 0 or res is not None:
            fails.append("FAIL 4s: shadow mode must stay silent and exit 0")
        else:
            try:
                rows = [json.loads(x) for x in open(logp, encoding="utf-8")]
                if len(rows) != 1 or rows[0].get("lines") != 251 or rows[0].get("tool") != "Bash":
                    fails.append("FAIL 4s: shadow log missing metadata row: %r" % rows)
                rawlog = open(logp, encoding="utf-8").read()
                if "shadow-secret" in rawlog or "tool_response" in rawlog or "tool_input" in rawlog:
                    fails.append("FAIL 4s: shadow log leaked content/input")
            except Exception as e:
                fails.append("FAIL 4s: shadow log unreadable: %s" % e)

    res, rc = run("this is not json")
    if rc != 0 or res is not None:
        fails.append("FAIL 5: malformed stdin must fail open (silent, exit 0)")

    res, rc = run(call("Bash", {}))
    if rc != 0 or res is not None:
        fails.append("FAIL 6: empty tool_response must stay silent")

    try:
        hooks_data = json.load(open(os.path.join(ROOT, "claude", "hooks.json")))
        cmds = json.dumps(hooks_data.get("hooks", {}).get("PostToolUse", []))
        if "big_output_gate.py" not in cmds:
            fails.append("FAIL 7: PostToolUse in claude/hooks.json lacks big_output_gate.py")
        if "${CLAUDE_PLUGIN_ROOT}" not in cmds:
            fails.append("FAIL 7: big_output_gate hook is not plugin-root relative")
    except Exception as e:
        fails.append("FAIL 7: could not read claude/hooks.json: %s" % e)

    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  all cases: warn over budget, silent under, env budget, "
          "string response, shadow metadata-only, fail-open, hook registered")


if __name__ == "__main__":
    main()
