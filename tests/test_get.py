#!/usr/bin/env python3
"""get.sh branching with a fake `claude` and HOME; nothing real is installed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
KEY = "genie-harness@genie-harness"


class GetTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="genie get test ")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.calls = self.home / "calls.log"
        self.plugins = self.home / ".claude" / "plugins"
        self.plugins.mkdir(parents=True)
        self.market = self.home / "market"
        (self.market / "router").mkdir(parents=True)
        (self.market / "router" / "safe_update.py").write_text(
            "import sys\n"
            f"open({str(self.calls)!r}, 'a').write('safe_update ' + ' '.join(sys.argv[1:]) + '\\n')\n",
            encoding="utf-8",
        )
        (self.bin / "python3").symlink_to(sys.executable)

    def fake_claude(self):
        claude = self.bin / "claude"
        claude.write_text(f'#!/bin/sh\necho "claude $*" >> "{self.calls}"\n', encoding="utf-8")
        claude.chmod(0o755)

    def run_get(self, *args):
        env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin"}
        return subprocess.run(["bash", str(ROOT / "get.sh"), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def log(self):
        return self.calls.read_text(encoding="utf-8").splitlines() if self.calls.exists() else []

    def test_fresh_claude_adds_and_installs(self):
        self.fake_claude()
        r = self.run_get("claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log(), ["claude plugin marketplace add royalskynet/genie-harness",
                                      f"claude plugin install {KEY}"])

    def test_installed_claude_updates_through_safe_update(self):
        self.fake_claude()
        (self.plugins / "known_marketplaces.json").write_text(
            json.dumps({"genie-harness": {"installLocation": str(self.market)}}), encoding="utf-8")
        (self.plugins / "installed_plugins.json").write_text(
            json.dumps({"plugins": {KEY: [{"scope": "user", "version": "0.5.1"}]}}), encoding="utf-8")
        r = self.run_get("claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log(), ["claude plugin marketplace update genie-harness",
                                      f"safe_update {KEY}"])

    def test_auto_with_no_host_fails_loud(self):
        r = self.run_get()
        self.assertEqual(r.returncode, 1)
        self.assertIn("neither claude nor codex", r.stderr)

    def test_unknown_host(self):
        r = self.run_get("vscode")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
