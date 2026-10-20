#!/usr/bin/env python3
"""Genie Done Gate — Claude Code `Stop` hook. Blocks once when either holds:

1. The assistant edited a code file after the user's last message and ran
   nothing afterwards.
2. The final reply cites a commit hash or a GitHub issue/PR URL that appears in
   no tool output and no user message this session (an invented result).

Exempt: .md/.txt edits, `stop_hook_active` re-entry, earlier turns.
Fails OPEN like guard_dangerous.py. Claude Code only (Codex has no Stop hook here).
"""
import json
import re
import sys

EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
REASON = ("You changed files but ran nothing after the last change. Run it once "
          "and show the real output, or say plainly why it cannot be run.")

# Commands that look at the world without exercising the change. Clearing the
# gate on these made `ls` after an edit count as having run it, which is the
# whole failure the gate exists to catch: evidence that cannot fail is not
# evidence. Kept deliberately narrow -- grep/sed/awk/jq/test are assertions as
# often as they are sightseeing, so they still count as a run.
NOOP_CMDS = {"cd", "ls", "pwd", "echo", "printf", "date", "which", "command",
             "true", "clear", "cat", "head", "tail", "wc", "open", "mkdir",
             "touch", "tree", "file"}
# `git <sub>` that only reports. `git status` after an edit is the classic
# "I ran something" that proves nothing about the change.
NOOP_GIT_SUBS = {"status", "diff", "log", "show", "branch", "remote"}

# Invented-id check. Only ids that can be quoted but never derived: a hash or an
# issue number is either in some output or it was made up. Numbers are left out
# on purpose -- sums and percentages are computed, so a correct one is absent
# from every output by construction (measured on 1423 transcripts: ~65% of raw
# hits were numbers, all inspected ones false). Ported from jev-gate idcheck.js.
ID_REASON = ("Your reply cites %s, which appears in no tool output or user message "
             "this session. An id can only be quoted, not derived. Run the command and "
             "quote what it returned, or remove the id. Saying plainly that something "
             "is unverified is fine.")
EMPH = re.compile(r"\*\*|__|\*|`")
GH_ISSUE = re.compile(r"https?://github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)/(\d+)", re.I)
HASH = re.compile(r"\b[0-9a-f]{7,40}\b")
HEX_RUN = re.compile(r"[0-9a-f]{7,}")
PLACEHOLDER = re.compile(r"^(org|owner|user|username|you|your-?\w*|example|repo|myorg|foo|bar)$", re.I)


def _hexish(t):
    return any(ch in "abcdef" for ch in t)  # 1234567 is a number, not a hash


def unsupported_ids(claim, evidence):
    """Ids asserted in `claim` that nothing in `evidence` supports. [] when either is empty."""
    c, e = EMPH.sub("", claim or ""), EMPH.sub("", evidence or "")
    if not c.strip() or not e.strip():
        return []
    out = []
    for m in GH_ISSUE.finditer(c):
        full, owner, repo, num = m.group(0), m.group(1), m.group(2), m.group(3)
        if PLACEHOLDER.match(owner) or PLACEHOLDER.match(repo) or full in e:
            continue
        # `gh issue view` prints repo and number in separate fields, never the URL.
        if repo in e and re.search(r"(?:\"?number\"?\s*[:=]\s*|#|issues/|pull/)%s\b" % num, e):
            continue
        out.append(full)
    for t in dict.fromkeys(HASH.findall(c)):
        if not _hexish(t) or t in e:
            continue
        # A longer claimed hash can extend a short one the output printed.
        if any(_hexish(r) and t.startswith(r) for r in HEX_RUN.findall(e)):
            continue
        out.append(t)
    return out


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text(b.get("text") if b.get("type") == "text" else b.get("content"))
                         if isinstance(b, dict) else str(b) for b in content)
    return "" if content is None else str(content)


def _lines(path, attachments=False):
    lines = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                line = json.loads(raw)
            except ValueError:
                continue  # half-flushed line must not disable the gate
            if isinstance(line, dict) and isinstance(line.get("message"), dict):
                lines.append((line.get("type"), line["message"].get("content")))
            elif attachments and isinstance(line, dict) and line.get("attachment"):
                # File contents and hook context the model was shown are evidence too.
                lines.append(("user", json.dumps(line["attachment"], ensure_ascii=False)))
    return lines


def invented_ids(path, last_message=None):
    """Ids in the final reply that no tool output or user message contains."""
    lines = _lines(path, attachments=True)
    evidence = "\n".join(_text(c) for t, c in lines if t == "user")
    claim = last_message
    if claim is None:
        for t, c in reversed(lines):
            if t == "assistant" and isinstance(c, list) and any(
                    isinstance(b, dict) and b.get("type") == "text" for b in c):
                claim = "\n".join(b.get("text", "") for b in c
                                  if isinstance(b, dict) and b.get("type") == "text")
                break
    return unsupported_ids(claim or "", evidence)


def counts_as_run(command):
    """True when a Bash command could actually exercise the change.

    Every segment must be a look-only command for the whole line to be
    discounted: `ls && pytest` runs the tests. Unparseable means it counts,
    like every other fail-open path in this hook.
    """
    text = str(command or "").strip()
    if not text:
        return False
    for seg in text.replace("&&", "\n").replace("||", "\n").replace(";", "\n").replace("|", "\n").split("\n"):
        words = seg.split()
        # Skip leading VAR=value env assignments.
        while words and "=" in words[0] and not words[0].startswith("-"):
            words = words[1:]
        if not words:
            continue
        head = words[0].rsplit("/", 1)[-1]
        if head == "git":
            if len(words) > 1 and words[1] in NOOP_GIT_SUBS:
                continue
            return True
        if head in NOOP_CMDS:
            continue
        return True
    return False


def needs_run(path):
    lines = _lines(path)

    # A typed user turn; tool results also arrive as type=user, as a list of tool_result.
    def typed(c):
        return isinstance(c, str) or (isinstance(c, list) and not any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in c))

    users = [i for i, (t, c) in enumerate(lines) if t == "user" and typed(c)]
    if not users:
        return False
    pending = False  # a code edit with no Bash after it
    for t, c in lines[users[-1] + 1:]:
        if t != "assistant" or not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            if b.get("name") == "Bash":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if counts_as_run(inp.get("command")):
                    pending = False
            elif b.get("name") in EDIT_TOOLS:
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                p = inp.get("file_path") or inp.get("notebook_path") or ""
                if not str(p).lower().endswith((".md", ".txt")):
                    pending = True  # unknown path counts as code
    return pending


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        if data.get("stop_hook_active") or not data.get("transcript_path"):
            return
        if needs_run(data["transcript_path"]):
            json.dump({"decision": "block", "reason": REASON}, sys.stdout)
            return
        ids = invented_ids(data["transcript_path"], data.get("last_assistant_message"))
        if ids:
            json.dump({"decision": "block", "reason": ID_REASON % ", ".join(ids[:5])}, sys.stdout)
    except Exception:
        return  # fail open


if __name__ == "__main__":
    main()
