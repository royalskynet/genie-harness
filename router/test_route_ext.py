#!/usr/bin/env python3
"""Self-check for route_ext.py. Run: python3 router/test_route_ext.py

Covers:
- \| restoration in columns
- Header and separator row skipping
- Stop at next ## heading
- Bad regex segment skipped but other segments in same row still match
- strong (m>=2), strong (short single-line), weak (long single hit)
- eligible six exclusions
- load_config =0 / bad file / host mismatch
"""
import json
import os
import sys
import tempfile
import re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import route_ext as r


def test_pipe_restoration():
    """\| in action/kw columns restored to |"""
    md = """## 任務路由表
| 情境 | 動作 | 關鍵字 |
|------|------|--------|
| 測試 | echo \\| pipe | kw1\\|kw2 |
"""
    rows = r.parse_routes(md, "任務路由表")
    assert len(rows) == 1
    assert rows[0]["action"] == "echo | pipe"
    assert rows[0]["kw"] == "kw1|kw2"


def test_header_and_separator_skipped():
    """Header row (情境) and separator row (---) are skipped"""
    md = """## 任務路由表
| 情境 | 動作 | 關鍵字 |
|------|------|--------|
| 真實情境 | 真實動作 | 真實kw |
"""
    rows = r.parse_routes(md, "任務路由表")
    assert len(rows) == 1
    assert rows[0]["when"] == "真實情境"


def test_stop_at_next_heading():
    """Parsing stops at next ## heading"""
    md = """## 任務路由表
| 情境 | 動作 | 關鍵字 |
|------|------|--------|
| 第一 | act1 | kw1 |
## 其他標題
| 第二 | act2 | kw2 |
"""
    rows = r.parse_routes(md, "任務路由表")
    assert len(rows) == 1
    assert rows[0]["when"] == "第一"


def test_bad_regex_segment_skipped():
    """Bad regex segment is skipped, other segments in same row still match"""
    md = """## 任務路由表
| 情境 | 動作 | 關鍵字 |
|------|------|--------|
| 測試 | act | bad[regex\\|good |
"""
    rows = r.parse_routes(md, "任務路由表")
    assert len(rows) == 1
    # Use long text so it's weak (single hit, len >= 25)
    long_text = "這是一個很長的文字包含 good 關鍵字" * 2
    row, m, strong = r.match(rows, long_text)
    assert row is not None
    assert m == 1
    assert not strong


def test_strong_m_ge_2():
    """strong when m >= 2"""
    md = """## 任務路由表
| 情境 | 動作 | 關鍵字 |
|------|------|--------|
| 測試 | act | kw1\\|kw2 |
"""
    rows = r.parse_routes(md, "任務路由表")
    row, m, strong = r.match(rows, "這裡有 kw1 也有 kw2")
    assert row is not None
    assert m == 2
    assert strong


def test_strong_short_single_line():
    """strong when len < 25 and single line (no newline)"""
    md = """## 任務路由表
| 情境 | 動作 | 關鍵字 |
|------|------|--------|
| 測試 | act | kw |
"""
    rows = r.parse_routes(md, "任務路由表")
    row, m, strong = r.match(rows, "短句 kw")
    assert row is not None
    assert m == 1
    assert strong


def test_weak_long_single_hit():
    """weak when long text with single hit"""
    md = """## 任務路由表
| 情境 | 動作 | 關鍵字 |
|------|------|--------|
| 測試 | act | kw |
"""
    rows = r.parse_routes(md, "任務路由表")
    long_text = "這是一個很長的文字 " * 5 + "kw"
    row, m, strong = r.match(rows, long_text)
    assert row is not None
    assert m == 1
    assert not strong


def test_eligible_exclusions():
    """Six exclusion cases for eligible()"""
    # 1. empty string
    assert not r.eligible("")
    # 2. starts with /
    assert not r.eligible("/compact")
    # 3. length < 12
    assert not r.eligible("短訊息")
    # 4. continue phrase with allow tag, bare < 12 or continue phrase < 40
    assert not r.eligible("[allow-pii] 繼續整合報告")
    assert not r.eligible("繼續做這個")
    assert not r.eligible("continue this")
    assert not r.eligible("接著處理")
    assert not r.eligible("接上一輪")
    assert not r.eligible("續做剩下的")
    # 5. bare token only (URL/path/UUID)
    assert not r.eligible("https://example.com/path")
    assert not r.eligible("~/some/path")
    assert not r.eligible("/absolute/path")
    assert not r.eligible("12345678-1234-1234-1234-123456789012")
    # 6. eligible positive case
    assert r.eligible("幫我把這個服務的設定檔整理一下好嗎")


def test_load_config():
    """load_config: =0, bad file, host mismatch all return None"""
    with tempfile.TemporaryDirectory() as tmp:
        # =0 via env
        os.environ["GENIE_ROUTE_EXT"] = "0"
        try:
            assert r.load_config("claude") is None
        finally:
            del os.environ["GENIE_ROUTE_EXT"]

        # missing file
        os.environ["GENIE_ROUTE_EXT"] = os.path.join(tmp, "nonexistent.json")
        try:
            assert r.load_config("claude") is None
        finally:
            del os.environ["GENIE_ROUTE_EXT"]

        # bad json
        bad_path = os.path.join(tmp, "bad.json")
        with open(bad_path, "w") as f:
            f.write("{not json}")
        os.environ["GENIE_ROUTE_EXT"] = bad_path
        try:
            assert r.load_config("claude") is None
        finally:
            del os.environ["GENIE_ROUTE_EXT"]

        # host not in hosts
        good_path = os.path.join(tmp, "good.json")
        with open(good_path, "w") as f:
            json.dump({"hosts": ["codex"], "table": "x", "heading": "y"}, f)
        os.environ["GENIE_ROUTE_EXT"] = good_path
        try:
            assert r.load_config("claude") is None
        finally:
            del os.environ["GENIE_ROUTE_EXT"]

        # valid config
        with open(good_path, "w") as f:
            json.dump({"hosts": ["claude"], "table": "x", "heading": "y"}, f)
        os.environ["GENIE_ROUTE_EXT"] = good_path
        try:
            cfg = r.load_config("claude")
            assert cfg is not None
            assert cfg["hosts"] == ["claude"]
        finally:
            del os.environ["GENIE_ROUTE_EXT"]


def test_is_fix_row():
    assert r.is_fix_row({"action": "fixindex find something"})
    assert not r.is_fix_row({"action": "other action"})
    assert not r.is_fix_row({})


def main():
    fails = []
    tests = [
        ("pipe_restoration", test_pipe_restoration),
        ("header_separator_skipped", test_header_and_separator_skipped),
        ("stop_at_next_heading", test_stop_at_next_heading),
        ("bad_regex_segment_skipped", test_bad_regex_segment_skipped),
        ("strong_m_ge_2", test_strong_m_ge_2),
        ("strong_short_single_line", test_strong_short_single_line),
        ("weak_long_single_hit", test_weak_long_single_hit),
        ("eligible_exclusions", test_eligible_exclusions),
        ("load_config", test_load_config),
        ("is_fix_row", test_is_fix_row),
    ]
    for name, fn in tests:
        try:
            fn()
            print(f"OK  {name}")
        except AssertionError as e:
            fails.append(f"{name}: {e}")
        except Exception as e:
            fails.append(f"{name}: {type(e).__name__}: {e}")

    if fails:
        print("\nFAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  %d tests" % len(tests))


if __name__ == "__main__":
    main()