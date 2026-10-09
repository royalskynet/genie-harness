#!/usr/bin/env python3
"""Self-test for selftest.py. Run: python3 router/test_selftest.py

Three scenarios:
1. Real repo runs -> stdout empty (PASS)
2. Copy repo, replace guard_dangerous.py with minimal stub -> output contains 'guard'
3. Copy repo, delete router/done_gate.py -> output contains 'hooks'
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SELFTEST = os.path.join(HERE, "selftest.py")


def run_selftest(root, extra_env=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, SELFTEST, "--root", root],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_real_repo():
    """① Real repo runs -> stdout empty."""
    rc, out, err = run_selftest(ROOT)
    if rc != 0:
        return f"real repo: rc={rc}, stderr={err.strip()[:200]}"
    if out.strip():
        return f"real repo: expected empty stdout, got: {out.strip()[:200]}"
    return None


def test_broken_guard():
    """② Copy repo, replace guard_dangerous.py -> output contains 'guard'."""
    with tempfile.TemporaryDirectory(prefix="genie-test-") as tmpdir:
        # Copy router/ and claude/
        shutil.copytree(os.path.join(ROOT, "router"), os.path.join(tmpdir, "router"))
        shutil.copytree(os.path.join(ROOT, "claude"), os.path.join(tmpdir, "claude"))

        # Replace guard_dangerous.py with minimal stub
        guard_path = os.path.join(tmpdir, "router", "guard_dangerous.py")
        with open(guard_path, "w") as f:
            f.write("import sys\n")

        rc, out, err = run_selftest(tmpdir)
        if rc != 0:
            return f"broken guard: rc={rc}, stderr={err.strip()[:200]}"
        if "guard" not in out:
            return f"broken guard: expected 'guard' in output, got: {out.strip()[:200]}"
    return None


def test_missing_done_gate():
    """③ Copy repo, delete router/done_gate.py -> output contains 'hooks'."""
    with tempfile.TemporaryDirectory(prefix="genie-test-") as tmpdir:
        # Copy router/ and claude/
        shutil.copytree(os.path.join(ROOT, "router"), os.path.join(tmpdir, "router"))
        shutil.copytree(os.path.join(ROOT, "claude"), os.path.join(tmpdir, "claude"))

        # Delete done_gate.py (referenced in hooks.json)
        done_gate_path = os.path.join(tmpdir, "router", "done_gate.py")
        os.unlink(done_gate_path)

        rc, out, err = run_selftest(tmpdir)
        if rc != 0:
            return f"missing done_gate: rc={rc}, stderr={err.strip()[:200]}"
        if "hooks" not in out:
            return f"missing done_gate: expected 'hooks' in output, got: {out.strip()[:200]}"
    return None


def main():
    fails = []

    # Test 1: Real repo
    err = test_real_repo()
    if err:
        fails.append(err)

    # Test 2: Broken guard
    err = test_broken_guard()
    if err:
        fails.append(err)

    # Test 3: Missing done_gate.py
    err = test_missing_done_gate()
    if err:
        fails.append(err)

    if fails:
        print("FAIL:")
        for f in fails:
            print(f"  {f}")
        sys.exit(1)

    print("PASS")


if __name__ == "__main__":
    main()