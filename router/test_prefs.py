#!/usr/bin/env python3
"""Tests for the preferences system.

The one that matters most is `test_blocks_cannot_disable_enforcement`. The whole
premise of this feature is "turn the safety nagging off without losing the gate",
and the most likely way to ship it wrong is to let a preference file reach the
guard. So that test runs the real guard as a subprocess with every block off and
a hostile prefs file, and requires it to still deny.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prefs  # noqa: E402
import guard_dangerous as guard  # noqa: E402
import overlap  # noqa: E402

# Tests must not depend on what this machine has installed.
_real_scan = overlap.scan
overlap.scan = lambda *a, **k: {}

PREFS_HOOK = os.path.join(HERE, "genie_router.py")  # the one UserPromptSubmit hook


def eq(got, want, label, fails):
    if got != want:
        fails.append("%s: got %r want %r" % (label, got, want))


def test_defaults_per_level(fails):
    d = prefs._blank({})
    eq(prefs.block_state("terms", d), "on", "beginner always gets the glossary", fails)
    eq(prefs.block_state("steps", d), "on", "beginner steps default", fails)

    adv = prefs._blank({"level": "advanced"})
    eq(prefs.block_state("terms", adv), "off", "advanced terms default", fails)
    eq(prefs.block_state("research", adv), "on", "advanced research default", fails)
    eq(prefs.block_state("research", prefs._blank({"level": "expert"})), "on",
       "experts also hear how others solved it", fails)
    eq(prefs.block_state("confirm", adv), "on", "confirm survives advanced", fails)


def test_levels_are_a_gradient(fails):
    """Each step up says less; expert says least. Register differs per level."""
    talk = lambda lvl: sum(prefs.block_state(b, prefs._blank({"level": lvl})) != "off"
                           for b in ("terms", "examples", "steps", "humanize"))
    counts = [talk(l) for l in prefs.LEVELS]
    eq(counts, sorted(counts, reverse=True), "verbosity never rises with level", fails)
    eq(prefs.LEVELS[-1], "expert", "expert is the top level", fails)
    eq(len(set(prefs.REGISTER[l] for l in prefs.LEVELS)), len(prefs.LEVELS),
       "every level has its own register", fails)
    ctx = prefs.render_context(prefs.resolve("hi", data={"level": "expert"}, persist=False))
    eq("register: " + prefs.REGISTER["expert"] in ctx, True, "register injected", fails)


def test_level_marker_persists(fails):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        prefs.save(prefs._blank({"blocks": {"terms": "on"}}), path)
        res = prefs.resolve("!level expert 幫我看這段", path=path)
        eq(res["level"], "expert", "marker applies this turn", fails)
        eq(prefs.load(path)["level"], "expert", "marker persists", fails)
        eq(prefs.load(path)["blocks"], {"terms": "on"}, "pins survive level marker", fails)
        eq(prefs.resolve("!level wizard", path=path)["level"], "expert",
           "unknown level ignored", fails)


def test_build_turns_research_on(fails):
    """Users rarely know a wheel exists; asking to build must trigger $wheel."""
    for p in ("幫我寫一個爬蟲程式", "我想做個記帳 app", "build me a CLI tool",
              "write a script to rename files", "想自己寫登入", "從零開始做"):
        res = prefs.resolve(p, data={}, persist=False)
        eq(res["blocks"]["research"], "on", "build nudge: " + p, fails)
    for p in ("寫個總結給我", "把這個函式改成非同步", "make a commit", "那個 bug 修好了嗎"):
        res = prefs.resolve(p, data={}, persist=False)
        eq(any("about to build" in n for n in res["changes"]), False, "no build nudge: " + p, fails)
    res = prefs.resolve("幫我寫一個爬蟲程式", data={"blocks": {"research": "off"}}, persist=False)
    eq(res["blocks"]["research"], "off", "durable research off still wins", fails)


def test_level_does_not_stomp_pins(fails):
    """Changing level supplies defaults; it must not erase an explicit choice."""
    data = prefs._blank({"level": "beginner", "blocks": {"terms": "off"}})
    data["level"] = "advanced"
    eq(prefs.block_state("terms", data), "off", "pin survives level change", fails)
    # a block that was never pinned now follows the new level
    data2 = prefs._blank({"blocks": {"terms": "off"}})
    data2["level"] = "advanced"
    eq(prefs.block_state("steps", data2), "off", "unpinned follows new level", fails)


def test_single_turn_does_not_persist(fails):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        prefs.save(prefs._blank({}), path)

        res = prefs.resolve("不用百科", path=path)
        eq(res["blocks"]["terms"], "off", "turn override applied", fails)
        eq(res["turn_overrides"], {"terms": "off"}, "recorded as turn override", fails)
        eq(prefs.load(path)["blocks"], {}, "turn override not persisted", fails)

        # and the next turn is back to normal
        res2 = prefs.resolve("那個 bug 修好了嗎", path=path)
        eq(res2["blocks"]["terms"], "on", "next turn unaffected", fails)


def test_durable_phrasing_persists(fails):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        prefs.save(prefs._blank({}), path)
        res = prefs.resolve("不要再給我百科了", path=path)
        eq(res["blocks"]["terms"], "off", "durable off applied", fails)
        eq(prefs.load(path)["blocks"].get("terms"), "off", "durable off persisted", fails)
        eq(res["changes"] and True, True, "change reported back", fails)
        # and it can be turned back on
        prefs.resolve("把百科打開", path=path)
        eq(prefs.load(path)["blocks"].get("terms"), "auto", "durable on restored", fails)


def test_marker_persists(fails):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        prefs.save(prefs._blank({}), path)
        prefs.resolve("!research off", path=path)
        eq(prefs.load(path)["blocks"].get("research"), "off", "marker persisted", fails)
        prefs.resolve("!no-research", path=path)
        eq(prefs.load(path)["blocks"].get("research"), "off", "no- prefix is off, not toggle", fails)
        prefs.resolve("!research auto", path=path)
        eq(prefs.load(path)["blocks"].get("research"), "auto", "explicit state wins", fails)


def test_asking_forces_on(fails):
    """Even with the block pinned off, asking what something is must explain it."""
    data = prefs._blank({"level": "advanced", "blocks": {"terms": "off"}})
    for ask in ("什麼是 hook", "教我怎麼用 docker", "explain this stack trace", "teach me docker"):
        res = prefs.resolve(ask, data=data, persist=False)
        eq(res["blocks"]["terms"], "on",
           "asking %r overrides an off pin for this turn" % ask, fails)


def test_code_prompts_are_not_pref_changes(fails):
    """B2: ordinary work and code must not silently flip preferences."""
    for p in ("幫我裝個 redis",
              "這個 bug 修好了嗎",
              "不要 drop the table",
              "git commit 修好 bug",
              "為什麼 build 失敗了",
              "刪掉 node_modules 再裝一次"):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "prefs.json")
            prefs.save(prefs._blank({}), path)
            res = prefs.resolve(p, path=path)
            if res["changes"]:
                fails.append("false preference change from %r: %s" % (p, res["changes"]))
            if res["turn_overrides"]:
                fails.append("false turn override from %r: %s" % (p, res["turn_overrides"]))
            if prefs.load(path)["blocks"]:
                fails.append("wrote prefs from %r: %s" % (p, prefs.load(path)["blocks"]))


def test_corrupt_and_hostile_files(fails):
    with tempfile.TemporaryDirectory() as td:
        for junk in ("", "not json", "{", "[]", "null", '{"level": "wizard"}',
                     '{"blocks": "off"}', '{"blocks": {"terms": "maybe"}}'):
            p = os.path.join(td, "prefs.json")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(junk)
            try:
                d = prefs.load(p)
            except Exception as e:
                fails.append("load(%r) raised %r" % (junk, e))
                continue
            if d["level"] not in prefs.LEVELS:
                fails.append("load(%r) produced level %r" % (junk, d["level"]))

        # a file that tries to switch off enforcement is ignored, not honoured
        p = os.path.join(td, "hostile.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"level": "advanced", "enforcement": False,
                       "allow_dangerous": "1", "sandbox": "off",
                       "blocks": {"terms": "off", "guard": "off", "safety": "off"}}, fh)
        d = prefs.load(p)
        eq(sorted(d.keys()), ["blocks", "level"], "unknown top-level keys dropped", fails)
        eq(sorted(d["blocks"].keys()), ["terms"], "unknown block keys dropped", fails)
        if "enforcement" in json.dumps(d) or "guard" in json.dumps(d):
            fails.append("hostile key survived normalisation: %r" % d)


def test_save_is_atomic(fails):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "sub", "prefs.json")
        prefs.save(prefs._blank({"level": "advanced", "blocks": {"terms": "off"}}), path)
        with open(path, encoding="utf-8") as fh:
            json.load(fh)  # must be valid JSON
        leftovers = [f for f in os.listdir(os.path.dirname(path)) if f.startswith(".prefs-")]
        if leftovers:
            fails.append("temp file left behind: %s" % leftovers)
        if prefs.load(path)["level"] != "advanced":
            fails.append("round-trip lost level")


def test_resolve_never_raises(fails):
    for p in (None, "", 123, [], {"a": 1}, "x" * 5000):
        try:
            prefs.resolve(p, data=prefs._blank({}), persist=False)
        except Exception as e:
            fails.append("resolve(%r) raised %r" % (p, e))


def test_context_mentions_the_boundary(fails):
    """The injected context must state the non-negotiable part out loud. Only the
    rules the model itself carries out count: the command gate and the host's
    permission prompts are enforced outside it, so they are not restated."""
    text = prefs.render_context(prefs.resolve("hello", persist=False, data=prefs._blank({})))
    for needed in ("level=", "terms", "research", "not preference-tunable"):
        if needed not in text:
            fails.append("injected context missing %r" % needed)
    if len(text.splitlines()) > 12:
        fails.append("injected context too long: %d lines" % len(text.splitlines()))


def test_clarity_survives_level_and_style_handoff(fails):
    """Misread = wrong action, so the clarity rule is not a verbosity preference:
    it must reach expert (humanize off) and a caveman-owned style (humanize off)."""
    rule = "one reading per sentence"
    for lvl in prefs.LEVELS:
        ctx = prefs.render_context(prefs.resolve("hi", data={"level": lvl}, persist=False))
        eq(rule in ctx, True, "clarity injected at %s" % lvl, fails)
        eq("Taiwan terms" in ctx, True, "Taiwan vocabulary injected at %s" % lvl, fails)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        res = prefs.resolve("!owner style=caveman !humanize off 好", path=path,
                            found={"style": ["caveman"]})
        eq(res["blocks"]["humanize"], "off", "humanize really off in this case", fails)
        eq(rule in prefs.render_context(res), True, "clarity survives style handoff", fails)


def test_decide_and_proceed_at_every_level(fails):
    """The standing instruction is to pick an option and do it, and to stop only
    for the irreversible or the redo-the-whole-result case. Not a preference: it
    reaches every level and no block can mute it."""
    for lvl in prefs.LEVELS:
        ctx = prefs.render_context(prefs.resolve("hi", data={"level": lvl}, persist=False))
        if "decide and proceed" not in ctx:
            fails.append("decide-and-proceed missing at %s" % lvl)
        if "ask only when a wrong guess" in ctx:
            fails.append("retired ask-only phrasing still injected at %s" % lvl)
    if not any("decide and proceed" in a for a in prefs.ALWAYS):
        fails.append("decide-and-proceed is not in ALWAYS (so it is tunable)")


def test_translation_and_no_false_balance_at_every_level(fails):
    """Semantic translation and no-token-counterpoint are honesty rules, not
    tone: a plain-words report that turns "partly worked" into "done" is a lie
    the user acts on. They must reach every level and survive humanize off."""
    rules = ("translate meaning both ways", "never rosier", "error text kept verbatim",
             "lead with the answer and its confidence", "say how weak it is",
             "the data that would decide", "'cannot rule out B' is not an argument")
    for lvl in prefs.LEVELS:
        ctx = prefs.render_context(prefs.resolve("hi", data={"level": lvl}, persist=False))
        for w in rules:
            if w not in ctx:
                fails.append("%r missing at %s" % (w, lvl))
    ctx = prefs.render_context(prefs.resolve("!humanize off 好", data={}, persist=False))
    for w in rules:
        if w not in ctx:
            fails.append("%r muted by humanize off" % w)


def test_stop_cases_and_pinned_lang(fails):
    """The per-turn stop rule names all 4 stop cases, not just 'irreversible': a
    narrower list here would talk the model out of stopping before a publish.
    A pinned language overrides follow-their-language, for users whose own rules
    say 'always reply in X'."""
    ctx = prefs.render_context(prefs.resolve("Can you add a login page", data={}, persist=False))
    for w in ("cannot be undone", "seen by others", "costs money", "someone else's rules"):
        if w not in ctx:
            fails.append("stop case missing from injection: %s" % w)
    eq("answer in the user's language" in ctx, True, "default follows their language", fails)
    ctx = prefs.render_context(prefs.resolve("Can you add a login page",
                                             data={"lang": "Traditional Chinese"}, persist=False))
    eq("always answer in Traditional Chinese" in ctx, True, "pinned lang", fails)
    eq("answer in the user's language" in ctx, False, "pinned lang replaces default", fails)


def test_companions_suggested_once_never_installed(fails):
    """A new device gets a one-line suggestion on the first run, only when the
    companion is absent, and is told not to install it."""
    with tempfile.TemporaryDirectory() as td:
        os.environ["CODEX_HOME"] = td
        try:
            p = os.path.join(td, "prefs.json")
            ctx = prefs.render_context(prefs.resolve("hi", path=p, found={}, persist=False))
            eq("OPTIONAL, not installed: ponytail" in ctx, True, "absent -> suggested", fails)
            eq("Do not install it yourself" in ctx, True, "never auto-install", fails)
            ctx = prefs.render_context(prefs.resolve("hi", path=p, persist=False,
                                                     found={"style": ["ponytail"]}))
            eq("OPTIONAL" in ctx, False, "present -> silent", fails)
            prefs.save({"level": "beginner"}, p)
            ctx = prefs.render_context(prefs.resolve("hi", path=p, found={}, persist=False))
            eq("OPTIONAL" in ctx, False, "not first run -> silent", fails)
        finally:
            del os.environ["CODEX_HOME"]


def test_fixindex_detected_suggested_and_used(fails):
    """Absent: suggested on first run. Present: not suggested, and a fix request
    is told to check it first. Absent again: the fix line never names it."""
    import genie_router as gr
    old = os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory() as td:
        try:
            os.environ["PATH"] = td
            p = os.path.join(td, "prefs.json")
            ctx = prefs.render_context(prefs.resolve("hi", path=p, found={}, persist=False))
            eq("OPTIONAL, not installed: fixindex" in ctx, True, "fixindex absent -> suggested", fails)
            res = prefs.resolve("x", data={}, persist=False)
            eq("fixindex" in gr.dispatch("fix_request", res), False, "absent -> not named", fails)
            exe = os.path.join(td, "fixindex")
            with open(exe, "w") as fh:
                fh.write("#!/bin/sh\n")
            os.chmod(exe, 0o755)
            ctx = prefs.render_context(prefs.resolve("hi", path=p, found={}, persist=False))
            eq("not installed: fixindex" in ctx, False, "fixindex present -> silent", fails)
            eq("fixindex find" in gr.dispatch("fix_request", res), True, "present -> fix checks it", fails)
            eq("fixindex" in gr.dispatch("clear_request", res), False, "only fix requests", fails)
        finally:
            os.environ["PATH"] = old


def test_blocks_cannot_disable_enforcement(fails):
    """B1. Every block off, a hostile prefs file, guard must still deny."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        prefs.save(prefs._blank({"level": "advanced",
                                 "blocks": {b: "off" for b in prefs.BLOCKS}}), path)
        env = dict(os.environ, GENIE_PREFS=path, GENIE_ALLOW_DANGEROUS="")
        env.pop("GENIE_ALLOW_DANGEROUS", None)
        for cmd in ("rm -rf /", "rm -rf ~", "git push --force origin main",
                    "mysql -e 'drop table users;'", "sudo rm -rf /usr/local"):
            p = subprocess.run(
                [sys.executable, os.path.join(HERE, "guard_dangerous.py")],
                input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
                capture_output=True, text=True, env=env)
            if not p.stdout.strip():
                fails.append("ENFORCEMENT LOST: %r was allowed with all blocks off" % cmd)
                continue
            dec = json.loads(p.stdout)["hookSpecificOutput"].get("permissionDecision")
            if dec != "deny":
                fails.append("ENFORCEMENT LOST: %r -> %r" % (cmd, dec))
        # and the guard exposes no env var the prefs system is allowed to set
        if set(prefs.BLOCKS) & {"guard", "sandbox", "enforcement", "safety", "approval"}:
            fails.append("an enforcement-ish name leaked into BLOCKS: %r" % (prefs.BLOCKS,))


