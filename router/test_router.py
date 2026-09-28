#!/usr/bin/env python3
"""Self-check: fails if the router logic breaks. Run: python3 router/test_router.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genie_router as r  # noqa: E402

CASES = [
    # regex tier
    ("我看不懂", "user_confused"),
    ("I don't get it", "user_confused"),
    ("把整個專案 rm -rf 重來", "risky_action"),
    ("force push to main", "risky_action"),
    ("React 還是 Vue 比較好", "research_needed"),
    ("幫我把專案跑起來", "execute_request"),
    ("幫我做一個網站", "ambiguous_request"),
    # embedding tier (no keyword hit)
    ("我想要一個可以記帳的東西", "ambiguous_request"),
    ("把 h1 的字改成紅色", "clear_request"),
    ("在 app.py 第 10 行加一個 print", "clear_request"),
    ("現在做手機 app 大家都用什麼", "research_needed"),
    ("這段話我完全跟不上", "user_confused"),
    ("I have no idea what you just said", "user_confused"),
    ("add a button that says hello", "clear_request"),
    ("can you make this faster somehow", "ambiguous_request"),
]


def main():
    fails = []
    t = time.time()
    for text, want in CASES:
        got, score, why = r.classify(text)
        ok = got == want
        print("%s %-40s -> %-18s %.2f %s" % ("OK " if ok else "BAD", text, got, score, why))
        if not ok:
            fails.append(text)
    print("total %.2fs for %d cases" % (time.time() - t, len(CASES)))
    # fallback must never crash
    r.MODEL_DIR = "/nonexistent"
    r._cache.clear()
    assert r.classify("把 h1 的字改成紅色")[0] == "clear_request"
    assert not fails, fails
    print("PASS")


if __name__ == "__main__":
    main()
