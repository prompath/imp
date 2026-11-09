import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def read(rel):
    return (ROOT / rel).read_text()


class TestManifests(unittest.TestCase):
    def test_marketplace_lists_imp(self):
        m = json.loads(read(".claude-plugin/marketplace.json"))
        self.assertEqual(m["name"], "imp")
        self.assertEqual(len(m["plugins"]), 1)
        self.assertEqual(m["plugins"][0]["name"], "imp")
        self.assertEqual(m["plugins"][0]["source"], "./")

    def test_plugin_json(self):
        p = json.loads(read(".claude-plugin/plugin.json"))
        self.assertEqual(p["name"], "imp")
        self.assertTrue(p["version"])
        self.assertEqual(p["hooks"], "./hooks/hooks.json")


class TestTemplates(unittest.TestCase):
    def test_template_files(self):
        from impctl import parse_frontmatter
        for f in ["defaults/project.md", "templates/STATUS.md", "templates/plan.md",
                  "templates/brief.md", "templates/deck-outlines.md", "templates/result.md"]:
            self.assertTrue((ROOT / f).is_file(), f)
        proj = parse_frontmatter(read("defaults/project.md"))
        for k in ["kind", "ideas_root", "integration_branch", "push_forbidden", "meeting", "deck", "agent_overrides", "notion"]:
            self.assertIn(k, proj)
        st = parse_frontmatter(read("templates/STATUS.md"))
        for k in ["id", "group", "stage", "round", "waiting_on", "gate", "started", "due", "last_update"]:
            self.assertIn(k, st)
        self.assertEqual(read("templates/deck-outlines.md").count("Assumptions to confirm"), 2)


AGENTS = ["business-researcher", "tech-researcher", "code-investigator", "data-analyst",
          "builder", "verifier", "claim-checker", "presenter", "reviewer"]
READ_ONLY = {"code-investigator", "reviewer", "verifier", "claim-checker"}
LEVELS = ["Verified", "Sourced", "Inferred", "Assumed"]


def tools_of(fm):
    return {t.strip() for t in fm.get("tools", "").split(",") if t.strip()}


class TestAgents(unittest.TestCase):
    def test_agents(self):
        from impctl import parse_frontmatter
        for name in AGENTS:
            text = read(f"agents/{name}.md")
            fm = parse_frontmatter(text)
            self.assertEqual(fm.get("name"), name)
            self.assertTrue(fm.get("description"), name)
            tools = tools_of(fm)
            if name == "data-analyst":
                self.assertFalse(tools & {"Bash", "Edit", "WebSearch"}, tools)
            if name in READ_ONLY:
                self.assertFalse(tools & {"Write", "Edit"}, (name, tools))
            else:
                self.assertIn("never push", text.lower(), name)
            if name in {"business-researcher", "tech-researcher", "presenter", "reviewer"}:
                for lvl in LEVELS:
                    self.assertIn(lvl, text, (name, lvl))
        self.assertIn("BLOCK", read("agents/reviewer.md"))
        self.assertEqual(parse_frontmatter(read("agents/reviewer.md")).get("model"), "opus")
        self.assertEqual(parse_frontmatter(read("agents/builder.md")).get("model"), "sonnet")
        # the claim-checker only fetches links; a search box could leak internal numbers
        self.assertNotIn("WebSearch", tools_of(parse_frontmatter(read("agents/claim-checker.md"))))


COMMANDS = ["idea", "continue", "notes", "ideas", "investigate", "save", "notion"]
REFS = ["routing", "gates", "evidence", "lifecycle", "segment-treatment", "investigate", "analysis", "explore", "state", "notion"]
WORKFLOWS = ["lifecycle", "segment-treatment", "investigate", "analysis", "explore"]