def test_guard_handoff_needs_a_real_guard(fails):
    """Handing the guard to another tool must not be a way to have no guard.

    `owners.guard` in the prefs file only counts while that tool is a PreToolUse
    hook in Codex. Without it the guard keeps denying.
    """
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        codex = os.path.join(td, "codex")
        os.makedirs(codex)
        prefs.save({"owners": {"guard": "dcg"}}, path)
        env = dict(os.environ, GENIE_PREFS=path, CODEX_HOME=codex)
        env.pop("GENIE_ALLOW_DANGEROUS", None)

        def decision():
            p = subprocess.run(
                [sys.executable, os.path.join(HERE, "guard_dangerous.py")],
                input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf ~"}}),
                capture_output=True, text=True, env=env)
            out = p.stdout.strip()
            return json.loads(out)["hookSpecificOutput"].get("permissionDecision") if out else "allow"

        eq(decision(), "deny", "owner named but not installed: guard stays on", fails)
        with open(os.path.join(codex, "hooks.json"), "w") as fh:
            json.dump({"hooks": {"PreToolUse": [{"hooks": [
                {"type": "command", "command": "dcg"}]}]}}, fh)
        eq(decision(), "allow", "owner installed: genie stands down", fails)
        prefs.save({"owners": {"guard": "genie"}}, path)
        eq(decision(), "deny", "owner genie: guard on", fails)


