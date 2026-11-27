#!/usr/bin/env python3
"""Genie Transcript Usage — zero-token measurement of where the input goes.

Reads a session transcript (JSONL), sums characters by source, prints a top-N
table with each source's share of the total. Shares sum to 100% by
construction: every measured character lands in exactly one bucket.

Two modes, picked by what the file actually records:

  api-request  Claude Code >= 2.1.332 logs `api-request` lines whose `tail`
               lists `api-request-blob` hashes -- the exact messages sent to
               the model, plus an `api-request-shape` (system prompt and tool
               definitions, re-sent on every request). Counting per request is
               honest input share: a blob tail-refs ten times cost ten times.
  messages     Older transcripts have only the conversation lines (user /
               assistant / attachment / summary). Each is counted once -- an
               approximation, since a long history is re-sent every turn.

Text-block markers split the sources the issue asks about: `memory_rules`
(injected CLAUDE.md / AGENTS.md bodies), `skills_list`, `hook_injection`
(router intent line, prefs, deferred Stop-gate notes), `system_reminder`,
`tool_return:<name>` per tool, `tool_call:<name>` for call inputs.

Usage: transcript_usage.py <transcript.jsonl> [--top N]
Exit: 0 measured, 1 nothing measurable, 2 bad input.
"""
import json
import os
import sys
from collections import defaultdict

HOOK_MARKERS = (
    "genie: intent=", "[genie prefs]", "deferred from last turn's Stop gates",
    "<user-prompt-submit-hook>", "Genie setup:",
)


