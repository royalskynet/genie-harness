#!/usr/bin/env python3
"""Genie preferences: graded verbosity blocks, with per-call opt-out.

The problem this solves. A harness tuned for a beginner is unbearable to someone
who already knows the material: the glossary explains "what is an API" to someone
who ships APIs, every question turns into a web search, and the whole thing gets
switched off wholesale. But switching everything off also throws away the safety
nagging and the step-by-step breakdown, which were the reason the harness exists.

So verbosity is split into independent **blocks**, each a tri-state:

    on     always include it
    auto   include it only when the model judges it earns its place   <- most blocks
    off    never include it

**The most important property of this module: blocks control prose, not
enforcement.** `terms`, `examples`, `steps`, `research`, `confirm` and `humanize`
are things Genie *says*. The catastrophic-command gate (`guard_dangerous.py`) and
Codex's own sandbox and approval policy are not in this file, are not reachable
from the prefs file, and cannot be switched off by any level or any block state.
That is a load-bearing boundary, and `test_prefs.py` asserts it rather than
trusting this docstring.

Ownership is the one bridge, and it is narrow: `owners` records which installed
tool the user chose for a job Genie shares (guard / research / style, see
overlap.py). It counts only while that tool is still installed.

Two more decisions worth knowing:

`level` is a *default layer*, not a set of pins. Changing your level never
overwrites a block you explicitly set; it only supplies defaults for blocks you
have not touched. So you can be a beginner who turned off the glossary, and the
answer survives you later becoming an expert.

Durable changes are deliberate. Plain phrasing ("不用百科") affects that turn
only. Pinning a block requires either an explicit marker (`!terms off`) or a
narrow "stop doing this" phrasing ("不要再給我百科"). Anything we detect is
reported back in the injected context, so a preference never changes silently.

Cost: no third-party imports, no network, no model. This runs on every prompt.
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import overlap  # noqa: E402

LEVELS = ("beginner", "intermediate", "advanced", "expert")
STATES = ("on", "auto", "off")

# Defaults per level. Only consulted for blocks the user has not pinned.
# `research` is on at every level: knowing how others already solved it is worth
# a look even for an expert. Off only when the user says so (`!research off`).
LEVEL_DEFAULTS = {
    "beginner": {
        "terms": "on", "examples": "on", "steps": "on",
        "research": "on", "confirm": "on", "humanize": "on",
    },
    "intermediate": {
        "terms": "auto", "examples": "auto", "steps": "auto",
        "research": "on", "confirm": "on", "humanize": "on",
    },
    "advanced": {
        "terms": "off", "examples": "auto", "steps": "off",
        "research": "on", "confirm": "on", "humanize": "off",
    },
    "expert": {
        "terms": "off", "examples": "off", "steps": "off",
        "research": "on", "confirm": "on", "humanize": "off",
    },
}

# How to explain, per level. Same length budget at every level; what changes is
# where the analogy comes from. Concrete table per term: $genie-explain.
REGISTER = {
    "beginner": "analogies from daily life (kitchen, post office, game saves); "
                "every new term gets a one-line glossary",
    "intermediate": "analogies from tools they already use (spreadsheets, folders, "
                    "browser tabs); name the real term once",
    "advanced": "analogies from adjacent technical ideas (an index, a queue, a lockfile); "
                "real terms freely",
    "expert": "no analogies; precise terms, the mechanism, the trade-off, a source link",
}

BLOCKS = tuple(LEVEL_DEFAULTS["beginner"].keys())

# What each block is, in one line. Used to build the injected context, so the
# model knows what it is being asked to do without reading this file.
BLOCK_MEANING = {
    "terms": "plain-language glossary for a term the user will meet again",
    "examples": "a concrete analogy or example when abstraction loses them",
    "steps": "numbered steps before doing multi-step work",
    "research": "run wheel: find an existing tool/package/service before hand-rolling, "
                "and tell the user if one exists",
    "confirm": "state what is irreversible and confirm before doing it",
    "humanize": "natural conversational tone, continuity, no robotic scaffolding",
}

# Hard-wired knowledge for the model, not a preference. Deliberately not tunable:
# how a turn reads depends on what was asked, not on how much the user likes verbosity.
ALWAYS = (
    "answer in the user's language",
    "ask only when a wrong guess would waste real work; batch every question into one message",
    "say plainly when you do not know",
    "assume they cannot type commands or skill names: run skills and commands yourself",
)

# The host's own permission layer, named in the injected context.
HOST_GUARD = {"codex": "Codex sandbox/approval", "claude": "Claude Code permission prompts"}

# --- parsers ---------------------------------------------------------------

# Explicit, unambiguous markers. `!terms off` / `!no-terms` / `!terms on|auto`
MARKER = re.compile(r"!\s*(?:no[- ]\s*)?(terms|examples|steps|research|confirm|humanize)\s*"
                    r"(?:=\s*)?(on|auto|off)?\b", re.IGNORECASE)

# Shared vocabulary. `NOUN` is a capture group so a match can be mapped to a
# block; alternations are ordered longest-first because re tries them in order
# and `不要` must not be consumed as `不` followed by a stray `再`.
NOUN = r"(小百科|百科|術語|解釋|說明|步驟|拆解|類比|比喻|搜尋|研究|社群|確認|glossary|explanation|example|step)"
GAP = r"[^，。；！？\n]{0,12}?"
NEG_OFF = r"(?:不要|不用|不需要|停止|不|別|勿|stop|don't|do not|no|skip|without)"
NEG_ON = r"(?:打開|開啟|恢復|加回|回來|enable|turn back on|bring back)"
GIVE = r"(?:給|出|附|加|講|說|寫|show|give)"

# Durable "stop doing this". Narrow on purpose: a false positive here silently
# mutes a feature for weeks. (Premortem B2)
DURABLE_OFF = re.compile(
    NEG_OFF + r"再" + GIVE + GAP + NOUN + r"|"
    r"(?:關掉|停用|永久(?:關閉|停用))(?:掉)?" + NOUN + r"|"
    r"(?:停止|永久|一直)" + GIVE + r"?" + GAP + NOUN + r"|" +
    r"\b(?:stop|quit|no more)\b" + GAP + NOUN, re.IGNORECASE)
DURABLE_ON = re.compile(
    r"(?:把|請)?" + NOUN + r"(?:重新)?" + NEG_ON + r"|" +
    NEG_ON + NOUN, re.IGNORECASE)

# Single-turn "not right now". Broader is fine: it expires immediately.
TURN_OFF = re.compile(
    NEG_OFF + GIVE + r"?" + GAP + NOUN + r"|" +
    r"\b(?:no|skip|without)\s+(?:the\s+)?(?:glossary|terms?|explanations?|steps?|examples?)\b",
    re.IGNORECASE)
# Asking for an explanation always means "glossary on", whatever the current
# setting is. One capture group so the block resolves to `terms`.
TURN_ON = re.compile(
    r"(什麼是|什麼叫做|教我|講清楚|解釋一下|說明一下|"
    r"\bwhat is\b|\bexplain\b|\bteach me\b)", re.IGNORECASE)
TURN_ON_BLOCK = "terms"

# About to build something. The user rarely knows a wheel already exists, so this
# turns `research` on for the turn instead of waiting for them to ask. A durable
# `research off` still wins: they asked us to stop.
BUILD = re.compile(
    r"(?:寫|做|弄|建|架|開發)(?:一個|一支|一套|個|支|套)[^，。；\n]{0,8}?"
    r"(?:程式|腳本|工具|網站|網頁|app|系統|bot|機器人|外掛|插件|套件|服務|功能|爬蟲|後台|介面|頁面|api)|"
    r"自己(?:寫|做|刻|造)|從零(?:開始)?(?:寫|做)|自動化|"
    r"\b(?:build|write|make|create|code)\s+(?:me\s+)?an?\s+(?:\w+\s+){0,3}?"
    r"(?:app|tool|script|bot|scraper|site|website|service|plugin|extension|cli|api)\b|"
    r"\bfrom scratch\b",
    re.IGNORECASE)

# "just do it" is a whole-register switch, not one block. Cheap to honour, and
# the alternative is a beginner asking for terseness and still getting essays.
JUST_CODE = re.compile(
    r"\bjust (?:code|the code|do it|answer)\b|"
    r"直接(?:給|說|做|講)(?:我)?(?:程式碼|代碼|重點|答案|結果)", re.IGNORECASE)
JUST_CODE_BLOCKS = ("terms", "examples", "steps")

# `!level expert`: the only way to change level from chat. Durable.
LEVEL_MARKER = re.compile(r"!\s*level\s*(?:=\s*)?(beginner|intermediate|advanced|expert)\b",
                          re.IGNORECASE)

# `!owner guard=dcg` / `!owner research=genie`: who does a job Genie shares.
OWNER_NAME = re.compile(r"[\w.@-]{1,60}")
OWNER_MARKER = re.compile(r"!\s*owner\s+(guard|research|style)\s*=\s*([\w.@-]{1,60})",
                          re.IGNORECASE)

CN_TO_BLOCK = {
    "百科": "terms", "小百科": "terms", "術語": "terms", "解釋": "terms",
    "說明": "terms", "步驟": "steps", "拆解": "steps", "類比": "examples",
    "比喻": "examples", "搜尋": "research", "研究": "research",
    "社群": "research", "確認": "confirm",
}
EN_TO_BLOCK = {
    "terms": "terms", "term": "terms", "glossary": "terms",
    "examples": "examples", "example": "examples",
    "steps": "steps", "step": "steps",
    "research": "research", "confirm": "confirm", "humanize": "humanize",
    "explanation": "terms", "explanations": "terms",
}


def default_path():
    return os.environ.get("GENIE_PREFS") or os.path.expanduser("~/.genie/prefs.json")


def _blank(data):
    """Normalise arbitrary input into a known-good shape.

    Unknown keys are dropped rather than merged. That is what makes
    `{"blocks": {"guard": "off"}}` a no-op instead of a privilege escalation
    attempt, and it means a hand-edited file cannot smuggle in a setting the
    model is meant to respect. (Premortem B1.)
    """
    out = {"level": "beginner", "blocks": {}}
    if not isinstance(data, dict):
        return out
    lvl = data.get("level")
    if lvl in LEVELS:
        out["level"] = lvl
    blocks = data.get("blocks")
    if isinstance(blocks, dict):
        for k, v in blocks.items():
            if k in BLOCKS and v in STATES:
                out["blocks"][k] = v
    # Who owns a job Genie shares with another tool. A name here only takes
    # effect while that tool is actually installed (see owner_of), so a
    # hand-edited `owners.guard` cannot switch the guard off by itself.
    owners = data.get("owners")
    if isinstance(owners, dict):
        for k, v in owners.items():
            if k in overlap.CAPS and isinstance(v, str) and OWNER_NAME.fullmatch(v):
                out.setdefault("owners", {})[k] = v.lower()
    seen = data.get("seen")
    if isinstance(seen, list):
        out["seen"] = [s for s in seen if isinstance(s, str)][:200]
    return out


def load(path=None):
    """Never raises. A missing, empty or corrupt file means defaults."""
    p = path or default_path()
    try:
        with open(p, encoding="utf-8") as fh:
            return _blank(json.load(fh))
    except Exception:
        return _blank({})


def save(data, path=None):
    """Atomic write: tmp file + rename, so two terminals cannot tear the file."""
    p = path or default_path()
    clean = _blank(data)
    d = os.path.dirname(p) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".prefs-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(clean, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def block_state(name, data):
    """Pinned wins, else the level's default."""
    pinned = data.get("blocks", {}).get(name)
    if pinned:
        return pinned
    return LEVEL_DEFAULTS.get(data.get("level", "beginner"), {}).get(name, "auto")