def test_overlap_asks_once_and_hands_off(fails):
    found = {"research": ["dont-reinvent"], "style": ["caveman"]}
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        res = prefs.resolve("hi", path=path, found=found)
        eq(res["first_run"], True, "no prefs file = first run", fails)
        ctx = prefs.render_context(res)
        eq("FIRST RUN" in ctx and "!research off" in ctx, True, "onboarding injected", fails)
        eq(sorted(res["ask_owner"]), ["research", "style"], "both overlaps asked", fails)
        res = prefs.resolve("hi", path=path, found=found)
        eq((res["first_run"], res["ask_owner"]), (False, {}), "asked only once", fails)
        res = prefs.resolve("hi", path=path, found=dict(found, research=["dont-reinvent", "deja-vu"]))
        eq(list(res["ask_owner"]), ["research"], "a newly installed tool asks again", fails)

        res = prefs.resolve("!owner style=caveman 好", path=path, found=found)
        eq(res["blocks"]["terms"], "off", "style handed off: glossary off", fails)
        eq("register:" in prefs.render_context(res), False, "style handed off: no register", fails)
        eq(res["blocks"]["confirm"], "on", "handoff never touches confirm", fails)
        res = prefs.resolve("什麼是 hook", path=path, found=found)
        eq(res["blocks"]["terms"], "on", "asking still explains", fails)
        res = prefs.resolve("!owner research=dont-reinvent 幫我寫一個爬蟲程式", path=path, found=found)
        eq(res["blocks"]["research"], "off", "research handed off: no $wheel nudge", fails)
        res = prefs.resolve("hi", path=path, found={})
        eq(res["blocks"]["terms"], "on", "tool uninstalled: genie takes the job back", fails)

    # Owner chosen up front (`prefs.py set owner`): never asked, not even once.
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        prefs.save(dict(prefs._blank({}), owners={"style": "caveman"}), path)
        res = prefs.resolve("hi", path=path, found=found)
        eq(list(res["ask_owner"]), ["research"], "stored owner is not asked again", fails)


