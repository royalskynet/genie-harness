#!/usr/bin/env python3
"""get.sh modes with fake `claude`, `git` and HOME; nothing real is installed.
Default mode asks only for missing add-ons; --all installs missing ones and asks
before updating installed ones, skipping what is already latest."""
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
        (self.market / ".claude-plugin").mkdir()
        (self.market / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"plugins": [{"name": "genie-harness", "source": "./"}]}), encoding="utf-8")
        self.set_latest("0.6.0")
        (self.market / "router" / "safe_update.py").write_text(
            "import sys\n"
            f"open({str(self.calls)!r}, 'a').write('safe_update ' + ' '.join(sys.argv[1:]) + '\\n')\n",
            encoding="utf-8")
        (self.bin / "python3").symlink_to(sys.executable)
        # Fake git: clone makes a repo with the files get.sh uses; FAKE_BEHIND sets
        # how many commits a clone is behind its upstream.
        git = self.bin / "git"
        git.write_text(
            "#!/bin/sh\n"
            f'echo "git $*" >> "{self.calls}"\n'
            'case "$*" in *rev-list*) echo "${FAKE_BEHIND:-0}"; exit 0 ;; esac\n'
            'if [ "$1" = clone ]; then eval d=\\${$#}; mkdir -p "$d/.git" "$d/skills/wheel"; '
            'touch "$d/skills/wheel/SKILL.md"; '
            f'printf \'echo "addon-install $0" >> "{self.calls}"\\n\' > "$d/install.sh"; fi\n',
            encoding="utf-8")
        git.chmod(0o755)
        claude = self.bin / "claude"
        claude.write_text(f'#!/bin/sh\necho "claude $*" >> "{self.calls}"\n', encoding="utf-8")
        claude.chmod(0o755)

    def set_latest(self, version):
        (self.market / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": version}), encoding="utf-8")

    def install_genie(self, version):
        (self.plugins / "known_marketplaces.json").write_text(
            json.dumps({"genie-harness": {"installLocation": str(self.market)}}), encoding="utf-8")
        (self.plugins / "installed_plugins.json").write_text(
            json.dumps({"plugins": {KEY: [{"scope": "user", "version": version}]}}), encoding="utf-8")

    def clone(self, rel):
        d = self.home / rel
        (d / ".git").mkdir(parents=True)
        (d / "install.sh").write_text(f'echo "addon-install $0" >> "{self.calls}"\n', encoding="utf-8")

    def run_get(self, *args, answers=None, behind=0):
        env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_BEHIND": str(behind),
               "GENIE_TTY": "/nonexistent/tty"}
        if answers is not None:
            tty = self.home / "answers"
            tty.write_text("".join(a + "\n" for a in answers), encoding="utf-8")
            env["GENIE_TTY"] = str(tty)
        return subprocess.run(["bash", str(ROOT / "get.sh"), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def log(self, prefix=""):
        lines = self.calls.read_text(encoding="utf-8").splitlines() if self.calls.exists() else []
        return [l for l in lines if l.startswith(prefix)]

    def cloned(self, repo):
        return any(repo in l for l in self.log("git clone"))

    # --- default mode ---

    def test_default_asks_each_missing_addon(self):
        r = self.run_get("claude", answers=["y", "n", "y"])  # wheel yes, fixindex no, ponytail yes
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"claude plugin install {KEY}", self.log("claude"))
        self.assertTrue(self.cloned("royalskynet/wheel-it"))
        self.assertTrue((self.home / ".claude" / "skills" / "wheel").is_symlink())
        self.assertFalse(self.cloned("royalskynet/fixindex"))
        self.assertIn("fixindex skipped", r.stdout)
        self.assertIn("claude plugin install ponytail@ponytail", self.log("claude"))

    def test_default_without_terminal_installs_no_addon(self):
        r = self.run_get("claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log("git clone"), [])
        self.assertEqual(r.stdout.count("skipped (install later with --all)"), 3)

    def test_default_leaves_installed_addons_alone(self):
        self.clone("dev/wheel")
        r = self.run_get("claude", "--yes", behind=3)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(any(" pull" in l for l in self.log("git")))
        self.assertIn("wheel installed, update available", r.stdout)

    def test_default_updates_genie_without_asking(self):
        self.install_genie("0.5.3")
        r = self.run_get("claude", answers=["n", "n", "n"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"safe_update {KEY}", self.log("safe_update"))

    # --- full mode ---

    def test_all_installs_missing_without_asking(self):
        r = self.run_get("claude", "--all", answers=["n", "n", "n"])  # answers must not be read
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.cloned("royalskynet/wheel-it"))
        self.assertTrue(self.cloned("royalskynet/fixindex"))
        self.assertEqual(len(self.log("addon-install")), 1)  # fixindex's own install.sh ran
        self.assertIn("claude plugin install ponytail@ponytail", self.log("claude"))

    def test_all_skips_latest(self):
        self.install_genie("0.6.0")
        self.clone("dev/wheel")
        r = self.run_get("claude", "--all", answers=[], behind=0)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Genie (Claude Code) already latest", r.stdout)
        self.assertIn("wheel already latest", r.stdout)
        self.assertEqual(self.log("safe_update"), [])
        self.assertFalse(any(" pull" in l for l in self.log("git")))

    def test_all_asks_before_updating(self):
        self.install_genie("0.5.3")
        self.clone("dev/wheel")
        self.clone("dev/fixindex")
        # Genie: no; wheel: yes; fixindex: no; ponytail is missing -> installed, no question
        r = self.run_get("claude", "--all", answers=["n", "y", "n"], behind=2)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log("safe_update"), [])
        self.assertIn("Genie (Claude Code) update skipped", r.stdout)
        pulls = [l for l in self.log("git") if " pull" in l]
        self.assertTrue(any("dev/wheel pull" in l for l in pulls), pulls)
        self.assertFalse(any("dev/fixindex pull" in l for l in pulls), pulls)
        self.assertIn("fixindex update skipped", r.stdout)
        self.assertIn("claude plugin install ponytail@ponytail", self.log("claude"))

    def test_all_without_terminal_updates(self):
        self.install_genie("0.5.3")
        r = self.run_get("claude", "--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"safe_update {KEY}", self.log("safe_update"))

    # --- errors ---

    def test_no_host_fails_loud(self):
        os.unlink(self.bin / "claude")
        r = self.run_get()
        self.assertEqual(r.returncode, 1)
        self.assertIn("neither claude nor codex", r.stderr)

    def test_unknown_argument_touches_nothing(self):
        r = self.run_get("vscode")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.log(), [])

    def test_existing_wheel_command_is_left_alone(self):
        (self.home / ".claude" / "commands").mkdir(parents=True)
        (self.home / ".claude" / "commands" / "wheel.md").write_text("mine", encoding="utf-8")
        r = self.run_get("claude", "--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.cloned("royalskynet/wheel-it"))
        self.assertFalse((self.home / ".claude" / "skills" / "wheel").exists())


if __name__ == "__main__":
    unittest.main()
