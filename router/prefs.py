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
# Only the analogy source is injected: what each block *does* is in AGENTS.md,
# so repeating it here spent a paragraph per turn to say nothing new.
REGISTER = {
    "beginner": "daily life (kitchen, post office, game saves)",
    "intermediate": "tools they already use (spreadsheets, folders, browser tabs); "
                    "name the real term once",
    "advanced": "adjacent technical ideas (an index, a queue, a lockfile); "
                "real terms freely",
    "expert": "none; precise terms, the mechanism, the trade-off, a source link",
}

BLOCKS = tuple(LEVEL_DEFAULTS["beginner"].keys())

# What each block means is not repeated per turn: the injected dial is only the
# state, and the meaning table lives in AGENTS.md where the model already reads
# it. Spending ~500 characters of every prompt to restate it bought nothing.

# Hard-wired knowledge for the model, not a preference. Deliberately not tunable:
# how a turn reads depends on what was asked, not on how much the user likes verbosity.
# Every line here is paid on every single turn, so each one is written at the
# shortest wording that still survives a literal reading. Adding a clause costs
# ~4 characters per word forever; say it in genie-humanizer instead unless the
# model has to have it in front of it while answering.
ALWAYS = (
    "answer in the user's language (Traditional Chinese: Taiwan terms, 軟體/程式/網路)",
    # The 4 stop cases stay spelled out. Shortening them to "irreversible, costly"
    # reads as a narrower list and talks the model out of stopping before a publish.
    "decide and proceed: pick one option and do it; ask only when it cannot be undone, "
    "is seen by others, costs money or system settings, changes someone else's rules, "
    "or a wrong guess wastes the whole job; batch all questions into one message",
    "say plainly when you do not know",
    # ASD-STE100-style clarity, at every level and under any style tool: a misread
    # is a wrong action. Detail lives in genie-humanizer.
    "one reading per sentence: short, one action each, one name per thing, active "
    "voice, no vague words",
    # Rhetorical slop: clear sentences carrying no information, including the
    # defensive counterpoint added to look even-handed. Detail in genie-humanizer.
    "no slop: no colon reveals, no 'not X but Y', no puffery, no meta-commentary, no "
    "profound last line, no unsourced claims; cut any sentence true of any product",
    # The old wording ("say so without a token counterpoint") was a prohibition and
    # was obeyed loosely; this is the shape to produce instead. "Cannot rule out"
    # is singled out because nothing can be ruled out, so it carries no weight.
    "verdicts: lead with the answer and its confidence ('A, strong evidence'); raise "
    "B only with concrete evidence and say how weak it is; 'both possible' only when "
    "the evidence is even, plus the data that would decide; 'cannot rule out B' is "
    "not an argument",
    # Semantic translation, both ways. Without it the model echoes their words
    # back as the spec, and reports "exit 137" as if it were an answer. "Never
    # rosier" is the part that matters: a plain-words summary is where "partly
    # worked" quietly becomes "done". Detail in genie-humanizer.
    "translate meaning both ways: their words -> a checkable target (name your reading "
    "only if readings differ); your results -> what it means for them, never rosier, "
    "error text kept verbatim",
    "they cannot type commands: run skills and commands yourself",
)


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
    # A pinned reply language, for a user whose own rules say "always X" even when
    # they type in another language. Free text, so it is length-capped.
    lang = data.get("lang")
    if isinstance(lang, str) and lang.strip():
        out["lang"] = lang.strip()[:40]
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


def resolve(prompt=None, data=None, persist=True, path=None, found=None, dups=None):
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
    if dups is None:
        dups = overlap.duplicates() if data is None else []
    data = _blank(data) if data is not None else load(path)
    turn, durable, notes = parse_prompt(prompt, data)
    text = prompt if isinstance(prompt, str) else ""

    lvl = LEVEL_MARKER.search(text)
    if lvl and lvl.group(1).lower() != data["level"]:
        notes.append("level -> %s (marker)" % lvl.group(1).lower())
    owners = {m.group(1).lower(): m.group(2).lower() for m in OWNER_MARKER.finditer(text)}
    for cap, who in owners.items():
        notes.append("owner of %s -> %s (marker)" % (cap, who))

    # Jobs another installed tool also does, that the user has not heard about yet.
    # ask: one of them has to own it. tell: they stack fine, so it is news, not a question.
    seen = set(data.get("seen", []))
    fresh = {c: n for c, n in found.items() if any("%s:%s" % (c, x) not in seen for x in n)}
    ask = {c: n for c, n in fresh.items()
           if c not in overlap.NOTIFY
           and c not in owners and c not in (data.get("owners") or {})}
    tell = {c: n for c, n in fresh.items() if c in overlap.NOTIFY}
    new_dups = [(k, m) for k, m in dups if k not in seen]

    if (durable or lvl or owners or ask or tell or new_dups or first_run) and persist:
        merged = _blank(data)
        merged["blocks"].update(durable)
        if lvl:
            merged["level"] = lvl.group(1).lower()
        if owners:
            merged.setdefault("owners", {}).update(owners)
        # Asked once is enough; a tool installed later is a new name and asks again.
        merged["seen"] = sorted(seen | {"%s:%s" % (c, x) for c, n in found.items() for x in n}
                                | {k for k, _ in new_dups})
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
        "coexist": tell,
        "duplicates": [m for _, m in new_dups],
        "handed_off": {c: o for c, o in handed.items() if o},
        "lang": data.get("lang"),
        "missing": overlap.missing_companions(found) if first_run else [],
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


