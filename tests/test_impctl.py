import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "impctl.py"
sys.path.insert(0, str(ROOT / "scripts"))

import impctl  # noqa: E402


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def status(id_, waiting="user", **kw):
    lines = [f"id: {id_}", f"waiting_on: {waiting}"] + [f"{k}: {v}" for k, v in kw.items()]
    return "---\n" + "\n".join(lines) + "\n---\nbody\n"


def make_project(base: Path, name: str, front: str = "") -> Path:
    p = base / name
    write(p / ".imp" / "project.md", f"---\nname: {name}\n{front}---\n")
    return p


class TestFrontmatter(unittest.TestCase):
    def test_parse_frontmatter_basic(self):
        self.assertEqual(
            impctl.parse_frontmatter("---\nid: offer-timing\nround: 2\n---\nbody"),
            {"id": "offer-timing", "round": "2"},
        )

    def test_parse_frontmatter_messy(self):
        text = (
            "---\n"
            'title: "Promo: timing"\n'
            "stage: experiment  # pitch | experiment\n"
            "  nested: no\n"
            "tags: [a, b]\n"
            "---\n"
        )
        fm = impctl.parse_frontmatter(text)
        self.assertEqual(fm["title"], "Promo: timing")
        self.assertEqual(fm["stage"], "experiment")
        self.assertEqual(fm["tags"], "[a, b]")
        self.assertNotIn("nested", fm)

    def test_parse_frontmatter_blank_with_comment(self):
        fm = impctl.parse_frontmatter("---\nname:      # blank = folder name\nround:\n---\n")
        self.assertEqual(fm, {"name": "", "round": ""})

    def test_parse_frontmatter_unclosed_keeps_keys(self):
        self.assertEqual(impctl.parse_frontmatter("---\nid: returns-dash\nwaiting_on: user\n"),
                         {"id": "returns-dash", "waiting_on": "user"})

    def test_parse_frontmatter_none(self):
        self.assertEqual(impctl.parse_frontmatter("no frontmatter"), {})


class TestIdeas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_ideas_skips_non_status_and_local(self):
        p = make_project(self.base, "proj")
        write(p / "ideas" / "a" / "STATUS.md", status("a"))
        write(p / "ideas" / "a" / "notes.md", "---\ntitle: notes\n---\n")
        write(p / "ideas" / "a" / "local" / "x.md", status("leak"))
        ideas = impctl.find_ideas(p)
        self.assertEqual([i["id"] for i in ideas], ["a"])
        self.assertEqual(ideas[0]["_path"], "ideas/a/STATUS.md")

    def test_find_ideas_custom_root(self):
        p = make_project(self.base, "proj", "ideas_root: work/ideas\n")
        write(p / "work" / "ideas" / "b" / "STATUS.md", status("b"))
        write(p / "ideas" / "c" / "STATUS.md", status("c"))
        self.assertEqual([i["id"] for i in impctl.find_ideas(p)], ["b"])

    def test_format_rows_missing_fields(self):
        rows = impctl.format_rows([
            {"id": "old", "stage": "pitch", "waiting_on": "marketing", "last_update": "2026-10-01"},
            {"id": "new", "stage": "experiment", "round": "2", "waiting_on": "user", "last_update": "2026-10-20"},
            {"id": "bare", "waiting_on": "agents"},
        ])
        lines = rows.splitlines()
        self.assertTrue(lines[0].startswith("new"))
        self.assertIn("experiment r2", lines[0])
        self.assertIn("waiting: user", lines[0])
        self.assertTrue(lines[1].startswith("old"))
        bare = [l for l in lines if l.startswith("bare")][0]
        self.assertIn("-", bare)

    def test_resolve_exact_substring_ambiguous_unknown(self):
        ideas = [{"id": "offer-timing"}, {"id": "offer-timing-v2"}, {"id": "price-rule-fix", "title": "Price Rule"}]
        self.assertEqual(impctl.resolve(ideas, "offer-timing")["id"], "offer-timing")
        self.assertEqual(impctl.resolve(ideas, "price")["id"], "price-rule-fix")
        self.assertEqual(impctl.resolve(ideas, "TIMING-V")["id"], "offer-timing-v2")
        with self.assertRaises(impctl.AmbiguousIdea) as cm:
            impctl.resolve(ideas, "offer")
        self.assertEqual(sorted(cm.exception.ids), ["offer-timing", "offer-timing-v2"])
        with self.assertRaises(impctl.UnknownIdea):
            impctl.resolve(ideas, "zzz")


class TestRegistryAndCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.reg = self.base / "cfg" / "projects.txt"
        self.env = dict(os.environ, IMP_REGISTRY=str(self.reg))
        self._old = os.environ.get("IMP_REGISTRY")
        os.environ["IMP_REGISTRY"] = str(self.reg)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("IMP_REGISTRY", None)
        else:
            os.environ["IMP_REGISTRY"] = self._old
        self.tmp.cleanup()

    def cli(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args],
            capture_output=True, text=True, env=self.env, cwd=cwd or self.base,
        )

    def test_registry_register_idempotent(self):
        p = make_project(self.base, "proj")
        self.assertTrue(impctl.register(p))
        self.assertFalse(impctl.register(p))
        self.assertEqual(impctl.load_registry(), [p.resolve()])

    def test_cli_all_missing_project(self):
        p = make_project(self.base, "alive", "kind: company\n")
        write(p / "ideas" / "x" / "STATUS.md", status("x-idea"))
        self.reg.parent.mkdir(parents=True)
        self.reg.write_text(f"{p.resolve()}\n/nonexistent/x\n")
        r = self.cli("ideas", "--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("alive (company)", r.stdout)
        self.assertIn("x-idea", r.stdout)
        self.assertIn("(not found on this machine)", r.stdout)

    def test_cli_scan_registers(self):
        make_project(self.base / "projects", "one")
        make_project(self.base / "projects", "two")
        r = self.cli("ideas", "--all", "--scan", str(self.base / "projects"))
        self.assertEqual(r.returncode, 0, r.stderr)
        names = sorted(p.name for p in impctl.load_registry())
        self.assertEqual(names, ["one", "two"])

    def test_cli_works_without_project_file(self):
        p = self.base / "plain"
        write(p / ".git" / "HEAD", "ref: refs/heads/main\n")
        write(p / "ideas" / "g" / "STATUS.md", status("gnn-vs-cf"))
        (p / "ideas" / "g" / "sub").mkdir()
        r = self.cli("ideas", cwd=p / "ideas" / "g" / "sub")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("gnn-vs-cf", r.stdout)
        self.assertEqual(self.cli("resolve", "gnn", cwd=p).returncode, 0)

    def test_cli_resolve_exit_codes(self):
        p = make_project(self.base, "proj")
        write(p / "ideas" / "a" / "STATUS.md", status("offer-timing"))
        write(p / "ideas" / "b" / "STATUS.md", status("offer-mix"))
        ok = self.cli("resolve", "timing", cwd=p)
        self.assertEqual((ok.returncode, ok.stdout.strip()), (0, "ideas/a/STATUS.md"))
        amb = self.cli("resolve", "offer", cwd=p)
        self.assertEqual(amb.returncode, 2)
        self.assertIn("offer-mix", amb.stderr)
        self.assertEqual(self.cli("resolve", "zzz", cwd=p).returncode, 1)


if __name__ == "__main__":
    unittest.main()