def owner_of(cap, data, found):
    """The other tool that owns `cap`, or "" when Genie does.

    Ownership only counts while that tool is still installed: uninstall it and
    Genie picks the job back up without anyone having to remember to.
    """
    o = data.get("owners", {}).get(cap, "")
    return o if o and o != "genie" and o in found.get(cap, ()) else ""


_NOUN_RE = re.compile(NOUN, re.IGNORECASE)


def _block_of(m):
    """Map a match to a block name.

    Scans every capture group and then the whole match, because an alternation
    may match a branch whose group did not participate. Rescuing the noun from
    the matched text is more robust than trusting group indices.
    """
    cands = [g for g in (m.groups() or ()) if g]
    cands.append(m.group(0))
    for c in cands:
        if c in CN_TO_BLOCK:
            return CN_TO_BLOCK[c]
        if c.lower() in EN_TO_BLOCK:
            return EN_TO_BLOCK[c.lower()]
        hit = _NOUN_RE.search(c)
        if hit:
            tok = hit.group(1)
            return CN_TO_BLOCK.get(tok, "") or EN_TO_BLOCK.get(tok.lower(), "")
    return ""


def parse_prompt(prompt, data=None):
    """-> (turn_overrides, durable_ops, notes). Pure; does not touch disk."""
    turn = {}
    durable = {}
    notes = []
    pinned = data.get("blocks", {}) if isinstance(data, dict) else {}
    if not prompt or not isinstance(prompt, str):
        return turn, durable, notes

    for m in MARKER.finditer(prompt):
        name, state = m.group(1).lower(), (m.group(2) or "toggle").lower()
        if state == "toggle":
            negated = bool(re.match(r"\s*!\s*no[- ]", m.group(0), re.IGNORECASE))
            already = name in turn or name in durable or name in pinned
            state = "off" if (negated or already) else "on"
        if state in STATES:
            durable[name] = state
            notes.append("%s -> %s (marker)" % (name, state))

    for rx, state, bucket in ((DURABLE_OFF, "off", durable), (DURABLE_ON, "auto", durable)):
        for m in rx.finditer(prompt):
            name = _block_of(m)
            if name:
                bucket[name] = state
                notes.append("%s -> %s (phrasing)" % (name, state))

    if JUST_CODE.search(prompt):
        for b in JUST_CODE_BLOCKS:
            turn[b] = "off"

    if BUILD.search(prompt) and "off" not in (pinned.get("research"), durable.get("research")):
        turn["research"] = "on"
        notes.append("research -> on (about to build: run wheel first)")

    for rx, state in ((TURN_OFF, "off"), (TURN_ON, "on")):
        for m in rx.finditer(prompt):
            name = TURN_ON_BLOCK if state == "on" else _block_of(m)
            if name:
                turn[name] = state
    return turn, durable, notes


