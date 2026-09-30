#!/usr/bin/env python3
"""UserPromptSubmit hook: resolve this turn's blocks and inject them.

Runs on every prompt, so it does the least work possible: read one small JSON
file, run a few regexes, write back only if something actually changed. No
imports beyond the standard library, no network, no model.

Output shape is the `UserPromptSubmit` contract: `additionalContext`. It is
context, not a command -- the model is told what this turn looks like and is
trusted to follow it. Anything that must hold regardless of preference lives in
the guard or in Codex itself, never here.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import prefs
except Exception:
    sys.exit(0)  # prefs module broken: never break the prompt


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return
    if not raw.strip():
        return
    try:
        data = json.loads(raw)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    prompt = data.get("prompt") or data.get("user_prompt") or ""
    if not isinstance(prompt, str) or not prompt.strip():
        return

    try:
        res = prefs.resolve(prompt)
        text = prefs.render_context(res)
    except Exception:
        return  # fail open: a preferences problem must not block the prompt

    json.dump({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": text,
    }}, sys.stdout)


if __name__ == "__main__":
    main()