def test_coexist_is_told_not_arbitrated(fails):
    """route/done stack without fighting: say it once, never ask who owns it.

    The failure this pins: treating them like guard/research/style would have the
    assistant offer to switch one off, and for `done` the user may have no other
    safety net -- so a tidier config costs them the only check they had.
    """
    found = {"route": ["jev-route"], "done": ["jev-gate-mcp"]}
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        res = prefs.resolve("hi", path=path, found=found)
        eq(sorted(res["coexist"]), ["done", "route"], "both coexist overlaps told", fails)
        eq(res["ask_owner"], {}, "coexist caps are never arbitrated", fails)
        ctx = prefs.render_context(res)
        eq("COEXIST:" in ctx and "jev-route" in ctx, True, "COEXIST line injected", fails)
        eq("OVERLAP:" in ctx, False, "no OVERLAP line for a coexist cap", fails)
        eq("nothing to turn off" in ctx, True, "coexist says there is nothing to switch off", fails)
        eq("set owner" in ctx, False, "coexist offers no owner marker", fails)
        res = prefs.resolve("hi", path=path, found=found)
        eq(res["coexist"], {}, "told only once", fails)
        res = prefs.resolve("hi", path=path, found=dict(found, route=["jev-route", "other-router"]))
        eq(list(res["coexist"]), ["route"], "a newly installed tool is told again", fails)
        # Handing a coexist cap away is meaningless, so it must not change any block.
        before = prefs.resolve("hi", path=path, found=found)["blocks"]
        after = prefs.resolve("!owner route=jev-route hi", path=path, found=found)["blocks"]
        eq(after, before, "a coexist owner marker changes no block", fails)


