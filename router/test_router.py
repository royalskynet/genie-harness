#!/usr/bin/env python3
"""Self-check: fails if the router logic breaks. Run: python3 router/test_router.py

Two jobs:

1. A handful of hand-picked cases that pin the *boundaries* between intents
   (teach_me vs user_confused, risky vs execute). These are the ones that
   regress silently when someone edits keywords.

2. The dev set in `eval_set.json`, scored per class. Per-class matters:
   an aggregate of 96% can hide a class that is 0%, and the class that must
   never be wrong is `risky_action` -- a wrong label there means the model
   proceeds instead of asking.

C1: `eval_set.json` is ~90 hand-written cases, not a benchmark. The numbers
below are a regression baseline for this repo, not evidence of generalisation.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import genie_router as r  # noqa: E402

CASES = [
    # teach_me must win over user_confused: there is no "previous answer" to
    # simplify when the user is asking what something *is*.
    ("什麼是 hook", "teach_me"),
    ("教我怎麼用 docker", "teach_me"),
    ("I don't get it", "user_confused"),
    ("把整個專案 rm -rf 重來", "risky_action"),
    ("force push to main", "risky_action"),
    ("React 還是 Vue 比較好", "research_needed"),
    ("幫我把專案跑起來", "execute_request"),
    ("幫我做一個網站", "ambiguous_request"),
    ("我想要一個可以記帳的東西", "build_request"),
    ("把 h1 的字改成紅色", "clear_request"),
    ("在 app.py 第 10 行加一個 print", "clear_request"),
    ("現在做手機 app 大家都用什麼", "research_needed"),
    ("這段話我完全跟不上", "user_confused"),
    ("I have no idea what you just said", "user_confused"),
    ("add a button that says hello", "clear_request"),
    ("can you make this faster somehow", "ambiguous_request"),
    # boundaries that used to be wrong
    ("幫我裝個 redis", "execute_request"),
    ("什麼是 API", "teach_me"),
    ("react 還是 vue", "research_needed"),
    ("幫我看看這個錯誤", "clear_request"),
]


def run_cases(cases, fails, label):
    t = time.time()
    for text, want in cases:
        got, score, why = r.classify(text)
        ok = got == want
        print("%s %-38s -> %-18s %.2f %s" % ("OK " if ok else "BAD", text, got, score, why))
        if not ok:
            fails.append("%s: %r -> %s (want %s)" % (label, text, got, want))
    print("total %.2fs for %d cases" % (time.time() - t, len(cases)))


def run_eval_set(fails):
    path = os.path.join(HERE, "eval_set.json")
    if not os.path.exists(path):
        fails.append("router/eval_set.json is missing")
        return
    data = json.load(open(path, encoding="utf-8"))
    cases = data["cases"]
    per_class = {}
    abstained = []
    for c in cases:
        got, score, why = r.classify(c["text"])
        want = c["want"]
        per_class.setdefault(want, []).append(got == want)
        if got == r.UNSURE:
            abstained.append(c["text"])
        if got != want and got != r.UNSURE:
            fails.append("eval: %r -> %s (want %s)" % (c["text"], got, want))
    print("\nper-class strict accuracy (n=%d):" % len(cases))
    for k in sorted(per_class):
        v = per_class[k]
        print("  %-18s %d/%d = %d%%" % (k, sum(v), len(v), round(100 * sum(v) / len(v))))
    strict = sum(1 for c in cases if r.classify(c["text"])[0] == c["want"])
    safe = sum(1 for c in cases
               if r.classify(c["text"])[0] in (c["want"], r.UNSURE))
    print("strict %d/%d = %d%%   safe %d/%d = %d%%   abstained %d"
          % (strict, len(cases), round(100 * strict / len(cases)),
             safe, len(cases), round(100 * safe / len(cases)), len(abstained)))
    # the one number that must never move
    if safe != len(cases):
        fails.append("SAFE ACCURACY IS NOT 100%% -- %d cases got a wrong label "
                     "instead of abstaining" % (len(cases) - safe))
    if strict < 0.90 * len(cases):
        fails.append("strict accuracy dropped below 90%% of the dev set")


def test_missing_model_warns(fails):
    """C3: a missing model directory must be loud, not a silent accuracy collapse."""
    r._cache.clear()
    old = r.MODEL_DIR
    r.MODEL_DIR = "/nonexistent"
    try:
        import io, contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            intent, score, why = r.classify("把 h1 的字改成紅色")
        if "fallback" not in why:
            fails.append("missing model did not fall back (why=%r)" % why)
        if "model" not in err.getvalue().lower():
            fails.append("missing model produced no stderr warning")
    finally:
        r.MODEL_DIR = old
        r._cache.clear()


def test_dispatch(fails):
    """Wheel-first is the point of the router: once the goal is known, the DO
    line must make the model look for prior art before proposing how."""
    on = {"blocks": {"research": "on"}}
    for intent in r.WHEEL_INTENTS:
        do = r.dispatch(intent, on, "codex")
        if "MUST be $wheel" not in do:
            fails.append("dispatch %s: no wheel-first: %r" % (intent, do))
    if "genie-harness:wheel" not in r.dispatch("build_request", on, "claude"):
        fails.append("dispatch: claude host must name the namespaced plugin skill")
    for intent in ("clear_request", "teach_me", "risky_action", "continue"):
        if "wheel" in r.dispatch(intent, on, "codex"):
            fails.append("dispatch %s: wheel where it is not wanted" % intent)
    off = r.dispatch("build_request", {"blocks": {"research": "off"}}, "codex")
    if "wheel" in off or "{" in off:
        fails.append("dispatch: research off still searches or leaks a placeholder: %r" % off)
    mine = r.dispatch("build_request", {"blocks": {"research": "on"},
                                        "handed_off": {"research": "my-tool"}}, "codex")
    if "my-tool" not in mine or "$wheel" in mine:
        fails.append("dispatch: hand-off to another prior-art tool ignored: %r" % mine)
    deg = r.dispatch("degraded", on, "codex")
    if "MUST be $wheel" not in deg or "router could not classify" not in deg:
        fails.append("dispatch: missing model must hand judgment back, wheel-first: %r" % deg)
    for intent in list(r.DO):
        for res in ({}, {"blocks": {"research": "off"}}):
            out = r.dispatch(intent, res, "claude")
            if "{" in out or re.search(r"MUST be (?![$\w])", out):
                fails.append("dispatch %s: unfilled placeholder: %r" % (intent, out))


def test_local_tools_follow_level(fails):
    """Advanced/expert users are pointed at what is already installed; the rest
    are not. Wheel answers "does a wheel exist?", this asks the narrower question
    (`which`, `--help`, the skills already listed) that only a senior reader can
    act on, so handing it to a beginner is noise."""
    phrase = "already on this machine"
    on = {"blocks": {"research": "on"}}
    for intent in r.LOCAL_TOOL_INTENTS:
        for lvl in r.LOCAL_TOOL_LEVELS:
            out = r.dispatch(intent, dict(on, level=lvl), "codex")
            if phrase not in out or "--help" not in out:
                fails.append("dispatch %s/%s: no local-tools steer: %r" % (intent, lvl, out))
        for lvl in ("beginner", "intermediate"):
            out = r.dispatch(intent, dict(on, level=lvl), "codex")
            if phrase in out:
                fails.append("dispatch %s/%s: local-tools steer for a %s: %r"
                             % (intent, lvl, lvl, out))
    # not an intent where "just run what is here" is the right instruction
    for intent in ("teach_me", "user_confused", "risky_action", "ambiguous_request",
                   "continue"):
        out = r.dispatch(intent, dict(on, level="expert"), "codex")
        if phrase in out:
            fails.append("dispatch %s/expert: local-tools steer where it does not belong: %r"
                         % (intent, out))
    # and it must not break the rest of the line
    for intent in r.LOCAL_TOOL_INTENTS:
        out = r.dispatch(intent, {"level": "advanced",
                                  "blocks": {"research": "off"}}, "codex")
        if "{" in out or re.search(r"MUST be (?![$\w])", out):
            fails.append("dispatch %s: local-tools steer leaked a placeholder: %r" % (intent, out))


def test_route_log(fails):
    """The calibration log: one redacted JSONL line per prompt, honours GENIE_LOG,
    rotates, and never breaks the hook. Fail-open is the property that matters --
    a log that can lose a prompt must not be able to cost one."""
    import io, contextlib, shutil, tempfile
    tmp = tempfile.mkdtemp()
    env = {k: os.environ.pop(k, None) for k in ("GENIE_LOG",)}
    old_home = os.environ.get("HOME")
    try:
        def logged(prompt="幫我把專案跑起來 sk-abcdefghijklmnopqrstuvwxyz123456", **kw):
            """-> parsed records at the configured log path."""
            path = kw.get("path") or os.path.join(tmp, "route.log")
            os.environ["GENIE_LOG"] = kw.get("genie_log", path)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                ctx = r.hook(json.dumps({"prompt": prompt}), "claude")
            if not ctx or "DO:" not in ctx:
                fails.append("route log: hook lost its DO line (ctx=%r)" % ctx)
            if not os.path.exists(path):
                return []
            return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

        recs = logged()
        if len(recs) != 1:
            fails.append("route log: want 1 record, got %d" % len(recs))
        else:
            rec = recs[0]
            for key in ("ts", "intent", "score", "via", "conf", "text"):
                if key not in rec:
                    fails.append("route log: missing field %r in %r" % (key, rec))
            if rec.get("intent") != "execute_request":
                fails.append("route log: intent %r (want execute_request)" % rec.get("intent"))
            if rec.get("score") != round(rec.get("score", -1), 2):
                fails.append("route log: score not 2dp: %r" % rec.get("score"))
            if "abcdefghijklmnop" in json.dumps(rec, ensure_ascii=False):
                fails.append("route log: token leaked into the log: %r" % rec)
            if "[REDACTED]" not in rec.get("text", ""):
                fails.append("route log: 24+ char run was not redacted: %r" % rec.get("text"))
            if not rec["text"].startswith("幫我把專案跑起來"):
                fails.append("route log: text truncated wrongly: %r" % rec["text"])

        # appends, not overwrites: one line per prompt
        logged()
        lines = [l for l in open(os.path.join(tmp, "route.log"), encoding="utf-8") if l.strip()]
        if len(lines) != 2:
            fails.append("route log: second prompt did not append a second line")

        # 200-char cap
        os.remove(os.path.join(tmp, "route.log"))
        long_recs = logged(prompt="幫我" + "跑起來 " * 80)
        if len(long_recs[0]["text"]) > 200:
            fails.append("route log: text not capped at 200 chars (%d)"
                         % len(long_recs[0]["text"]))

        # GENIE_LOG=0 opts out and creates nothing
        os.remove(os.path.join(tmp, "route.log"))
        os.environ["HOME"] = tmp
        os.environ["GENIE_LOG"] = "0"
        r.hook(json.dumps({"prompt": "幫我把專案跑起來"}), "claude")
        if os.path.exists(os.path.join(tmp, ".genie", "route.log")):
            fails.append("route log: GENIE_LOG=0 still wrote ~/.genie/route.log")

        # unset GENIE_LOG -> ~/.genie/route.log, directory created
        del os.environ["GENIE_LOG"]
        r.hook(json.dumps({"prompt": "幫我把專案跑起來"}), "claude")
        if not os.path.exists(os.path.join(tmp, ".genie", "route.log")):
            fails.append("route log: default path not written")

        # unwritable path: swallowed, hook still speaks
        os.environ["GENIE_LOG"] = "/nonexistent/x/r.log"
        ctx = r.hook(json.dumps({"prompt": "幫我把專案跑起來"}), "claude")
        if "DO:" not in ctx or "genie: intent=" not in ctx:
            fails.append("route log: unwritable log broke the hook: %r" % ctx)

        # rotation: an oversized log becomes route.log.1 and a new one starts
        big = os.path.join(tmp, "big.log")
        with open(big, "w", encoding="utf-8") as fh:
            fh.write("x" * (r.LOG_MAX_BYTES + 1))
        logged(genie_log=big, path=big)
        if not os.path.exists(big + ".1"):
            fails.append("route log: oversized log was not rotated to route.log.1")
        if os.path.getsize(big) > r.LOG_MAX_BYTES:
            fails.append("route log: new log still over the cap after rotation")
    finally:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home
        shutil.rmtree(tmp, ignore_errors=True)


def test_abstain_is_silent(fails):
    """Below threshold: prefs only, no `intent=` tag and no `DO:` line. The
    classifier's own abstention must not be dressed up as a judgment."""
    saved = r.INTENTS["threshold"]
    try:
        r.INTENTS["threshold"] = 2.0  # nothing can clear this -> always abstain
        ctx = r.hook(json.dumps({"prompt": "這個東西大概要怎麼辦才好"}), "claude")
        if "intent=" in ctx:
            fails.append("abstain: still emitted an intent tag: %r" % ctx)
        if "DO:" in ctx:
            fails.append("abstain: still emitted a DO line: %r" % ctx)
        if "[genie prefs]" not in ctx:
            fails.append("abstain: dropped the prefs line too: %r" % ctx)
    finally:
        r.INTENTS["threshold"] = saved
    # a regex hit still routes, so abstaining did not break the normal path
    ctx = r.hook(json.dumps({"prompt": "幫我把專案跑起來"}), "claude")
    if "intent=execute_request" not in ctx or "DO:" not in ctx:
        fails.append("abstain: a regex hit stopped routing: %r" % ctx)


