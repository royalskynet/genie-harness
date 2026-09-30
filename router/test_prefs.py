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

PREFS_HOOK = os.path.join(HERE, "prefs_hook.py")


def eq(got, want, label, fails):
    if got != want:
        fails.append("%s: got %r want %r" % (label, got, want))


def test_defaults_per_level(fails):
    d = prefs._blank({})
    eq(prefs.block_state("terms", d), "auto", "beginner terms default", fails)
    eq(prefs.block_state("steps", d), "on", "beginner steps default", fails)

    adv = prefs._blank({"level": "advanced"})
    eq(prefs.block_state("terms", adv), "off", "advanced terms default", fails)
    eq(prefs.block_state("research", adv), "auto", "advanced research default", fails)
    eq(prefs.block_state("confirm", adv), "on", "confirm survives advanced", fails)


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
        eq(res2["blocks"]["terms"], "auto", "next turn unaffected", fails)


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
    """The injected context must state the non-negotiable part out loud."""
    text = prefs.render_context(prefs.resolve("hello", persist=False, data=prefs._blank({})))
    for needed in ("level=", "terms", "research", "no preference can turn them off"):
        if needed not in text:
            fails.append("injected context missing %r" % needed)
    if len(text.splitlines()) > 12:
        fails.append("injected context too long: %d lines" % len(text.splitlines()))


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
            if "terms[on]" not in out["additionalContext"]:
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
