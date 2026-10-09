#!/usr/bin/env python3
"""Genie self-check: runs at SessionStart to verify the three hooks work.

Three independent checks, each with a 2-second timeout. Any timeout is treated
as skipped (not a failure) to avoid slowing down session start.
"""
import json
import os
import subprocess
import sys
import tempfile
import argparse


def run_with_timeout(cmd, input_data, env, timeout=2):
    """Run a command with timeout. Returns (rc, stdout, timed_out)."""
    try:
        proc = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout, False
    except subprocess.TimeoutExpired:
        return -1, "", True
    except Exception:
        return -1, "", False


def check_guard(root, env):
    """Check 1: guard_dangerous.py denies 'rm -rf ~'."""
    guard_path = os.path.join(root, "router", "guard_dangerous.py")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf ~"}})
    rc, out, timed_out = run_with_timeout([sys.executable, guard_path], payload, env)
    if timed_out:
        return "skipped"
    if rc != 0 or not out.strip():
        return "guard"
    try:
        data = json.loads(out)
        if data.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
            return "ok"
    except Exception:
        pass
    return "guard"


def check_router(root, env):
    """Check 2: genie_router.py routes a basic execute_request."""
    router_path = os.path.join(root, "router", "genie_router.py")
    payload = json.dumps({"prompt": "幫我把這個專案跑起來可以嗎", "session_id": "selftest"})
    rc, out, timed_out = run_with_timeout(
        [sys.executable, router_path, "--host", "claude"], payload, env
    )
    if timed_out:
        return "skipped"
    if rc != 0 or not out.strip():
        return "router"
    return "ok"


def check_hooks(root, env):
    """Check 3: every ${CLAUDE_PLUGIN_ROOT}/... path in hooks.json exists."""
    hooks_path = os.path.join(root, "claude", "hooks.json")
    try:
        with open(hooks_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return "hooks"

    hooks = data.get("hooks", {})
    for event, entries in hooks.items():
        for entry in entries:
            for h in entry.get("hooks", []):
                cmd = h.get("command", "")
                if not cmd:
                    continue
                # Find all ${CLAUDE_PLUGIN_ROOT}/... patterns
                import re
                for match in re.finditer(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s\"']+)", cmd):
                    rel_path = match.group(1)
                    abs_path = os.path.join(root, rel_path)
                    if not os.path.exists(abs_path):
                        return "hooks"
    return "ok"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", help="Root directory (default: parent of this file)")
    args = parser.parse_args()

    if args.root:
        root = os.path.abspath(args.root)
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Create isolated temp directory for this run
    with tempfile.TemporaryDirectory(prefix="genie-selftest-") as tmpdir:
        env = dict(os.environ)
        env["GENIE_PREFS"] = os.path.join(tmpdir, "p.json")
        env["GENIE_LOG"] = "0"
        env["GENIE_STATE_DIR"] = tmpdir

        failed = []
        for name, check_fn in [
            ("guard", check_guard),
            ("router", check_router),
            ("hooks", check_hooks),
        ]:
            result = check_fn(root, env)
            if result != "ok" and result != "skipped":
                failed.append(name)

        if failed:
            print(f"Genie self-check failed: {', '.join(failed)}. Some protections may be off. Tell the user in one plain sentence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())