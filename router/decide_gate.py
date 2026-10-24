#!/usr/bin/env python3
"""Genie Decide Gate — Claude Code `PreToolUse` hook on AskUserQuestion.

AGENTS.md says only four kinds of thing are worth stopping for (irreversible,
seen by others, costs money or system settings, changes someone else's rules),
and prefs say "decide and proceed". Both were text the model could skip. This
makes the cheap half of them a gate:

* Reversible question where the model already marked exactly one option
  "(Recommended)" -> denied: it has decided, so it should do it and say in one
  line which default it took and how to change it.
* Irreversible question -> asked, always. But it must carry a recommendation
  and a reason: exactly one "(Recommended)" option whose description says why.
  A bare choice on a one-way door is a question the user cannot answer well.
* Everything else (no recommendation, several, multiSelect) -> passes.

No model call. Fails OPEN like the other gates. Claude Code only: Codex has no
AskUserQuestion tool.

Every deny starts with "Genie decide_gate:" and appends one JSONL line to
~/.genie/decide.log (`GENIE_DECIDE_LOG` = a path, or "0" to opt out). Another
gate on the same tool shows one deny reason to the model, so without these the
stacked case cannot tell who blocked.
"""
import json
import os
import re
import sys
import time

# The four kinds, as words that show up in questions about them. Erring towards
# "irreversible" only costs a recommendation line; the other way skips a question
# the user had to see.
IRREVERSIBLE = re.compile(
    r"delete|remove|drop\s+table|wipe|overwrite|force|push|publish|deploy|release|"
    r"go\s+live|public|send|e-?mail|post\b|merge|pull\s+request|\bPR\b|pay|paid|"
    r"subscri|purchase|buy|billing|credit\s+card|sudo|system\s+setting|reset\s+--hard|"
    r"rm\s+-rf|irreversible|cannot\s+be\s+undone|rewrite\s+history|credential|secret|"
    r"刪除|刪掉|移除|清空|覆蓋|覆寫|推送|發布|公開|上線|部署|對外|寄出|發送|發訊息|合併|"
    r"付費|訂閱|花錢|購買|信用卡|系統設定|不可逆|改規則|制度|憑證|金鑰",
    re.I)
RECOMMENDED = re.compile(r"\(recommended\)|（建議）|\(建議\)|（推薦）", re.I)
SOURCE = "Genie decide_gate: "
LOG_MAX_BYTES = 1024 * 1024  # same cap as route.log; one older file kept as .1

TAKE = ("You already picked \"%s\" as the recommended option, and this is reversible. "
        "Do it instead of asking. In your reply, say in one line which default you took "
        "and how to change it.")
LINT = ("This one is irreversible, so asking is right, but %s. Ask again with exactly one "
        "option marked \"(Recommended)\" and its description saying why, plus what it "
        "does and whether it can be undone.")


def judge(question):
    """Return (kind, text) for one AskUserQuestion question, or None to let it through."""
    if not isinstance(question, dict) or question.get("multiSelect"):
        return None
    options = [o for o in question.get("options") or [] if isinstance(o, dict)]
    if len(options) < 2:
        return None
    blob = " ".join([str(question.get("question") or "")] + [
        "%s %s" % (o.get("label") or "", o.get("description") or "") for o in options])
    recs = [o for o in options if RECOMMENDED.search(str(o.get("label") or ""))]
    if IRREVERSIBLE.search(blob):
        if len(recs) != 1:
            return ("lint", LINT % "no single option is marked as the recommendation")
        if len(str(recs[0].get("description") or "").strip()) < 4:
            return ("lint", LINT % "the recommended option gives no reason")
        return None
    if len(recs) == 1:
        return ("take", TAKE % RECOMMENDED.sub("", str(recs[0].get("label"))).strip())
    return None


def log_deny(kind, questions):
    """Append one record per deny. Errors are swallowed: logging must never
    turn a fail-open gate into a failing one."""
    try:
        env = os.environ.get("GENIE_DECIDE_LOG")
        if env == "0":
            return
        path = os.path.expanduser(env or "~/.genie/decide.log")
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".1")
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind,
               "question": " | ".join(str((q or {}).get("question") or "")[:200]
                                      for q in questions if isinstance(q, dict))}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        return


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        if not isinstance(data, dict) or data.get("tool_name") != "AskUserQuestion":
            return
        questions = (data.get("tool_input") or {}).get("questions") or []
        verdicts = [v for v in (judge(q) for q in questions) if v]
        # Any irreversible question without a recommendation wins; take-only
        # applies when every question was answerable by its own recommendation.
        lints = [t for k, t in verdicts if k == "lint"]
        takes = [t for k, t in verdicts if k == "take"]
        reason = lints[0] if lints else (" ".join(takes) if takes and len(takes) == len(questions) else None)
        if reason:
            log_deny("lint" if lints else "take", questions)
            json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                              "permissionDecision": "deny",
                                              "permissionDecisionReason": SOURCE + reason}}, sys.stdout)
    except Exception:
        return  # fail open


if __name__ == "__main__":
    main()
