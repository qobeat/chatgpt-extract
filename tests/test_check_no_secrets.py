"""Integration tests for scripts/check_no_secrets.sh."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
CHECK = os.path.join(ROOT, "scripts", "check_no_secrets.sh")


class CheckNoSecretsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        os.makedirs(os.path.join(self.tmp, "scripts"), exist_ok=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.tmp,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=self.tmp,
            check=True,
        )
        shutil.copy2(CHECK, os.path.join(self.tmp, "scripts", "check_no_secrets.sh"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _run_check(self) -> int:
        r = subprocess.run(
            ["bash", "scripts/check_no_secrets.sh"],
            cwd=self.tmp,
            capture_output=True,
            text=True,
        )
        return r.returncode

    def test_passes_clean_published_readme(self):
        readme = os.path.join(self.tmp, "published", "README.md")
        os.makedirs(os.path.dirname(readme), exist_ok=True)
        with open(readme, "w", encoding="utf-8") as f:
            f.write("# Docs\n\nNever commit `source_conversation_ids`.\n")
        subprocess.run(["git", "add", "published/README.md"], cwd=self.tmp, check=True)
        self.assertEqual(self._run_check(), 0)

    def test_fails_on_internal_json_with_conversation_ids(self):
        bad = os.path.join(self.tmp, "reconstructed_projects.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write('{"projects":[{"source_conversation_ids":["x"]}]}\n')
        subprocess.run(["git", "add", "reconstructed_projects.json"], cwd=self.tmp, check=True)
        # path rule fires before content scan
        self.assertEqual(self._run_check(), 1)

    def test_fails_on_staged_json_with_conversation_ids(self):
        bad = os.path.join(self.tmp, "published", "projects.json")
        os.makedirs(os.path.dirname(bad), exist_ok=True)
        with open(bad, "w", encoding="utf-8") as f:
            f.write('{"projects":[{"source_conversation_ids":["x"]}]}\n')
        subprocess.run(["git", "add", "published/projects.json"], cwd=self.tmp, check=True)
        self.assertEqual(self._run_check(), 1)


if __name__ == "__main__":
    unittest.main()
