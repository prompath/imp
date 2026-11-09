import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import impctl  # noqa: E402

NOW = datetime(2027, 1, 15, 9, 0).timestamp()
D = lambda n: (date(2027, 1, 15) + timedelta(days=n)).isoformat()  # noqa: E731


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def status(id_, body="", **kw):
    kw.setdefault("waiting_on", "agents")
    kw.setdefault("last_update", D(0))
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in dict(id=id_, **kw).items()) + "---\n" + body


class TestTasks(unittest.TestCase):
    def test_parse(self):
        t = impctl._tasks("- [ ] T1: Send deck (due 2027-01-20) (remind 2027-01-19 10:00)\n"
                          "- [x] T2: Book room (done 2027-01-14)\n"
                          "- [ ] T3: plain (see notes) here\n"
                          "- [ ] no number\n  - [X] T10: indented (remind 2027-01-15 15:00) (due x)\n")
        self.assertEqual([(x["n"], x["done"], x["text"], x["due"], x["remind"], x["done_on"]) for x in t], [
            (1, False, "Send deck", "2027-01-20", "2027-01-19 10:00", ""),
            (2, True, "Book room", "", "", "2027-01-14"),
            (3, False, "plain (see notes) here", "", "", ""),
            (10, True, "indented", "x", "2027-01-15 15:00", "")])

    def test_open_questions_helper(self):
        self.assertEqual(impctl._open_questions("## Open questions\n\n- D1: a\n  b\n- <q>\n-\n## Next\n- no\n"), ["D1: a b"])


class TestClassifyOverdue(unittest.TestCase):
    def test_overdue_before_stale(self):
        c = impctl.classify
        old = D(-30)
        self.assertEqual(c({"stage": "experiment", "due": D(-1), "last_update": old}, [], NOW), ("waiting", f"due {D(-1)}"))
        self.assertEqual(c({"stage": "pitch", "due": D(0), "last_update": D(0)}, [], NOW), ("idle", ""))
        self.assertEqual(c({"stage": "backlog", "due": D(-1)}, [], NOW), ("idle", "backlog"))
        self.assertEqual(c({"stage": "shelved", "due": D(-1)}, [], NOW), ("idle", "shelved"))
        self.assertEqual(c({"stage": "done", "due": D(-1)}, [], NOW), ("done", ""))
        self.assertEqual(c({"stage": "pitch", "due": "next week", "last_update": D(0)}, [], NOW), ("idle", ""))

    def test_banner_on_overdue_row(self):
        idea = {"stage": "experiment", "due": D(-2), "last_update": D(-2)}
        row = (*impctl.classify(idea, [], NOW), idea, [])
        self.assertEqual(impctl.banner_state([row], 0), {"mood": "waiting", "agents": 0, "waiting": 1, "gate": "you"})


class SecretaryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env = {"IMP_REGISTRY": str(self.base / "projects.txt"), "IMP_ACTIVITY": str(self.base / "act"),
                    "IMP_SECRETARY": str(self.base / "sec")}
        self._old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.act = self.base / "act"
        self.act.mkdir()
        self.on = self.project("team", "notion: on\n")
        self.off = self.project("solo")

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def project(self, name, front=""):
        p = self.base / name
        write(p / ".imp" / "project.md", f"---\nname: {name}\n{front}---\n")
        impctl.register(p)
        return p

    def idea(self, proj, id_, body="", **kw):
        write(proj / "ideas" / id_ / "STATUS.md", status(id_, body, **kw))


