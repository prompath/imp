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
        self.assertEqual((pr["imp_id"], pr["repo"], pr["name"], pr["domain"], pr["use_case"], pr["blocked_by"]),
                         ("agents/a", "agents", "T", "Pricing", "offers", "agents/b"))
        self.assertEqual((pr["start"], pr["end"], pr["path"]), ("2026-10-01", "2026-11-05", "ideas/a/STATUS.md"))

    def test_start_falls_back_to_first_decision_and_end_to_monitor_until(self):
        self.idea(body="## Decisions\n\n- 2026-09-03: go (user)\n- 2026-09-09: more\n",
                  last_update="2026-11-05", monitor_until="2026-12-01")
        (pr,) = self.export()["projects"]
        self.assertEqual((pr["start"], pr["end"]), ("2026-09-03", "2026-12-01"))

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
