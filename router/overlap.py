#!/usr/bin/env python3
"""Find other installed tools that do a job Genie also does.

Genie is a general harness, not a security suite and not the only way to find
prior art. When a user already runs a dedicated tool for one of these jobs, two
tools doing it means double warnings, contradictory tone, or one tool's denial
masking the other's. So Genie does not fight: it notices, asks the user once who
should own the job, and stands down on its side if the answer is "the other one".

Detection is a cheap static scan, no network and no model, of the host Genie
runs in (Claude Code sets CLAUDE_PLUGIN_ROOT for plugin hooks):
  - Codex: hook commands in $CODEX_HOME/hooks.json, skill dirs in
    ~/.agents/skills and $CODEX_HOME/skills
  - Claude Code: hook commands in ~/.claude/settings.json, skill dirs in
    ~/.claude/skills, plus enabledPlugins names (ponytail: a plugin's own
    hooks are not read, so a plugin never counts as a guard; add when a
    plugin-shipped guard is seen in the wild)
Anything that resolves into the Genie checkout itself is ignored.

ponytail: name-signature matching, so an unrecognised tool with a bland name is
missed. Add its signature to SIGNATURES when that happens.
"""
import glob
import json
import os
import re
import shutil

GENIE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# job -> what it means, in one line (shown to the user when asking)
# One entry per standing Genie capability, so an overlap anywhere gets surfaced:
# guard = PreToolUse, route = UserPromptSubmit, done = Stop, research/style = skills.
CAPS = {
    "guard": "block catastrophic commands (rm -rf ~, force push to main, drop table)",
    "research": "look for an existing tool before building ($wheel)",
    "style": "tone and depth of replies (level, glossary, analogies)",
    "route": "read each message and tell the assistant what this turn needs",
    "done": "ask for real output before a task is called finished",
}

SIGNATURES = {
    "guard": re.compile(r"\bdcg\b|destructive[-_ ]?command|safety[-_]?net|dangerous|"
                        r"guardrail|\w*guard\w*", re.I),
    "research": re.compile(r"\w*wheel\w*|prior[-_]?art|dont[-_]?reinvent|deja[-_]?vu|"
                           r"reinvent", re.I),
    # ponytail-review/audit/debt/help are one-shot reports, not a tone or depth mode.
    "style": re.compile(r"caveman|terse|output[-_]?style|ponytail(?![-_]?(review|audit|debt|help))|"
                        r"\basd\b|asd[-_]style", re.I),
    "route": re.compile(r"\w*rout\w*|\bintent\b|classif|triage|preclassif", re.I),
    "done": re.compile(r"\w*gate\w*|done[-_]?check|complet|\bclaim\b|stop[-_]?hook", re.I),
}

# Two kinds of overlap. ARBITRATE: both tools act on the same turn and fight, so
# one has to own it. NOTIFY: they stack without fighting (a second opinion costs
# a little noise, not a wrong outcome), so say it once and leave both running --
# turning one off would cost the user a layer they may be the only one to have.
NOTIFY = ("route", "done")

# Who should go quiet here. Picking an owner is small and reversible, so that is
# all a user is ever asked for; folding another tool's rules into Genie is a
# checkout workflow (read both sets, keep the difference, ship the skill) and
# belongs upstream, not in an injected instruction.
RECOMMEND = {
    "guard": "suggest Genie keeps the floor and {other} keeps whatever it covers beyond "
             "it; if only one may speak, prefer the one with more rules, and say which "
             "checks the other one had",
    "research": "suggest Genie ($wheel is wired to the level and to build detection), "
                "unless {other} is a workflow the user already relies on",
    "style": "suggest Genie, with {other}'s sharper rules folded into $genie-humanizer; "
             "hand over only if {other} is doing something Genie's levels cannot express",
}

# What to say for a NOTIFY overlap: no question, no owner, nothing to turn off.
COEXIST = {
    "route": "Genie names what the turn needs, {other} may point at a tool or a level. "
             "Follow both; they answer different questions",
    "done": "both ask for evidence before finishing. Genie's is mechanical (files changed, "
            "nothing run); {other} may judge the wording. Keep both",
}

# Which hook event can actually do the job: only PreToolUse blocks a command,
# only UserPromptSubmit sees the message before the reply, only Stop sees the end.
_EVENTS = {"guard": ("PreToolUse",), "research": None, "style": None,
           "route": ("UserPromptSubmit",), "done": ("Stop",)}


def codex_home():
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def on_claude():
    return bool(os.environ.get("CLAUDE_PLUGIN_ROOT"))


