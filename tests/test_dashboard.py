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
        self.assertEqual(run(read)["idea"], IDEAS + "/offer-timing")
        bash = ev("PreToolUse", tool_name="Bash", tool_input={"command": "cat ideas/returns/plan.md"})
        self.assertEqual(run(bash)["idea"], IDEAS + "/returns")
        other = ev("PreToolUse", tool_name="Bash", tool_input={"command": "cat myideas/x/plan.md ideas/local/y"})
        self.assertNotIn("idea", run(other))
        brief = ev("PreToolUse", tool_name="Agent", tool_input={"prompt": "# Brief: builder for task-dashboard\n\n**Goal:** x"})
        self.assertEqual(run(brief)["idea"], IDEAS + "/task-dashboard")
        self.assertNotIn("idea", run(read, state={"ideas_dir": ""}))

    def test_subagent_cwd_keeps_session_cwd(self):
        sub = ev("PreToolUse", tool_name="Read", agent_id="a1", agent_type="imp:builder", cwd="/p/ideas/x", tool_input={})
        bash = ev("PreToolUse", tool_name="Bash", tool_input={"command": "cat ideas/returns/plan.md"})
        del bash["cwd"]
        s = run(ev("SessionStart"), sub)
        self.assertEqual(s["cwd"], "/p")
        self.assertEqual(run(bash, state=s)["idea"], IDEAS + "/returns")

    def test_subagent_reads_do_not_relink_the_session(self):
        read = lambda **kw: ev("PreToolUse", tool_name="Read", tool_input={"file_path": IDEAS + "/other/plan.md"}, **kw)
        main = run(ev("SessionStart"), ev("PreToolUse", tool_name="Read", tool_input={"file_path": IDEAS + "/mine/plan.md"}))
        s = run(read(agent_id="a1", agent_type="imp:tech-researcher"), state=main)
        self.assertEqual((s["idea"], s["agents"]), (IDEAS + "/mine", {"a1": "imp:tech-researcher"}))
        self.assertEqual(run(read(), state=main)["idea"], IDEAS + "/other")  # the main session still relinks

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
        keys = {"id", "kind", "role", "room", "activity", "project", "idea", "title", "note"}
        self.assertEqual([(c["id"], c["room"], c["activity"], c["role"]) for c in data["characters"]],
                         [("proj/evil", "office", "work", "chief"), ("proj/evil#1", "office", "work", "builder")])
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

    def test_2_backlog_sunbathes_live_or_not(self):
        live = sess("waiting_reply")
        rows = [row({"id": "a"}, stage="backlog"), row({"id": "b"}, live, stage="backlog", gate="G1", waiting_on="user")]
        self.assertEqual(rooms(rows), {"p/a": ("pool", "idle", ""), "p/b": ("pool", "idle", "")})

    def test_3_permission_and_gates_go_to_the_kitchen(self):
        rows = [row({"id": "perm"}, sess("needs_permission")),
                row({"id": "gate"}, sess("waiting_reply"), gate="G2"),
                row({"id": "user"}, waiting_on="user", gate="G1"),
                row({"id": "user2"}, sess("waiting_reply"), waiting_on="user"),
                row({"id": "busy"}, sess("working"), gate="G2", stage="ship")]
        self.assertEqual(rooms(rows), {
            "p/perm": ("lounge", "wait", "permission"), "p/gate": ("lounge", "wait", "G2 Ready to push"),
            "p/user": ("lounge", "wait", "G1 Plan"), "p/user2": ("lounge", "wait", "waiting on you"),
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
            "s0": ("office", "work", "side-project"), "s0#1": ("office", "work", "side-project"),
            "s1": ("lounge", "wait", "y")})

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
            "p/x": ("lead", "chief", "lounge"), "p/x#1": ("agent", "builder", "lab"), "p/x#2": ("agent", "general-purpose", "lab"),
            "p/bk": ("lead", "chief", "pool"), "p/bk#1": ("agent", "reviewer", "office"), "p/dead": ("lead", "chief", "lounge")})


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
