import hashlib
import json
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

    def test_format_rows_groups(self):
        rows = impctl.format_rows([
            {"id": "loose", "stage": "pitch", "waiting_on": "user", "last_update": "2026-10-25"},
            {"id": "vendor", "group": "General / Sertis", "waiting_on": "user", "last_update": "2026-10-01"},
            {"id": "old", "group": "Postpaid / NBO main", "waiting_on": "user", "last_update": "2026-10-01"},
            {"id": "new", "group": "Postpaid / NBO main", "waiting_on": "user", "last_update": "2026-10-20"},
            {"id": "rl", "group": "Postpaid / NBO content", "waiting_on": "user", "last_update": "2026-10-02"},
            {"id": "adhoc", "group": "General", "waiting_on": "user", "last_update": "2026-10-03"},
        ])
        self.assertEqual([l.split()[0] if l.startswith("    ") else l.strip() for l in rows.splitlines()], [
            "General", "adhoc", "Sertis", "vendor",
            "Postpaid", "NBO content", "rl", "NBO main", "new", "old",
            "(ungrouped)", "loose",
        ])

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
        r = self.cli("ideas", "--projects")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("alive (company)", r.stdout)
        self.assertIn("x-idea", r.stdout)
        self.assertIn("(not found on this machine)", r.stdout)

    def test_cli_scan_registers(self):
        make_project(self.base / "projects", "one")
        make_project(self.base / "projects", "two")
        r = self.cli("ideas", "--projects", "--scan", str(self.base / "projects"))
        self.assertEqual(r.returncode, 0, r.stderr)
        names = sorted(p.name for p in impctl.load_registry())
        self.assertEqual(names, ["one", "two"])

    def test_cli_hides_done_and_filters(self):
        p = make_project(self.base, "proj")
        write(p / "ideas" / "a" / "STATUS.md", status("live-one", stage="pitch", group="Pricing / Vouchers"))
        write(p / "ideas" / "b" / "STATUS.md", status("old-one", "agents", stage="done"))
        write(p / "ideas" / "c" / "STATUS.md", status("parked", "agents", stage="shelved"))

        def ids(*flags):
            out = self.cli("ideas", *flags, cwd=p).stdout
            return sorted(i for i in ("live-one", "old-one", "parked") if i in out)

        self.assertEqual(ids(), ["live-one"])
        self.assertEqual(ids("--all"), ["live-one", "old-one", "parked"])
        self.assertEqual(ids("--done"), ["old-one"])
        write(p / "ideas" / "d" / "STATUS.md", status("watched", stage="monitor"))
        self.assertIn("watched", self.cli("ideas", cwd=p).stdout)
        self.assertEqual(self.cli("ideas", "--monitor", cwd=p).stdout.count("\n"), 1)
        self.assertEqual(ids("--done", "--shelved"), ["old-one", "parked"])
        self.assertEqual(ids("--stage", "pitch"), ["live-one"])
        self.assertEqual(ids("--all", "--waiting", "agents"), ["old-one", "parked"])
        self.assertEqual(ids("--group", "pricing"), ["live-one"])
        self.assertNotEqual(self.cli("ideas", "--stage", "nope", cwd=p).returncode, 0)

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