def resolve(prompt=None, data=None, persist=True, path=None, found=None):
    """Full pipeline. Returns a dict describing this turn.

    `found` is the overlap scan ({job: [other tools]}); scanned from disk when
    reading the real prefs file, empty when the caller hands in `data`.
    """
    first_run = data is None and not os.path.exists(path or default_path())
    if found is None:
        found = {}
        if data is None:
            try:
                found = overlap.scan()
            except Exception:
                pass
    data = _blank(data) if data is not None else load(path)
    turn, durable, notes = parse_prompt(prompt, data)
    text = prompt if isinstance(prompt, str) else ""

    lvl = LEVEL_MARKER.search(text)
    if lvl and lvl.group(1).lower() != data["level"]:
        notes.append("level -> %s (marker)" % lvl.group(1).lower())
    owners = {m.group(1).lower(): m.group(2).lower() for m in OWNER_MARKER.finditer(text)}
    for cap, who in owners.items():
        notes.append("owner of %s -> %s (marker)" % (cap, who))

    # Jobs another installed tool also does, that the user has not been asked about.
    seen = set(data.get("seen", []))
    ask = {c: n for c, n in found.items()
           if c not in owners and any("%s:%s" % (c, x) not in seen for x in n)}

    if (durable or lvl or owners or ask or first_run) and persist:
        merged = _blank(data)
        merged["blocks"].update(durable)
        if lvl:
            merged["level"] = lvl.group(1).lower()
        if owners:
            merged.setdefault("owners", {}).update(owners)
        # Asked once is enough; a tool installed later is a new name and asks again.
        merged["seen"] = sorted(seen | {"%s:%s" % (c, x) for c, n in found.items() for x in n})
        try:
            save(merged, path)
            data = merged
        except Exception:
            notes.append("(could not write prefs file; change applies to this turn only)")
    if lvl:  # applies this turn even if the write failed
        data = dict(data, level=lvl.group(1).lower())
    if owners:
        data = dict(data, owners=dict(data.get("owners", {}), **owners))

    states = {b: block_state(b, data) for b in BLOCKS}
    handed = {c: owner_of(c, data, found) for c in overlap.CAPS}
    if handed["research"]:
        states["research"] = "off"
        turn.pop("research", None)  # the other tool does its own build nudge
        notes[:] = [n for n in notes if "about to build" not in n]
    if handed["style"]:
        for b in STYLE_BLOCKS:
            states[b] = "off"
    for name, st in turn.items():
        states[name] = st
    return {
        "level": data["level"],
        "pinned": dict(data["blocks"]),
        "turn_overrides": turn,
        "changes": notes,
        "blocks": states,
        "first_run": first_run,
        "ask_owner": ask,
        "handed_off": {c: o for c, o in handed.items() if o},
    }


