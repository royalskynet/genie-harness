#!/usr/bin/env python3
"""Genie Blame Gate — Claude Code `Stop` hook: block once when the final reply
blames a failure on the model or a timeout and names no alternative cause.

"The model is too weak" and "it timed out" sound like explanations and are
often wrong: swap the model and the failure stays, because the real cause was
stale config, permissions, or a wrong route. This is the cheap half of a
counterfactual check -- a regex, no model call. The other half (repeat
failures) lives in fail_streak.py's warning.

Passes when the reply already rules the model/timeout out, or lists alternative
causes or checks. `stop_hook_active` re-entry always passes. Fails OPEN.
Claude Code only (Codex has no Stop hook here).
"""
import json
import re
import sys

import defer

SUBJ = r"(?:模型|model|LLM|timeout|time\s*out|timed\s+out|逾時|超時|太慢)"
BLAME = re.compile("|".join([
    r"(?:是|因為|原因(?:是|在)|歸因(?:於|到)|卡在|怪)\s*(?:這個|那個|免費|弱)?" + SUBJ,
    SUBJ + r"\s*(?:太弱|不行|不夠(?:強|聰明|力)?|能力不足|造成|導致|害的|的問題|的鍋)",
    r"換(?:個|成|一個)?(?:更強的?|別的|大)?模型(?:就|應該|會)",
    r"\b(?:the\s+)?model\s+(?:is\s+|was\s+)?(?:too\s+weak|too\s+small|not\s+capable|not\s+smart)",
    r"\bbecause\s+(?:of\s+)?(?:a\s+|the\s+)?(?:time\s*out|model)",
    r"\b(?:a\s+)?(?:bigger|stronger|better)\s+model\s+(?:would|should|will)",
]), re.I)
# Already did the counterfactual, or explicitly ruled the model/timeout out.
DONE = re.compile(
    r"替代(?:根因|解釋|假設|原因)|反事實|已排除|排除了|(?:不是|並非|非|排除)\s*(?:模型|model|timeout|逾時|超時)|"
    r"alternative\s+(?:cause|explanation)|ruled\s+out|not\s+(?:the\s+)?(?:model|timeout)", re.I)

REASON = ("Your reply blames the model or a timeout but names no alternative cause. "
          "Before closing, list three causes a check could prove wrong (stale config or "
          "state, permissions, wrong route or path, a dependency not running) and the "
          "result of the smallest check for each. Swapping models, raising the timeout, "
          "resending or restarting is not a fix until those are ruled out. If you did "
          "check them, say what you ruled out.")


def blames(text):
    t = str(text or "")
    return bool(t) and bool(BLAME.search(t)) and not DONE.search(t)


def last_text(path):
    last = ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            msg = line.get("message") if isinstance(line, dict) else None
            if line.get("type") == "assistant" and isinstance(msg, dict) and isinstance(msg.get("content"), list):
                texts = [b.get("text", "") for b in msg["content"] if isinstance(b, dict) and b.get("type") == "text"]
                if texts:
                    last = "\n".join(texts)
    return last


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        if not isinstance(data, dict) or data.get("stop_hook_active"):
            return
        text = data.get("last_assistant_message")
        if text is None and data.get("transcript_path"):
            text = last_text(data["transcript_path"])
        if blames(text):
            # Deferred to the next turn when a session id exists (defer.py); block otherwise.
            if not defer.write(data.get("session_id"), "blame_gate", REASON):
                json.dump({"decision": "block", "reason": REASON}, sys.stdout)
    except Exception:
        return  # fail open


if __name__ == "__main__":
    main()