class TestAgenda(SecretaryCase):
    def fixtures(self):
        self.idea(self.on, "late", stage="experiment", due=D(-2),
                  body="## Tasks\n\n- [ ] T1: send deck (due 2027-01-10)\n- [ ] T2: soon (due 2027-01-17)\n"
                       "- [ ] T3: someday\n- [x] T4: shipped (done 2027-01-14)\n- [ ] T5: far (due 2027-03-01)\n")
        self.idea(self.on, "soon", stage="pitch", due=D(3))
        self.idea(self.on, "later", stage="pitch", due=D(20))
        self.idea(self.on, "check", stage="monitor", next_check=D(0), monitor_until=D(-1), due=D(-40))
        self.idea(self.on, "quiet", stage="monitor", next_check=D(5), monitor_until=D(30))
        self.idea(self.on, "gate", stage="pitch", waiting_on="user", gate="G1",
                  body="## Open questions\n\n- D1: which offer\n")
        self.idea(self.on, "nogate", stage="pitch", waiting_on="user")
        self.idea(self.on, "finished", stage="done", due=D(-5), body="## Tasks\n\n- [ ] T1: never listed\n")
        self.idea(self.on, "parked", stage="shelved", due=D(-5))
        self.idea(self.on, "bad", stage="pitch", due="next week", body="## Tasks\n\n- [ ] T1: x (remind tomorrow)\n")
        self.idea(self.off, "mine", stage="pitch", body="## Tasks\n\n- [ ] T1: local only (due 2027-01-15)\n")
        write(self.base / "sec" / "tasks.md", "# Tasks\n\n- [ ] T1: renew parking card (due 2027-01-12)\n"
                                              "- [ ] T2: loose (remind 2027-01-15 15:00)\n- [x] T3: gone\n")

    def refs(self, a):
        return {s: [(i["ref"], i["note"]) for i in items] for s, items in a["sections"].items()}

    def test_sections(self):
        self.fixtures()
        a = impctl.agenda(NOW)
        r = self.refs(a)
        self.assertEqual(sorted(r["overdue"]), [("secretary/T1", ""), ("team/late", "experiment"), ("team/late/T1", "")])
        self.assertEqual(sorted(r["due"]), [("solo/mine/T1", ""), ("team/late/T2", ""), ("team/soon", "pitch")])
        self.assertEqual(sorted(r["checks"]), [("team/check", f"check due {D(0)}"),
                                               ("team/check", f"monitor_until {D(-1)} reached")])
        self.assertEqual(r["gates"], [("team/gate", "G1 Plan")])
        self.assertEqual(a["sections"]["gates"][0]["questions"], ["D1: which offer"])
        self.assertEqual(sorted(r["tasks"]), [("secretary/T2", ""), ("team/bad/T1", ""), ("team/late/T3", ""),
                                              ("team/late/T5", "")])
        self.assertEqual(sorted(a["problems"]), ["team/bad/T1: remind 'tomorrow' is not YYYY-MM-DD HH:MM",
                                                 "team/bad: due 'next week' is not YYYY-MM-DD"])
        listed = {ref for items in r.values() for ref, _ in items}
        for gone in ("finished", "finished/T1", "parked", "later", "quiet", "nogate", "late/T4"):
            self.assertNotIn(f"team/{gone}", listed)
        self.assertNotIn("secretary/T3", listed)

    def test_keys(self):
        self.fixtures()
        items = {i["ref"]: i for items in impctl.agenda(NOW)["sections"].values() for i in items}
        self.assertEqual(items["team/late/T1"]["key"], "team/late/T1")
        self.assertEqual(items["solo/mine/T1"]["key"], "")  # project without notion: on stays local
        self.assertEqual(items["secretary/T2"]["key"], "secretary/T2")
        self.assertEqual(items["secretary/T2"]["remind"], "2027-01-15 15:00")
        self.assertEqual(items["team/late"]["key"], "")

    def test_new_reports_only_unseen(self):
        self.fixtures()
        first = impctl.agenda(NOW)
        self.assertTrue(first["sections"]["overdue"])
        again = impctl.agenda(NOW, new=True)
        self.assertEqual((sum(map(len, again["sections"].values())), again["problems"]), (0, []))
        self.assertEqual(impctl.format_agenda(again, new=True), "nothing new")
        with (self.base / "sec" / "tasks.md").open("a") as f:
            f.write("- [ ] T4: fresh (due 2027-01-15)\n")
        self.assertEqual(self.refs(impctl.agenda(NOW, new=True))["due"], [("secretary/T4", "")])
        # due soon one day, overdue the next: new again, and yesterday's seen-file is dropped
        tomorrow = NOW + 3 * 86400
        self.assertIn(("secretary/T4", ""), self.refs(impctl.agenda(tomorrow, new=True))["overdue"])
        self.assertEqual([p.name for p in (self.base / "sec").glob("seen-*")], [f"seen-{D(3)}.txt"])

    def test_text_output(self):
        self.fixtures()
        text = impctl.format_agenda(impctl.agenda(NOW))
        self.assertIn("Overdue\n", text)
        self.assertIn("  team/gate  G1 Plan\n    ? D1: which offer", text)
        self.assertIn("  secretary/T2  loose  remind 2027-01-15 15:00", text)
        self.assertTrue(text.endswith("Problems\n  team/bad: due 'next week' is not YYYY-MM-DD\n"
                                      "  team/bad/T1: remind 'tomorrow' is not YYYY-MM-DD HH:MM"))

    def test_never_loads_sessions(self):
        old = self.act / "old.json"
        old.write_text(json.dumps({"state": "ended", "last_seen": NOW - 90000}))
        with mock.patch.object(impctl, "load_sessions", side_effect=AssertionError("load_sessions called")):
            impctl.agenda(NOW)
            impctl.journal(NOW)
        self.assertTrue(old.exists())

    def test_cli_json(self):
        self.fixtures()
        out = impctl.subprocess.run([sys.executable, str(ROOT / "scripts" / "impctl.py"), "agenda", "--json"],
                                    capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(out.returncode, 0, out.stderr)
        a = json.loads(out.stdout)
        self.assertEqual(set(a), {"today", "sections", "problems"})
        self.assertTrue(all("key" in i for items in a["sections"].values() for i in items))


class TestJournal(SecretaryCase):
    def test_touched_ideas(self):
        self.idea(self.on, "a")
        self.idea(self.on, "b")
        self.idea(self.off, "c")
        ideas = lambda p, i: str((p / "ideas" / i / "plan.md").resolve())  # noqa: E731
        sessions = {"s1": (ideas(self.on, "a"), NOW - 3600), "s2": (ideas(self.off, "c"), NOW - 60),
                    "s3": (ideas(self.on, "a"), NOW - 600), "s4": (ideas(self.on, "b"), NOW - 12 * 3600),
                    "s5": (ideas(self.on, "b"), NOW - 2 * 86400), "s6": ("/elsewhere/x.md", NOW)}
        for sid, (idea, seen) in sessions.items():
            (self.act / f"{sid}.json").write_text(json.dumps({"idea": idea, "last_seen": seen, "state": "ended"}))
        hm = lambda t: time.strftime("%H:%M", time.localtime(t))  # noqa: E731
        self.assertEqual(impctl.journal(NOW), [(hm(NOW - 60), "solo/c"), (hm(NOW - 600), "team/a"),
                                               (hm(NOW - 12 * 3600), "team/b")])
        self.assertEqual([r for _, r in impctl.journal(NOW, today_only=True)], ["solo/c", "team/a"])
        self.assertTrue((self.act / "s5.json").exists())


if __name__ == "__main__":
    unittest.main()
