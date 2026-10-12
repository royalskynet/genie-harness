#!/usr/bin/env python3
"""Genie wheel registry — the store behind step 0 of `skills/wheel/SKILL.md`.

Why a CLI and not the skill's `grep`. Step 0 is "look at what you already decided
before deciding again", and the skill was writing `~/.wheel/registry.tsv` with a
hand-rolled `printf` plus a `date -v+30d || date -d +30days` portability dance. A
hand-rolled writer is where a registry rots, in two specific ways:

  * A verdict typed as `借鏡+自造` or `借鏡|自造` is not a verdict the skill can
    act on. SKILL.md says "不發明組合字串" and nothing enforces it.
  * One missing TAB shifts every later column, so `review_by` silently holds the
    wrong value and a live decision reads as expired — the failure mode this file
    exists to prevent is a stale card *looking* fresh, not a missing card.

So the grammar is enforced at the only moment it can be: the write. One verdict
word, or several joined by the full-width `｜` — `|` and `+` are exactly the typos
that need rejecting, so they are not accepted as separators. `check` covers the
rows that did not come through this CLI (hand-edited, pasted from a chat, written
by an older skill version): it names each broken line by number and never
rewrites it, because a card someone typed by hand is still their decision.

Storage is `$WHEEL_REGISTRY`, else `~/.wheel/registry.tsv`. Five TAB-separated
columns: date, verdict, problem, choice, review_by. `review_by` is why the file
carries an expiry at all — a card about model routing or a free quota is stale in
a month, and the three windows (30 / 90 / 180) are the skill's, not a guess.

Cost: standard library only, no network. The contract is argv → exit code →
stdout, so `test_wheel_registry.py` drives this as a subprocess and never
touches a real `~/.wheel/registry.tsv`.
"""
import datetime
import os
import re
import sys

# skills/wheel/SKILL.md §5, lowest cost to highest. Kept in this order so the
# usage text reads as the ladder, not as an alphabet.
VERDICTS = ("不做", "換題", "設定", "採用", "改用", "借鏡", "自造")
# Full-width on purpose. Half-width `|` reads as a shell pipe and `+` as
# arithmetic, which is why both are common in hand-typed verdicts and neither is
# a verdict the skill can act on.
VERDICT_SEP = "｜"
COLUMNS = 5
# SKILL.md's review windows: fast-moving (AI/LLM/agent, model routing, free
# quotas) 30, ordinary packages and CLIs 90, OS mechanisms and mature frameworks
# 180. Three values, not a range: a card re-reviewed on a whim is a card nobody
# trusts.
DAY_CHOICES = ("30", "90", "180")
DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
DEFAULT_PATH = os.path.expanduser("~/.wheel/registry.tsv")

USAGE = """wheel_registry -- 輪子卡登記簿（skills/wheel/SKILL.md 第 0 步與收尾登記）
  find <kw> [kw...]                    找舊卡（不分大小寫、字面比對），最多印最後 5 筆
                                      每筆前綴 [有效] 或 [過期]；沒有命中印「無舊卡」
  add <verdict> <problem> <choice> <30|90|180>
                                      登記一筆，review_by = 今天 + 天數
  check                               逐列檢查欄數／日期／verdict；全對印 ok <列數> rows
verdict: %s
        多個用全形 ｜ 串接，例如 設定｜不做
檔案: %s（環境變數 WHEEL_REGISTRY 可改）
""" % (" / ".join(VERDICTS), "%s")


def registry_path():
    """`$WHEEL_REGISTRY`, else `~/.wheel/registry.tsv`.

    An empty env var counts as unset: `WHEEL_REGISTRY=` must not silently write a
    row to a file named "".
    """
    return os.environ.get("WHEEL_REGISTRY") or DEFAULT_PATH


def today():
    return datetime.date.today()


def parse_date(text):
    """`YYYY-MM-DD`, and a day that exists -- `2026-02-31` is a typo, not a date.

    Regex first so a 19-digit field cannot reach strptime's error text, which
    quotes the whole string and would put a stranger's bytes in our message.
    """
    if not DATE_RE.match(text or ""):
        return None
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def verdict_ok(verdict):
    """One verdict word, or several joined by `｜`. Nothing else.

    Splitting and comparing to the whole vocabulary is what rejects the near
    misses: `借鏡+自造` and `借鏡|自造` arrive as a single unrecognised token, and
    `設定｜` / `｜不做` leave an empty part that matches no word.
    """
    return bool(verdict) and all(part in VERDICTS for part in verdict.split(VERDICT_SEP))


def read_rows(path):
    """-> [(1-based line number, text without its newline)], in file order.

    A missing file is zero rows rather than an error: step 0 runs before the
    first `add`, and "you have no cards yet" is the normal first answer. Anything
    else (unreadable, is a directory) raises, so a broken path is reported as a
    failure rather than as an empty registry.
    """
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [(n, line.rstrip("\r\n")) for n, line in enumerate(fh, 1)]


