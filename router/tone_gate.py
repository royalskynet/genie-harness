#!/usr/bin/env python3
"""Genie Tone Gate — Claude Code `Stop` hook: spot-check the final reply for
Chinese AI-tone patterns and hand a note to the next turn.

The patterns are the ones a paired human/AI study found reliably higher in AI
Chinese (same topic, same facts, same length; larashero3-dotcom/lieflat-less-ai-tone).
The regexes here are written from those findings, not copied from that repo.
Only shapes a regex can see are checked: the "not X but Y" turn, conclusion
colons, stock openers, topic shells, 3+ items strung with 、, and dashes.

Never blocks: a style note is not worth a round the user can see. It goes
through defer.py, so the model reads it before its next reply; with no session
id it is dropped. Skipped when the `humanize` block is off. Fails OPEN.
Claude Code only (Codex has no Stop hook here).
"""
import json
import re
import sys

import defer
import prefs

CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
# Markdown list items and table rows list things on purpose.
LISTY = re.compile(r"^\s*(?:[-*+|]|\d+[.)])")

CHECKS = [
    ("不是X而是Y", re.compile(
        r"(?:不是|並非|并非|與其說|与其说)[^，。！？；\n]{1,20}[，,]?\s*(?:而是|不如說|不如说)"
        r"|(?:看似|表面上?)[^，。！？；\n]{1,20}[，,]\s*(?:實則|实则|實際上|实际上)"
        r"|你以為[^，。！？；\n]{1,20}[，,]\s*其實|你以为[^，。！？；\n]{1,20}[，,]\s*其实")),
    ("結論冒號", re.compile(
        r"(?:一句話(?:總結|說|概括)|一句话(?:总结|说|概括)|總結|总结|結論|结论|核心(?:是|在於|在于)?"
        r"|關鍵(?:是|在於)?|关键(?:是|在于)?|重點是|重点是|本質(?:上|是)|本质(?:上|是)|說白了|说白了)[：:]")),
    ("起手式", re.compile(r"(?:說白了|说白了|說穿了|说穿了|先說結論|先说结论)[，,]")),
    ("話題殼", re.compile(
        r"(?:對於|对于)[^，。！？\n]{2,15}(?:來說|来说)|就[^，。！？\n]{2,15}而言")),
]
# 4+ items joined by 、 inside one clause. Three is everyday technical listing
# (measured: 11% of real replies hit at 3, mostly file or option lists).
CLAUSE = re.compile(r"[，,。！？；;\n]")
DASH = re.compile(r"——|—")
CJK = re.compile(r"[一-鿿]")


def scan(text):
    """[(name, example)] for each pattern found; [] when clean or not Chinese."""
    body = CODE.sub("", str(text or ""))
    lines = [ln for ln in body.splitlines() if not LISTY.match(ln)]
    prose = "\n".join(lines)
    cjk = len(CJK.findall(prose))
    if cjk < 20:
        return []
    hits = []
    for name, rx in CHECKS:
        m = rx.search(prose)
        if m:
            hits.append((name, m.group(0)))
    for clause in CLAUSE.split(prose):
        if clause.count("、") >= 3:
            hits.append(("頓號連排", clause.strip()[:30]))
            break
    dashes = len(DASH.findall(prose))
    # Short replies: none. Long ones: at most 2, and under 2 per 1000 characters.
    if dashes and (cjk < 300 or dashes > max(2, cjk * 2 // 1000)):
        hits.append(("破折號", "%d 個／%d 字" % (dashes, cjk)))
    return hits


def note(hits):
    parts = "；".join("%s「%s」" % (n, ex) for n, ex in hits[:4])
    return ("tone_gate: last reply hit AI-tone patterns: %s. Write the next reply "
            "without them (fixes in genie-humanizer); do not rewrite the last one." % parts)


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        if not isinstance(data, dict) or data.get("stop_hook_active"):
            return
        if prefs.block_state("humanize", prefs.load()) == "off":
            return
        text = data.get("last_assistant_message")
        if text is None and data.get("transcript_path"):
            import blame_gate
            text = blame_gate.last_text(data["transcript_path"])
        hits = scan(text)
        if hits:
            defer.write(data.get("session_id"), "tone_gate", note(hits))
    except Exception:
        return  # fail open


if __name__ == "__main__":
    main()