# Blocks a dedicated style tool (caveman and friends) takes over when it owns `style`.
STYLE_BLOCKS = ("terms", "examples", "humanize")
CLI = "python3 " + os.path.abspath(__file__)

ONBOARDING = (
    "FIRST RUN. Before answering, introduce Genie in at most 3 short lines: it explains "
    "things at the user's level, looks for an existing tool before building one, and "
    "stops before anything irreversible. Then ask ONE question, which level fits them: "
    "beginner (everyday analogies + glossary) / intermediate (analogies from tools they "
    "use) / advanced (adjacent tech, no glossary) / expert (no analogies: mechanism, "
    "trade-off, source). Say that at every level Genie still checks how others already "
    "solved it before building, since that is worth knowing even for an expert, and "
    "that `!research off` turns it off. They can answer `!level <l>` or in plain words; "
    "on plain words run `%s set level <l>`. Then answer their message." % CLI)


def render_context(res, host="codex"):
    """The short block injected as UserPromptSubmit additionalContext."""
    handed = res.get("handed_off", {})
    lines = ["[genie prefs] level=%s" % res["level"]]
    if not handed.get("style"):
        lines.append("register: " + REGISTER.get(res["level"], REGISTER["beginner"]))
    if res.get("first_run"):
        lines.append(ONBOARDING)
    if res["changes"]:
        lines.append("changed this message: " + "; ".join(res["changes"]))
    for cap, names in sorted(res.get("ask_owner", {}).items()):
        other = "/".join(names)
        lines.append(
            "OVERLAP: %s also does `%s` (%s). Ask the user once, in the same message as "
            "anything else you ask, who should own it, with this advice: %s. On their "
            "answer run `%s set owner %s <genie|%s>`. If they pick Genie, offer to turn "
            "%s's version off, show the exact change and wait for a yes (it is their "
            "config, not Genie's)." % (other, cap, overlap.CAPS[cap],
                                       overlap.RECOMMEND[cap].format(other=other),
                                       CLI, cap, names[0], other))
    for name in BLOCKS:
        st = res["blocks"][name]
        owned = next((o for c, o in handed.items()
                      if (c == "research" and name == "research")
                      or (c == "style" and name in STYLE_BLOCKS)), "")
        mark = " (this turn only)" if name in res["turn_overrides"] else (
            " (handled by %s)" % owned if owned else (
                " (you set this)" if name in res["pinned"] else ""))
        lines.append("- %s[%s]%s: %s" % (name, st, mark, BLOCK_MEANING[name]))
    lines.append("not preference-tunable, always on: " + "; ".join(ALWAYS))
    if handed.get("guard"):
        lines.append("catastrophic-command gate: handed to %s by the user; Genie's guard "
                     "stands down while %s is installed. %s still apply."
                     % (handed["guard"], handed["guard"], HOST_GUARD.get(host, HOST_GUARD["codex"])))
    else:
        lines.append("NOT blocks, and no preference can turn them off: the "
                     "catastrophic-command gate, and %s." % HOST_GUARD.get(host, HOST_GUARD["codex"]))
    return "\n".join(lines)