def render_context(res, host="codex", part="all"):
    """The prefs block. part="all": everything, every turn (Codex: no SessionStart).
    part="static": level/register/blocks/ALWAYS, sent once by Claude's SessionStart
    (re-runs after /compact and /clear). part="turn": only what this message
    changed or raised; the static block rides along only when the state moved.
    UserPromptSubmit context stays in the transcript, so a static block sent every
    turn piles up one copy per message."""
    if part == "turn":
        news = []
        if res.get("first_run"):
            news.append(ONBOARDING)
        news += _notices(res)
        if res["changes"] or res["turn_overrides"]:
            return render_context(res, host, "static") + ("\n" + "\n".join(news) if news else "") \
                + "\nchanged this message: " + ("; ".join(res["changes"]) or "turn-only override")
        return "\n".join(news)
    handed = res.get("handed_off", {})
    lines = ["[genie prefs] level=%s" % res["level"]]
    # Not droppable when terms and examples are off: at the upper levels the register
    # is the instruction NOT to reach for an analogy, and it sets how every sentence
    # is pitched, not just the two blocks that spell a term out.
    if not handed.get("style"):
        lines.append("register: " + REGISTER.get(res["level"], REGISTER["beginner"]))
    if part == "all":
        if res.get("first_run"):
            lines.append(ONBOARDING)
        if res["changes"]:
            lines.append("changed this message: " + "; ".join(res["changes"]))
        lines += _notices(res)
    lines.append(_dial(res, handed))
    always = list(ALWAYS)
    if res.get("lang"):
        always[0] = "always answer in %s, whatever they write in" % res["lang"]
    lines.append("not preference-tunable, always on: " + "; ".join(always))
    # No line about the command gate or the host's permission prompts: both are
    # enforced outside the model, so telling it every turn changed nothing it did.
    return "\n".join(lines)


def _notices(res):
    """One-time lines: optional companions, overlaps, duplicates."""
    lines = []
    if res.get("first_run"):
        for name, why, how in res.get("missing", []):
            lines.append("OPTIONAL, not installed: %s (%s). Mention it once, in one line, "
                         "with how to add it: %s. Do not install it yourself." % (name, why, how))
    for cap, names in sorted(res.get("ask_owner", {}).items()):
        other = "/".join(names)
        lines.append(
            "OVERLAP: %s also does `%s` (%s). Ask the user once, in the same message as "
            "anything else you ask, who should own it, with this advice: %s. "
            "On their answer run `%s set owner %s <genie|%s>`. If they pick Genie, offer "
            "to turn %s's version off, show the exact change and wait for a yes (it is "
            "their config, not Genie's)." % (other, cap, overlap.CAPS[cap],
                                             overlap.RECOMMEND[cap].format(other=other),
                                             CLI, cap, names[0], other))
    for cap, names in sorted(res.get("coexist", {}).items()):
        other = "/".join(names)
        lines.append(
            "COEXIST: %s also does `%s` (%s). Nothing to decide and nothing to turn off: "
            "%s. Tell the user once, in one line, so a second nudge is not a surprise."
            % (other, cap, overlap.CAPS[cap], overlap.COEXIST[cap].format(other=other)))
    for msg in res.get("duplicates", []):
        lines.append("DUPLICATE: " + msg + ". Raise it once, alongside anything else you ask.")
    return lines


def _dial(res, handed):
    # One line, states only: this runs on every prompt, so the dial has to be
    # scannable at a glance rather than six paragraphs long. Marks ride along
    # after the value so a change never changes state silently.
    # Marks are single characters with one legend at the end: spelling out
    # "(you set this)" beside four pinned blocks cost 56 characters of every prompt.
    dial, legend = [], []
    for name in BLOCKS:
        owned = next((o for c, o in handed.items()
                      if (c == "research" and name == "research")
                      or (c == "style" and name in STYLE_BLOCKS)), "")
        if name in res["turn_overrides"]:
            mark = "~"
        elif owned:
            mark = "^"
            if owned not in legend:
                legend.append(owned)
        else:
            mark = "*" if name in res["pinned"] else ""
        dial.append("%s=%s%s" % (name, res["blocks"][name], mark))
    key = ["%s %s" % (mark, meaning)
           for mark, meaning in (("*", "you set"), ("~", "this turn only"),
                                 ("^", "handled by " + "/".join(legend)))
           if any(d.endswith(mark) for d in dial)]
    return "blocks: " + " ".join(dial) + ("  (%s)" % "; ".join(key) if key else "")


USAGE = """genie prefs
  (no args)                 show current settings
  set level <l>             beginner | intermediate | advanced | expert
  set owner <job> <who>     guard | research | style -> genie or the other tool
  set lang <language>       always reply in it (e.g. "Traditional Chinese"); "off" to follow theirs
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
        if data.get("lang"):
            print("lang: %s" % data["lang"])
        print("file: %s" % p)
        return 0
    if args[0] == "path":
        print(p)
        return 0
    if args[0] == "context":  # Claude SessionStart: the static block, once per session
        print(render_context(resolve(None, persist=False), "claude", "static"))
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
        elif key == "lang":
            if val in ("", "off"):
                data.pop("lang", None)
            else:
                data["lang"] = " ".join(args[2:])[:40]
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
