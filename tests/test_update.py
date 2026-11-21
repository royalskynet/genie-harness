#!/usr/bin/env python3
"""Real local Git repositories exercise rewritten-history updates safely."""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="genie update test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.origin = self.root / "origin"
        self.clone = self.root / "clone"
        self.git(self.root, "init", "-q", "-b", "main", str(self.origin))
        (self.origin / "install.sh").write_text("#!/bin/sh\necho installed\n")
        (self.origin / ".gitignore").write_text("ignored*\n")
        self.commit("old history")
        self.git(self.root, "clone", "-q", str(self.origin), str(self.clone))
        self.old_head = self.git(self.clone, "rev-parse", "HEAD")
        self.git(self.origin, "checkout", "-q", "--orphan", "rewritten")

    def git(self, repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=Update Test",
             "-c", "user.email=update@example.invalid", *args],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout.strip()

    def commit(self, message):
        self.git(self.origin, "add", "-f", ".")
        self.git(self.origin, "commit", "-qm", message)

    def rewrite(self, path):
        target = self.origin / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("upstream content\n")
        self.commit("rewritten history")
        self.git(self.origin, "branch", "-f", "main", "HEAD")

    def run_update(self):
        return subprocess.run(
            ["bash", str(ROOT / "update.sh"), str(self.clone)],
            capture_output=True, text=True, timeout=30,
        )

    def assert_collision(self, local, upstream):
        self.rewrite(upstream)
        target = self.clone / local
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("local content\n")
        result = self.run_update()
        self.assertEqual(target.read_text(), "local content\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("untracked files", result.stderr)
        self.assertIn(local, result.stderr)
        self.assertIn("Move or rename", result.stderr)
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), self.old_head)
        self.assertEqual(self.git(self.clone, "branch", "--list", "genie-before-update-*"), "")
        self.assertNotIn("installed", result.stdout)

    def test_untracked_collision(self):
        self.assert_collision("local file.txt", "local file.txt")

    def test_ignored_collision(self):
        self.assert_collision("ignored.txt", "ignored.txt")

    def test_local_file_blocks_upstream_directory(self):
        self.assert_collision("directory", "directory/upstream.txt")

    def test_local_directory_blocks_upstream_file(self):
        self.assert_collision("directory/local.txt", "directory")

    def test_noncolliding_files_survive(self):
        self.rewrite("new.txt")
        for name in ("local.txt", "ignored.txt"):
            (self.clone / name).write_text("keep me\n")
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("local.txt", "ignored.txt"):
            self.assertEqual((self.clone / name).read_text(), "keep me\n")
        self.assertEqual((self.clone / "new.txt").read_text(), "upstream content\n")
        self.assertIn("installed", result.stdout)
        backup = self.git(self.clone, "branch", "--list", "genie-before-update-*")
        self.assertEqual(self.git(self.clone, "rev-parse", backup), self.old_head)

    def test_no_untracked_files(self):
        self.rewrite("new.txt")
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("installed", result.stdout)


if __name__ == "__main__":
    unittest.main()
