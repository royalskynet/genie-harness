#!/usr/bin/env python3
"""Self-check for transcript_usage.py. Run: python3 router/test_transcript_usage.py

What must hold (issue: P0 measurement script):
  * api-request transcripts -> per-request accounting: shape (system + tool
    definitions) counted once per request, tail blobs categorised, tool_result
    attributed to the tool that produced it, memory/skills/hook markers split.
  * conversation-only transcripts -> messages mode, same 100% share invariant.
  * shares always sum to 100%; bad input exits non-zero.

Run as subprocess: the contract is argv -> stdout -> exit code.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "transcript_usage.py")


def run(path, extra=()):
    p = subprocess.run([sys.executable, SCRIPT, path] + list(extra),
                       capture_output=True, text=True, timeout=20)
    return p.stdout, p.returncode


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def shares(out):
    """-> {source: pct} parsed from the table rows."""
    got = {}
    for line in out.splitlines():
        parts = line.rsplit(None, 2)
        if len(parts) == 3 and parts[2].endswith("%") and parts[1].isdigit():
            got[parts[0]] = float(parts[2].rstrip("%"))
    return got


def make_api_transcript(path):
    sys_txt = "You are a helpful assistant. " * 10
    tools = [{"name": "Bash", "description": "run a command",
              "input_schema": {"type": "object"}}]
    rows = [
        {"type": "api-request-shape", "shapeHash": "s1",
         "shape": {"system": [{"type": "text", "text": sys_txt}], "tools": tools}},
        {"type": "api-request-blob", "hash": "h1",
         "message": {"role": "user", "content": [
             {"type": "text", "text": "hi, please list files"}]}},
        {"type": "api-request-blob", "hash": "h2",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "Sure."},
             {"type": "tool_use", "id": "t1", "name": "Bash",
              "input": {"command": "ls -la"}}]}},
        {"type": "api-request-blob", "hash": "h3",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1",
              "content": "x\n" * 400}]}},
        {"type": "api-request-blob", "hash": "h4",
         "message": {"role": "user", "content": [
             {"type": "text", "text": "<system-reminder>\nContents of "
              "/cfg/CLAUDE.md (user's private global instructions):\n"
              + "rule\n" * 40 + "</system-reminder>"}]}},
        {"type": "api-request", "shapeHash": "s1",
         "tail": ["h1", "h2", "h3", "h4"], "params": {}},
        {"type": "queue-operation", "content": "bookkeeping, never sent"},
    ]
    write_jsonl(path, rows)


def make_msg_transcript(path):
    rows = [
        {"type": "user", "message": {"role": "user", "content": "do the thing"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "id": "u9", "name": "Read",
             "input": {"file_path": "/tmp/f"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "u9", "content": "body " * 50}]}},
        {"type": "attachment", "attachment": {
            "type": "hook_success", "hookEvent": "SessionStart",
            "stdout": "rules rules rules", "stderr": "", "content": ""}},
    ]
    write_jsonl(path, rows)


def main():
    fails = []
    tmp = tempfile.mkdtemp(prefix="tu-")
    api_t = os.path.join(tmp, "api.jsonl")
    msg_t = os.path.join(tmp, "msg.jsonl")
    make_api_transcript(api_t)
    make_msg_transcript(msg_t)

    out, rc = run(api_t)
    if rc != 0:
        fails.append("FAIL 1: api-request transcript exit %d: %s" % (rc, out[:200]))
    else:
        if "mode: api-request" not in out:
            fails.append("FAIL 1: mode line missing: %s" % out.splitlines()[:2])
        sh = shares(out)
        for want in ("tool_return:Bash", "tool_definition", "system_prompt",
                     "memory_rules", "user_input"):
            if want not in sh:
                fails.append("FAIL 1: source %r missing; got %s" % (want, sorted(sh)))
        if "tool_return:?" in sh or "tool_call:?" in sh:
            fails.append("FAIL 1: tool name unresolved: %s" % sorted(sh))
        if "shares sum to 100.0%" not in out:
            fails.append("FAIL 1: shares do not sum to 100%: %s"
                         % out.strip().splitlines()[-2:])

    out, rc = run(msg_t)
    if rc != 0:
        fails.append("FAIL 2: messages transcript exit %d" % rc)
    else:
        if "mode: messages" not in out:
            fails.append("FAIL 2: wrong mode: %s" % out.splitlines()[:1])
        sh = shares(out)
        for want in ("tool_return:Read", "tool_call:Read", "hook:SessionStart",
                     "user_input"):
            if want not in sh:
                fails.append("FAIL 2: source %r missing; got %s" % (want, sorted(sh)))
        if "shares sum to 100.0%" not in out:
            fails.append("FAIL 2: shares do not sum to 100%")

    out, rc = run(api_t, extra=("--top", "2"))
    rows = [l for l in out.splitlines()
            if len(l.rsplit(None, 2)) == 3 and l.rsplit(None, 2)[2].endswith("%")
            and l.rsplit(None, 2)[1].isdigit()]
    if rc != 0 or len(rows) != 3 or "...other" not in rows[-1]:
        fails.append("FAIL 3: --top 2 expected 2 rows + other, rc=%d got %s"
                     % (rc, rows))

    out, rc = run(os.path.join(tmp, "nope.jsonl"))
    if rc == 0:
        fails.append("FAIL 4: missing file should exit non-zero")

    empty = os.path.join(tmp, "empty.jsonl")
    write_jsonl(empty, [{"type": "queue-operation", "content": "x"}])
    out, rc = run(empty)
    if rc == 0:
        fails.append("FAIL 5: bookkeeping-only file should exit non-zero")

    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  all cases: api-request mode, messages mode, tool attribution, "
          "memory/skills markers, --top, 100%% invariant, bad input")


if __name__ == "__main__":
    main()
