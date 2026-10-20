#!/usr/bin/env python3
"""Self-check for the blame gate. Run: python3 router/test_blame_gate.py

MUST_BLOCK: replies that pin a failure on the model or a timeout and stop there.
MUST_PASS: replies that mention a model or timeout without blaming it, or that
already ruled it out -- a gate that blocks those gets switched off.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "blame_gate.py")

MUST_BLOCK = [
    "失敗是因為模型太弱，換個更強的模型應該就好。",
    "這次沒過是 timeout 的問題，我把上限加到 600s。",
    "看起來是免費模型能力不足。",
    "It failed because of a timeout.",
    "The model is too weak for this task.",
    "A bigger model would handle this.",
]
MUST_PASS = [
    "驗收 exit 0，3 個檔都改好了。",
    "不是模型的問題：已排除 stale config，根因是路由走錯。",
    "我先列替代根因：設定過期、權限、路由，各跑一個 probe。",
    "curl --max-time 10 設定 timeout 為 10 秒。",
    "Set the request timeout to 30s as asked; tests pass.",
    "It is not the model: the config was stale, ruled out by re-reading it.",
    "Switched the default model to sonnet per your request.",
    "",
]


def run(payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, GATE], input=raw, capture_output=True,
                          text=True, cwd=tempfile.gettempdir())


def blocked(p):
    try:
        return json.loads(p.stdout).get("decision") == "block"
    except ValueError:
        return False


def main():
    fails = []
    for s in MUST_BLOCK:
        if not blocked(run({"last_assistant_message": s})):
            fails.append("NOT BLOCKED: %r" % s)
    for s in MUST_PASS:
        p = run({"last_assistant_message": s})
        if p.returncode != 0 or p.stdout.strip():
            fails.append("FALSE POSITIVE: %r -> %r" % (s, p.stdout[:80]))
    # Re-entry must pass, or a blocking Stop hook loops on itself.
    if run({"last_assistant_message": MUST_BLOCK[0], "stop_hook_active": True}).stdout.strip():
        fails.append("RE-ENTRY LOOP RISK")
    # Transcript fallback when the payload has no last_assistant_message.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "why did it fail?"}}) + "\n")
            fh.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text", "text": MUST_BLOCK[3]}]}}) + "\n")
        if not blocked(run({"transcript_path": path})):
            fails.append("TRANSCRIPT FALLBACK NOT BLOCKED")
    for junk in ["", "not json", "{}", "[]", '{"transcript_path": "/nonexistent"}']:
        p = run(junk)
        if p.returncode != 0 or p.stdout.strip():
            fails.append("MALFORMED NOT SAFE: %r" % junk)
    with open(os.path.join(HERE, "..", "claude", "hooks.json"), encoding="utf-8") as fh:
        stops = json.load(fh)["hooks"].get("Stop", [])
    if not any("blame_gate.py" in h["command"] for m in stops for h in m["hooks"]):
        fails.append("claude/hooks.json Stop hook does not reference blame_gate.py")
    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  %d must-block, %d must-pass, re-entry, transcript fallback, malformed, hook registered"
          % (len(MUST_BLOCK), len(MUST_PASS)))


if __name__ == "__main__":
    main()