def git(p: Path, *args):
    return subprocess.run(["git", "-C", str(p), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, check=True).stdout


IDEA = ("---\nid: offer-timing\ntitle: Offer timing\nstage: pitch               # backlog | pitch\nwaiting_on: user\n"
        "gate: G1                   # G1 | G2\nnext_step: present the deck\nlast_update: 2026-01-01\n---\n\n"
        "# Offer timing\n\n## Decisions\n\n- 2026-01-01: start (user)\n\n## Feedback log\n\nSee [plan](rounds/r1/plan.md).\n")


class TestStage(unittest.TestCase):
    setUp, tearDown, cli = TestRegistryAndCli.setUp, TestRegistryAndCli.tearDown, TestRegistryAndCli.cli

    def snapshot(self, p: Path) -> dict:
        return {f: f.read_bytes() for f in p.rglob("*") if f.is_file() and ".git" not in f.parts}

    def mapped(self) -> Path:
        """A git project with `stage_folders: done=implemented`, an idea in ideas/pitch/Offer Timing and links to it."""
        p = make_project(self.base, "proj", "stage_folders: done=implemented\nlink_check: echo checked; exit 3\n")
        idea = p / "ideas" / "pitch" / "Offer Timing"
        write(idea / "STATUS.md", IDEA.replace("See [plan]", "[me](</ideas/pitch/Offer Timing/STATUS.md>) [plan]"))
        write(idea / "rounds" / "r1" / "plan.md", "plan")
        write(p / "INDEX.md", "- [a](/ideas/pitch/Offer%20Timing/STATUS.md)\n- [b](</ideas/pitch/Offer Timing/STATUS.md>)\n"
                              "- [c](/ideas/pitch/Offer Timing/)\n- [d](/ideas/pitch/Offer Timing)\n"
                              "- [e](/ideas/pitch/Offer Timing Two/x.md)\n- [f](ideas/pitch/Offer Timing/STATUS.md)\n"
                              "- [g](/ideas/pitch/Offer Timing#top)\n- [h](/ideas/pitch/Offer Timing \"title\")\n")
        write(p / "ideas" / "pitch" / "flat-note.md", status("flat-note", stage="pitch"))
        git(p, "init", "-q")
        git(p, "add", "-A")
        git(p, "commit", "-qm", "init")
        write(idea / "local" / "rows.csv", "untracked")
        return p

    def test_dry_run_writes_nothing_and_apply_edits_only_frontmatter(self):
        p = make_project(self.base, "proj")
        write(p / "ideas" / "offer-timing" / "STATUS.md", IDEA)
        before = self.snapshot(p)
        r = self.cli("stage", "offer", "done", cwd=p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("stage pitch -> done, gate G1 -> '', waiting_on user -> '', next_step present the deck -> done", r.stdout)
        self.assertIn("dry run", r.stdout)
        self.assertNotIn("move ", r.stdout)  # no stage_folders: imp's own layout never moves
        self.assertEqual(self.snapshot(p), before)
        r = self.cli("stage", "offer", "done", "--apply", cwd=p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("dry run", r.stdout)
        self.assertTrue(r.stdout.strip().splitlines()[-1].startswith("next (by hand): update the tracker"))
        today = impctl.date.today().isoformat()
        want = (IDEA.replace("stage: pitch      ", "stage: done       ").replace("waiting_on: user", "waiting_on:")
                .replace("gate: G1  ", "gate:     ").replace("next_step: present the deck", "next_step: done")
                .replace("last_update: 2026-01-01", f"last_update: {today}")
                .replace("start (user)\n", f"start (user)\n- {today}: done (from pitch) (user)\n"))
        self.assertEqual((p / "ideas" / "offer-timing" / "STATUS.md").read_text(), want)
        self.assertEqual(self.cli("stage", "offer", "done", cwd=p).returncode, 1)  # already done

    def test_shelved_needs_reason(self):
        p = make_project(self.base, "proj")
        write(p / "ideas" / "x" / "STATUS.md", status("x-idea", stage="pitch") + "\n## Decisions\n\n## Rounds\n")
        r = self.cli("stage", "x-idea", "shelved", "--apply", cwd=p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--reason", r.stderr)
        r = self.cli("stage", "x-idea", "shelved", "--reason", "no budget", "--apply", cwd=p)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (p / "ideas" / "x" / "STATUS.md").read_text()
        today = impctl.date.today().isoformat()
        self.assertIn(f"## Decisions\n\n- {today}: shelved (from pitch): no budget (user)\n\n## Rounds", text)
        fm = impctl.parse_frontmatter(text)
        self.assertEqual((fm["stage"], fm["next_step"], fm["waiting_on"]), ("shelved", "shelved: no budget", ""))
        self.assertIn("x-idea", self.cli("ideas", "--shelved", cwd=p).stdout)  # waiting_on kept as a key: still listed

    def test_on_hold_and_resume_without_move(self):
        p = make_project(self.base, "proj")
        write(p / "ideas" / "x" / "STATUS.md", status("x-idea", stage="experiment", round=2) + "\n## Decisions\n")
        write(p / "ideas" / "y" / "STATUS.md", status("y-idea", stage="pitch"))
        r = self.cli("stage", "x-idea", "resume", cwd=p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("to resume from", r.stderr)  # no `(from …)` line
        self.assertEqual(self.cli("stage", "x-idea", "on-hold", "--apply", cwd=p).returncode, 0)
        self.assertEqual(self.cli("ideas", "--on-hold", cwd=p).stdout.count("\n"), 1)
        self.assertIn("x-idea", self.cli("ideas", "--on-hold", cwd=p).stdout)
        self.assertIn("x-idea", self.cli("ideas", cwd=p).stdout)  # not hidden
        r = self.cli("stage", "x-idea", "resume", "--apply", cwd=p)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (p / "ideas" / "x" / "STATUS.md").read_text()
        self.assertEqual(impctl.parse_frontmatter(text)["stage"], "experiment")
        self.assertIn("resumed experiment (from on-hold) (user)", text)
        self.assertIn("nothing to resume", self.cli("stage", "x-idea", "resume", cwd=p).stderr)

    def test_unknown_and_ambiguous(self):
        p = make_project(self.base, "proj")
        write(p / "ideas" / "a" / "STATUS.md", status("offer-timing"))
        write(p / "ideas" / "b" / "STATUS.md", status("offer-mix"))
        self.assertEqual(self.cli("stage", "offer", "done", cwd=p).returncode, 2)
        self.assertEqual(self.cli("stage", "zzz", "done", cwd=p).returncode, 1)
        self.assertNotEqual(self.cli("stage", "offer-mix", "pitch", cwd=p).returncode, 0)  # not a stage target

    def test_move_rewrites_links_and_runs_check(self):
        p = self.mapped()
        before = self.snapshot(p)
        r = self.cli("stage", "offer", "done", cwd=p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("move ideas/pitch/Offer Timing -> ideas/implemented/Offer Timing", r.stdout)
        self.assertIn("link INDEX.md: 6", r.stdout)
        self.assertIn("run echo checked; exit 3", r.stdout)
        self.assertEqual(self.snapshot(p), before)
        r = self.cli("stage", "offer", "done", "--apply", cwd=p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("checked\nlink_check exit 3\nlink_check FAILED (exit 3)", r.stdout)
        new = p / "ideas" / "implemented" / "Offer Timing"
        self.assertFalse((p / "ideas" / "pitch" / "Offer Timing").exists())
        self.assertEqual((new / "local" / "rows.csv").read_text(), "untracked")
        self.assertEqual((p / "INDEX.md").read_text(),
                         "- [a](/ideas/implemented/Offer%20Timing/STATUS.md)\n- [b](</ideas/implemented/Offer Timing/STATUS.md>)\n"
                         "- [c](/ideas/implemented/Offer Timing/)\n- [d](/ideas/implemented/Offer Timing)\n"
                         "- [e](/ideas/pitch/Offer Timing Two/x.md)\n- [f](ideas/pitch/Offer Timing/STATUS.md)\n"
                         "- [g](/ideas/implemented/Offer Timing#top)\n- [h](/ideas/implemented/Offer Timing \"title\")\n")
        text = (new / "STATUS.md").read_text()
        self.assertIn("[me](</ideas/implemented/Offer Timing/STATUS.md>) [plan](rounds/r1/plan.md)", text)
        self.assertIn("done (from pitch; moved from ideas/pitch/Offer Timing) (user)", text)
        changed = git(p, "status", "--porcelain", "--untracked-files=all").replace('"', "").splitlines()
        self.assertEqual(sorted(changed), [  # git mv: staged renames; nothing else touched
            " M INDEX.md", "?? ideas/implemented/Offer Timing/local/rows.csv",
            "R  ideas/pitch/Offer Timing/rounds/r1/plan.md -> ideas/implemented/Offer Timing/rounds/r1/plan.md",
            "RM ideas/pitch/Offer Timing/STATUS.md -> ideas/implemented/Offer Timing/STATUS.md"])
        r = self.cli("stage", "offer", "resume", "--apply", cwd=p)  # back to pitch, folder and links too
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((p / "INDEX.md").read_text().count("/ideas/pitch/Offer"), 7)
        status_md = p / "ideas" / "pitch" / "Offer Timing" / "STATUS.md"
        self.assertEqual(impctl.parse_frontmatter(status_md.read_text())["stage"], "pitch")
        self.assertIn("resumed pitch (from done) (user)", status_md.read_text())

    def test_failed_move_writes_nothing(self):
        p = self.mapped()
        before = self.snapshot(p)
        lock = p / ".git" / "index.lock"
        lock.write_text("")  # git mv fails
        r = self.cli("stage", "offer", "done", "--apply", cwd=p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("imp: git", r.stderr)
        self.assertEqual(self.snapshot(p), before)
        lock.unlink()
        write(p / "ideas" / "implemented", "a file in the way")
        before = self.snapshot(p)
        r = self.cli("stage", "offer", "done", "--apply", cwd=p)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.startswith("imp: "), r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.snapshot(p), before)

    def test_reason_with_hash_and_no_git(self):
        p = make_project(self.base, "proj", "stage_folders: done=implemented\n")
        write(p / "ideas" / "x" / "STATUS.md", status("x-idea", stage="pitch"))
        before = self.snapshot(p)
        r = self.cli("stage", "x-idea", "shelved", "--reason", "see #12", "--apply", cwd=p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("without '#'", r.stderr)
        self.assertEqual(self.snapshot(p), before)
        r = self.cli("stage", "x-idea", "done", cwd=p)
        self.assertIn("links not rewritten:", r.stdout)

    def test_target_exists_and_flat_note(self):
        p = self.mapped()
        write(p / "ideas" / "implemented" / "Offer Timing" / "keep.md", "x")
        before = self.snapshot(p)
        r = self.cli("stage", "offer", "done", "--apply", cwd=p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("already exists", r.stderr)
        self.assertEqual(self.snapshot(p), before)
        r = self.cli("stage", "flat-note", "done", "--apply", cwd=p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no move: ideas/pitch/flat-note.md is a flat note", r.stdout)
        self.assertEqual(impctl.parse_frontmatter((p / "ideas" / "pitch" / "flat-note.md").read_text())["stage"], "done")


class TestCurrentAndCodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.act = self.base / "activity"
        self.act.mkdir()
        self._old = os.environ.get("IMP_ACTIVITY")
        os.environ["IMP_ACTIVITY"] = str(self.act)
        self.p = make_project(self.base, "proj")
        write(self.p / "ideas" / "fix" / "STATUS.md", status("bill-fix"))
        write(self.p / "ideas" / "research" / "inv-x.md", status("inv-x"))
        write(self.p / "ideas" / "research" / "inv-x-y.md", status("inv-x-y"))

    def tearDown(self):
        if self._old is None:
            os.environ.pop("IMP_ACTIVITY", None)
        else:
            os.environ["IMP_ACTIVITY"] = self._old
        self.tmp.cleanup()

    def session(self, sid, idea):
        write(self.act / f"{sid}.json", json.dumps({"cwd": str(self.p), "idea": str(self.p / idea)}))

    def ids(self, session=""):
        return [i["id"] for i in impctl.current_ideas(self.p, session)]

    def test_owner_folder_flat_note_and_side_files(self):
        ideas = impctl.find_ideas(self.p)
        own = lambda rel: (impctl.owner(self.p, ideas, str(self.p / rel)) or {}).get("id")
        self.assertEqual(own("ideas/fix/rounds/r1/plan.md"), "bill-fix")
        self.assertEqual(own("ideas/research/inv-x.md"), "inv-x")
        self.assertEqual(own("ideas/research/inv-x-plan.md"), "inv-x")
        self.assertEqual(own("ideas/research/inv-x-y-queries/01.py"), "inv-x-y")
        self.assertIsNone(own("ideas/research"))

    def test_current_from_session_link(self):
        self.session("s1", "ideas/fix/plan.md")
        self.session("s2", "ideas/research/inv-x-sizing.md")
        self.assertEqual(self.ids("s1"), ["bill-fix"])
        self.assertEqual(self.ids("s2"), ["inv-x"])

    def test_current_falls_back_to_uncommitted_files(self):
        subprocess.run(["git", "init", "-q", str(self.p)], check=True)
        self.session("s3", "ideas/research")  # an old hook linked the stage folder only
        self.assertEqual(sorted(self.ids("s3")), ["bill-fix", "inv-x", "inv-x-y"])
        subprocess.run(["git", "-C", str(self.p), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.p), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True)
        write(self.p / "ideas" / "research" / "inv-x-plan.md", "plan")
        self.assertEqual(self.ids("s3"), ["inv-x"])
        self.assertEqual(self.ids("missing"), ["inv-x"])

    def test_undefined_codes(self):
        slides = [("slide 1", "Sales by channel: MYA, WEB and NGCM (NGCM = campaign tool)"),
                  ("slide 2", "ARPU rose. LTCG: long-term control group. Round R66, G1")]
        self.assertEqual(impctl.undefined_codes(slides, "ARPU\naverage revenue"), [("slide 1", ["MYA", "WEB"])])

    def test_codes_reads_pptx(self):
        import zipfile
        deck = self.base / "d.pptx"
        with zipfile.ZipFile(deck, "w") as z:
            for n, text in [(2, "QW &amp; MYA"), (10, "fine")]:
                z.writestr(f"ppt/slides/slide{n}.xml", f"<p:sld><a:t>{text}</a:t></p:sld>")
        self.assertEqual(impctl.deck_slides(deck), [("slide 2", "QW & MYA"), ("slide 10", "fine")])


class TestBlockedBy(unittest.TestCase):
    def test_blocked_by_replaces_waiting(self):
        out = impctl.format_rows([{"id": "a", "waiting_on": "user", "blocked_by": "bill-fix"}])
        self.assertIn("blocked by: bill-fix", out)
        self.assertNotIn("waiting: user", out)


class TestNotionExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self._old = os.environ.get("IMP_REGISTRY")
        os.environ["IMP_REGISTRY"] = str(self.base / "projects.txt")
        self.p = make_project(self.base, "agents", "notion: on\n")
        impctl.register(self.p)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("IMP_REGISTRY", None)
        else:
            os.environ["IMP_REGISTRY"] = self._old
        self.tmp.cleanup()

    def idea(self, id_="a", body="", **kw):
        write(self.p / "ideas" / id_ / "STATUS.md", status(id_, **kw).replace("body\n", body))
        return self.p / "ideas" / id_

    def export(self):
        return impctl.notion_export(0)

    def tasks(self):
        return {t["task_id"]: t for t in self.export()["tasks"]}

    def test_project_fields(self):
        self.idea(title="T", group="Pricing / offers", stage="experiment", round="2", gate="G2",
                  blocked_by="b", last_update="2026-11-05", started="2026-10-01")
        (pr,) = self.export()["projects"]
        self.assertEqual((pr["imp_id"], pr["repo"], pr["name"], pr["group"], pr["domain"], pr["use_case"], pr["blocked_by"]),
                         ("agents/a", "agents", "T", "Pricing / offers", "Pricing", "offers", "agents/b"))
        self.assertEqual((pr["start"], pr["end"], pr["path"]), ("2026-10-01", "2026-11-05", "ideas/a/STATUS.md"))

    def test_ur_id_and_source(self):
        self.idea("a", ur=" UR-123 ")
        self.idea("b")
        p = {x["imp_id"]: x for x in self.export()["projects"]}
        self.assertEqual((p["agents/a"]["ur_id"], p["agents/a"]["source"]), ("UR-123", "MKT request"))
        self.assertEqual((p["agents/b"]["ur_id"], p["agents/b"]["source"]), ("", "Internal"))

    def test_start_falls_back_to_first_decision_and_end_to_monitor_until(self):
        self.idea(body="## Decisions\n\n- 2026-09-03: go (user)\n- 2026-09-09: more\n",
                  last_update="2026-11-05", monitor_until="2026-12-01")
        (pr,) = self.export()["projects"]
        self.assertEqual((pr["start"], pr["end"]), ("2026-09-03", "2026-12-01"))

    def test_due_is_end_when_set(self):
        self.idea(last_update="2026-11-05", monitor_until="2026-12-01", due="2026-11-20")
        (pr,) = self.export()["projects"]
        self.assertEqual(pr["end"], "2026-11-20")

    def test_flat_note_exported_db_local_and_non_ideas_skipped(self):
        fm = lambda i: f"---\nid: {i}\nwaiting_on: user\n---\n"
        write(self.p / "ideas" / "research" / "x.md", fm("x") + "## Open questions\n\n- Q1 why\n")
        write(self.p / "ideas" / "research" / "plain.md", "# no frontmatter\n\n## Open questions\n\n- Q9 no\n")
        write(self.p / "ideas" / "y" / "db" / "STATUS.md", fm("dbx") + "## Open questions\n\n- Q2 no\n")
        write(self.p / "ideas" / "y" / "local" / "z.md", fm("z"))
        e = self.export()
        self.assertEqual([p["imp_id"] for p in e["projects"]], ["agents/x"])
        self.assertEqual(sorted(self.tasks()), ["agents/x/q/Q1"])

    def test_round_tasks(self):
        d = self.idea(round="3", stage="experiment", body=(
            "## Rounds\n\n| Round | Hypothesis | Branch @ sha | Verdict | Learned | Result |\n|---|---|---|---|---|---|\n"
            "| 1 | from row | exp/a-r1 @ abc | worked | x | rounds/r1/result.md |\n"
            "| <n> | <h> | | | | |\n"))
        write(d / "rounds" / "r2" / "plan.md", "# P\n\n**Hypothesis (round 2):** from plan\n")
        t = self.tasks()
        self.assertEqual(sorted(t), ["agents/a/r1", "agents/a/r2", "agents/a/r3"])
        self.assertEqual((t["agents/a/r1"]["name"], t["agents/a/r1"]["status"], t["agents/a/r1"]["verdict"]),
                         ("R1: from row", "Done", "worked"))
        self.assertEqual((t["agents/a/r2"]["name"], t["agents/a/r2"]["status"]), ("R2: from plan", "Done"))
        self.assertEqual((t["agents/a/r3"]["name"], t["agents/a/r3"]["status"]), ("R3", "Open"))

    def test_round_done_when_stage_past_experiment(self):
        self.idea(round="1", stage="monitor")
        self.assertEqual(self.tasks()["agents/a/r1"]["status"], "Done")

    def test_question_keys(self):
        self.idea(body="## Open questions\n\n- D1: label  one\n-   r2: not a   label\n-\n- <question>\n"
                       "- A1: dup\n- A1: dup again\n\n## Artifacts\n\n- x\n")
        t = self.tasks()
        h = lambda s: hashlib.sha1(s.encode()).hexdigest()[:8]
        self.assertEqual(sorted(t), sorted([
            "agents/a/q/D1", f"agents/a/q/{h('r2: not a label')}",
            f"agents/a/q/{h('A1: dup')}", f"agents/a/q/{h('A1: dup again')}"]))
        self.assertEqual(t["agents/a/q/D1"]["name"], "D1: label one")

    def test_question_continuation_lines_join_the_bullet(self):
        self.idea(body="## Open questions\n\n- D1: long\n  wrapped\n  - sub\n- D2: next\n")
        t = self.tasks()
        self.assertEqual(sorted(t), ["agents/a/q/D1", "agents/a/q/D2"])
        self.assertEqual(t["agents/a/q/D1"]["name"], "D1: long wrapped - sub")

    def test_verdict_normalised_or_blank_with_warning(self):
        self.idea(round="4", stage="experiment", body=(
            "## Rounds\n\n| Round | Hypothesis | Branch @ sha | Verdict | Learned | Result |\n|---|---|---|---|---|---|\n"
            "| 1 | h | b | Worked, mostly | x | r |\n| 2 | h | b | No effect (flat) | x | r |\n"
            "| 3 | h | b | great | x | r |\n"))
        t = self.tasks()
        self.assertEqual([t[f"agents/a/r{n}"]["verdict"] for n in (1, 2, 3, 4)], ["", "no effect", "", ""])
        w = self.export()["warnings"]
        self.assertEqual(len(w), 2)  # r1 ("worked," keeps its comma) and r3
        self.assertIn("agents/a/r3", w[1])

    def test_opt_in_and_idless(self):
        other = make_project(self.base, "personal")  # no notion key
        impctl.register(other)
        write(other / "ideas" / "x" / "STATUS.md", status("x"))
        write(self.p / "ideas" / "n" / "STATUS.md", "---\nwaiting_on: user\n---\n")
        out = self.export()
        self.assertEqual(out["projects"], [])
        self.assertEqual(len(out["warnings"]), 1)

    def test_name_clash_stops(self):
        twin = make_project(self.base / "sub", "agents")
        impctl.register(twin)
        with self.assertRaises(ValueError) as cm:
            self.export()
        self.assertIn(str(twin), str(cm.exception))
        self.assertIn(str(self.p), str(cm.exception))

    def test_reads_only_status_and_plan(self):
        d = self.idea(round="1", body="## Open questions\n\n- D1: q\n")
        write(d / "db" / "schema.md", "---\nwaiting_on: user\nid: SECRET-DB\n---\nSECRET-DB\n")
        write(d / "local" / "rows.md", "---\nwaiting_on: user\nid: SECRET-LOCAL\n---\nSECRET-LOCAL\n")
        write(d / "notes.md", "SECRET-NOTES\n")
        write(d / "db" / "STATUS.md", "---\nid: SECRET-DBSTATUS\nwaiting_on: user\n---\nSECRET-DBSTATUS\n")
        out = json.dumps(self.export())
        for s in ["SECRET-DB", "SECRET-LOCAL", "SECRET-NOTES", "SECRET-DBSTATUS", "schema.md", "rows.md"]:
            self.assertNotIn(s, out)

    def test_cli_json(self):
        self.idea()
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "ideas", "--json"], capture_output=True, text=True,
                           env=dict(os.environ, IMP_REGISTRY=str(self.base / "projects.txt")), cwd=self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["projects"][0]["imp_id"], "agents/a")


if __name__ == "__main__":
    unittest.main()
