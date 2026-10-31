import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))

import no_push  # noqa: E402


def event(command, cwd):
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})


class TestNoPush(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "proj"
        (self.root / ".imp").mkdir(parents=True)
        (self.root / ".imp" / "project.md").write_text("---\npush_forbidden: projects/*/service-*\n---\n")
        self.clone = self.root / "projects" / "a" / "service-a"
        (self.clone / "src").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, command, cwd):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = no_push.main(event(command, cwd))
        return code, err.getvalue()

    def test_blocks_push_in_clone(self):
        code, err = self.run_hook("git push origin feature/x", self.clone)
        self.assertEqual(code, 2)
        self.assertIn("push/PR blocked", err)

    def test_blocks_push_in_clone_subfolder(self):
        self.assertEqual(self.run_hook("git push", self.clone / "src")[0], 2)

    def test_blocks_cd_and_dash_C(self):
        self.assertEqual(self.run_hook("cd projects/a/service-a && git push", self.root)[0], 2)
        self.assertEqual(self.run_hook("git -C projects/a/service-a push", self.root)[0], 2)

    def test_blocks_compound_forms(self):
        r = self.root
        for cmd in [
            "cd projects/a/service-a;git push",
            "cd projects/a/service-a&&git push",
            "(cd projects/a/service-a; git push)",
            "cd projects/a && cd service-a && git push",
            "pushd projects/a/service-a && git push",
            'bash -c "cd projects/a/service-a && git push"',
            "git --git-dir=projects/a/service-a/.git push",
            "git -c a=b -c c=d -C projects/a/service-a push",
            f"git -C {self.clone} push",
        ]:
            self.assertEqual(self.run_hook(cmd, r)[0], 2, cmd)

    def test_blocks_other_pr_writes(self):
        self.assertEqual(self.run_hook("gh pr comment 3 -b hi", self.clone)[0], 2)
        self.assertEqual(self.run_hook("gh api graphql -f query='mutation { createPullRequest(input:{}) { x } }'", self.clone)[0], 2)

    def test_blocks_gh_pr_and_api(self):
        self.assertEqual(self.run_hook("gh pr create --fill", self.clone)[0], 2)
        self.assertEqual(self.run_hook("gh api repos/o/r/pulls -f title=x", self.clone)[0], 2)

    def test_allows_non_push_in_clone(self):
        for cmd in ["git commit -m x", "git status", "gh pr view 3", "gh pr list", "gh pr diff 3", "echo push"]:
            self.assertEqual(self.run_hook(cmd, self.clone)[0], 0, cmd)

    def test_allows_push_outside_forbidden(self):
        self.assertEqual(self.run_hook("git push", self.root)[0], 0)

    def test_allows_without_project_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_hook("git push", d)[0], 0)

    def test_malformed_input_allows(self):
        self.assertEqual(no_push.main("not json"), 0)
        self.assertEqual(no_push.main('{"tool_name":"Read"}'), 0)

    def test_hooks_json_shape(self):
        h = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        entries = h["hooks"]["PreToolUse"]
        bash = [e for e in entries if e.get("matcher") == "Bash"]
        self.assertTrue(any("no_push.py" in hk["command"] for e in bash for hk in e["hooks"]))


if __name__ == "__main__":
    unittest.main()