def test_overlap_asks_only_who_owns_it(fails):
    """One small question -- who owns it -- and never a merge chore.

    The failure this pins: asking a non-developer to diff two rule sets, fold the
    difference in and delete a tool they do not understand. Picking an owner is
    reversible and takes one word; merging is a checkout workflow and belongs
    upstream. Genie must also never be the one told to step aside -- most users
    have no second tool, so a Genie that stands down leaves them no check at all.
    """
    found = {"guard": ["some-guard"], "style": ["some-style"]}
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        ctx = prefs.render_context(prefs.resolve("hi", path=path, found=found))
        eq("OVERLAP:" in ctx, True, "OVERLAP still raised", fails)
        eq("who should own it" in ctx, True, "the owner question is asked", fails)
        for chore in ("move into Genie", "fold the difference", "Removing their tool"):
            eq(chore in ctx, False, "no merge chore is handed to the user (%s)" % chore, fails)
    for cap in sorted(set(overlap.CAPS) - set(overlap.NOTIFY)):
        advice = overlap.RECOMMEND[cap]
        eq(advice.startswith("suggest {other}"), False,
           "`%s` must not tell Genie to step aside" % cap, fails)
        eq("Genie" in advice, True, "`%s` advice says where Genie stands" % cap, fails)


def test_every_capability_is_detectable(fails):
    """Each standing Genie capability must be scannable, or an overlap goes unseen.

    Genie runs five jobs; three live in skills, two only exist as hooks. If a cap
    has no signature, no event binding and no message, nothing will ever report it.
    """
    for cap in overlap.CAPS:
        eq(cap in overlap.SIGNATURES, True, "cap %s has a signature" % cap, fails)
        eq(cap in overlap._EVENTS, True, "cap %s declares its events" % cap, fails)
        has_msg = cap in overlap.RECOMMEND or cap in overlap.COEXIST
        eq(has_msg, True, "cap %s has something to say when found" % cap, fails)
        # Exactly one of the two paths: arbitrate (RECOMMEND) or notify (COEXIST).
        eq((cap in overlap.NOTIFY), (cap in overlap.COEXIST),
           "cap %s: NOTIFY and COEXIST agree" % cap, fails)
        eq((cap in overlap.NOTIFY), (cap not in overlap.RECOMMEND),
           "cap %s: arbitrated xor told" % cap, fails)
    # A hook-only job must not be matched by a skill or plugin name: a skill cannot
    # block a command, inject into every turn, or run at Stop.
    for cap in ("guard", "route", "done"):
        eq(overlap._EVENTS[cap] is not None, True, "%s is hook-only" % cap, fails)


