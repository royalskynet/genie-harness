#!/usr/bin/env python3
"""Self-check: fails if the router logic breaks. Run: python3 router/test_router.py

Two jobs:

1. A handful of hand-picked cases that pin the *boundaries* between intents
   (teach_me vs user_confused, risky vs execute). These are the ones that
   regress silently when someone edits keywords.

2. The 74-case dev set in `eval_set.json`, scored per class. Per-class matters:
   an aggregate of 96% can hide a class that is 0%, and the class that must
   never be wrong is `risky_action` -- a wrong label there means the model
   proceeds instead of asking.

C1: `eval_set.json` is 74 hand-written cases, not a benchmark. The numbers
below are a regression baseline for this repo, not evidence of generalisation.
"""
import json
import os
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
    ("我想要一個可以記帳的東西", "ambiguous_request"),
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


def main():
    fails = []
    run_cases(CASES, fails, "boundary")
    run_eval_set(fails)
    test_missing_model_warns(fails)
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
    print("\nPASS  %d boundary cases + 74-case dev set (per-class, safe=100%%) + missing-model warning"
          % len(CASES))


if __name__ == "__main__":
    main()
