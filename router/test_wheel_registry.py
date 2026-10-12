#!/usr/bin/env python3
"""Self-check for the wheel registry CLI. Run: python3 router/test_wheel_registry.py

The registry is the one file that decides whether Genie cites a past decision or
re-researches it. Two ways it lies, and both halves of this test exist for them:

  * a live card that reads as expired -- the reader trusts `[過期]`, redoes the
    research, and the old card quietly disagrees with the new work;
  * an expired or malformed card read as live -- the reader stops researching on a
    stale answer and never finds out.

So the grammar is pinned hard (one verdict word, or `｜`-joined; no `+`, no `|`,
no space; five columns; two real dates; three review windows) and every rejection
must leave the file byte-identical: a refused `add` that appended a row anyway
would be worse than one that wrote nothing, because the caller was told it failed.

Every case runs the CLI as a subprocess against a registry inside a tempdir, with
`WHEEL_REGISTRY` popped from the child environment and `HOME` pointed at a
tempdir for the default-path case. The user's real `~/.wheel/registry.tsv` is
their decisions; no test here reads or writes it.
"""
import datetime
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "wheel_registry.py")

VERDICTS = ("不做", "換題", "設定", "採用", "改用", "借鏡", "自造")
GOOD_VERDICTS = list(VERDICTS) + [
    "設定｜不做",
    "不做｜換題｜設定｜採用｜改用｜借鏡｜自造",
]

CHECKS = []


def eq(got, want, label, fails):
    CHECKS.append(label)
    if got != want:
        fails.append("%s: got %r, want %r" % (label, got, want))


def ok(cond, label, fails):
    CHECKS.append(label)
    if not cond:
        fails.append(label)


def run(*args, **kw):
    """argv in, exit code + stdout + stderr out. `WHEEL_REGISTRY` is popped first:
    a caller who exported one must not decide what these tests read."""
    env = dict(os.environ)
    env.pop("WHEEL_REGISTRY", None)
    if kw.get("registry") is not None:
        env["WHEEL_REGISTRY"] = kw["registry"]
    if kw.get("home") is not None:
        env["HOME"] = kw["home"]
    return subprocess.run([sys.executable, CLI] + [str(a) for a in args],
                          capture_output=True, text=True, env=env,
                          cwd=tempfile.gettempdir())


def registry(tmp, *parts):
    return os.path.join(tmp, *parts)