def row_problems(text):
    """Every reason this row is unusable, in check order: columns, dates, verdict.

    A row with the wrong column count returns that alone -- the remaining fields
    are not the ones they look like, so reporting them would point at the wrong
    word.
    """
    fields = text.split("\t")
    if len(fields) != COLUMNS:
        return ["欄數 %d，應為 %d（date/verdict/problem/choice/review_by）"
                % (len(fields), COLUMNS)]
    out = []
    for label, value in (("date", fields[0]), ("review_by", fields[4])):
        if parse_date(value.strip()) is None:
            out.append("%s 不是 YYYY-MM-DD 的日期：%r" % (label, value))
    if not verdict_ok(fields[1]):
        out.append("verdict 不合法：%r（只能是 %s，或用全形 ｜ 串接數個）"
                   % (fields[1], " / ".join(VERDICTS)))
    return out


def _expired(text):
    """review_by < today. A row we cannot read a review_by out of counts as expired.

    `[有效]` promises "still live, cite this card and stop researching". A row with
    the wrong column count or an unparseable date cannot back that promise, so it
    is marked stale and re-checked here -- dropping it would let a whole broken
    registry answer "無舊卡", which is the one answer that is always safe to be
    wrong about. `check` is where such a row gets reported.
    """
    fields = text.split("\t")
    if len(fields) != COLUMNS:
        return True
    due = parse_date(fields[4].strip())
    return due is None or due < today()


def cmd_find(keywords):
    if not keywords:
        return usage("find 需要至少一個關鍵字")
    needles = [k.lower() for k in keywords]
    rows = read_rows(registry_path())
    hits = [text for _, text in rows if any(k in text.lower() for k in needles)]
    if not hits:
        print("無舊卡")
        return 0
    # Whole-line, case-insensitive, literal -- the same match as the `grep -iF`
    # this replaces, so a card found by either command is the same card.
    # Last 5 only: step 0 answers "what did we already decide", and the newest row
    # is the one that supersedes the rest.
    for text in hits[-5:]:
        print(("[過期] " if _expired(text) else "[有效] ") + text)
    return 0


def cmd_add(args):
    if len(args) != 4:
        return usage("add 需要 4 個引數：<verdict> <problem> <choice> <30|90|180>")
    verdict, problem, choice, days = args
    bad = []
    if not verdict_ok(verdict):
        bad.append("verdict 不合法：%r（只能是 %s，或用全形 ｜ 串接數個）"
                   % (verdict, " / ".join(VERDICTS)))
    if days not in DAY_CHOICES:
        bad.append("天數只能是 %s（依領域變化速度：快 30／中 90／慢 180），收到 %r"
                   % ("/".join(DAY_CHOICES), days))
    # A TAB or newline inside a field shifts every column after it, so the row
    # would still parse and still be wrong. Not something a caller can notice
    # afterwards, so it is refused here.
    for name, value in (("verdict", verdict), ("problem", problem), ("choice", choice)):
        if "\t" in value or "\n" in value or "\r" in value:
            bad.append("%s 欄位含 TAB 或換行，會把後面的欄位推歪" % name)
    if bad:
        for line in bad:
            sys.stderr.write("wheel_registry: %s\n" % line)
        return 2
    path = registry_path()
    row = [today().isoformat(), verdict, problem, choice,
           (today() + datetime.timedelta(days=int(days))).isoformat()]
    try:
        append_row(path, row)
    except OSError as e:
        sys.stderr.write("wheel_registry: 寫不進 %s：%s\n" % (path, e))
        return 1
    return 0


def append_row(path, fields):
    """Append one row, creating the directory (step 0 runs before the first add)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    row = "\t".join(fields)
    # A file whose last line lacks its newline (interrupted write, hand edit)
    # would swallow this row into the previous one. Close the line instead: a
    # half-written row then shows up in `check` instead of two decisions quietly
    # merging into one.
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as fh:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                row = "\n" + row
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(row + "\n")


def cmd_check(args):
    if args:
        return usage("check 不接受引數")
    rows = read_rows(registry_path())
    # Violations go to stdout, not stderr: the caller asked for a report and
    # pipes it (`check > out`), so this is data. Exit 1 is the only thing telling
    # it apart from the ok line.
    reported, count = [], 0
    for lineno, text in rows:
        if not text.strip():
            continue  # a blank line is formatting, not a broken row
        count += 1
        reported += ["line %d: %s" % (lineno, why) for why in row_problems(text)]
    if reported:
        for line in reported:
            print(line)
        return 1
    print("ok %d rows" % count)
    return 0


def usage(message=None):
    if message:
        sys.stderr.write("wheel_registry: %s\n" % message)
    sys.stderr.write(USAGE % registry_path())
    return 2


def main(argv):
    args = list(argv[1:])
    if not args:
        return usage()
    if args[0] in ("-h", "--help", "help"):
        sys.stdout.write(USAGE % registry_path())
        return 0
    cmd, rest = args[0], args[1:]
    try:
        if cmd == "find":
            return cmd_find(rest)
        if cmd == "add":
            return cmd_add(rest)
        if cmd == "check":
            return cmd_check(rest)
    except OSError as e:
        sys.stderr.write("wheel_registry: %s：%s\n" % (registry_path(), e))
        return 1
    return usage("未知子指令：%s" % cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv))