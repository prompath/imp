import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "hooks"))

import activity  # noqa: E402
import impctl  # noqa: E402

NOW = 1_800_000_000.0  # 2027-01-15
TODAY = "2027-01-15"
IDEAS = "/p/ideas"


def ev(name, **kw):
    return dict({"hook_event_name": name, "session_id": "s1", "cwd": "/p"}, **kw)


def run(*events, state=None):
    s = state or {"ideas_dir": IDEAS}
    for e in events:
        s = activity.reduce(s, e, NOW)
    return s


class TestReducer(unittest.TestCase):
    def test_states(self):
        self.assertEqual(run(ev("SessionStart"))["state"], "working")
        perm = ev("Notification", notification_type="permission_prompt", message="Claude needs your permission")
        self.assertEqual(run(ev("SessionStart"), perm)["state"], "needs_permission")
        self.assertEqual(run(perm, ev("PostToolUse", tool_name="Bash"))["state"], "working")
        self.assertEqual(run(ev("Notification", notification_type="idle_prompt"))["state"], "waiting_reply")
        self.assertEqual(run(ev("Notification", notification_type="auth_success"))["state"], "working")
        self.assertEqual(run(ev("UserPromptSubmit"), ev("Stop"))["state"], "waiting_reply")
        self.assertEqual(run(ev("UserPromptSubmit"), ev("SessionEnd"))["state"], "ended")
        self.assertEqual(run(ev("SessionStart"))["last_seen"], NOW)

    def test_stop_inside_subagent_or_with_background_work_is_ignored(self):
        self.assertEqual(run(ev("UserPromptSubmit"), ev("Stop", agent_id="a1"))["state"], "working")
        self.assertEqual(run(ev("UserPromptSubmit"), ev("Stop", background_tasks=[{"id": "t"}]))["state"], "working")

    def test_agents(self):
        s = run(ev("SubagentStart", agent_id="a1", agent_type="imp:builder"),
                ev("PreToolUse", tool_name="Read", agent_id="a2", agent_type="imp:reviewer", tool_input={}))
        self.assertEqual(s["agents"], {"a1": "imp:builder", "a2": "imp:reviewer"})
        s = run(ev("SubagentStop", agent_id="a1", agent_type="imp:builder"), ev("SubagentStop", agent_id="zz"), state=s)
        self.assertEqual(s["agents"], {"a2": "imp:reviewer"})

    def test_idea_from_paths_and_briefs(self):
        read = ev("PreToolUse", tool_name="Read", tool_input={"file_path": IDEAS + "/offer-timing/STATUS.md"})
        self.assertEqual(run(read)["idea"], IDEAS + "/offer-timing/STATUS.md")
        bash = ev("PreToolUse", tool_name="Bash", tool_input={"command": "cat ideas/returns/plan.md"})
        self.assertEqual(run(bash)["idea"], IDEAS + "/returns/plan.md")
        spaced = ev("PreToolUse", tool_name="Read", tool_input={"file_path": IDEAS + "/pitch/Big Idea/plan.md"})
        self.assertEqual(run(spaced)["idea"], IDEAS + "/pitch/Big Idea/plan.md")
        quoted = ev("PreToolUse", tool_name="Bash", tool_input={"command": 'cat "ideas/pitch/Big Idea/plan.md" | wc'})
        self.assertEqual(run(quoted)["idea"], IDEAS + "/pitch/Big Idea/plan.md")
        other = ev("PreToolUse", tool_name="Bash", tool_input={"command": "cat myideas/x/plan.md ideas/local/y"})
        self.assertNotIn("idea", run(other))
        brief = ev("PreToolUse", tool_name="Agent", tool_input={"prompt": "# Brief: builder for task-dashboard\n\n**Goal:** x"})
        self.assertEqual(run(brief)["idea"], IDEAS + "/task-dashboard")
        self.assertNotIn("idea", run(read, state={"ideas_dir": ""}))

    def test_brief_goal_and_latest_action(self):
        brief = ev("PreToolUse", tool_name="Agent", tool_input={
            "subagent_type": "imp:reviewer", "prompt": "# Brief: reviewer for x\n\n**Goal:** Check the plan. Then more.\n"})
        start = ev("SubagentStart", agent_id="a1", agent_type="imp:reviewer")
        read = ev("PreToolUse", agent_id="a1", agent_type="imp:reviewer", tool_name="Read",
                  tool_input={"file_path": "/secret/dir/plan.md"})
        s = run(brief, start, read)
        self.assertEqual(s["work"]["a1"], {"goal": "Check the plan", "act": "reading plan.md", "at": NOW})
        self.assertEqual(s["briefs"], [])
        bash = ev("PreToolUse", agent_id="a1", agent_type="imp:reviewer", tool_name="Bash",
                  tool_input={"command": "pytest /secret", "description": "Run the tests"})
        self.assertEqual(run(bash, state=s)["work"]["a1"]["act"], "running: run the tests")
        self.assertNotIn("a1", run(ev("SubagentStop", agent_id="a1"), state=s)["work"])
        other = run(ev("SubagentStart", agent_id="a2", agent_type="imp:builder"), state=run(brief))
        self.assertEqual(other["work"]["a2"], {"goal": ""})  # a brief goes only to its own agent type

    def test_says(self):
        work = {"goal": "Check the plan", "act": "reading plan.md", "at": NOW - 20}
        self.assertEqual(impctl.agent_says("reviewer", "on x", work, NOW),
                         "I'm the reviewer on x: check the plan. Right now I'm reading plan.md (20s ago).")
        self.assertEqual(impctl.agent_says("builder", "in p", {}, NOW), "I'm the builder in p. I'm just getting started.")
        idea = {"id": "x", "stage": "experiment", "round": 1, "waiting_on": "user", "next_step": "Run the probe."}
        self.assertEqual(impctl.lead_says(idea, "wait", "G1 Plan"),
                         "I'm running x, experiment round 1, and waiting for you at G1 Plan. Next: Run the probe.")
        self.assertEqual(impctl.lead_says({"id": "y"}, "work", ""), "I'm running y, no stage, and my agents are at work.")
        self.assertEqual(impctl.lead_says({"id": "z", "waiting_on": "-"}, "idle", ""), "I'm running z, no stage, and waiting on nobody.")

    def test_subagent_cwd_keeps_session_cwd(self):
        sub = ev("PreToolUse", tool_name="Read", agent_id="a1", agent_type="imp:builder", cwd="/p/ideas/x", tool_input={})
        bash = ev("PreToolUse", tool_name="Bash", tool_input={"command": "cat ideas/returns/plan.md"})
        del bash["cwd"]
        s = run(ev("SessionStart"), sub)
        self.assertEqual(s["cwd"], "/p")
        self.assertEqual(run(bash, state=s)["idea"], IDEAS + "/returns/plan.md")

    def test_subagent_reads_do_not_relink_the_session(self):
        read = lambda **kw: ev("PreToolUse", tool_name="Read", tool_input={"file_path": IDEAS + "/other/plan.md"}, **kw)
        main = run(ev("SessionStart"), ev("PreToolUse", tool_name="Read", tool_input={"file_path": IDEAS + "/mine/plan.md"}))
        s = run(read(agent_id="a1", agent_type="imp:tech-researcher"), state=main)
        self.assertEqual((s["idea"], s["agents"]), (IDEAS + "/mine/plan.md", {"a1": "imp:tech-researcher"}))
        self.assertEqual(run(read(), state=main)["idea"], IDEAS + "/other/plan.md")  # the main session still relinks

    def test_registered_for_every_event(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        for name in ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart",
                     "SubagentStop", "Notification", "Stop", "SessionEnd"]:
            self.assertTrue(any("activity.py" in h["command"] for e in hooks[name] for h in e["hooks"]), name)

    def test_hook_commands_exit_0_when_script_missing(self):
        import subprocess
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        cmds = {h["command"] for evs in hooks.values() for e in evs for h in e["hooks"]}
        with tempfile.TemporaryDirectory() as empty:
            env = dict(os.environ, CLAUDE_PLUGIN_ROOT=empty)
            for cmd in cmds:
                r = subprocess.run(["sh", "-c", cmd], input="{}", capture_output=True, text=True, env=env)
                self.assertEqual((r.returncode, r.stdout), (0, ""), cmd)

    def test_changes_appended_only_on_state_change(self):
        s = activity.reduce({"ideas_dir": IDEAS}, ev("SessionStart"), 1)
        s = activity.reduce(s, ev("PreToolUse", tool_name="Read", tool_input={}), 2)
        s = activity.reduce(s, ev("Stop"), 3)
        self.assertEqual(s["changes"], [[1, "working"], [3, "waiting_reply"]])
        for t in range(100):
            s = activity.reduce(s, ev("Stop" if t % 2 else "UserPromptSubmit"), 10 + t)
        self.assertEqual(len(s["changes"]), 50)
        self.assertEqual(s["changes"][-1], [109, "waiting_reply"])

    def test_main_writes_and_never_fails(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["IMP_ACTIVITY"] = d
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(activity.main(json.dumps(ev("SessionStart", cwd=d))), 0)
                    self.assertEqual(activity.main("not json"), 0)
                    self.assertEqual(activity.main(json.dumps(ev("Stop", session_id="../x"))), 0)
                self.assertEqual(out.getvalue(), "")
                s = json.loads((Path(d) / "s1.json").read_text())
                self.assertEqual((s["state"], s["ideas_dir"]), ("working", ""))
                self.assertEqual(sorted(os.listdir(d)), ["s1.json"])
            finally:
                del os.environ["IMP_ACTIVITY"]


def h8(text):
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def idea(**kw):
    return dict({"id": "x", "stage": "experiment", "waiting_on": "agents", "last_update": TODAY}, **kw)


def sess(state, age=0, **agents):
    return {"state": state, "last_seen": NOW - age, "agents": agents}


class TestClassify(unittest.TestCase):
    def test_groups(self):
        c = impctl.classify
        self.assertEqual(c(idea(), [sess("needs_permission")], NOW), ("waiting", "permission prompt"))
        self.assertEqual(c(idea(gate="G2"), [sess("waiting_reply")], NOW), ("waiting", "G2 Ready to push"))
        self.assertEqual(c(idea(), [sess("working", a="imp:builder", b="reviewer")], NOW),
                         ("progress", "builder, reviewer"))
        self.assertEqual(c(idea(waiting_on="user", gate="G1"), [], NOW), ("waiting", "G1 Plan"))
        self.assertEqual(c(idea(), [], NOW), ("idle", ""))
        self.assertEqual(c(idea(stage="done"), [sess("working")], NOW), ("done", ""))

    def test_dead_sessions_and_staleness(self):
        c = impctl.classify
        self.assertEqual(c(idea(), [sess("working", age=601)], NOW)[0], "idle")
        self.assertEqual(c(idea(), [sess("ended")], NOW)[0], "idle")
        self.assertEqual(c(idea(stage="backlog", waiting_on="user"), [], NOW), ("idle", "backlog"))
        self.assertEqual(c(idea(waiting_on="user", last_update="2027-01-08"), [], NOW), ("idle", "7d without update"))
        self.assertEqual(c(idea(waiting_on="user", last_update="2027-01-09"), [], NOW)[0], "waiting")
        self.assertEqual(c(idea(stage="shelved"), [sess("working")], NOW)[0], "progress")

    def test_on_hold_is_idle_never_overdue(self):
        c = impctl.classify
        self.assertEqual(c(idea(stage="on-hold", waiting_on="user", due="2027-01-01", last_update="2026-01-01"), [], NOW),
                         ("idle", "on-hold"))

    def test_monitor(self):
        c = impctl.classify
        old = "2026-12-01"  # long before TODAY: a monitored idea is never stale
        due = idea(stage="monitor", next_check=TODAY, monitor_until="2027-02-01", last_update=old)
        self.assertEqual(c(due, [], NOW), ("waiting", "monitoring check due"))
        later = dict(due, next_check="2027-01-20")
        self.assertEqual(c(later, [], NOW), ("idle", "monitoring until 2027-02-01"))
        self.assertEqual(c(later, [sess("working")], NOW)[0], "progress")


HOST = "127.0.0.1:8765"


class TestDashboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = {"IMP_REGISTRY": str(base / "projects.txt"), "IMP_ACTIVITY": str(base / "act")}
        os.environ.update(self.env)
        p = base / "proj"
        (p / ".imp").mkdir(parents=True)
        (p / ".imp" / "project.md").write_text("---\nname: proj\n---\n")
        for id_, extra in [("evil", "title: <script>alert(1)</script>\nnext_step: a & b\n"), ("old", "stage: done\n")]:
            (p / "ideas" / id_).mkdir(parents=True)
            (p / "ideas" / id_ / "STATUS.md").write_text(
                f"---\nid: {id_}\nwaiting_on: agents\nlast_update: {TODAY}\n{extra}---\n")
        impctl.register(p)
        act = base / "act"
        act.mkdir()
        (act / "live.json").write_text(json.dumps(
            {"idea": str(p.resolve() / "ideas" / "evil"), "state": "working", "last_seen": NOW, "agents": {"a": "imp:builder"}}))
        (act / "gone.json").write_text(json.dumps({"state": "ended", "last_seen": NOW - 90000}))
        self.act = act

    def tearDown(self):
        for k in self.env:
            del os.environ[k]
        self.tmp.cleanup()

    def test_render(self):
        rows = impctl.dashboard_rows(NOW)
        self.assertFalse((self.act / "gone.json").exists())
        page = impctl.render(rows, False, NOW)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>alert", page)
        self.assertIn("a &amp; b", page)
        self.assertIn("In progress (1)", page)
        self.assertIn("<td>builder</td>", page)
        self.assertIn('<noscript><meta http-equiv="refresh" content="5"></noscript>', page)
        self.assertIn("fetch(location.href", page)
        self.assertNotIn("Done (", page)
        done = impctl.render(rows, True, NOW)
        self.assertIn("Done (1)", done)
        self.assertIn('value="1" checked', done)

    def test_flat_notes_link_only_their_own_session(self):
        p = Path(self.tmp.name).resolve() / "proj" / "ideas"
        (p / "research").mkdir()
        for id_ in ("a", "b"):
            (p / "research" / f"{id_}.md").write_text(f"---\nid: {id_}\nwaiting_on: user\nlast_update: {TODAY}\n---\n")
        (self.act / "flat.json").write_text(json.dumps(
            {"idea": str(p / "research" / "a.md"), "state": "working", "last_seen": NOW, "agents": {"r": "imp:reviewer"}}))
        (self.act / "brief.json").write_text(json.dumps(
            {"idea": str(p / "b"), "state": "working", "last_seen": NOW, "agents": {}}))
        rows = {r[2]["id"]: r[3] for r in impctl.dashboard_rows(NOW)}
        self.assertEqual([s["_sid"] for s in rows["a"]], ["flat"])
        self.assertEqual([s["_sid"] for s in rows["b"]], ["brief"])  # a brief links by id
        self.assertEqual([s["_sid"] for s in rows["evil"]], ["live"])  # a folder idea still matches by prefix

    def get(self, path, host=HOST):
        return impctl.route(path, host, 8765)

    def test_api_rooms_shape_headers_and_no_paths(self):
        with mock.patch.object(impctl.time, "time", return_value=NOW):  # route() reads the clock
            status, headers, body = self.get("/api/rooms")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        data = json.loads(body)
        self.assertEqual(set(data), {"ts", "characters"})
        keys = {"id", "kind", "role", "room", "activity", "project", "idea", "title", "note", "live", "says"}
        self.assertEqual([(c["id"], c["room"], c["activity"], c["role"]) for c in data["characters"]],
                         [("proj/evil", "office", "work", "chief"), ("proj/evil#" + h8("a"), "office", "work", "builder")])
        self.assertTrue(all(set(c) == keys for c in data["characters"]))
        self.assertNotIn(self.tmp.name, body.decode())
        self.assertNotIn(os.path.realpath(self.tmp.name), body.decode())

    def test_pages(self):
        status, headers, body = self.get("/rooms?demo=1")
        self.assertEqual((status, body), (200, (ROOT / "scripts" / "rooms.html").read_bytes()))
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn(b"imp ideas", self.get("/?done=1")[2])
        self.assertIn(b'<a href="/rooms">Rooms</a>', self.get("/")[2])

    def test_unknown_paths_and_traversal_are_404(self):
        for path in ["/x", "/rooms/", "/rooms.html", "/api", "/api/rooms/x", "/scripts/impctl.py", "/rooms/../impctl.py",
                     "/../README.md", "/%2e%2e/README.md", "/rooms%2f..%2fimpctl.py", "//etc/passwd", "/rooms\\..\\x"]:
            self.assertEqual(self.get(path)[0], 404, path)

    def test_host_allow_list_covers_every_path(self):
        for path in ["/", "/rooms", "/api/rooms", "/x"]:
            for host in ["evil.example", "evil.example:8765", "127.0.0.1", "127.0.0.1:80", "localhost", "", "[::1]:8765",
                         "127.0.0.1:8765.evil.example", "127.0.0.1:8765, evil"]:
                self.assertEqual(self.get(path, host)[0], 403, (path, host))
            self.assertEqual(self.get(path, "localhost:8765")[0], 404 if path == "/x" else 200, path)


def row(i, *mine, **kw):
    i = dict(idea(**kw), project="p", **i)
    return (impctl.classify(i, list(mine), NOW)[0], "", i, list(mine))


def rooms(rows, sessions=()):
    out = impctl.rooms_state(rows, list(sessions), NOW)["characters"]
    return {c["id"]: (c["room"], c["activity"], c["note"]) for c in out}


class TestRooms(unittest.TestCase):
    """The room table of the plan, row by row; the first matching row wins."""

    def test_1_done_and_shelved_are_hidden(self):
        w = sess("working", a="imp:builder")
        rows = [row({"id": "d"}, w, stage="done"), row({"id": "s"}, w, stage="shelved"), row({"id": "n"}, stage="done")]
        self.assertEqual(rooms(rows, [w]), {})  # linked sessions of hidden ideas don't turn up as unlinked

    def test_2_backlog_follows_the_other_rows(self):  # r3: the server sends nobody to the pool; the page does, by ticks
        rows = [row({"id": "a"}, stage="backlog"), row({"id": "b"}, sess("needs_permission"), stage="backlog"),
                row({"id": "c"}, sess("working"), stage="backlog")]
        self.assertEqual(rooms(rows), {"p/a": ("lounge", "idle", ""), "p/b": ("lounge", "wait", "permission"),
                                       "p/c": ("office", "work", "")})

    def test_live_flag(self):
        lone = dict(sess("waiting_reply"), cwd="/x/y")
        rows = [row({"id": "on"}, sess("working", a="imp:builder")), row({"id": "gate"}, gate="G1"),
                row({"id": "old"}, sess("working", age=601))]
        got = {c["id"]: c["live"] for c in impctl.rooms_state(rows, [lone], NOW)["characters"]}
        self.assertEqual(got, {"p/on": True, f"p/on#{h8('a')}": True, "p/gate": False, "p/old": False, "s0": True})

    def test_3_permission_and_gates_go_to_the_kitchen(self):
        rows = [row({"id": "perm"}, sess("needs_permission")),
                row({"id": "gate"}, sess("waiting_reply"), gate="G2"),
                row({"id": "user"}, waiting_on="user", gate="G1"),
                row({"id": "user2"}, sess("waiting_reply"), waiting_on="user"),
                row({"id": "busy"}, sess("working"), gate="G2", stage="ship")]
        self.assertEqual(rooms(rows), {
            "p/perm": ("lounge", "wait", "permission"), "p/gate": ("lounge", "wait", "G2 Ready to push"),
            "p/user": ("lounge", "wait", "G1 Plan"), "p/user2": ("lounge", "wait", ""),
            "p/busy": ("workshop", "work", "")})  # live work keeps the character in its room

    def test_4_stage_picks_the_room_and_a_plain_reply_stays(self):
        rows = [row({"id": st}, sess("working"), stage=st) for st in ("pitch", "experiment", "ship", "document")]
        rows.append(row({"id": "chat"}, sess("waiting_reply"), stage="ship"))
        self.assertEqual(rooms(rows), {
            "p/pitch": ("meeting", "work", ""), "p/experiment": ("lab", "work", ""),
            "p/ship": ("workshop", "work", ""), "p/document": ("library", "work", ""),
            "p/chat": ("workshop", "reply", "")})

    def test_5_blank_stage_and_unlinked_sessions_go_to_the_office(self):
        lone = dict(sess("working", a="imp:builder"), cwd="/home/me/code/side-project/")
        perm = dict(sess("needs_permission"), cwd="/x/y")
        old = sess("working", age=601)
        rows = [row({"id": "blank"}, sess("working"), stage=""), row({"id": "chat"}, sess("waiting_reply"), stage="")]
        got = impctl.rooms_state(rows, [lone, perm, old], NOW)["characters"]
        self.assertEqual({c["id"]: (c["room"], c["activity"], c["project"]) for c in got}, {
            "p/blank": ("office", "work", "p"), "p/chat": ("office", "reply", "p"),
            "s0": ("office", "work", "side-project"), "s0#" + h8("a"): ("office", "work", "side-project"),
            "s1": ("lounge", "wait", "y")})  # no _sid, as in these fixtures: the index

    def test_ids_are_hashes_and_stable(self):
        a = dict(sess("working", z="imp:builder", y="imp:reviewer"), cwd="/x/p", _sid="session-file")
        b = dict(sess("working"), cwd="/x/q", _sid="other")
        ids = lambda *ss: [c["id"] for c in impctl.rooms_state([], list(ss), NOW)["characters"]]
        got = ids(b, a)
        self.assertEqual(got, ["s" + h8("other"), "s" + h8("session-file"), f"s{h8('session-file')}#{h8('y')}",
                               f"s{h8('session-file')}#{h8('z')}"])
        self.assertEqual(ids(a), got[1:])  # another session going away moves nobody's id
        self.assertFalse(any("session-file" in i for i in got))

    def test_6_not_live_sits_on_the_couch(self):
        rows = [row({"id": "none"}), row({"id": "dead"}, sess("working", age=601)), row({"id": "ended"}, sess("ended")),
                row({"id": "stale"}, waiting_on="user", last_update="2027-01-08")]
        self.assertEqual(set(rooms(rows).values()), {("lounge", "idle", "")})
        self.assertEqual(len(rooms(rows)), 4)

    def test_agents_stay_in_the_stage_room_or_the_office(self):
        b = sess("needs_permission", a1="imp:builder", a2="general-purpose")
        rows = [row({"id": "x"}, b, stage="experiment"), row({"id": "bk"}, sess("working", z="imp:reviewer"), stage="backlog"),
                row({"id": "dead"}, sess("working", age=601, q="imp:builder"))]
        got = {c["id"]: (c["kind"], c["role"], c["room"]) for c in impctl.rooms_state(rows, [], NOW)["characters"]}
        self.assertEqual(got, {
            "p/x": ("lead", "chief", "lounge"), f"p/x#{h8('a1')}": ("agent", "builder", "lab"),
            f"p/x#{h8('a2')}": ("agent", "general-purpose", "lab"), "p/bk": ("lead", "chief", "office"),
            f"p/bk#{h8('z')}": ("agent", "reviewer", "office"), "p/dead": ("lead", "chief", "lounge")})


class TestRoomsPage(unittest.TestCase):
    page = (ROOT / "scripts" / "rooms.html").read_text()

    def test_static_scans(self):
        for bad in ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"]:
            self.assertNotIn(bad, self.page, bad)
        self.assertEqual(re.findall("[\u2580-\u259f]", self.page), [])  # sprites are pixels, not block glyphs
        self.assertIn("prefers-reduced-motion", self.page)
        self.assertRegex(self.page, r'matchMedia\("[^"]*prefers-reduced-motion[^"]*"\)')
        self.assertIn('motion.addEventListener("change"', self.page)
        self.assertRegex(self.page, r"<button[^>]*>Pause</button>")

    def test_whole_script_parses(self):  # the IIFE never runs in the node tests; a redeclared name would still be caught here
        if not shutil.which("node"):
            self.skipTest("node not installed")
        check = """
        const t = require("fs").readFileSync(process.argv[1], "utf8");
        new (require("vm").Script)(t.split("<script>")[1].split("</script>")[0]);
        """
        r = subprocess.run(["node", "-e", check, str(ROOT / "scripts" / "rooms.html")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_every_door_is_reachable(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        check = """
        const t = require("fs").readFileSync(process.argv[1], "utf8");
        const pure = t.split("<script>")[1].split("</script>")[0].split("// ---- end pure ----")[0];
        const m = require("vm").runInNewContext(pure + ";({DOORS, CAMPUS_DOOR, bfs})", {});
        if (!m.DOORS.length || !m.CAMPUS_DOOR) throw new Error("no doors");
        for (const d of m.DOORS)
          if (!m.bfs(m.CAMPUS_DOOR.x, m.CAMPUS_DOOR.y, d.x, d.y)) throw new Error("unreachable door " + JSON.stringify(d));
        """
        r = subprocess.run(["node", "-e", check, str(ROOT / "scripts" / "rooms.html")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def pure(self, body):
        """Run JS against the DOM-free part of the page (an empty context: any DOM or window use throws) and return its JSON."""
        if not shutil.which("node"):
            self.skipTest("node not installed")
        check = """
        const t = require("fs").readFileSync(process.argv[1], "utf8");
        const pure = t.split("<script>")[1].split("</script>")[0].split("// ---- end pure ----")[0];
        const out = require("vm").runInNewContext(pure + ";(() => {" + process.argv[2] + "})()", {});
        console.log(JSON.stringify(out));
        """
        r = subprocess.run(["node", "-e", check, str(ROOT / "scripts" / "rooms.html"), body], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_keep_sends_unticked_not_live_leads_to_the_pool(self):
        got = self.pure("""
        const c = (id, live, activity, note, kind) => ({id, kind: kind || (id.includes("#") && /#[0-9a-f]{8}$/.test(id) ? "agent" : "lead"),
          live: !!live, room: "lab", activity: activity || (live ? "work" : "idle"), note: note || ""});
        const chars = [c("p/a"), c("p/live", true), c("p/live#0123abcd", true), c("p/gate", false, "wait", "G1 Plan"),
          c("q#1/x"), c("p/ideas/old.md"), c("s1a2b3c4d", true), c("s1a2b3c4d#00000001", true)];
        const run = (on, all) => keep(chars, {all: !!all, on: new Set(on)});
        const where = list => list.map(x => x.id + ":" + x.room + ":" + x.activity + ":" + x.note);
        const saved = parsePick(null) || {all: false, on: new Set()};
        return {none: where(run([])), tick: where(run(["p/a", "q#1/x", "p/ideas/old.md", "p/live"])), all: run([], true) === chars,
          saved: where(keep(chars, saved)), untouched: chars.every(x => x.room === "lab"), store: STORE,
          norm: normalize({characters: [{id: "a", live: true}, {id: "b", live: "yes"}, {id: "c"}]}).characters.map(x => x.live),
          keys: ["p/a#0123abcd", "q#1/x#deadbeef", "s1a2b3c4d#00000001", "p/a#xyz"].map(ideaKey)};
        """)
        self.assertEqual(got["none"], [  # the default: only live ideas and sessions are in; a gate keeps its wait at the pool
            "p/a:pool:idle:", "p/live:lab:work:", "p/live#0123abcd:lab:work:", "p/gate:pool:wait:G1 Plan", "q#1/x:pool:idle:",
            "p/ideas/old.md:pool:idle:", "s1a2b3c4d:lab:work:", "s1a2b3c4d#00000001:lab:work:"])
        self.assertEqual(got["tick"], [  # a tick brings an idea in; a # in the project or a path id is still one idea
            "p/a:lab:idle:", "p/live:lab:work:", "p/live#0123abcd:lab:work:", "p/gate:pool:wait:G1 Plan", "q#1/x:lab:idle:",
            "p/ideas/old.md:lab:idle:", "s1a2b3c4d:lab:work:", "s1a2b3c4d#00000001:lab:work:"])
        self.assertTrue(got["all"])  # All brings everyone in, as sent
        self.assertEqual(got["saved"], got["none"])  # nothing saved: nothing ticked
        self.assertTrue(got["untouched"])  # keep copies, it never edits the poll
        self.assertEqual(got["norm"], [True, False, False])  # only a real true is live
        self.assertEqual(got["store"], "imp-rooms-ideas-v2")  # the r2 key, where "all" was the default, is never read
        self.assertEqual(got["keys"], ["p/a", "q#1/x", "s1a2b3c4d", "p/a#xyz"])

    def test_saved_choice_is_validated(self):
        got = self.pure("""
        const ok = parsePick('{"all":false,"on":["p/a"]}'), r2 = parsePick('{"all":true,"on":[],"unlinked":true}');
        const bad = [null, "", "{", "[]", "null", '{"all":1,"on":[]}', '{"all":true,"on":{"p/a":1}}',
          '{"all":true,"on":[1]}', JSON.stringify({all: false, on: ["x".repeat(201)]}),
          JSON.stringify({all: false, on: Array.from({length: 501}, (_, i) => "k/" + i)}),
          '{"all":"yes","on":["constructor"]}'].map(s => parsePick(s));
        return {ok: [ok.all, [...ok.on], Object.keys(ok)], r2: [r2.all, Object.keys(r2)], bad};
        """)
        self.assertEqual(got["ok"], [False, ["p/a"], ["all", "on"]])
        self.assertEqual(got["r2"], [True, ["all", "on"]])  # an extra field is dropped; the v2 key keeps r2 saves out anyway
        self.assertEqual(got["bad"], [None] * 11)

    def test_pool_and_lawn_hold_twenty(self):
        got = self.pure("""
        const pool = SPOTS.filter(s => spotGroup(s) === "pool:l");
        const wait = {id: "p/w", kind: "lead", room: "pool", activity: "wait", note: "G1 Plan"};
        const idle = Array.from({length: pool.length}, (_, i) => ({id: "p/i" + i, kind: "lead", room: "pool", activity: "idle", note: ""}));
        const want = c => ({id: c.id, group: charGroup(c), pri: priority(c)});
        const first = assignSpots(idle.map(want), new Map()), after = assignSpots(idle.concat([wait]).map(want), first);
        return {n: pool.length, towels: pool.filter(s => s.kind === "t").length,
          lost: pool.filter(s => !bfs(CAMPUS_DOOR.x, CAMPUS_DOOR.y, s.x, s.y)).length, wait: after.get("p/w") >= 0,
          heads: pool.filter(s => s.kind === "t").every(s => tileAt(s.x - 1, s.y) === "u")};
        """)
        self.assertGreaterEqual(got["n"], 20)
        self.assertGreaterEqual(got["towels"], 12)
        self.assertEqual(got["lost"], 0)  # every lounger and towel is reachable from the campus door
        self.assertTrue(got["heads"])
        self.assertTrue(got["wait"])  # a full pool still finds a waiting idea a spot: its ! never goes to the overflow

    def test_kitchen_gives_spots_by_priority(self):
        got = self.pure("""
        const kitchen = SPOTS.filter(s => spotGroup(s) === "lounge:k").length;
        const wait = (id, note) => ({id, activity: "wait", note, room: "lounge"});
        const want = c => ({id: c.id, group: charGroup(c), pri: priority(c)});
        const old = Array.from({length: kitchen}, (_, i) => wait("g" + i, i < 2 ? "" : "G1 Plan"));
        const first = assignSpots(old.map(want), new Map());
        const next = old.concat([wait("zz", "permission"), wait("zy", "G2 Review")]);
        const after = assignSpots(next.map(want), first);
        const lost = next.filter(c => after.get(c.id) < 0).map(c => c.id);
        return {kitchen, pri: [priority(wait("a", "permission")), priority(wait("a", "G1")), priority(wait("a", "")),
          priority({activity: "work", note: ""})], lost, perm: after.get("zz") >= 0, gate: after.get("zy") >= 0,
          first: [...first.values()].every(v => v >= 0), distinct: new Set([...after.values()].filter(v => v >= 0)).size};
        """)
        self.assertGreaterEqual(got["kitchen"], 5)
        self.assertEqual(got["pri"], [0, 1, 2, 3])
        self.assertTrue(got["first"] and got["perm"] and got["gate"])
        self.assertEqual(got["lost"], ["g0", "g1"])  # the two plain waits walk to the overflow, the gates keep their spots
        self.assertEqual(got["distinct"], got["kitchen"])

    def test_cut_and_the_hot_agent_tag(self):
        got = self.pure("""
        const agent = {kind: "agent", role: "builder", idea: "agent-rooms"}, lead = {kind: "lead", role: "chief", idea: "a-long-idea-name-here", project: "imp"};
        return [cut("abc", 3), cut("abcd", 3), cut("", 3), tagText(agent, false), tagText(agent, true), tagText({kind: "agent", role: "x", idea: ""}, true),
          tagText({kind: "agent", role: "r".repeat(30), idea: "i".repeat(30)}, true), tagText(lead, false), tagText({kind: "lead", idea: "", project: ""}, false)];
        """)
        self.assertEqual(got[:3], ["abc", "ab\u2026", ""])
        self.assertEqual(got[3:6], ["builder", "builder \u00b7 agent-rooms", "x"])
        self.assertEqual(got[6], "r" * 19 + "\u2026 \u00b7 " + "i" * 17 + "\u2026")
        self.assertEqual(got[7:], ["a-long-idea-name-\u2026 \u00b7 imp", "?"])

    def test_tags_keep_off_bodies_and_stay_with_their_owner(self):
        got = self.pure("""
        const man = (id, rank, cx, w, hot) => ({id, rank, hot: !!hot, cx, hh: 32, body: {x: cx - 20, y: 200, w: 40, h: 96},
          ys: [162, 126, 300], labels: [{label: id, w}]});
        // b is listed first, but the lead a picks first; c and d are walled in above and below; e is at the canvas edge
        const people = [man("b", 2, 264, 80), man("a", 1, 200, 240), man("c", 2, 600, 80), man("d", 0, 800, 80, true), man("e", 2, 10, 240)];
        const blocked = [{x: 500, y: 0, w: 400, h: 200}, {x: 500, y: 296, w: 400, h: 304}];
        const tags = placeTags(people, blocked, 1000, 600, 4, 32);
        const hit = (b, o) => o.x < b.x + b.w && b.x < o.x + o.w && o.y < b.y + b.h && b.y < o.y + o.h;
        const far = (x, y, o) => Math.hypot(Math.max(o.x - x, 0, x - o.x - o.w), Math.max(o.y - y, 0, y - o.y - o.h));
        const bad = [];
        for (const p of people) {
          const b = tags.get(p.id);
          if (!b || p.hot) continue;
          const x = b.x + b.w / 2, y = b.y + b.h / 2;
          if (people.some(q => hit(b, q.body))) bad.push(p.id + " on a body");
          if (people.some(q => q !== p && far(x, y, q.body) <= far(x, y, p.body))) bad.push(p.id + " nearer someone else");
          if (Math.abs(x - p.cx) > 32) bad.push(p.id + " drifts");
        }
        const y = id => tags.get(id) && tags.get(id).y;
        return {bad, a: y("a"), b: y("b"), c: tags.get("c"), d: y("d"), e: tags.get("e"), size: tags.size};
        """)
        self.assertEqual(got["bad"], [])
        self.assertEqual((got["a"], got["b"]), (162, 126))  # the lead takes the slot above the head, the agent the one higher
        self.assertIsNone(got["c"])  # no clear slot: hover only
        self.assertIsNotNone(got["d"])  # hot: drawn even when walled in
        self.assertIsNone(got["e"])  # kept on the canvas it would drift 110 px off its owner
        self.assertEqual(got["size"], 5)

    def test_a_body_with_no_tag_blocks_and_tags_hold_their_slot(self):
        got = self.pure("""
        const man = (id, cx, y, extra) => Object.assign({id, rank: 2, hot: false, cx, hh: 32, body: {x: cx - 20, y, w: 40, h: 96},
          ys: [y - 38, y - 74, y + 100], labels: [{label: id, w: 80}, {label: "s", w: 40}]}, extra);
        // w, a departing walker just above a, is a body with no labels: it fills both slots over a's head, so a goes under its feet
        const one = placeTags([man("a", 200, 200), man("w", 200, 100, {labels: []})], [], 1000, 600, 4, 32);
        // a held the slot under its feet and the short label last frame: it keeps both while they are still legal
        const two = placeTags([man("a", 200, 300)], [], 1000, 600, 4, 32, new Map([["a", {s: 2, li: 1, d: 0}]]));
        // hot at the edge: every slot drifts too far, so a clamped centred box is drawn
        const hot = placeTags([man("h", 2, 200, {hot: true, labels: [{label: "h", w: 300}]})], [], 1000, 600, 4, 32);
        return {aY: one.get("a") && one.get("a").y, w: one.has("w"), size: one.size, two: two.get("a"), hot: hot.get("h")};
        """)
        self.assertEqual(got["aY"], 300)
        self.assertFalse(got["w"])
        self.assertEqual(got["size"], 1)
        self.assertEqual((got["two"]["y"], got["two"]["label"]), (400, "s"))
        self.assertEqual((got["hot"]["x"], got["hot"]["y"], got["hot"]["w"]), (0, 162, 300))

    def test_a_tag_shows_only_after_its_slot_has_been_legal_for_a_while(self):
        got = self.pure("""
        const since = new Map(), up = {s: 0, li: 0}, down = {s: 2, li: 0}, on = (t, m, hot) => {
          const [out, wake] = holdTags(new Map(m), since, t, 400, new Set(hot || []));
          return [[...out].map(([id, b]) => id + ":" + (b ? b.s : "-")).join(" "), wake];
        };
        // a waits in its slot, shows at 400 ms, hides at once, moves and waits again; b is hot and shows at once
        const run = [on(0, [["a", up], ["b", null]]), on(399, [["a", up]]), on(400, [["a", up]]), on(500, [["a", null]]),
          on(600, [["a", up]]), on(1000, [["a", down], ["b", up]], ["b"]), on(1400, [["a", down]])];
        // a still frame (wait 0) shows every legal tag, a new one too
        const still = holdTags(new Map([["c", up], ["a", down]]), since, 1401, 0, new Set())[0];
        return {run, still: [...still.keys()].filter(id => still.get(id)), left: [...since.keys()]};
        """)
        self.assertEqual(got["run"], [["a:- b:-", 400], ["a:-", 1], ["a:0", None], ["a:-", None], ["a:-", 400],
                                      ["a:- b:0", 400], ["a:2", None]])  # None: Infinity in JSON, nothing waits
        self.assertEqual(got["still"], ["c", "a"])
        self.assertEqual(got["left"], ["a", "c"])  # b left the input map, so its wait is forgotten

    def test_wait_text_does_not_double(self):
        got = self.pure("""
        const w = note => stateText({activity: "wait", note, room: "lounge"});
        return [w("G1 Plan"), w(""), w("permission"), stateText({activity: "idle", room: "pool"}), roomText({room: "pool"})];
        """)
        self.assertEqual(got, ["waiting on you: G1 Plan", "waiting on you", "waiting on you: permission", "not in the building",
                               "Pool (not ticked)"])

    def test_s2_helpers_stay_dom_free(self):  # the empty context above throws on any DOM or window use at load
        got = self.pure("""
        const hex = /^#[0-9a-f]{6}$/;
        return {s: S, ramps: ["#336699", "#c0c0c0", "#e2463e"].map(h => ramp(h).length === 4 && ramp(h).every(x => hex.test(x))),
          hsl: hslHex(120, 0.5, 0.5)};
        """)
        self.assertEqual(got["s"], 2)
        self.assertEqual(got["ramps"], [True] * 3)
        self.assertRegex(got["hsl"], r"^#[0-9a-f]{6}$")


class TestPanels(unittest.TestCase):
    def test_stat_counts(self):
        rows = [("waiting", "", {}, []), ("waiting", "", {}, []), ("progress", "", {}, []), ("done", "", {}, [])]
        sessions = [sess("working", a="imp:builder", b="imp:reviewer"), sess("working", age=601, c="x"), sess("ended", d="y")]
        c = impctl.stat_counts(rows, sessions, NOW)
        self.assertEqual((c["waiting"], c["progress"], c["idle"], c["done"], c["agents"]), (2, 1, 0, 1, 2))

    def test_gate_track(self):
        self.assertEqual(impctl.gate_track(idea(gate="G2")), [("G1", ""), ("G-data", ""), ("G2", "cur"), ("G3", "")])
        self.assertEqual(impctl.gate_track(idea(stage="pitch")), [("G1", "next"), ("G-data", ""), ("G2", ""), ("G3", "")])
        self.assertEqual(impctl.gate_track(idea(stage="experiment", gate="G-data"))[1], ("G-data", "cur"))
        self.assertEqual([m for _, m in impctl.gate_track(idea(stage="backlog"))], ["", "", "", ""])

    def test_timeline_segments(self):
        changes = [[100, "working"], [500, "needs_permission"], [700, "working"], [900, "waiting_reply"], [1000, "ended"]]
        self.assertEqual(impctl.timeline(changes, 600, 2000),
                         [(600, 700, "needs_permission"), (700, 900, "working"), (900, 1000, "waiting_reply")])
        self.assertEqual(impctl.timeline([[100, "working"]], 0, 400), [(100, 400, "working")])
        self.assertEqual(impctl.timeline([], 0, 400), [])

    def test_render_panels_and_escaping(self):
        i = idea(id="a<b", title="t", gate="G2", project="p&q", _folder="/f")
        s = {"idea": "/f", "state": "waiting_reply", "last_seen": NOW, "agents": {},
             "changes": [[NOW - 4000, "working"], [NOW - 600, "waiting_reply"]]}
        loose = {"cwd": "/w/<evil>", "state": "needs_permission", "last_seen": NOW, "changes": [[NOW - 60, "needs_permission"]]}
        page = impctl.render([("waiting", "G2 Ready to push", i, [s])], False, NOW, [s, loose])
        self.assertIn('<span class="pill amber">G2 Ready to push</span>', page)
        self.assertIn('<span class="cur">G2</span>', page)
        self.assertIn("p&amp;q/a&lt;b", page)
        self.assertIn("&lt;evil&gt;", page)
        self.assertNotIn("<evil>", page)
        self.assertIn('<rect x="0" width="3000"', page)  # working, clipped to the 60-min window
        self.assertIn('<rect x="3000" width="600" height="10" fill="var(--amber)"', page)
        self.assertIn('fill="var(--red)"', page)


def seq(i, *agents):
    live = [{"agents": {str(n): a for n, a in enumerate(agents)}}] if agents else []
    people, msgs = impctl.sequence(i, live)
    cur = [(a, b, l) for a, b, l, st in msgs if st == "current"]
    return people, msgs, cur[0] if cur else None


class TestSequence(unittest.TestCase):
    def test_gates(self):
        self.assertEqual(seq(idea(gate="G1"))[2], ("chief", "you", "G1 plan"))
        self.assertEqual(seq(idea(gate="G2"))[2], ("chief", "you", "G2 diff"))
        self.assertEqual(seq(idea(stage="ship", gate="G2"))[2], ("chief", "you", "G2 merge"))
        self.assertEqual(seq(idea(stage="ship", gate="G3"))[2], ("you", "chief", "G3 tested"))
        self.assertEqual(seq(idea(stage="pitch", gate="meeting"))[2], ("chief", "you", "meeting"))
        self.assertEqual(seq(idea(stage="pitch", gate="G-data"))[2][2], "pitch deck")
        self.assertEqual(seq(idea(gate="G-data"))[2][2], "results / notes")

    def test_live_agents(self):
        self.assertEqual(seq(idea(), "imp:builder")[2], ("builder", "chief", "commits"))
        self.assertEqual(seq(idea(), "imp:builder", "imp:reviewer")[2], ("reviewer", "chief", "PASS/BLOCK"))
        self.assertEqual(seq(idea(stage="ship"), "imp:builder")[2][2], "feature branch")
        self.assertEqual(seq(idea(stage="pitch"), "imp:tech-researcher")[2][2], "recon")
        self.assertEqual(seq(idea(), "imp:verifier")[2], seq(idea(), "imp:reviewer")[2])
        self.assertEqual(seq(idea(stage="pitch"), "imp:claim-checker")[2][2], "check")
        self.assertEqual(seq(idea(stage="document"), "presenter")[2][2], "docs")
        self.assertEqual(seq(idea(gate="G2"), "imp:builder")[2][2], "G2 diff")  # the gate wins
        people = seq(idea(), "imp:builder")[0]
        self.assertEqual(people, [("you", False), ("chief", False), ("builder", True), ("reviewer", False)])
        self.assertEqual([p for p, _ in seq(idea(stage="pitch"))[0]], ["you", "chief", "researcher", "reviewer", "presenter"])

    def test_waiting_on_and_fallback(self):
        self.assertEqual(seq(idea(waiting_on="user"))[2][2], "G2 diff")
        self.assertEqual(seq(idea(stage="pitch", waiting_on="user"))[2][2], "G1 plan")
        self.assertEqual(seq(idea(stage="document", waiting_on="user"))[2][2], "done")
        self.assertEqual(seq(idea(stage="pitch", waiting_on="marketing"))[2][2], "meeting")
        self.assertEqual(seq(idea(waiting_on="marketing"))[2][2], "results / notes")
        self.assertEqual(seq(idea())[2][2], "brief")  # agents, no gate: the step after go
        self.assertEqual(seq(idea(stage="document"))[2][2], "docs")
        for stage in ("backlog", "shelved", "done", ""):
            self.assertEqual(impctl.sequence(idea(stage=stage), []), ([], []))

    def test_statuses(self):
        st = [m[3] for m in seq(idea(gate="G2"))[1]]
        self.assertEqual(st, ["done"] * 6 + ["current", "next"])

    def test_svg(self):
        people, msgs, _ = seq(idea(gate="G2"), "imp:builder")
        svg = impctl.sequence_svg(people, msgs)
        self.assertEqual(svg.count('class="dot"'), 1)
        self.assertIn('class="node c-green live"', svg)
        self.assertIn("◆ G2 diff", svg)
        self.assertEqual(svg.count('<g class="msg done">'), 6)
        self.assertIn('<g class="msg next">', svg)

    def test_svg_width(self):  # 1:1 (width = viewBox), wider with more participants
        msgs = [("you", "chief", "x", "next")]
        def width(n):
            svg = impctl.sequence_svg([(p, False) for p in impctl.ACTORS[:n]], msgs)
            w = int(svg.split('<svg class="seq" width="')[1].split('"')[0])
            self.assertIn(f'style="--w:{w}px"', svg)
            self.assertIn(f'viewBox="0 0 {w} ', svg)
            return w
        self.assertGreater(width(5), width(3))
        self.assertGreaterEqual(width(3), 3 * 140)

    def test_banner_and_seqwrap_share_width(self):
        self.assertIn("#banner,.seqwrap{width:50%;min-width:min(100%,max(480px,var(--w,0px)));margin:0 auto}", impctl.PAGE)
        self.assertIn(".seqwrap{width:calc(50cqw + 9px);", impctl.PAGE)  # = 50% of body, the banner's width


class TestBannerAndColumns(unittest.TestCase):
    def test_mood_priority(self):
        b = impctl.banner_state
        w, p, i = ("waiting", "G2 Ready to push", idea(gate="G2"), []), ("progress", "", idea(), []), ("idle", "", idea(), [])
        self.assertEqual(b([i, p, w], 2), {"mood": "waiting", "agents": 2, "waiting": 1, "gate": "G2"})
        self.assertEqual(b([i, p], 0)["mood"], "working")
        self.assertEqual(b([i], 1)["mood"], "working")
        self.assertEqual(b([i], 0), {"mood": "idle", "agents": 0, "waiting": 0, "gate": ""})
        perm = ("waiting", "permission prompt", idea(last_update="2030-01-01"), [])
        self.assertEqual(b([w, perm], 0)["gate"], "you")  # a permission prompt is the most urgent

    def test_render_columns_details_and_escaping(self):
        rows = [("waiting", "G1 Plan", idea(id="w", gate='G1"><x', project="p", _folder="/w", title="t" * 40), []),
                ("progress", "builder", idea(id="p<1>", project="p", _folder="/p"), [sess("working", a="imp:builder")]),
                ("idle", "", idea(id="i", project="p", _folder="/i"), []),
                ("idle", "backlog", idea(id="b", stage="backlog", project="p", _folder="/b"), [])]
        page = impctl.render(rows, False, NOW)
        self.assertEqual(page.count("<table>"), 3)
        self.assertEqual(page.count("<table><colgroup>"), 3)
        self.assertEqual(page.count("<colgroup>"), 3)
        self.assertIn("table-layout:fixed", page)
        self.assertIn(f'<td title="{"t" * 40}">', page)
        self.assertIn('data-id="p/p&lt;1&gt;" data-open="1" open><summary>sequence</summary>', page)
        self.assertIn('data-id="p/i" data-open="0"><summary>show sequence</summary>', page)
        self.assertNotIn('data-id="p/b"', page)  # backlog has no sequence
        self.assertIn('data-mood="waiting"', page)
        self.assertIn('data-gate="G1&quot;&gt;&lt;x"', page)
        self.assertNotIn('"><x', page)
        self.assertIn('<pre id="banner"', page)
        self.assertLess(page.index('<pre id="banner"'), page.index('<div id="panels">'))
        self.assertLess(page.index('<div id="panels">'), page.index('<div id="mood"'))
        self.assertIn("requestAnimationFrame", page)
        self.assertIn("prefers-reduced-motion", page)
        self.assertIn('localStorage.getItem("imp-char")', page)
        self.assertIn("Object.prototype.hasOwnProperty.call(FRAMES", page)  # "constructor" in storage must not pass

    def test_block_glyphs_drawn_as_pixels(self):
        js = impctl.PAGE.split("<script>")[1].split("(function () {")[0]
        hill = re.search(r"var HILL = (\[.*?\])", js)
        glyphs = set("".join(json.loads(hill[1]))) - {" "}
        table = set(re.findall(r'"(.)": \d+', re.search(r"var PX = \{(.*?)\}", js)[1]))
        self.assertTrue(glyphs and glyphs <= table, glyphs - table)
        if not shutil.which("node"):
            self.skipTest("node not installed")
        check = js + """
        var blocks = /[\\u2580-\\u259f]/, d = {agents: 2, waiting: 3, gate: "G2"};
        Object.keys(FRAMES).forEach(function (kind) {
          ["working", "waiting", "idle"].forEach(function (mood) {
            d.mood = mood;
            for (var t = 0; t < 12; t++)
              [40, 120].forEach(function (w) {
                var html = FRAMES[kind](t, w, d).map(function (row) { return rowHtml(row, 8); }).join("\\n");
                if (blocks.test(html)) throw new Error(kind + " " + mood + ": " + html);
              });
          });
          d.mood = "idle";
          if (kind === "ants" && ants(7, 120, d).map(function (row) { return rowHtml(row, 8); }).join("").indexOf("<rect") < 0)
            throw new Error("ants drew no pixels");
        });"""
        r = subprocess.run(["node", "-e", check], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
