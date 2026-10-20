#!/usr/bin/env python3
"""Self-check for safe_update. Run: python3 router/test_safe_update.py

A fake plugin cache, a fake `claude` that behaves like the real update (deletes
the old version, installs a new one), and a fake process list. Break the clean-up,
the put-back or the retire marking and this fails.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "safe_update.py")
OLDEST = "Mon Jan  5 00:00:00 2026"  # the one running claude process

FAKE_CLAUDE = """#!%(py)s
import json, os, shutil, sys
calls = os.path.join(%(t)r, "calls")
with open(calls, "a") as fh:
    fh.write("%%s %%s\\n" %% (os.getcwd(), " ".join(sys.argv[1:])))
c = %(c)r
shutil.rmtree(os.path.join(c, "2.0"), ignore_errors=True)
os.makedirs(os.path.join(c, "3.0"), exist_ok=True)
p = os.path.join(%(pd)r, "installed_plugins.json")
d = json.load(open(p))
for e in d["plugins"]["p@m"]:
    e["version"], e["installPath"] = "3.0", os.path.join(c, "3.0")
json.dump(d, open(p, "w"))
"""


def setup(t, ps_text):
    pd = os.path.join(t, "plugins")
    c = os.path.join(pd, "cache", "m", "p")
    proj = os.path.realpath(os.path.join(t, "proj"))
    for v in ("1.0", "0.9", "2.0", "1.5"):
        os.makedirs(os.path.join(c, v))
    os.makedirs(proj)
    with open(os.path.join(c, "1.0", ".retired-at"), "w") as fh:
        fh.write("1000\n")          # retired before the oldest process -> remove
    with open(os.path.join(c, "0.9", ".retired-at"), "w") as fh:
        fh.write("99999999999\n")   # retired after it -> keep
    with open(os.path.join(c, "2.0", "hook.py"), "w") as fh:
        fh.write("pass\n")
    with open(os.path.join(pd, "installed_plugins.json"), "w") as fh:
        json.dump({"plugins": {"p@m": [
            {"scope": "user", "version": "2.0", "installPath": os.path.join(c, "2.0")},
            {"scope": "project", "projectPath": proj, "version": "2.0",
             "installPath": os.path.join(c, "2.0")}]}}, fh)
    fake = os.path.join(t, "claude")
    with open(fake, "w") as fh:
        fh.write(FAKE_CLAUDE % {"py": sys.executable, "t": t, "c": c, "pd": pd})
    os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
    ps = os.path.join(t, "ps.txt")
    if ps_text is not None:
        with open(ps, "w") as fh:
            fh.write(ps_text)
    env = dict(os.environ, CLAUDE_PLUGINS_DIR=pd, CLAUDE_BIN=fake, SAFE_UPDATE_PS=ps)
    p = subprocess.run([sys.executable, SCRIPT, "p@m"], env=env, capture_output=True, text=True)
    return p, c, proj


def main():
    fails = []
    with tempfile.TemporaryDirectory() as t:
        p, c, proj = setup(t, "%s /usr/local/bin/claude --resume x\n"
                              "Tue Jan  1 00:00:00 2030 /usr/bin/tmux new claude\n" % OLDEST)
        has = lambda *parts: os.path.exists(os.path.join(c, *parts))
        if p.returncode != 0:
            fails.append("exit %d: %s" % (p.returncode, p.stderr[-200:]))
        if has("1.0"):
            fails.append("1.0 retired before every session was not removed")
        if not has("0.9"):
            fails.append("0.9 still possibly in use was removed")
        if not (has("2.0", "hook.py") and has("2.0", ".retired-at")):
            fails.append("2.0 deleted by the update was not put back and retired")
        if not has("1.5", ".retired-at"):
            fails.append("1.5 not installed was not marked retired")
        if has("3.0", ".retired-at"):
            fails.append("3.0 in use was marked retired")
        calls = open(os.path.join(t, "calls")).read()
        if "%s plugin update p@m -s project" % proj not in calls:
            fails.append("project scope not updated from its directory: %r" % calls)
        if "plugin update p@m -s user" not in calls:
            fails.append("user scope not updated")
    with tempfile.TemporaryDirectory() as t:
        p, c, _ = setup(t, None)  # process list unavailable
        if not os.path.exists(os.path.join(c, "1.0")):
            fails.append("removed a retired version without knowing which sessions run")
    if fails:
        print("FAIL (%d):" % len(fails))
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("PASS  clean-up, put-back, retire marking, every scope, unknown process list")


if __name__ == "__main__":
    main()