USAGE = """genie prefs
  (no args)                 show current settings
  set level <l>             beginner | intermediate | advanced | expert
  set owner <job> <who>     guard | research | style -> genie or the other tool
  set <block> <state>       %s
  clear <block>             back to following your level
  reset                     forget everything
  path                      where this file lives
""" % " | ".join("%s=%s" % (b, s) for b in BLOCKS for s in STATES)


def main(argv):
    args = list(argv[1:])
    p = default_path()
    if not args or args[0] in ("show", "list", "get"):
        data = load(p)
        print("level: %s" % data["level"])
        for b in BLOCKS:
            src = "pinned" if b in data["blocks"] else "from level"
            print("  %-9s %-4s (%s)" % (b, block_state(b, data), src))
        for cap, who in sorted(data.get("owners", {}).items()):
            print("owner: %-8s %s" % (cap, who))
        print("file: %s" % p)
        return 0
    if args[0] == "path":
        print(p)
        return 0
    if args[0] == "reset":
        save(_blank({}), p)
        print("reset to defaults (level=beginner)")
        return 0
    if args[0] == "set" and len(args) >= 2:
        data = load(p)
        key, val = args[1], (args[2] if len(args) > 2 else "")
        if key == "level":
            if val not in LEVELS:
                print("level must be one of: %s" % ", ".join(LEVELS))
                return 2
            data["level"] = val
        elif key == "owner" and len(args) > 3:
            if val not in overlap.CAPS or not OWNER_NAME.fullmatch(args[3]):
                print("usage: set owner <%s> <genie|tool>" % "|".join(overlap.CAPS))
                return 2
            data.setdefault("owners", {})[val] = args[3].lower()
        elif key in BLOCKS:
            if val not in STATES:
                print("%s must be one of: %s" % (key, ", ".join(STATES)))
                return 2
            data["blocks"][key] = val
        else:
            print("unknown key: %s\n\n%s" % (key, USAGE))
            return 2
        save(data, p)
        print("saved: level=%s %s %s" % (data["level"],
                                         json.dumps(data["blocks"], ensure_ascii=False),
                                         json.dumps(data.get("owners", {}))))
        return 0
    if args[0] == "clear" and len(args) >= 2:
        data = load(p)
        if args[1] in data["blocks"]:
            del data["blocks"][args[1]]
            save(data, p)
            print("cleared %s" % args[1])
        else:
            print("%s was not pinned" % args[1])
        return 0
    sys.stdout.write(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