def _content_text(content):
    """tool_result / block content -> its text, whatever shape it came in."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                parts.append(b["text"])
            else:
                parts.append(json.dumps(b, ensure_ascii=False))
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


def _classify_text(text, role):
    if role == "assistant":
        return "assistant_text"
    if "Contents of " in text and ".md" in text:
        return "memory_rules"  # CLAUDE.md / AGENTS.md body injected by the host
    if "available_skills" in text:
        return "skills_list"
    for m in HOOK_MARKERS:
        if m in text:
            return "hook_injection"
    if "<system-reminder" in text:
        return "system_reminder"
    if "<command-name" in text or "<local-command" in text:
        return "command"
    return "user_input" if role == "user" else "%s_text" % role


def _account_message(msg, counts, id2name):
    if not isinstance(msg, dict):
        return
    role = msg.get("role") or "unknown"
    content = msg.get("content")
    if isinstance(content, str):
        counts[_classify_text(content, role)] += len(content)
        return
    if not isinstance(content, list):
        return
    for b in content:
        if not isinstance(b, dict):
            counts["other"] += len(str(b))
            continue
        bt = b.get("type")
        if bt == "text":
            t = b.get("text") or ""
            counts[_classify_text(t, role)] += len(t)
        elif bt == "thinking":
            counts["assistant_thinking"] += len(b.get("thinking") or "")
        elif bt == "tool_use":
            name = b.get("name") or "?"
            if isinstance(b.get("id"), str):
                id2name[b["id"]] = name
            counts["tool_call:%s" % name] += len(
                json.dumps(b.get("input"), ensure_ascii=False))
        elif bt == "tool_result":
            name = id2name.get(b.get("tool_use_id"), "?")
            counts["tool_return:%s" % name] += len(_content_text(b.get("content")))
        else:
            counts["other:%s" % bt] += len(json.dumps(b, ensure_ascii=False))


def _account_attachment(line, counts):
    att = line.get("attachment") or {}
    if att.get("type") == "hook_success":
        name = att.get("hookEvent") or att.get("hookName") or "?"
        n = len(att.get("stdout") or "") + len(att.get("stderr") or "")
        n += len(_content_text(att.get("content")))
        counts["hook:%s" % name] += n
    else:
        counts["attachment"] += len(json.dumps(att, ensure_ascii=False))


def measure(path):
    """-> (mode, counts dict, n_api_requests)."""
    lines = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.rstrip("\n")
            if raw:
                lines.append(raw)

    parsed, unparsed_chars = [], 0
    for raw in lines:
        try:
            parsed.append(json.loads(raw))
        except Exception:
            unparsed_chars += len(raw)

    blobs, shapes, id2name = {}, {}, {}
    has_requests = False
    for d in parsed:
        if not isinstance(d, dict):
            continue
        t = d.get("type")
        if t == "api-request-blob" and isinstance(d.get("hash"), str):
            blobs[d["hash"]] = d.get("message") or {}
        elif t == "api-request-shape" and isinstance(d.get("shapeHash"), str):
            shapes[d["shapeHash"]] = d.get("shape") or {}
        elif t == "api-request":
            has_requests = True
        elif t in ("user", "assistant"):
            _index_tool_names(d.get("message"), id2name)
    for m in blobs.values():
        _index_tool_names(m, id2name)

    counts = defaultdict(int)
    if unparsed_chars:
        counts["unparsed"] = unparsed_chars
    n_req = 0
    if has_requests:
        mode = "api-request"
        for d in parsed:
            if not isinstance(d, dict) or d.get("type") != "api-request":
                continue
            n_req += 1
            shape = shapes.get(d.get("shapeHash")) or {}
            for s in shape.get("system") or []:
                if isinstance(s, dict):
                    counts["system_prompt"] += len(s.get("text") or "")
            tools = shape.get("tools")
            if tools:
                counts["tool_definition"] += len(
                    json.dumps(tools, ensure_ascii=False))
            for h in d.get("tail") or []:
                m = blobs.get(h)
                if m is not None:
                    _account_message(m, counts, id2name)
    else:
        mode = "messages"
        for d in parsed:
            if not isinstance(d, dict):
                continue
            t = d.get("type")
            if t in ("user", "assistant"):
                _account_message(d.get("message"), counts, id2name)
            elif t == "system":
                counts["system:%s" % d.get("subtype", "?")] += len(
                    json.dumps(d, ensure_ascii=False))
            elif t == "attachment":
                _account_attachment(d, counts)
            elif t == "summary":
                counts["summary"] += len(d.get("summary") or "")
            # queue-operation, session-owner, ai-title, ... are transcript
            # bookkeeping that never reaches the model: not input, not counted.
    return mode, counts, n_req


def _index_tool_names(msg, id2name):
    if not isinstance(msg, dict):
        return
    for b in msg.get("content") or []:
        if isinstance(b, dict) and b.get("type") == "tool_use" \
                and isinstance(b.get("id"), str) and b.get("name"):
            id2name[b["id"]] = b["name"]


def main(argv):
    args, top = [], 10
    i = 1
    while i < len(argv):
        if argv[i] == "--top" and i + 1 < len(argv):
            try:
                top = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            args.append(argv[i])
            i += 1
    if len(args) != 1:
        sys.stderr.write("usage: transcript_usage.py <transcript.jsonl> [--top N]\n")
        return 2
    path = os.path.expanduser(args[0])
    if not os.path.isfile(path):
        sys.stderr.write("transcript_usage: no such file: %s\n" % path)
        return 2

    mode, counts, n_req = measure(path)
    total = sum(counts.values())
    if total == 0:
        sys.stderr.write("transcript_usage: nothing measurable in %s\n" % path)
        return 1

    print("mode: %s%s" % (mode, " (%d requests)" % n_req if n_req else ""))
    print("total input chars: %d" % total)
    print("%-28s %10s %6s" % ("source", "chars", "share"))
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    shown, rest = ranked[:top], ranked[top:]
    big = []
    for name, n in shown:
        pct = n * 100.0 / total
        if pct >= 10.0:
            big.append("%s (%.1f%%)" % (name, pct))
        print("%-28s %10d %5.1f%%" % (name, n, pct))
    if rest:
        n = sum(v for _, v in rest)
        print("%-28s %10d %5.1f%%" % ("...other (%d sources)" % len(rest), n,
                                      n * 100.0 / total))
    print("shares sum to %.1f%%" % (sum(counts.values()) * 100.0 / total))
    print("over 10%%: %s" % (", ".join(big) if big else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