def rows_of(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [line.rstrip("\n") for line in fh]
    except FileNotFoundError:
        return []


def write_rows(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(line + "\n" for line in lines))


def today(offset=0):
    return (datetime.date.today() + datetime.timedelta(days=offset)).isoformat()


# --- add: one well-formed row per call --------------------------------------
def test_add_writes_one_row(fails):
    with tempfile.TemporaryDirectory() as tmp:
        # Nested on purpose: the directory usually does not exist when step 0 has
        # already run, so `add` is the thing that has to create it.
        path = registry(tmp, "wheel", "cards", "registry.tsv")
        p = run("add", "借鏡", "q one", "pick", 30, registry=path)
        eq(p.returncode, 0, "add exits 0", fails)
        rows = rows_of(path)
        eq(len(rows), 1, "add appends exactly one row", fails)
        f = rows[0].split("\t")
        eq(len(f), 5, "five TAB-separated columns", fails)
        eq(f[1], "借鏡", "verdict lands in column 2", fails)
        eq(f[2], "q one", "problem lands in column 3", fails)
        eq(f[3], "pick", "choice lands in column 4", fails)
        ok(f[0] in (today(), today(0)) and f[0] == f[0].strip(), "date column is today", fails)
        ok(f[4] in (today(30),), "review_by is today + 30 days", fails)
        eq(run("check", registry=path).stdout.strip(), "ok 1 rows",
           "a row this CLI wrote passes check", fails)


def test_add_accepts_every_verdict_and_separator(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        for v in GOOD_VERDICTS:
            p = run("add", v, "problem %s" % v, "choice", 90, registry=path)
            eq(p.returncode, 0, "add accepts verdict %r" % v, fails)
        eq(len(rows_of(path)), len(GOOD_VERDICTS), "every accepted verdict wrote a row", fails)
        p = run("check", registry=path)
        eq((p.returncode, p.stdout.strip()), (0, "ok %d rows" % len(GOOD_VERDICTS)),
           "all seven verdicts and the ｜-joined forms pass check", fails)


def test_add_honours_the_three_review_windows(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        for d in (30, 90, 180):
            eq(run("add", "採用", "q%d" % d, "c", d, registry=path).returncode, 0,
               "add accepts %d days" % d, fails)
        got = [r.split("\t")[4] for r in rows_of(path)]
        eq(got, [today(30), today(90), today(180)],
           "review_by follows the window asked for", fails)


# --- add: what it must refuse, and must not touch ----------------------------
BAD_VERDICTS = [
    ("plus separator", "借鏡+自造"),
    ("half-width pipe", "借鏡|自造"),
    ("space separated", "借鏡 自造"),
    ("comma separated", "借鏡,自造"),
    ("parenthesised", "(借鏡)"),
    ("trailing full stop", "借鏡."),
    ("not a verdict at all", "採用吧"),
    ("near miss 採用/採用了", "採用了"),
    ("trailing separator", "設定｜"),
    ("leading separator", "｜不做"),
    ("separator only", "｜"),
    ("empty", ""),
]

BAD_DAYS = ["45", "0", "7", "-30", "30.5", "", "3 0", "三十", "180 "]

# A TAB or newline inside a field shifts every later column, so the row still
# parses and still says the wrong thing.
BAD_FIELDS = [
    ("TAB in problem", "借鏡", "a\tb", "p", "30"),
    ("TAB in choice", "借鏡", "q", "a\tb", "30"),
    ("TAB in verdict", "借鏡\t自造", "q", "p", "30"),
    ("newline in problem", "借鏡", "a\nb", "p", "30"),
    ("newline in choice", "借鏡", "q", "a\nb", "30"),
    ("carriage return in problem", "借鏡", "a\rb", "p", "30"),
]


def test_add_refuses_bad_verdicts(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        write_rows(path, [today() + "\t借鏡\tq\tp\t" + today(30)])
        before = rows_of(path)
        for label, verdict in BAD_VERDICTS:
            p = run("add", verdict, "q", "p", 30, registry=path)
            eq(p.returncode, 2, "refuses verdict (%s): %r" % (label, verdict), fails)
            ok(p.stderr.strip(), "refused verdict (%s) explains itself on stderr" % label, fails)
        eq(rows_of(path), before, "no refused verdict touched the file", fails)


def test_add_refuses_bad_days(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        before = rows_of(path)
        for days in BAD_DAYS:
            p = run("add", "借鏡", "q", "p", days, registry=path)
            eq(p.returncode, 2, "refuses days=%r" % days, fails)
            ok(p.stderr.strip(), "refused days=%r explains itself on stderr" % days, fails)
        eq(rows_of(path), before, "no refused day count touched the file", fails)


def test_add_refuses_embedded_tabs_and_newlines(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        before = rows_of(path)
        for label, verdict, problem, choice, days in BAD_FIELDS:
            p = run("add", verdict, problem, choice, days, registry=path)
            eq(p.returncode, 2, "refuses %s" % label, fails)
            eq(rows_of(path), before, "%s wrote nothing" % label, fails)
        eq(rows_of(path), [], "the file still does not exist", fails)


def test_add_refuses_wrong_arg_counts(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        for args in ([], ["借鏡"], ["借鏡", "q", "p"], ["借鏡", "q", "p", "30", "extra"]):
            p = run(*(["add"] + args), registry=path)
            eq(p.returncode, 2, "add with %d arguments is a usage error" % len(args), fails)
            ok(not os.path.exists(path), "usage error created no file (%d args)" % len(args), fails)


# --- find: the step-0 lookup --------------------------------------------------
def test_find_is_case_insensitive_and_literal(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        run("add", "借鏡", "q one", "pick", 30, registry=path)
        p = run("find", "Q ONE", registry=path)
        eq(p.returncode, 0, "find exits 0 on a hit", fails)
        eq(len(p.stdout.strip().splitlines()), 1, "one row matched", fails)
        ok(p.stdout.startswith("[有效] "), "a live card is prefixed [有效]", fails)
        ok("q one" in p.stdout, "the matched row is printed", fails)
        # Literal, like the `grep -iF` this replaces: a dot is a dot, not any char.
        write_rows(path, [today() + "\t自造\ta.c\tpick\t" + today(30)])
        eq(run("find", "abc", registry=path).stdout.strip(), "無舊卡",
           "find does not treat the keyword as a pattern", fails)
        eq(run("find", "A.C", registry=path).stdout.count("[有效] "), 1,
           "find matches the keyword literally, ignoring case", fails)


def test_find_matches_any_column(fails):
    """The old command was `grep -iF` over the whole line, so every column counts:
    the card you are about to re-make is often named by its choice, not its question."""
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        run("add", "採用", "how do I parse tsv", "python csv", 30, registry=path)
        for kw in ("how do I", "採用", "python csv", "csv"):
            eq(run("find", kw, registry=path).stdout.count("[有效] "), 1,
               "keyword %r hits the row" % kw, fails)


def test_find_keeps_only_the_last_five(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        for i in range(7):
            run("add", "借鏡", "shared problem %d" % i, "c", 30, registry=path)
        run("add", "採用", "unrelated", "c", 30, registry=path)
        lines = run("find", "shared problem", registry=path).stdout.strip().splitlines()
        eq(len(lines), 5, "find shows the last 5 matches, not all of them", fails)
        ok(all(l.startswith("[有效] ") for l in lines), "all five carry the prefix", fails)
        eq([l.split("\t")[2] for l in lines],
           ["shared problem %d" % i for i in (2, 3, 4, 5, 6)],
           "the last five, oldest first", fails)


def test_find_marks_expiry_against_today(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        write_rows(path, [
            today(-1) + "\t借鏡\tfresh\tc\t" + today(1),
            today(-1) + "\t借鏡\tdue today\tc\t" + today(),
            today(-40) + "\t借鏡\tlong gone\tc\t" + today(-1),
            today(-400) + "\t借鏡\tancient\tc\t" + today(-370),
            "2020-01-01\t設定\tunreadable\tc\tlast tuesday",
            today() + "\t借鏡\tshort row\tc",
        ])
        got = {}
        for kw in ("fresh", "due today", "long gone", "ancient", "unreadable", "short row"):
            line = run("find", kw, registry=path).stdout.strip()
            got[kw] = line.split(" ", 1)[0] if line else ""
        eq(got["fresh"], "[有效]", "review_by in the future is live", fails)
        eq(got["due today"], "[有效]", "review_by today is still live, not expired", fails)
        eq(got["long gone"], "[過期]", "review_by yesterday is expired", fails)
        eq(got["ancient"], "[過期]", "a card from last year is expired", fails)
        # A row we cannot read a review_by out of must not be promoted to live:
        # "[有效]" tells the reader to stop researching on it.
        eq(got["unreadable"], "[過期]", "an unparseable review_by counts as expired", fails)
        eq(got["short row"], "[過期]", "a row with too few columns counts as expired", fails)


def test_find_without_a_hit_is_not_a_failure(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        p = run("find", "zzz-none", registry=path)
        eq(p.returncode, 0, "no hit is exit 0, not an error", fails)
        eq(p.stdout.strip(), "無舊卡", "no hit prints 無舊卡", fails)
        run("add", "借鏡", "q one", "pick", 30, registry=path)
        eq(run("find", "zzz-none", registry=path).stdout.strip(), "無舊卡",
           "no hit in a populated registry prints 無舊卡", fails)
        eq(run("find", registry=path).returncode, 2, "find with no keyword is a usage error", fails)


def test_find_on_a_registry_that_does_not_exist_yet(fails):
    """Step 0 runs before the first add, so this is the normal first answer."""
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "never-written.tsv")
        p = run("find", "anything", registry=path)
        eq((p.returncode, p.stdout.strip()), (0, "無舊卡"),
           "a missing registry reads as no cards, exit 0", fails)


# --- check: report the broken rows, never rewrite them ------------------------
def test_check_passes_a_clean_file(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        for v in GOOD_VERDICTS[:3]:
            run("add", v, "problem " + v, "choice", 90, registry=path)
        p = run("check", registry=path)
        eq((p.returncode, p.stdout.strip()), (0, "ok 3 rows"), "a clean file passes", fails)
        write_rows(path, [today() + "\t借鏡\tq\tc\t" + today(1), ""])
        eq(run("check", registry=path).stdout.strip(), "ok 1 rows",
           "a blank line is formatting, not a broken row", fails)


def test_check_reports_every_violation_by_line_number(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        write_rows(path, [
            today() + "\t借鏡\tgood\tc\t" + today(30),                      # 1 ok
            today() + "\t借鏡\tfour columns\tc",                            # 2 too few columns
            today() + "\t借鏡\tslash date\tc\t2026/01/01",                  # 3 wrong format
            today() + "\t借鏡\tnonexistent day\tc\t2026-02-31",             # 4 right shape, no such day
            today() + "\t借鏡+自造\tplus verdict\tc\t" + today(30),         # 5 bad verdict
            today() + "\t借鏡\tshort date\tc\t30d",                         # 6 bad review_by
            today(-40) + "\t借鏡\tstale but well formed\tc\t" + today(-1),   # 7 ok: check does not judge age
            today() + "\t採用｜不做\tjoined\tc\t" + today(30),               # 8 ok: ｜ is legal
        ])
        p = run("check", registry=path)
        eq(p.returncode, 1, "a file with violations exits 1", fails)
        out = p.stdout.splitlines()
        for n in (2, 3, 4, 5, 6):
            hits = [l for l in out if l.startswith("line %d: " % n)]
            eq(len(hits), 1, "line %d reported once" % n, fails)
        for n in (1, 7, 8):
            ok(not any(l.startswith("line %d: " % n) for l in out),
               "line %d is legal and not reported" % n, fails)
        ok("欄數 4" in p.stdout, "the column-count reason is named", fails)
        ok("date" in p.stdout and "review_by" in p.stdout, "both date columns are named", fails)
        ok("verdict" in p.stdout, "the verdict reason is named", fails)
        eq(len(rows_of(path)), 8, "check never rewrites the file", fails)


def test_check_empty_and_missing(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        p = run("check", registry=path)
        eq((p.returncode, p.stdout.strip()), (0, "ok 0 rows"),
           "a missing registry is zero rows, exit 0", fails)
        write_rows(path, [])
        eq(run("check", registry=path).stdout.strip(), "ok 0 rows",
           "an empty registry is zero rows", fails)


# --- where the file lives ------------------------------------------------------
def test_default_path_uses_home_not_a_real_registry(fails):
    """`$WHEEL_REGISTRY` unset falls back to `~/.wheel/registry.tsv`. HOME is
    pointed at a tempdir here, so this proves the fallback without ever reading
    or writing the user's own registry."""
    with tempfile.TemporaryDirectory() as tmp:
        p = run("add", "借鏡", "q", "p", 30, home=tmp)
        eq(p.returncode, 0, "add works with WHEEL_REGISTRY unset", fails)
        default = registry(tmp, ".wheel", "registry.tsv")
        ok(os.path.isfile(default), "the default path is $HOME/.wheel/registry.tsv", fails)
        eq(len(rows_of(default)), 1, "the default-path add wrote one row", fails)
        eq(run("find", "q", home=tmp).returncode, 0, "find reads the same default path", fails)
        # The env var wins over HOME, or a test harness could not redirect a user.
        with tempfile.TemporaryDirectory() as other:
            path = registry(other, "explicit.tsv")
            run("add", "採用", "q2", "p2", 90, registry=path, home=tmp)
            eq(len(rows_of(path)), 1, "WHEEL_REGISTRY overrides the default path", fails)


def test_unknown_subcommand_is_a_usage_error(fails):
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        for args in (["nope"], ["findx", "q"], ["check", "extra"], ["add"]):
            p = run(*args, registry=path)
            eq(p.returncode, 2, "%r is a usage error" % (args,), fails)
        eq(run("--help", registry=path).returncode, 0, "--help exits 0", fails)
        eq(run(registry=path).returncode, 2, "no subcommand is a usage error", fails)


def test_exit_codes_stay_distinct(fails):
    """0 success, 1 a broken registry, 2 a refused request. Collapsing any two of
    them makes a shell script's `|| rc=$?` branch do the wrong thing."""
    with tempfile.TemporaryDirectory() as tmp:
        path = registry(tmp, "registry.tsv")
        write_rows(path, [today() + "\t借鏡\tq\tp\t" + today(30)])
        eq(run("check", registry=path).returncode, 0, "0 = check passed", fails)
        eq(run("add", "借鏡+自造", "q", "p", 30, registry=path).returncode, 2,
           "2 = request refused", fails)
        write_rows(path, [today() + "\t借鏡\tbroken row"])
        eq(run("check", registry=path).returncode, 1, "1 = registry broken", fails)


def main():
    fails = []
    for fn in (test_add_writes_one_row,
               test_add_accepts_every_verdict_and_separator,
               test_add_honours_the_three_review_windows,
               test_add_refuses_bad_verdicts,
               test_add_refuses_bad_days,
               test_add_refuses_embedded_tabs_and_newlines,
               test_add_refuses_wrong_arg_counts,
               test_find_is_case_insensitive_and_literal,
               test_find_matches_any_column,
               test_find_keeps_only_the_last_five,
               test_find_marks_expiry_against_today,
               test_find_without_a_hit_is_not_a_failure,
               test_find_on_a_registry_that_does_not_exist_yet,
               test_check_passes_a_clean_file,
               test_check_reports_every_violation_by_line_number,
               test_check_empty_and_missing,
               test_default_path_uses_home_not_a_real_registry,
               test_unknown_subcommand_is_a_usage_error,
               test_exit_codes_stay_distinct):
        try:
            fn(fails)
        except Exception as e:
            fails.append("%s raised %r" % (fn.__name__, e))
    if fails:
        print("FAIL (%d of %d checks):" % (len(fails), len(CHECKS)))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  %d checks across %d cases: add writes 5 columns / every verdict and "
          "all 3 review windows, refuses bad verdicts (%d), bad day counts (%d) and "
          "embedded TAB or newline without touching the file, find is literal + "
          "case-insensitive + last-5 + live/expired + 無舊卡, check reports every "
          "violation by line and passes a clean file, default path honours "
          "WHEEL_REGISTRY then HOME, exit codes 0/1/2 stay distinct"
          % (len(CHECKS), 19, len(BAD_VERDICTS), len(BAD_DAYS)))


if __name__ == "__main__":
    main()