def test_overlap_scan_ignores_genie(fails):
    with tempfile.TemporaryDirectory() as td:
        sk = os.path.join(td, "skills")
        os.makedirs(sk)
        os.symlink(os.path.join(overlap.GENIE_DIR, "skills", "wheel"), os.path.join(sk, "wheel"))
        os.makedirs(os.path.join(sk, "caveman"))
        with open(os.path.join(td, "hooks.json"), "w") as fh:
            json.dump({"hooks": {
                "PreToolUse": [{"hooks": [
                    {"command": "python3 %s/router/guard_dangerous.py" % overlap.GENIE_DIR},
                    {"command": "node /opt/x/safety-net/hook.js"}]}],
                "UserPromptSubmit": [{"hooks": [{"command": "my-guard-thing"}]}]}}, fh)
        got = _real_scan(home=td, dirs=[sk])
        eq(got, {"guard": ["safety-net"], "style": ["caveman"]},
           "own files ignored; only PreToolUse counts as a guard", fails)


def test_overlap_scan_claude_host(fails):
    """Under Claude Code the scan reads ~/.claude, not the Codex config."""
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "skills", "dont-reinvent"))
        with open(os.path.join(td, "settings.json"), "w") as fh:
            json.dump({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "dcg"}]}],
                "SessionStart": [{"hooks": [{"command": "cat ~/.claude/shared/asd-style.md"}]}]},
                "enabledPlugins": {"caveman@caveman": True, "ponytail@ponytail": False,
                                   "genie-harness@genie-harness": True}}, fh)
        old = {k: os.environ.get(k) for k in ("CLAUDE_PLUGIN_ROOT", "CLAUDE_CONFIG_DIR")}
        os.environ.update(CLAUDE_PLUGIN_ROOT=overlap.GENIE_DIR, CLAUDE_CONFIG_DIR=td)
        try:
            got = _real_scan()
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        eq(got, {"guard": ["dcg"], "research": ["dont-reinvent"],
                 "style": ["asd-style.md", "caveman"]},
           "claude host: settings.json hooks + skills + enabled plugins (not genie, not disabled)", fails)


