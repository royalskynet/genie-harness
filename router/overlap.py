#!/usr/bin/env python3
"""Find other installed tools that do a job Genie also does.

Genie is a general harness, not a security suite and not the only way to find
prior art. When a user already runs a dedicated tool for one of these jobs, two
tools doing it means double warnings, contradictory tone, or one tool's denial
masking the other's. So Genie does not fight: it notices, asks the user once who
should own the job, and stands down on its side if the answer is "the other one".

Detection is a cheap static scan, no network and no model:
  - Codex hook commands in $CODEX_HOME/hooks.json
  - skill directory names in ~/.agents/skills and $CODEX_HOME/skills
Anything that resolves into the Genie checkout itself is ignored.

ponytail: name-signature matching, so an unrecognised tool with a bland name is
missed. Add its signature to SIGNATURES when that happens.
"""
import json
import os
import re

GENIE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# job -> what it means, in one line (shown to the user when asking)
CAPS = {
    "guard": "block catastrophic commands (rm -rf ~, force push to main, drop table)",
    "research": "look for an existing tool before building ($wheel)",
    "style": "tone and depth of replies (level, glossary, analogies)",
}

SIGNATURES = {
    "guard": re.compile(r"\bdcg\b|destructive[-_ ]?command|safety[-_]?net|dangerous|"
                        r"guardrail|\w*guard\w*", re.I),
    "research": re.compile(r"\w*wheel\w*|prior[-_]?art|dont[-_]?reinvent|deja[-_]?vu|"
                           r"reinvent", re.I),
    "style": re.compile(r"caveman|terse|output[-_]?style|ponytail", re.I),
}

# Advice given when asking. Genie's guard is a beginner floor, so a dedicated
# tool is the better owner; for research and style Genie's version is wired
# into the level system, so it is the default suggestion.
RECOMMEND = {
    "guard": "suggest {other}: Genie is not a security suite, its guard is only a floor "
             "for beginners; a dedicated tool covers more",
    "research": "suggest Genie ($wheel is wired to the level and to build detection), "
                "unless {other} is a workflow the user already relies on",
    "style": "suggest Genie at beginner/intermediate, {other} at advanced/expert "
             "(terse styles fight beginner explanations)",
}

# Only a PreToolUse hook can actually block a command.
_EVENTS = {"guard": ("PreToolUse",), "research": None, "style": None}


def codex_home():
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def skill_dirs():
    return [os.path.expanduser("~/.agents/skills"), os.path.join(codex_home(), "skills")]


def _is_genie(path):
    try:
        return os.path.realpath(path).startswith(os.path.realpath(GENIE_DIR) + os.sep)
    except Exception:
        return False


def _name(text, rx):
    """The path segment containing the match, without extension: a stable name."""
    for seg in re.split(r"[\s/\\'\"]+", text):
        if rx.search(seg):
            return re.sub(r"\.(js|mjs|ts|py|sh)$", "", seg).lower()
    return ""


def scan(home=None, dirs=None):
    """-> {cap: sorted list of other tools}. Never raises."""
    found = {c: set() for c in CAPS}
    home = home or codex_home()
    try:
        with open(os.path.join(home, "hooks.json"), encoding="utf-8") as fh:
            hooks = json.load(fh).get("hooks", {})
    except Exception:
        hooks = {}
    for event, entries in (hooks.items() if isinstance(hooks, dict) else ()):
        for e in entries if isinstance(entries, list) else ():
            for h in (e.get("hooks") or []) if isinstance(e, dict) else ():
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                if not isinstance(cmd, str) or not cmd or GENIE_DIR in cmd or "genie" in cmd.lower():
                    continue
                for cap, rx in SIGNATURES.items():
                    if _EVENTS[cap] and event not in _EVENTS[cap]:
                        continue
                    n = _name(cmd, rx)
                    if n:
                        found[cap].add(n)
    for d in dirs if dirs is not None else skill_dirs():
        try:
            names = os.listdir(d)
        except Exception:
            continue
        for n in names:
            if n.startswith(".") or n.startswith("genie") or _is_genie(os.path.join(d, n)):
                continue
            for cap, rx in SIGNATURES.items():
                if cap != "guard" and rx.search(n):  # a skill cannot block a command
                    found[cap].add(n.lower())
    return {c: sorted(v) for c, v in found.items() if v}


if __name__ == "__main__":
    print(json.dumps(scan(), indent=2))
