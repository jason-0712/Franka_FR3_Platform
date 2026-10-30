"""Patch reconstruction in disposable checkouts; no user worktree mutation."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class Deployment(unittest.TestCase):
    def run_command(self, *args, cwd):
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)

    def test_pinned_patch_reconstruction_idempotence_and_wrong_version(self):
        if not (ROOT/".git").exists():
            self.skipTest("Source snapshot has no Git metadata; patch reconstruction is tested in the original checkout")
        patches = sorted((ROOT/"patches/nested_repos").glob("*.patch"))
        self.assertTrue(patches, "Pinned control-description patch is missing")
        if any(not (ROOT/patch.stem.replace("__", "/")/".git").exists() for patch in patches):
            self.skipTest("Control submodules are absent; run git submodule update --init --recursive")
        with tempfile.TemporaryDirectory(prefix="franka platform relocated ") as directory:
            root = Path(directory)/"different user workspace"
            root.mkdir()
            self.assertEqual(self.run_command("git", "init", "-q", cwd=root).returncode, 0)
            (root/"scripts").mkdir()
            (root/"patches/nested_repos").mkdir(parents=True)
            script = root/"scripts/apply_nested_repo_patches.sh"
            shutil.copyfile(ROOT/"scripts/apply_nested_repo_patches.sh", script)
            patched_repos = []
            for patch in patches:
                relative = patch.stem.replace("__", "/")
                source = ROOT/relative
                destination = root/relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                cloned = self.run_command("git", "clone", "-q", "--shared", str(source), str(destination), cwd=root)
                self.assertEqual(cloned.returncode, 0, cloned.stderr)
                commit = self.run_command("git", "rev-parse", "HEAD", cwd=source).stdout.strip()
                self.assertEqual(self.run_command("git", "update-index", "--add", "--cacheinfo",
                    "160000,"+commit+","+relative, cwd=root).returncode, 0)
                shutil.copyfile(patch, root/"patches/nested_repos"/patch.name)
                patched_repos.append(destination)
            committed = self.run_command("git", "-c", "user.name=Offline Test", "-c", "user.email=offline@example.invalid",
                "commit", "-qm", "Pin disposable test checkouts", cwd=root)
            self.assertEqual(committed.returncode, 0, committed.stderr)
            check = self.run_command("bash", str(script), "--check", cwd=root)
            self.assertEqual(check.returncode, 0, check.stderr)
            for repository in patched_repos:
                self.assertEqual(self.run_command("git", "diff", "--exit-code", cwd=repository).returncode, 0)
            first = self.run_command("bash", str(script), cwd=root)
            self.assertEqual(first.returncode, 0, first.stderr)
            diffs = [self.run_command("git", "diff", "--binary", cwd=p).stdout for p in patched_repos]
            second = self.run_command("bash", str(script), cwd=root)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(diffs, [self.run_command("git", "diff", "--binary", cwd=p).stdout for p in patched_repos])
            self.assertIn("already applied", second.stdout)
            # A different commit must fail before applying or undoing any patch.
            changed = patched_repos[0]
            committed = self.run_command("git", "-c", "user.name=Offline Test", "-c", "user.email=offline@example.invalid",
                "commit", "--allow-empty", "-qm", "Unexpected version", cwd=changed)
            self.assertEqual(committed.returncode, 0, committed.stderr)
            wrong = self.run_command("bash", str(script), cwd=root)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn("expected pinned commit", wrong.stderr)


if __name__ == "__main__":
    unittest.main()
