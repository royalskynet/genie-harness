#!/usr/bin/env python3
"""Update a Claude Code plugin without breaking sessions that are still running.

`claude plugin update` deletes the old version's cache directory. A session
that is already running resolved ${CLAUDE_PLUGIN_ROOT} to that directory when
it started, so after the update its hooks point at files that are gone:
`python3 missing.py` exits 2, and exit 2 from a PreToolUse hook blocks the tool.
Every open session stops working until it is restarted.

This wraps the update:
1. Clean up: a version marked `.retired-at` is deleted once no claude process
   started before that time is still alive.
2. Back up every version directory in the cache.
3. Update every scope this plugin is installed in (user, and each project or
   local scope from its own directory), so all of them move together.
4. Put back any version the update deleted, and mark every version that is no
   longer installed `.retired-at`. Running sessions keep their version; a
   restart picks up the new one.

Usage: python3 safe_update.py [name@marketplace]   (default genie-harness@genie-harness)
Env for tests: CLAUDE_PLUGINS_DIR, CLAUDE_BIN, SAFE_UPDATE_PS (a file holding
`ps -A -o lstart=,command=` output). Stdlib only.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

LSTART = "%a %b %d %H:%M:%S %Y"


def claude_starts():
    """Start times (epoch) of running claude processes, or None when they
    cannot be listed (no `ps`, e.g. Windows). None means "unknown": keep
    every old version rather than guess that nobody uses it."""
    fake = os.environ.get("SAFE_UPDATE_PS")
    try:
        if fake:
            with open(fake, encoding="utf-8") as fh:
                out = fh.read()
        else:
            out = subprocess.run(["ps", "-A", "-o", "lstart=,command="], capture_output=True,
                                 text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    starts = []
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        exe = parts[5].split(" ", 1)[0]
        if os.path.basename(exe) != "claude":
            continue
        try:
            starts.append(time.mktime(time.strptime(" ".join(parts[:5]), LSTART)))
        except ValueError:
            continue
    return starts


def versions(cache):
    if not os.path.isdir(cache):
        return []
    return sorted(n for n in os.listdir(cache)
                  if os.path.isdir(os.path.join(cache, n)) and not os.path.islink(os.path.join(cache, n)))


def retired_at(path):
    try:
        with open(os.path.join(path, ".retired-at"), encoding="utf-8") as fh:
            return float(fh.read().strip())
    except (OSError, ValueError):
        return None


def mark(path, now):
    with open(os.path.join(path, ".retired-at"), "w", encoding="utf-8") as fh:
        fh.write("%d\n" % now)


def main(argv):
    key = argv[1] if len(argv) > 1 else "genie-harness@genie-harness"
    name, _, mkt = key.partition("@")
    pdir = os.path.expanduser(os.environ.get("CLAUDE_PLUGINS_DIR", "~/.claude/plugins"))
    claude = os.environ.get("CLAUDE_BIN", "claude")
    cache = os.path.join(pdir, "cache", mkt, name)
    with open(os.path.join(pdir, "installed_plugins.json"), encoding="utf-8") as fh:
        entries = json.load(fh).get("plugins", {}).get(key, [])
    if not entries:
        print("safe_update: %s is not installed" % key, file=sys.stderr)
        return 1

    # 1. clean up versions nobody can still be using
    starts = claude_starts()
    for v in versions(cache):
        path = os.path.join(cache, v)
        r = retired_at(path)
        if r is None or starts is None:
            continue
        if all(s > r for s in starts):
            shutil.rmtree(path, ignore_errors=True)
            print("safe_update: removed %s (no session started before it was retired)" % v)

    # 2. back up
    backup = tempfile.mkdtemp(prefix="safe-update-")
    try:
        for v in versions(cache):
            shutil.copytree(os.path.join(cache, v), os.path.join(backup, v), symlinks=True)

        # 3. update every scope
        failed = 0
        for e in entries:
            scope = e.get("scope", "user")
            cwd = e.get("projectPath") if scope in ("project", "local") else None
            if cwd and not os.path.isdir(cwd):
                print("safe_update: skip %s scope, %s is gone" % (scope, cwd), file=sys.stderr)
                continue
            rc = subprocess.run([claude, "plugin", "update", key, "-s", scope], cwd=cwd).returncode
            failed |= rc != 0

        # 4. put back deleted versions; retire whatever is no longer installed
        now = time.time()
        for v in os.listdir(backup):
            dest = os.path.join(cache, v)
            if not os.path.exists(dest):
                shutil.move(os.path.join(backup, v), dest)
                print("safe_update: kept %s for sessions still running it" % v)
        with open(os.path.join(pdir, "installed_plugins.json"), encoding="utf-8") as fh:
            entries = json.load(fh).get("plugins", {}).get(key, [])
        live = {os.path.realpath(e.get("installPath", "")) for e in entries}
        for v in versions(cache):
            path = os.path.join(cache, v)
            if os.path.realpath(path) not in live and retired_at(path) is None:
                mark(path, now)
    finally:
        shutil.rmtree(backup, ignore_errors=True)
    print("safe_update: %s; restart a session to use the new version, open ones keep theirs"
          % " ".join("%s=%s" % (e.get("scope"), e.get("version")) for e in entries))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