def hooks_file(home=None):
    if home:
        return os.path.join(home, "hooks.json")
    if on_claude():
        return os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"),
                            "settings.json")
    return os.path.join(codex_home(), "hooks.json")


def skill_dirs():
    if on_claude():
        return [os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"),
                             "skills")]
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
    try:
        with open(hooks_file(home), encoding="utf-8") as fh:
            cfg = json.load(fh)
        hooks = cfg.get("hooks", {})
        plugins = [k.split("@")[0] for k, v in (cfg.get("enabledPlugins") or {}).items() if v]
    except Exception:
        hooks, plugins = {}, []
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
            if n.lower() == "wheel":  # a copy of Genie's own skill: duplicates() reports it
                continue
            for cap, rx in SIGNATURES.items():
                # A skill cannot block a command, inject into every turn, or run at Stop:
                # those jobs need a hook, so only a hook counts as another owner of them.
                if _EVENTS[cap] is None and rx.search(n):
                    found[cap].add(n.lower())
    for n in plugins:
        if not n.startswith("genie"):
            for cap, rx in SIGNATURES.items():
                if _EVENTS[cap] is None and rx.search(n):
                    found[cap].add(n.lower())
    return {c: sorted(v) for c, v in found.items() if v}


WHEEL_REGISTRY = os.path.expanduser("~/.wheel/registry.tsv")


def legacy_registries():
    """Other places an older or private wheel kept its cards."""
    claude = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return [os.path.join(claude, "wheel", "registry.tsv"),
            os.path.join(codex_home(), "wheel", "registry.tsv")]


def duplicates(dirs=None):
    """-> [(key, message)] for copies of Genie's own parts outside the checkout.

    Not an overlap: a second copy of $wheel is not another tool to hand the job
    to, it is the same tool drifting apart, with wheel cards split across two
    registries so step 0 misses old decisions. Never raises.
    """
    out = []
    for d in dirs if dirs is not None else skill_dirs():
        p = os.path.join(d, "wheel")
        try:
            if os.path.isdir(p) and not _is_genie(p):
                out.append(("dup:skill:" + p,
                            "a separate copy of Genie's $wheel skill is installed at %s. Two "
                            "copies drift apart. Diff it against Genie's skills/wheel/SKILL.md, "
                            "move any local-only rule into the user's CLAUDE.md/AGENTS.md, then "
                            "offer to delete the copy (show the exact path, wait for a yes)" % p))
        except Exception:
            pass
    for r in legacy_registries():
        try:
            if os.path.isfile(r) and not (os.path.exists(WHEEL_REGISTRY)
                                          and os.path.samefile(r, WHEEL_REGISTRY)):
                out.append(("dup:registry:" + r,
                            "wheel cards are also kept in %s, so $wheel step 0 misses them. "
                            "Append its lines to %s, then replace its folder with a symlink to "
                            "~/.wheel (reversible; say what you did)" % (r, WHEEL_REGISTRY)))
        except Exception:
            pass
    return out


# Tools Genie works better next to but never installs: a new device should not
# inherit one person's setup. Suggested once, on the first run, only if absent.
COMPANIONS = (
    ("ponytail", "keeps the code it writes minimal: stdlib and what is already "
                 "installed before anything new; its always-on hook needs `node` on PATH",
     "Claude Code `/plugin marketplace add DietrichGebert/ponytail` then "
     "`/plugin install ponytail@ponytail`; Codex `codex plugin marketplace add "
     "DietrichGebert/ponytail` then install it from `/plugins`"),
    ("fixindex", "a personal fix log: every bug fixed once is found again by its error "
                 "text, and Genie's fix requests check it first",
     "`git clone https://github.com/royalskynet/fixindex.git ~/dev/fixindex && "
     "ln -s ~/dev/fixindex/fixindex ~/.local/bin/fixindex && mkdir -p ~/notes/runbook/fixes`, "
     "then add `export FIXINDEX_DIR=$HOME/notes/runbook/fixes` to the shell profile "
     "(without it fixindex looks in the current directory)"),
)


def missing_companions(found):
    """-> [(name, why, how)] for companions not on PATH, not seen by scan(), and
    not in Codex's plugin cache."""
    names = {n for v in found.values() for n in v}
    out = []
    for name, why, how in COMPANIONS:
        cache = glob.glob(os.path.join(codex_home(), "plugins", "cache", "*", name))
        if shutil.which(name) or any(name in n for n in names) or (cache and not on_claude()):
            continue
        out.append((name, why, how))
    return out


if __name__ == "__main__":
    print(json.dumps(scan(), indent=2))
