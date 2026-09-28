#!/usr/bin/env python3
"""Isolated integration checks for install.sh; no Codex settings are touched."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("genie-execute", "genie-explain", "genie-humanizer", "genie-research")


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="genie install test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        shim = self.bin / "python3"
        shim.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "if sys.argv[1:3] == ['-c', 'import numpy']:\n"
            "    sys.exit(1 if os.getenv('GENIE_TEST_NO_NUMPY') else 0)\n"
            "if sys.argv[1:] and sys.argv[1].endswith('router/test_router.py'):\n"
            "    print('router self-check: PASS')\n"
            "    raise SystemExit(0)\n"
            "os.execv(os.environ['GENIE_TEST_REAL_PYTHON'], "
            "[os.environ['GENIE_TEST_REAL_PYTHON'], *sys.argv[1:]])\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)

    def make_repo(self, parent):
        repo = parent / "genie-harness"
        (repo / "router" / "model").mkdir(parents=True)
        (repo / "skills").mkdir()
        for name in SKILLS:
            (repo / "skills" / name).mkdir()
        shutil.copy2(ROOT / "install.sh", repo / "install.sh")
        shutil.copy2(ROOT / "AGENTS.md", repo / "AGENTS.md")
        (repo / "router" / "model" / "vocab.json").touch()
        return repo

    def run_install(self, repo, home, codex, *, no_numpy=False):
        env = os.environ.copy()
        env.update({
            "HOME": str(home),
            "CODEX_HOME": str(codex),
            "GENIE_TEST_REAL_PYTHON": sys.executable,
            "PATH": f"{self.bin}:{env['PATH']}",
        })
        if no_numpy:
            env["GENIE_TEST_NO_NUMPY"] = "1"
        else:
            env.pop("GENIE_TEST_NO_NUMPY", None)
        return subprocess.run(
            ["bash", str(repo / "install.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )

    def expected_hook(self, repo, matcher=None):
        command = " ".join((
            shlex.quote(sys.executable),
            shlex.quote(str(repo / "router" / "genie_router.py")),
        ))
        identity = {
            "event_name": "user_prompt_submit",
            "hooks": [{
                "type": "command",
                "command": command,
                "timeout": 5,
                "async": False,
            }],
        }
        if matcher is not None:
            identity["matcher"] = matcher
        digest = "sha256:" + hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return command, digest

    def test_pep668_failure_prints_usable_user_install_command(self):
        repo = self.make_repo(self.root / "pep668")
        home, codex = self.root / "home", self.root / "codex"
        home.mkdir()
        codex.mkdir()

        result = self.run_install(repo, home, codex, no_numpy=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "python3 -m pip install --user --break-system-packages numpy",
            result.stdout,
        )
        self.assertFalse((codex / "hooks.json").exists())

    def test_reinstall_preserves_backups_and_refreshes_moved_hook(self):
        repo_parent = self.root / "checkout with spaces"
        repo = self.make_repo(repo_parent)
        home, codex = self.root / "home", self.root / "codex"
        skill_root = home / ".agents" / "skills"
        skill_root.mkdir(parents=True)
        codex.mkdir()

        existing_skill = skill_root / "genie-explain"
        existing_skill.mkdir()
        (existing_skill / "user-file").write_text("keep me", encoding="utf-8")
        hooks = {
            "hooks": {"UserPromptSubmit": [{"hooks": [
                {"type": "command", "command": "python3 /tools/other.py", "timeout": 5},
                {
                    "type": "command",
                    "command": "python3 /old/genie-harness/router/genie_router.py",
                    "timeout": 5,
                },
            ]}]}
        }
        (codex / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
        (codex / "config.toml").write_text(
            f'[other]\nkeep = true\n\n'
            f'[hooks.state."{codex / "hooks.json"}:user_prompt_submit:0:0"]\n'
            'trusted_hash = "sha256:stale"\n',
            encoding="utf-8",
        )
        (codex / "AGENTS.md").write_text("original agents\n", encoding="utf-8")
        originals = {
            name: (codex / name).read_bytes()
            for name in ("hooks.json", "config.toml", "AGENTS.md")
        }

        first = self.run_install(repo, home, codex)
        self.assertEqual(first.returncode, 0, first.stdout)
        backup_skill = skill_root / "genie-explain.bak-genie"
        self.assertEqual((backup_skill / "user-file").read_text(), "keep me")
        self.assertTrue((skill_root / "genie-explain").is_symlink())

        repo_moved = self.root / "moved checkout with spaces" / "genie-harness"
        repo_moved.parent.mkdir()
        repo.rename(repo_moved)
        second = self.run_install(repo_moved, home, codex)
        self.assertEqual(second.returncode, 0, second.stdout)

        current = json.loads((codex / "hooks.json").read_text())
        registrations = current["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(registrations), 1)
        self.assertEqual(registrations[0]["hooks"][0]["command"], "python3 /tools/other.py")
        hook = next(
            hook
            for registration in registrations
            for hook in registration["hooks"]
            if "genie_router.py" in hook["command"]
        )
        command, digest = self.expected_hook(repo_moved)
        self.assertEqual(hook["command"], command)
        config = (codex / "config.toml").read_text()
        self.assertIn(digest, config)
        self.assertIn(f'{codex / "hooks.json"}:user_prompt_submit:0:1', config)
        for name in SKILLS:
            link = skill_root / name
            self.assertTrue(link.is_symlink(), name)
            self.assertTrue(
                os.path.realpath(link).startswith(os.path.realpath(repo_moved / "skills") + os.sep),
                f"{name}: real={os.path.realpath(link)} link={os.readlink(link)} expected={repo_moved / 'skills'}",
            )
        for name, contents in originals.items():
            self.assertEqual((codex / f"{name}.bak-genie").read_bytes(), contents, name)

    def test_existing_backup_collision_aborts_before_installing_any_skill(self):
        repo = self.make_repo(self.root / "collision")
        home, codex = self.root / "home", self.root / "codex"
        skill_root = home / ".agents" / "skills"
        (skill_root / "genie-humanizer").mkdir(parents=True)
        (skill_root / "genie-humanizer.bak-genie").write_text("older backup")
        codex.mkdir()

        result = self.run_install(repo, home, codex)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backup already exists", result.stdout)
        self.assertFalse((skill_root / "genie-execute").exists())
        self.assertTrue((skill_root / "genie-humanizer").is_dir())
        self.assertFalse((codex / "hooks.json").exists())

    def test_config_backup_collision_aborts_before_changing_hooks(self):
        repo = self.make_repo(self.root / "config-collision")
        home, codex = self.root / "home", self.root / "codex"
        home.mkdir()
        codex.mkdir()
        hooks = codex / "hooks.json"
        hooks.write_text('{"hooks": {}}\n', encoding="utf-8")
        original_hooks = hooks.read_bytes()
        (codex / "config.toml").write_text("[other]\nkeep = true\n", encoding="utf-8")
        (codex / "config.toml.bak-genie").write_text("older backup", encoding="utf-8")

        result = self.run_install(repo, home, codex)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backup already exists", result.stdout)
        self.assertEqual(hooks.read_bytes(), original_hooks)


if __name__ == "__main__":
    unittest.main()
