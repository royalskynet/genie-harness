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
        # Fake git: `clone <url> <dir>` makes a repo with the files get.sh uses.
        git = self.bin / "git"
        git.write_text(
            "#!/bin/sh\n"
            f'echo "git $*" >> "{self.calls}"\n'
            'if [ "$1" = clone ]; then eval d=\\${$#}; mkdir -p "$d/.git" "$d/skills/wheel"; '
            'touch "$d/skills/wheel/SKILL.md"; '
            f'printf \'echo "addon-install $0" >> "{self.calls}"\\n\' > "$d/install.sh"; fi\n',
            encoding="utf-8")
        git.chmod(0o755)

    def fake_claude(self):
        claude = self.bin / "claude"
        claude.write_text(f'#!/bin/sh\necho "claude $*" >> "{self.calls}"\n', encoding="utf-8")
        claude.chmod(0o755)

    def run_get(self, *args):
        env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin"}
        return subprocess.run(["bash", str(ROOT / "get.sh"), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def log(self, prefix=""):
        lines = self.calls.read_text(encoding="utf-8").splitlines() if self.calls.exists() else []
        return [l for l in lines if l.startswith(prefix)]

    def test_fresh_claude_adds_and_installs(self):
        self.fake_claude()
        r = self.run_get("claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log("claude"), ["claude plugin marketplace add royalskynet/genie-harness",
                                              f"claude plugin install {KEY}"])
        # wheel is on by default and becomes a Claude user skill
        self.assertTrue(any("royalskynet/wheel-it" in l for l in self.log("git clone")))
        self.assertTrue((self.home / ".claude" / "skills" / "wheel").is_symlink())

    def test_installed_claude_updates_through_safe_update(self):
        self.fake_claude()
        (self.plugins / "known_marketplaces.json").write_text(
            json.dumps({"genie-harness": {"installLocation": str(self.market)}}), encoding="utf-8")
        (self.plugins / "installed_plugins.json").write_text(
            json.dumps({"plugins": {KEY: [{"scope": "user", "version": "0.5.1"}]}}), encoding="utf-8")
        r = self.run_get("claude", "--no-wheel")
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
        self.assertEqual(self.log(), [])

    def test_with_all_installs_fixindex_and_ponytail(self):
        self.fake_claude()
        r = self.run_get("claude", "--with", "all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any("royalskynet/fixindex" in l for l in self.log("git clone")))
        self.assertEqual(len(self.log("addon-install")), 1)  # fixindex's own install.sh ran
        self.assertIn("claude plugin marketplace add DietrichGebert/ponytail", self.log("claude"))
        self.assertIn("claude plugin install ponytail@ponytail", self.log("claude"))
        self.assertTrue((self.home / "notes" / "runbook" / "fixes").is_dir())

    def test_unknown_addon_touches_nothing(self):
        self.fake_claude()
        r = self.run_get("claude", "--with=fixindx")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.log(), [])

    def test_existing_wheel_command_is_left_alone(self):
        self.fake_claude()
        (self.home / ".claude" / "commands").mkdir(parents=True)
        (self.home / ".claude" / "commands" / "wheel.md").write_text("mine", encoding="utf-8")
        r = self.run_get("claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.home / ".claude" / "skills" / "wheel").exists())


if __name__ == "__main__":
    unittest.main()