def test_duplicate_wheel_and_registry(fails):
    """A private copy of $wheel splits wheel cards across registries: flag it once."""
    with tempfile.TemporaryDirectory() as td:
        sk = os.path.join(td, "skills")
        os.makedirs(os.path.join(sk, "wheel"))
        os.makedirs(os.path.join(td, "wheel"))
        open(os.path.join(td, "wheel", "registry.tsv"), "w").close()
        old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = td
        try:
            dups = overlap.duplicates([sk])
            eq(sorted(k.split(":")[1] for k, _ in dups), ["registry", "skill"],
               "private wheel copy and its registry are both flagged", fails)
            eq(_real_scan(home=td, dirs=[sk]).get("research"), None,
               "a wheel copy is a duplicate, not a research overlap", fails)
            path = os.path.join(td, "prefs.json")
            eq(len(prefs.resolve("hi", path=path, found={}, dups=dups)["duplicates"]), 2,
               "first turn raises both", fails)
            eq(prefs.resolve("hi", path=path, found={}, dups=dups)["duplicates"], [],
               "raised once, not every turn", fails)
        finally:
            os.environ.pop("CLAUDE_CONFIG_DIR", None) if old is None else os.environ.__setitem__("CLAUDE_CONFIG_DIR", old)
        eq([k for k, _ in overlap.duplicates([os.path.join(overlap.GENIE_DIR, "skills")])
            if k.startswith("dup:skill:")], [],
           "genie's own wheel is never a duplicate", fails)


def test_hook_shape_and_fail_open(fails):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "prefs.json")
        prefs.save(prefs._blank({}), path)
        env = dict(os.environ, GENIE_PREFS=path)

        p = subprocess.run([sys.executable, PREFS_HOOK],
                           input=json.dumps({"prompt": "什麼是 hook"}),
                           capture_output=True, text=True, env=env)
        if p.returncode != 0:
            fails.append("hook exited %d: %s" % (p.returncode, p.stderr[:120]))
        try:
            out = json.loads(p.stdout)["hookSpecificOutput"]
            if out["hookEventName"] != "UserPromptSubmit":
                fails.append("wrong event name: %r" % out["hookEventName"])
            if "terms=on" not in out["additionalContext"]:
                fails.append("asking-for turn did not force terms on")
        except Exception as e:
            fails.append("hook output not parseable: %r / %r" % (p.stdout[:120], e))

        # garbage in must never crash the prompt
        for junk in ("", "not json", "{}", '{"prompt": null}', "[]", '{"prompt": 5}'):
            q = subprocess.run([sys.executable, PREFS_HOOK], input=junk,
                               capture_output=True, text=True, env=env)
            if q.returncode != 0:
                fails.append("hook crashed on %r (rc=%d)" % (junk, q.returncode))

        # an empty prompt produces no context at all
        q = subprocess.run([sys.executable, PREFS_HOOK],
                           input=json.dumps({"prompt": "   "}),
                           capture_output=True, text=True, env=env)
        if q.stdout.strip():
            fails.append("hook emitted context for an empty prompt")


def main():
    fails = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(fails)
    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    n = len([k for k in globals() if k.startswith("test_")])
    print("PASS  %d prefs tests, including blocks-cannot-disable-enforcement" % n)


if __name__ == "__main__":
    main()