def test_machine_turns_are_not_classified(fails):
    """UserPromptSubmit also carries turns nobody typed. Those get no injection
    at all: a label on a background-task report dispatches skills for work the
    user never asked for."""
    machine = (
        "<task-notification>\n<task-id>abc</task-id>\nfixed the bug\n</task-notification>",
        "<local-command-stdout>error: command failed</local-command-stdout>",
        "<system-reminder>something broke</system-reminder>",
        "[Artifact comment sent to Claude] please fix this",
    )
    for text in machine:
        if r.hook(json.dumps({"prompt": text}), "claude") != "":
            fails.append("machine turn was classified: %r" % text[:40])
    # and a real message that merely mentions one still routes
    ctx = r.hook(json.dumps({"prompt": "幫我看看 task-notification 是什麼"}), "claude")
    if "intent=" not in ctx:
        fails.append("machine-turn filter swallowed a real question: %r" % ctx)


def main():
    fails = []
    test_dispatch(fails)
    test_local_tools_follow_level(fails)
    test_abstain_is_silent(fails)
    test_machine_turns_are_not_classified(fails)
    run_cases(CASES, fails, "boundary")
    run_eval_set(fails)
    test_missing_model_warns(fails)
    test_route_log(fails)
    # fallback must never crash
    r.MODEL_DIR = "/nonexistent"
    r._cache.clear()
    assert r.classify("把 h1 的字改成紅色")[0] in (r.INTENTS["default"], r.UNSURE)
    r.MODEL_DIR = os.environ.get("GENIE_MODEL_DIR", os.path.join(HERE, "model"))
    r._cache.clear()
    if fails:
        print("\nFAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("\nPASS  %d boundary cases + dev set (per-class, safe=100%%) + dispatch + missing-model warning"
          % len(CASES))


if __name__ == "__main__":
    main()
