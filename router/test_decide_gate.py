#!/usr/bin/env python3
"""Self-check for the decide gate. Run: python3 router/test_decide_gate.py

Same contract as the other gates: stdin -> stdout -> exit code, run as a
subprocess. MUST_DENY are questions the gate exists to catch; MUST_PASS are the
ones a user really has to see, and a gate that swallows them gets turned off.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "decide_gate.py")


def ask(question, *options, multi=False):
    opts = [{"label": o[0], "description": o[1]} if isinstance(o, tuple) else {"label": o, "description": ""}
            for o in options]
    return {"tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": question, "header": "q",
                                          "multiSelect": multi, "options": opts}]}}


LOG = os.path.join(tempfile.mkdtemp(), "decide.log")


def run(payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, GATE], input=raw, capture_output=True,
                          text=True, cwd=tempfile.gettempdir(),
                          env=dict(os.environ, GENIE_DECIDE_LOG=LOG))


def log_lines():
    if not os.path.exists(LOG):
        return []
    with open(LOG, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


MUST_DENY = [
    ("reversible, one recommended -> take it",
     ask("Report format?", "Markdown (Recommended)", "PDF"), "Do it instead of asking"),
    ("reversible, 建議 marker",
     ask("報告格式？", "Markdown（建議）", "PDF"), "Do it instead of asking"),
    ("irreversible, no recommendation",
     ask("Force push to main?", "Yes", "No"), "no single option"),
    ("irreversible, recommendation without a reason",
     ask("Delete the old backups?", "Delete (Recommended)", "Keep"), "gives no reason"),
    ("irreversible in Chinese, no recommendation",
     ask("要發布到公開頁面嗎？", "發布", "先不要"), "no single option"),
]

MUST_PASS = [
    ("irreversible with recommendation and reason",
     ask("Delete the old backups?", ("Delete (Recommended)", "Three off-site copies exist; this frees 40 GB"), "Keep")),
    ("reversible, no recommendation", ask("Report format?", "Markdown", "PDF")),
    ("reversible, two recommended", ask("Report format?", "Markdown (Recommended)", "PDF (Recommended)")),
    ("multi-select", ask("Which reports?", "Markdown (Recommended)", "PDF", multi=True)),
    ("single option", ask("Report format?", "Markdown (Recommended)")),
    ("another tool", {"tool_name": "Bash", "tool_input": {"command": "ls"}}),
]

MALFORMED = ["", "not json", "{}", "[]", '{"tool_name": "AskUserQuestion"}',
             '{"tool_name": "AskUserQuestion", "tool_input": {"questions": "x"}}']


def main():
    fails = []
    for label, payload, needle in MUST_DENY:
        before = len(log_lines())
        p = run(payload)
        try:
            out = json.loads(p.stdout)["hookSpecificOutput"]
            reason = out["permissionDecisionReason"]
            ok = out["permissionDecision"] == "deny" and needle in reason
        except (ValueError, KeyError, TypeError):
            ok, reason = False, ""
        if not ok:
            fails.append("NOT DENIED: %s -> %r" % (label, p.stdout[:120]))
            continue
        if not reason.startswith("Genie decide_gate: "):
            fails.append("NO SOURCE PREFIX: %s -> %r" % (label, reason[:60]))
        recs = log_lines()[before:]
        kind = "take" if "instead of asking" in reason else "lint"
        q = payload["tool_input"]["questions"][0]["question"]
        if len(recs) != 1 or recs[0].get("kind") != kind or recs[0].get("question") != q:
            fails.append("BAD LOG: %s -> %r" % (label, recs))
    logged = len(log_lines())
    for label, payload in MUST_PASS:
        p = run(payload)
        if p.returncode != 0 or p.stdout.strip():
            fails.append("FALSE POSITIVE: %s -> %r" % (label, p.stdout[:120]))
    for junk in MALFORMED:
        p = run(junk)
        if p.returncode != 0 or p.stdout.strip():
            fails.append("MALFORMED NOT SAFE: %r -> %r" % (junk, p.stdout[:60]))
    if len(log_lines()) != logged:
        fails.append("LOGGED A PASS: %d extra lines" % (len(log_lines()) - logged))
    with open(os.path.join(HERE, "..", "claude", "hooks.json"), encoding="utf-8") as fh:
        hooks = json.load(fh)["hooks"]["PreToolUse"]
    if not any("decide_gate.py" in h["command"] and "AskUserQuestion" in m.get("matcher", "")
               for m in hooks for h in m["hooks"]):
        fails.append("claude/hooks.json has no AskUserQuestion PreToolUse hook for decide_gate.py")
    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  %d cases: %d must-deny, %d must-pass, %d malformed, hook registered"
          % (len(MUST_DENY) + len(MUST_PASS) + len(MALFORMED), len(MUST_DENY), len(MUST_PASS), len(MALFORMED)))


if __name__ == "__main__":
    main()
