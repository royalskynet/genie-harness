#!/usr/bin/env python3
"""Self-check for the tone gate. Run: python3 router/test_tone_gate.py

MUST_HIT: one reply per pattern; the named pattern must be reported.
MUST_PASS: plain replies, code, lists and English -- a gate that nags on
those gets switched off.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tone_gate  # noqa: E402

PAD = "這次改了設定檔，測試全部通過，下一步是合併分支。"
MUST_HIT = [
    ("不是X而是Y", PAD + "真正的問題不是速度，而是記憶體不夠。"),
    ("不是X而是Y", PAD + "這看似設定錯誤，實則是權限問題。"),
    ("結論冒號", PAD + "一句話總結：這個方案太貴。"),
    ("起手式", PAD + "說白了，就是快取沒清。"),
    ("話題殼", PAD + "對於新手來說，這個指令最危險。"),
    ("頓號連排", PAD + "它會檢查標點、句長、冒號、引號和破折號。"),
    ("破折號", PAD + "答案很簡單——重開。"),
    ("不是X而是Y", "真正的壁垒不是技术，而是认知。" + PAD),
]
MUST_PASS = [
    PAD,
    PAD + "\n```\nprint('不是 a，而是 b、c、d')\n```",
    PAD + "\n- 標點、句長、冒號\n- 結論：通過",
    PAD + "它不是 bug。重開後恢復正常。",
    PAD + "輸入、輸出、測試全部要改。",
    "Tests pass. The root cause is not the model but a stale config — fixed.",
    "好",
]


def run_hook(payload, state):
    env = dict(os.environ, GENIE_STATE_DIR=state, GENIE_PREFS=os.path.join(state, "p.json"))
    subprocess.run([sys.executable, os.path.join(HERE, "tone_gate.py")],
                   input=json.dumps(payload).encode(), env=env, check=True,
                   capture_output=True)


def main():
    fails = []
    for name, text in MUST_HIT:
        got = [n for n, _ in tone_gate.scan(text)]
        if name not in got:
            fails.append("MISS %s: %s -> %s" % (name, text, got))
    for text in MUST_PASS:
        got = tone_gate.scan(text)
        if got:
            fails.append("FALSE HIT: %r -> %s" % (text, got))

    with tempfile.TemporaryDirectory() as state:
        bad = PAD + "說白了，就是快取沒清。"
        # Hit -> note deferred to the session file; nothing on stdout (never blocks).
        run_hook({"session_id": "s1", "last_assistant_message": bad}, state)
        path = os.path.join(state, "defer-s1.txt")
        if not os.path.exists(path) or "起手式" not in open(path, encoding="utf-8").read():
            fails.append("hook did not defer a note")
        # humanize off -> silent.
        with open(os.path.join(state, "p.json"), "w") as fh:
            json.dump({"blocks": {"humanize": "off"}}, fh)
        run_hook({"session_id": "s2", "last_assistant_message": bad}, state)
        if os.path.exists(os.path.join(state, "defer-s2.txt")):
            fails.append("hook wrote a note with humanize off")

    for f in fails:
        print("FAIL", f)
    total = len(MUST_HIT) + len(MUST_PASS) + 2
    print("%s %d/%d" % ("PASS" if not fails else "FAIL", total - len(fails), total))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