class TestSkillsAndCommands(unittest.TestCase):
    def test_commands(self):
        from impctl import parse_frontmatter
        for c in COMMANDS:
            text = read(f"commands/{c}.md")
            self.assertEqual(parse_frontmatter(text).get("disable-model-invocation"), "true", c)
            self.assertIn("imp:chief-of-staff", text, c)
        names = {p.name for p in (ROOT / "commands").iterdir()}
        self.assertFalse(names & {"status.md", "feedback.md"})

    def test_push_command_waits_for_user(self):
        from impctl import parse_frontmatter
        text = read("commands/push.md")
        self.assertEqual(parse_frontmatter(text).get("disable-model-invocation"), "true")
        for s in ["explicit yes", "Never force-push", "push_forbidden", "git log --oneline @{u}..HEAD", "git diff --staged > <file>"]:
            self.assertIn(s, text, s)

    def test_skill(self):
        from impctl import parse_frontmatter
        skill = read("skills/chief-of-staff/SKILL.md")
        self.assertEqual(parse_frontmatter(skill).get("name"), "chief-of-staff")
        for r in REFS:
            self.assertIn(f"references/{r}.md", skill, r)
            self.assertTrue((ROOT / f"skills/chief-of-staff/references/{r}.md").is_file(), r)
        for s in ["G1", "G2", "BLOCK", "agent_overrides", "scripts/impctl.py", ".imp/workflows",
                  "relative to the plugin folder", "replace any other plan", "> <temp file>"]:
            self.assertIn(s, skill, s)
        self.assertIn('git diff <base>..<branch> > "$f"', read("agents/reviewer.md"))
        everything = skill + "".join(
            p.read_text() for p in (ROOT / "skills/chief-of-staff/references").glob("*.md"))
        for a in AGENTS:
            self.assertIn(a, everything, a)

    def test_secretary(self):
        from impctl import parse_frontmatter
        cmd = read("commands/secretary.md")
        self.assertEqual(parse_frontmatter(cmd).get("disable-model-invocation"), "true")
        self.assertIn('skill: "imp:secretary"', cmd)
        self.assertNotIn("imp:chief-of-staff", cmd)
        skill = read("skills/secretary/SKILL.md")
        self.assertEqual(parse_frontmatter(skill).get("name"), "secretary")
        for s in ["Never use the Agent tool", "Never load the `imp:chief-of-staff` skill", "never push",
                  "Re-read the file right before each edit", "agenda --new", "journal --today", "CronCreate",
                  "PushNotification", "`ntn`", "<repo>/<id>/T<n>", "secretary/T<n>", "Never mention imp",
                  "name the exact pages", "wrap up", "show the resolved date"]:
            self.assertIn(s, skill, s)
        self.assertIn("Secretary exception", read("skills/chief-of-staff/references/gates.md"))
        self.assertIn("## Tasks", read("templates/STATUS.md"))

    def test_workflow_files_have_frontmatter(self):
        from impctl import parse_frontmatter
        for w in WORKFLOWS:
            fm = parse_frontmatter(read(f"skills/chief-of-staff/references/{w}.md"))
            for k in ["name", "use_when", "entry", "agents"]:
                self.assertTrue(fm.get(k), (w, k))


class TestInit(unittest.TestCase):
    def test_init(self):
        from impctl import parse_frontmatter
        cmd = read("commands/imp-init.md")
        self.assertEqual(parse_frontmatter(cmd).get("disable-model-invocation"), "true")
        self.assertIn("imp:imp-init", cmd)
        skill = read("skills/imp-init/SKILL.md")
        self.assertEqual(parse_frontmatter(skill).get("name"), "imp-init")
        for s in ["local/", "register"]:
            self.assertIn(s, skill, s)


class TestDocsSite(unittest.TestCase):
    def test_site(self):
        import re
        html = read("docs/site/index.html")
        for s in ["/idea", "/continue", "/notes", "/ideas", "/investigate", "/imp:notion", "/imp-init", "/imp:dashboard", "/imp:secretary",
                  "G1", "G2", "Verified", "push_forbidden", "agent_overrides", ".imp/workflows"]:
            self.assertIn(s, html, s)
        for src in re.findall(r'<script[^>]*src="([^"]+)"', html):
            self.assertTrue(src.startswith("https://cdn.jsdelivr.net/"), src)


if __name__ == "__main__":
    unittest.main()
