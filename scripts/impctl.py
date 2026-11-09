#!/usr/bin/env python3
"""imp helpers: frontmatter, project registry, idea listing and ID matching.

Stdlib only. Used by the chief-of-staff and secretary skills through the CLI, by hooks/no_push.py and
hooks/activity.py, and by `impctl.py dashboard` (a local server on 127.0.0.1 only: a page of every idea,
live, and /rooms, a pixel campus of who works where).
"""
import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

PROJECT_FILE = Path(".imp") / "project.md"


class UnknownIdea(Exception):
    def __init__(self, query):
        super().__init__(f"no idea matches '{query}'")
        self.query = query


class AmbiguousIdea(Exception):
    def __init__(self, query, ids):
        super().__init__(f"'{query}' matches several ideas: {', '.join(ids)}")
        self.query = query
        self.ids = ids


def _clean(value: str) -> str:
    value = value.strip()
    if value.startswith("#"):
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def parse_frontmatter(text: str) -> dict:
    """Top-level `key: value` pairs of a leading --- block (flat YAML only)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        if not line or line[0] in " \t-#":
            continue
        key, sep, value = line.partition(":")
        if sep and key.strip():
            out[key.strip()] = _clean(value)
    return out  # no closing ---: keep what was read so the idea still lists


def _read_frontmatter(path: Path) -> dict:
    try:
        return parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def find_project_root(start: Path):
    start = Path(start).resolve()
    for d in [start, *start.parents]:
        if (d / PROJECT_FILE).is_file():
            return d
    return None


def project_config(root: Path) -> dict:
    cfg = {"name": root.name, "kind": "personal", "ideas_root": "ideas"}
    cfg.update({k: v for k, v in _read_frontmatter(root / PROJECT_FILE).items() if v})
    return cfg


def registry_path() -> Path:
    env = os.environ.get("IMP_REGISTRY")
    return Path(env) if env else Path.home() / ".config" / "imp" / "projects.txt"


def load_registry() -> list:
    path = registry_path()
    if not path.is_file():
        return []
    return [Path(l.strip()) for l in path.read_text().splitlines() if l.strip()]


def register(root: Path) -> bool:
    root = Path(root).resolve()
    if root in load_registry():
        return False
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(f"{root}\n")
    return True


def find_ideas(root: Path) -> list:
    root = Path(root)
    ideas_dir = root / project_config(root)["ideas_root"]
    ideas = []
    for dirpath, dirnames, filenames in os.walk(ideas_dir):
        dirnames[:] = sorted(d for d in dirnames if d != "local" and not d.startswith("."))
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            path = Path(dirpath) / name
            fm = _read_frontmatter(path)
            if "waiting_on" in fm:
                fm["_path"] = path.relative_to(root).as_posix()
                ideas.append(fm)
    return ideas


def format_rows(ideas: list) -> str:
    ideas = sorted(ideas, key=lambda i: i.get("last_update") or "", reverse=True)
    rows = []
    for i in ideas:
        stage = i.get("stage") or "-"
        if i.get("round"):
            stage += f" r{i['round']}"
        wait = f"blocked by: {i['blocked_by']}" if i.get("blocked_by") else f"waiting: {i.get('waiting_on') or '-'}"
        rows.append((i.get("id") or "-", stage, wait, i.get("last_update") or "-"))
    if not rows:
        return "  (no ideas)"
    widths = [max(len(r[c]) for r in rows) for c in range(3)]
    lines = ["  ".join(r[c].ljust(widths[c]) for c in range(3)) + "  " + r[3] for r in rows]
    if not any(i.get("group") for i in ideas):
        return "\n".join(lines)

    groups = {}
    for i, line in zip(ideas, lines):
        domain, _, use_case = (i.get("group") or "").partition("/")
        groups.setdefault((domain.strip(), use_case.strip()), []).append(line)
    out, last_domain = [], None
    for domain, use_case in sorted(groups, key=lambda g: (not g[0], g)):  # ungrouped last
        if domain != last_domain:
            out.append(domain or "(ungrouped)")
            last_domain = domain
        if use_case:
            out.append(f"  {use_case}")
        out += [f"    {line}" for line in groups[domain, use_case]]
    return "\n".join(out)


STAGES = ["backlog", "pitch", "experiment", "ship", "monitor", "document", "done", "shelved"]
HIDDEN = {"done", "shelved"}  # left out of /ideas unless --all or a stage filter asks for them


def filter_ideas(ideas: list, stages=None, show_all=False, waiting=None, group=None) -> list:
    if stages:
        ideas = [i for i in ideas if i.get("stage") in stages]
    elif not show_all:
        ideas = [i for i in ideas if i.get("stage") not in HIDDEN]
    if waiting:
        ideas = [i for i in ideas if i.get("waiting_on") == waiting]
    if group:
        ideas = [i for i in ideas if (i.get("group") or "").lower().startswith(group.lower())]
    return ideas


def resolve(ideas: list, query: str) -> dict:
    for i in ideas:
        if i.get("id") == query:
            return i
    q = query.lower()
    hits = [i for i in ideas if q in (i.get("id") or "").lower() or q in (i.get("title") or "").lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise UnknownIdea(query)
    raise AmbiguousIdea(query, [i.get("id") or i["_path"] for i in hits])


def idea_anchor(root: Path, idea: dict) -> tuple:
    """(anchor, by_id): a STATUS.md idea owns its folder; a flat note (`research/<id>.md`) owns only itself."""
    path = root / idea["_path"]
    anchor = str(path.parent) if path.name == "STATUS.md" else str(path)
    by_id = os.path.join(str(root / project_config(root)["ideas_root"]), idea["id"]) if idea.get("id") else None
    return anchor, by_id


def owner(root: Path, ideas: list, path: str):
    """The idea that owns an absolute path, or None. A flat note also owns its `<stem>-*` side files."""
    best, best_len = None, 0
    for idea in ideas:
        anchor, by_id = idea_anchor(root, idea)
        stem = anchor[:-3] if anchor.endswith(".md") else None
        if path in (anchor, by_id) or path.startswith(anchor + "/") or (stem and path.startswith(stem + "-")):
            if len(anchor) > best_len:  # longest anchor wins: inv-x-y over inv-x
                best, best_len = idea, len(anchor)
    return best


def current_ideas(root: Path, session: str = "") -> list:
    """Ideas this session works on: its activity link, else ideas with uncommitted files."""
    ideas = find_ideas(root)
    if session:
        files = [activity_path() / f"{session}.json"]
    else:  # newest session in this project: the one running this command
        files = sorted(activity_path().glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        try:
            s = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        cwd = str(s.get("cwd") or "")
        if not session and not (cwd == str(root) or cwd.startswith(str(root) + "/")):
            continue
        hit = owner(root, ideas, s["idea"]) if s.get("idea") else None
        if hit:
            return [hit]
        break
    out = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "-z", "--untracked-files=all", "--",
                          project_config(root)["ideas_root"]], capture_output=True, text=True).stdout
    hits, entries, k = {}, out.split("\0"), 0
    while k < len(entries):
        e, k = entries[k], k + 1
        if len(e) < 4:
            continue
        if e[0] in "RC":
            k += 1  # a rename's original path follows as its own entry
        hit = owner(root, ideas, str(root / e[3:]))
        if hit:
            hits[hit["_path"]] = hit
    return list(hits.values())


CODE = re.compile(r"\b[A-Z][A-Z0-9]*[A-Z][A-Z0-9]*\b")  # two or more capitals, digits allowed: MYA, LTCG, NBO5


def deck_slides(path: Path) -> list:
    """(label, text) per slide of a .pptx; one entry for an .html or .md file."""
    if path.suffix == ".pptx":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
            nums = sorted(int(re.search(r"\d+", n).group()) for n in names)
            return [(f"slide {i}", html.unescape(" ".join(re.findall(r"<a:t>([^<]*)</a:t>",
                                                                   z.read(f"ppt/slides/slide{i}.xml").decode("utf-8")))))
                    for i in nums]
    return [(path.name, re.sub(r"<[^>]+>", " ", path.read_text()))]


def undefined_codes(slides: list, glossary: str) -> list:
    """(label, codes) for slides using a code that neither the deck nor the glossary defines."""
    deck = " ".join(t for _, t in slides)
    def defined(c):
        e = re.escape(c)
        return bool(re.search(rf"\b{e}\b\s*(\(|:|=)|\(\s*{e}\s*\)", deck) or re.search(rf"\b{e}\b", glossary))
    out = []
    for label, text in slides:
        codes = sorted(c for c in set(CODE.findall(text)) if not defined(c))
        if codes:
            out.append((label, codes))
    return out


def _glossary_text(paths: list) -> str:
    parts = []
    for p in map(Path, paths):
        for f in ([p] if p.is_file() else sorted(p.rglob("*.md"))):
            parts += [f.stem, f.read_text(errors="replace")]
    return "\n".join(parts)


def _scan(base: Path):
    for dirpath, dirnames, _ in os.walk(base):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", ".venv")]
        if (Path(dirpath) / PROJECT_FILE).is_file():
            register(Path(dirpath))


def _project_arg(value, require=False):
    start = Path(value).resolve() if value else Path.cwd().resolve()
    root = find_project_root(start)
    if root is None:
        if require:
            sys.exit("imp: no .imp/project.md here or above; run /imp-init")
        # unconnected project: run on defaults from the git root (or here)
        root = next((d for d in [start, *start.parents] if (d / ".git").exists()), start)
    return root

# --- dashboard ---------------------------------------------------------------

LIVE_SECS = 600  # a session silent this long without SessionEnd counts as ended (crash)
STALE_DAYS = 7
GATES = {"G1": "G1 Plan", "G-data": "G-data", "G2": "G2 Ready to push", "G3": "G3 Tested", "meeting": "Meeting"}
GROUPS = [("waiting", "Waiting on you"), ("progress", "In progress"), ("idle", "Idle"), ("done", "Done")]


def activity_path() -> Path:
    env = os.environ.get("IMP_ACTIVITY")
    return Path(env) if env else Path.home() / ".config" / "imp" / "activity"


def load_sessions(now: float) -> list:
    """Activity files written by hooks/activity.py; deletes ones silent for over a day."""
    sessions = []
    for f in sorted(activity_path().glob("*.json")):
        try:
            s = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if now - (s.get("last_seen") or 0) > 86400:
            f.unlink(missing_ok=True)
            continue
        s["_sid"] = f.stem  # becomes a hash in the rooms API, so the page never sees the file name
        sessions.append(s)
    return sessions


def _live(s: dict, now: float) -> bool:
    return s.get("state") != "ended" and now - (s.get("last_seen") or 0) < LIVE_SECS


def _agents(sessions: list) -> str:
    names = {t.split(":")[-1] for s in sessions for t in (s.get("agents") or {}).values()}
    return ", ".join(sorted(names))


def _day(value: str):
    """The date of a `YYYY-MM-DD` string, else None."""
    try:
        return date.fromisoformat(value) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or "") else None
    except ValueError:
        return None


def classify(idea: dict, sessions: list, now: float) -> tuple:
    """(group, note) for one idea; `sessions` are the ones linked to it."""
    live = [s for s in sessions if _live(s, now)]
    states = {s.get("state") for s in live}
    gate = GATES.get(idea.get("gate") or "", idea.get("gate") or "")
    stage = idea.get("stage") or ""
    if stage == "done":
        return "done", ""
    if "needs_permission" in states:
        return "waiting", "permission prompt"
    if "waiting_reply" in states:
        return "waiting", gate or "your reply"
    if "working" in states:
        return "progress", _agents(live) or "working"
    try:
        days = (date.fromtimestamp(now) - date.fromisoformat(idea.get("last_update") or "")).days
    except ValueError:
        days = 0
    if stage == "monitor":  # quiet between checks by design, so never stale
        if (idea.get("next_check") or "9999") <= date.fromtimestamp(now).isoformat():
            return "waiting", "monitoring check due"
        return "idle", f"monitoring until {idea.get('monitor_until') or '?'}"
    due = _day(idea.get("due") or "")  # a malformed date is never compared; `agenda` reports it
    if due and due < date.fromtimestamp(now) and stage not in ("backlog", "shelved"):
        return "waiting", f"due {due.isoformat()}"
    if stage in ("backlog", "shelved") or days >= STALE_DAYS:
        return "idle", stage if stage in ("backlog", "shelved") else f"{days}d without update"
    if idea.get("waiting_on") == "user":
        return "waiting", gate or "waiting on you"
    return "idle", ""


def dashboard_rows(now: float, sessions=None) -> list:
    """(group, note, idea, sessions) for every idea in the registry."""
    sessions = load_sessions(now) if sessions is None else sessions
    rows = []
    for root in load_registry():
        if not (root / PROJECT_FILE).is_file():
            continue
        name = project_config(root)["name"]
        for idea in find_ideas(root):
            folder = str((root / idea["_path"]).parent)
            anchor, by_id = idea_anchor(root, idea)  # by_id: the link a brief makes
            mine = [s for s in sessions if s.get("idea") and (
                s["idea"] in (anchor, by_id) or s["idea"].startswith(anchor + "/"))]
            group, note = classify(idea, mine, now)
            rows.append((group, note, dict(idea, project=name, _folder=folder), mine))
    return rows


def _section(body: str, title: str) -> list:
    """Lines under `## <title>` up to the next `## `."""
    out, on = [], False
    for line in body.splitlines():
        if line.startswith("## "):
            on = line[3:].strip().lower() == title.lower()
        elif on:
            out.append(line)
    return out


def _hypothesis(plan: Path) -> str:
    try:
        for line in plan.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\*\*Hypothesis[^*]*\*\*:?\s*(.*)", line)
            if m:
                return m.group(1).strip()
    except OSError:
        pass
    return ""


def _body(path: Path) -> str:
    """The file's text after its frontmatter."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.split("\n---", 1)[1] if text.startswith("---") and "\n---" in text else text


def _open_questions(body: str) -> list:
    """Bullet texts under `## Open questions`; a wrapped line or sub-bullet joins its bullet."""
    texts = []
    for line in _section(body, "Open questions"):
        if re.match(r"[-*](\s|$)", line):
            texts.append(" ".join(line.split()[1:]))
        elif texts and line[:1] in (" ", "\t") and line.strip():  # sub-bullet or wrapped line: part of the bullet
            texts[-1] = f"{texts[-1]} {line.strip()}".strip()
    return [q for q in texts if q and not re.fullmatch(r"<.*>", q)]


TASK = re.compile(r"\s*[-*] \[([ xX])\] T(\d+):\s*(.*)")
TAG = re.compile(r"\s*\((due|remind|done) ([^()]*)\)\s*$")


def _tasks(text: str) -> list:
    """Task lines `- [ ] T1: text (due YYYY-MM-DD) (remind YYYY-MM-DD HH:MM)`, done `- [x] T1: text (done YYYY-MM-DD)`."""
    out = []
    for line in text.splitlines():
        m = TASK.fullmatch(line.rstrip())
        if not m:
            continue
        rest, tags = m.group(3), {}
        while t := TAG.search(rest):  # tags trail the text, in any order
            tags[t.group(1)] = t.group(2).strip()
            rest = rest[:t.start()]
        out.append({"n": int(m.group(2)), "done": m.group(1) != " ", "text": rest.strip(),
                    "due": tags.get("due", ""), "remind": tags.get("remind", ""), "done_on": tags.get("done", "")})
    return out


VERDICTS = ["worked", "worse", "no effect", "inconclusive", "broken"]


def notion_export(now: float) -> dict:
    """Projects and tasks of the repos with `notion: on`. Reads only each idea's own file (STATUS.md or flat note) and each round's plan.md Hypothesis line."""
    roots = [r for r in load_registry() if (r / PROJECT_FILE).is_file()]
    names = [project_config(r)["name"] for r in roots]
    on = {project_config(r)["name"]: r for r in roots if project_config(r).get("notion") == "on"}
    for name in on:
        if names.count(name) > 1:
            paths = ", ".join(str(r) for r in roots if project_config(r)["name"] == name)
            raise ValueError(f"two registered projects are named '{name}' ({paths}); rename one in .imp/project.md")
    projects, tasks, warnings = [], [], []
    for _, _, idea, _ in dashboard_rows(now, sessions=[]):  # [] so the activity files are not cleaned up
        repo = idea["project"]
        if repo not in on:
            continue
        parts = Path(idea["_path"]).parts
        if {"db", "local"} & set(parts):  # db/ and local/ dumps: never read, never listed
            continue
        if not idea.get("id"):
            warnings.append(f"{repo}: {idea['_path']} skipped (no id)")
            continue
        root = on[repo]
        body = _body(root / idea["_path"])
        key = f"{repo}/{idea['id']}"
        decided = re.search(r"^- (\d{4}-\d{2}-\d{2})", "\n".join(_section(body, "Decisions")), re.M)
        blocked = idea.get("blocked_by") or ""
        domain, _, use_case = (idea.get("group") or "").partition("/")
        ur = (idea.get("ur") or "").strip()
        projects.append({
            "imp_id": key, "ur_id": ur, "source": "MKT request" if ur else "Internal", "name": idea.get("title") or idea["id"], "repo": repo,
            "kind": idea.get("kind") or project_config(root)["kind"], "group": (idea.get("group") or "").strip(),
            "domain": domain.strip(),
            "use_case": use_case.strip(), "stage": idea.get("stage") or "", "gate": idea.get("gate") or "",
            "waiting_on": idea.get("waiting_on") or "", "round": idea.get("round") or "",
            "next_step": idea.get("next_step") or "", "branch": idea.get("branch") or "",
            "blocked_by": (blocked if "/" in blocked else f"{repo}/{blocked}") if blocked else "",
            "start": idea.get("started") or (decided.group(1) if decided else ""),
            "end": idea.get("due") or idea.get("monitor_until") or idea.get("last_update") or "", "path": idea["_path"]})
        rows = {}
        for line in _section(body, "Rounds"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            num = cells[0].lstrip("rR")
            if line.lstrip().startswith("|") and len(cells) >= 6 and num.isdigit() and not any("<" in c for c in cells):
                rows[int(num)] = cells
        last = int(idea["round"]) if (idea.get("round") or "").isdigit() else 0
        past = idea.get("stage") in ("ship", "monitor", "document", "done")
        for n in range(1, last + 1):
            c = rows.get(n) or [""] * 6
            hyp = c[1] or _hypothesis((root / idea["_path"]).parent / "rounds" / f"r{n}" / "plan.md")
            words = c[3].lower().split()
            verdict = " ".join(words[:2]) if words[:2] == ["no", "effect"] else (words[0] if words else "")
            if verdict not in VERDICTS:
                if c[3]:
                    warnings.append(f"{key}/r{n}: verdict '{c[3]}' is not one of {', '.join(VERDICTS)}; left blank")
                verdict = ""
            tasks.append({"task_id": f"{key}/r{n}", "project": key, "name": f"R{n}: {hyp}" if hyp else f"R{n}",
                          "type": "round", "status": "Done" if c[3] or n < last or past else "Open",
                          "verdict": verdict, "branch_sha": c[2], "result": c[5]})
        texts = _open_questions(body)
        labels = [m.group(1) if (m := re.match(r"([A-Z]{1,2}\d+)\b", q)) else "" for q in texts]
        seen = set()
        for q, label in zip(texts, labels):
            k = label if label and labels.count(label) == 1 else hashlib.sha1(q.encode()).hexdigest()[:8]
            if k not in seen:  # an identical bullet twice is one task
                seen.add(k)
                tasks.append({"task_id": f"{key}/q/{k}", "project": key, "name": q, "type": "question",
                              "status": "Open", "verdict": "", "branch_sha": "", "result": ""})
    return {"projects": projects, "tasks": tasks, "warnings": warnings}


# --- secretary ---------------------------------------------------------------

AGENDA = [("overdue", "Overdue"), ("due", "Due soon"), ("checks", "Monitor checks"),
          ("gates", "Waiting on you at a gate"), ("tasks", "Open tasks")]


def secretary_path() -> Path:
    env = os.environ.get("IMP_SECRETARY")
    return Path(env) if env else Path.home() / ".config" / "imp" / "secretary"


def agenda(now: float, days: int = 7, new: bool = False) -> dict:
    """{"today", "sections": {name: [item]}, "problems"} from every registered idea and the secretary's tasks.md.

    Every run records what it reported in a per-day seen-file; `new` keeps only items not reported before today."""
    today = date.fromtimestamp(now)
    sections = {k: [] for k, _ in AGENDA}
    problems = []
    roots = [r for r in load_registry() if (r / PROJECT_FILE).is_file()]
    notion = {project_config(r)["name"] for r in roots if project_config(r).get("notion") == "on"}

    def day(value, ref, field, fmt="YYYY-MM-DD"):  # malformed: reported, never compared
        d = _day(value)
        if value and not d:
            problems.append(f"{ref}: {field} '{value}' is not {fmt}")
        return d

    def due_section(value, ref):
        d = day(value, ref, "due")
        return None if not d else "overdue" if d < today else "due" if (d - today).days <= days else None

    def today_note(value, other):  # "due today" makes the morning notice; the seen-file is per day
        return "due today" if _day(value) == today else other

    def add_tasks(tasks, prefix, keyed, path):
        for t in tasks:
            ref = f"{prefix}/T{t['n']}"
            stamp = t["remind"]
            if stamp and not (re.fullmatch(r"(\S+) \d{2}:\d{2}", stamp) and _day(stamp.split()[0])):
                problems.append(f"{ref}: remind '{stamp}' is not YYYY-MM-DD HH:MM")
            if t["done"]:
                continue
            sections[due_section(t["due"], ref) or "tasks"].append(
                {"kind": "task", "ref": ref, "key": ref if keyed else "", "text": t["text"], "note": today_note(t["due"], ""),
                 "due": t["due"], "remind": stamp, "path": str(path)})

    for _, _, idea, _ in dashboard_rows(now, sessions=[]):  # [] so the activity files are not cleaned up
        stage = idea.get("stage") or ""
        if stage in HIDDEN:
            continue
        path = Path(idea["_folder"]) / Path(idea["_path"]).name
        ref = f"{idea['project']}/{idea.get('id') or idea['_path']}"
        item = {"kind": "idea", "ref": ref, "key": "", "text": idea.get("title") or "", "note": stage,
                "due": idea.get("due") or "", "remind": "", "path": str(path)}
        sec = due_section(idea.get("due") or "", ref)
        if sec and stage not in ("backlog", "monitor"):  # a monitored idea is listed by its checks instead
            sections[sec].append(dict(item, note=today_note(item["due"], stage)))
        if stage == "monitor":
            check = day(idea.get("next_check") or "", ref, "next_check")
            until = day(idea.get("monitor_until") or "", ref, "monitor_until")
            if check and check <= today:
                sections["checks"].append(dict(item, note=f"check due {check.isoformat()}"))
            if until and until <= today:
                sections["checks"].append(dict(item, note=f"monitor_until {until.isoformat()} reached"))
        try:
            body = _body(path)
        except OSError:
            continue
        if idea.get("waiting_on") == "user" and idea.get("gate"):
            sections["gates"].append(dict(item, note=GATES.get(idea["gate"], idea["gate"]),
                                          questions=_open_questions(body)))
        keyed = idea["project"] in notion and idea.get("id") and not {"db", "local"} & set(Path(idea["_path"]).parts)
        add_tasks(_tasks("\n".join(_section(body, "Tasks"))), ref, keyed, path)

    loose = secretary_path() / "tasks.md"
    if loose.is_file():
        add_tasks(_tasks(loose.read_text(encoding="utf-8", errors="replace")), "secretary", True, loose)

    seen_file = secretary_path() / f"seen-{today.isoformat()}.txt"
    seen = set(seen_file.read_text().splitlines()) if seen_file.is_file() else set()
    ids = {f"{s}|{i['ref']}|{i['note']}" for s, items in sections.items() for i in items} | {f"problem|{p}" for p in problems}
    if new:
        sections = {s: [i for i in items if f"{s}|{i['ref']}|{i['note']}" not in seen] for s, items in sections.items()}
        problems = [p for p in problems if f"problem|{p}" not in seen]
    if ids - seen:
        seen_file.parent.mkdir(parents=True, exist_ok=True)
        for old in seen_file.parent.glob("seen-*.txt"):
            if old != seen_file:
                old.unlink(missing_ok=True)
        with seen_file.open("a") as f:
            f.write("".join(f"{i}\n" for i in sorted(ids - seen)))
    return {"today": today.isoformat(), "sections": sections, "problems": problems}


def format_agenda(a: dict, new: bool = False) -> str:
    lines = []
    for key, title in AGENDA:
        if a["sections"][key]:
            lines.append(title)
        for i in a["sections"][key]:
            bits = [i["ref"], i["text"], i["note"], i["due"] and f"due {i['due']}", i["remind"] and f"remind {i['remind']}"]
            lines.append("  " + "  ".join(b for b in bits if b))
            lines += [f"    ? {q}" for q in i.get("questions") or []]
    if a["problems"]:
        lines += ["Problems"] + [f"  {p}" for p in a["problems"]]
    return "\n".join(lines) or ("nothing new" if new else "nothing due")


def journal(now: float, today_only: bool = False) -> list:
    """(HH:MM, project/id) for ideas the sessions of the last day touched, latest first; reads the activity
    files without `load_sessions`, which deletes old ones. A file keeps only each session's latest idea."""
    found = [(r, project_config(r)["name"], find_ideas(r)) for r in load_registry() if (r / PROJECT_FILE).is_file()]
    last = {}
    for f in activity_path().glob("*.json"):
        try:
            s = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        seen = s.get("last_seen") or 0
        if not s.get("idea") or now - seen > 86400 or (today_only and date.fromtimestamp(seen) != date.fromtimestamp(now)):
            continue
        for root, name, ideas in found:
            hit = owner(root, ideas, s["idea"])
            if hit:
                ref = f"{name}/{hit.get('id') or hit['_path']}"
                last[ref] = max(last.get(ref, 0), seen)
                break
    return [(time.strftime("%H:%M", time.localtime(t)), ref) for ref, t in sorted(last.items(), key=lambda x: -x[1])]


TRACK = ["G1", "G-data", "G2", "G3"]
NEXT_GATE = {"pitch": "G1", "experiment": "G2", "ship": "G3", "monitor": "G-data", "document": "G3"}
SPAN = 3600  # timeline window, seconds


def stat_counts(rows: list, sessions: list, now: float) -> dict:
    counts = {key: 0 for key, _ in GROUPS}
    for r in rows:
        counts[r[0]] += 1
    counts["agents"] = sum(len(s.get("agents") or {}) for s in sessions if _live(s, now))
    return counts


def gate_track(idea: dict) -> list:
    """(gate, mark) for G1 -> G-data -> G2 -> G3; mark is 'cur' (stopped there), 'next' or ''."""
    cur = idea.get("gate") or ""
    nxt = "" if cur else NEXT_GATE.get(idea.get("stage") or "", "")
    return [(g, "cur" if g == cur else "next" if g == nxt else "") for g in TRACK]


def timeline(changes: list, start: float, end: float) -> list:
    """(t0, t1, state) segments of `changes` ([[ts, state], ...]) clipped to [start, end]; 'ended' dropped."""
    segs = []
    for i, (ts, state) in enumerate(changes):
        t1 = changes[i + 1][0] if i + 1 < len(changes) else end
        t0, t1 = max(ts, start), min(t1, end)
        if t1 > t0 and state != "ended":
            segs.append((t0, t1, state))
    return segs


# Sequence diagram per idea: who hands what to whom in each stage (lifecycle.md).
SEQ = {
    "pitch": [("chief", "researcher", "recon"), ("chief", "you", "G1 plan"), ("you", "chief", "go"),
              ("chief", "presenter", "pitch deck"), ("chief", "reviewer", "check"), ("chief", "you", "meeting")],
    "experiment": [("chief", "you", "G1 plan"), ("you", "chief", "go"), ("chief", "builder", "brief"),
                   ("builder", "chief", "commits"), ("chief", "reviewer", "check"), ("reviewer", "chief", "PASS/BLOCK"),
                   ("chief", "you", "G2 diff"), ("you", "chief", "results / notes")],
    "ship": [("chief", "you", "G1 plan"), ("you", "chief", "go"), ("chief", "builder", "feature branch"),
             ("chief", "reviewer", "check"), ("chief", "you", "G2 merge"), ("you", "chief", "G3 tested")],
    "monitor": [("chief", "you", "check (G-data)"), ("you", "chief", "results"), ("chief", "you", "holds / fix")],
    "document": [("chief", "presenter", "docs"), ("chief", "you", "done")],
}
ACTORS = ["you", "chief", "researcher", "builder", "reviewer", "presenter"]
RESEARCHERS = {"business-researcher", "tech-researcher", "code-investigator", "data-analyst", "researcher"}
CHECKERS = {"verifier", "claim-checker"}  # drawn on the reviewer's lifeline
# G-data has no message of its own: it sits before the deck in a pitch and with the results in a round
GDATA_STEP = {"pitch": "pitch deck", "experiment": "results / notes"}
MARKETING_STEP = {"pitch": "meeting", "experiment": "results / notes"}


def _actor(agent_type: str) -> str:
    name = agent_type.split(":")[-1]
    return "researcher" if name in RESEARCHERS else "reviewer" if name in CHECKERS else name


def sequence(idea: dict, live: list) -> tuple:
    """(participants [(name, live)], messages [(from, to, label, status)]) for one idea.

    `live` are the idea's live sessions. status is done / current / next; stages without
    a sequence (backlog, shelved, done) give ([], [])."""
    stage = idea.get("stage") or ""
    steps = SEQ.get(stage)
    if not steps:
        return [], []
    labels = [s[2] for s in steps]
    running = {_actor(t) for s in live for t in (s.get("agents") or {}).values()}
    gate = idea.get("gate") or ""
    waiting_on = idea.get("waiting_on") or ""

    def at(label):
        return labels.index(label) if label in labels else None

    def gate_at(g):
        if g == "G-data":
            return at(GDATA_STEP.get(stage, ""))
        return next((n for n, l in enumerate(labels) if l.split()[0] == g), None)

    cur = gate_at(gate) if gate else None
    if cur is None:  # a running agent: the last message it takes part in
        hits = [n for n, (a, b, _) in enumerate(steps) if a in running or b in running]
        cur = max(hits) if hits else None
    if cur is None and waiting_on == "user":
        cur = gate_at(NEXT_GATE.get(stage, ""))
        cur = len(steps) - 1 if cur is None else cur
    if cur is None and waiting_on == "marketing":
        cur = at(MARKETING_STEP.get(stage, ""))
    if cur is None:  # agents at work with no gate: the step after the G1 go-ahead
        cur = at("go") + 1 if "go" in labels else 0
    used = {p for a, b, _ in steps for p in (a, b)}
    people = [(p, p in running) for p in ACTORS if p in used]
    msgs = [(a, b, l, "done" if n < cur else "current" if n == cur else "next") for n, (a, b, l) in enumerate(steps)]
    return people, msgs


ICONS = {  # 24x24 line icons centred on 0,0
    "you": '<circle cx="0" cy="-4" r="4"/><path d="M-7 8a7 6 0 0 1 14 0"/>',
    "chief": '<rect x="-6" y="-7" width="12" height="15" rx="2"/><path d="M-3-7v-2h6v2M-3-1h6M-3 3h6"/>',
    "researcher": '<circle cx="-2" cy="-2" r="5"/><path d="M2 2l5 5"/>',
    "builder": '<path d="M-6 7l7-7M-2-3l4-4 5 5-4 4z"/>',
    "reviewer": '<path d="M-6 0l4 4 8-8"/>',
    "presenter": '<rect x="-8" y="-7" width="16" height="10" rx="1"/><path d="M0 3v5M-4 8h8"/>',
}
NODE_COLOR = {"you": "amber", "chief": "blue"}
COL_W, ROW, TOP = 140, 18, 80


def sequence_svg(people: list, msgs: list) -> str:
    e = html.escape
    col = COL_W  # drawn 1:1 (width = viewBox), so labels are never scaled; centred in .seqwrap
    xs = {p: col // 2 + n * col for n, (p, _) in enumerate(people)}
    h = TOP + ROW * len(msgs)
    w = col * len(people)
    out = [f'<div class="seqwrap" style="--w:{w}px"><svg class="seq" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    for p, live in people:
        x = xs[p]
        out.append(f'<line class="life" x1="{x}" y1="56" x2="{x}" y2="{h - 4}"/>'
                   f'<g class="node c-{NODE_COLOR.get(p, "green" if live else "blue")}{" live" if live else ""}" transform="translate({x} 26)">'
                   f'<circle r="18"/><g class="ico">{ICONS.get(p, "")}</g></g>'
                   f'<text class="who" x="{x}" y="60">{e(p)}</text>')
    for n, (a, b, label, status) in enumerate(msgs):
        y, x1, x2 = TOP + ROW * n, xs[a], xs[b]
        d = 1 if x2 > x1 else -1
        gate = "you" in (a, b) and label.split()[0] in GATES
        text = ("◆ " if gate else "") + label
        out.append(f'<g class="msg {status}"><line x1="{x1 + 8 * d}" y1="{y}" x2="{x2 - 8 * d}" y2="{y}"/>'
                   f'<path d="M{x2 - 8 * d} {y}l{-7 * d} -4v8z"/>'
                   f'<text x="{(x1 + x2) // 2}" y="{y - 6}">{e(text)}</text>')
        if status == "current":
            out.append(f'<circle class="dot" cx="{x1 + 8 * d}" cy="{y}" r="4" style="--d:{(x2 - x1) - 16 * d}px"/>')
        out.append("</g>")
    return "".join(out) + "</svg></div>"


def banner_state(rows: list, agents: int) -> dict:
    """What the top banner shows: mood waiting > working > idle, plus counts and the most urgent gate."""
    waiting = sorted((r for r in rows if r[0] == "waiting"),
                     key=lambda r: (r[1] != "permission prompt", r[2].get("last_update") or ""))
    working = any(r[0] == "progress" for r in rows) or agents > 0
    mood = "waiting" if waiting else "working" if working else "idle"
    gate = (waiting[0][2].get("gate") or "you") if waiting else ""
    return {"mood": mood, "agents": agents, "waiting": len(waiting), "gate": gate}


# one column set, fixed widths (px; None shares the rest), for every group table
COLS = [("now", 140), ("project", 100), ("id", 140), ("title", None), ("stage", 110), ("gates", 280),
        ("agents", 120), ("next_step", None), ("branch", 170), ("last_update", 100)]


def _td(text) -> str:
    t = html.escape(text or "")
    # tooltip only past 8 chars, shorter text never reaches a column's edge
    return f'<td title="{t}">{t}</td>' if len(text or "") > 8 else f"<td>{t}</td>"


def _pill(group: str, note: str) -> str:
    kind = "red" if note == "permission prompt" else {"waiting": "amber", "progress": "blue", "done": "green"}.get(group, "grey")
    return f'<span class="pill {kind}">{html.escape(note or group)}</span>'


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<noscript><meta http-equiv="refresh" content="5"></noscript><title>imp ideas</title><style>
:root{--bg:#111217;--panel:#181b1f;--border:#2c3235;--text:#d8d9da;--muted:#8e9297;--head:#1f2226;
--red:#f2495c;--amber:#ff9830;--blue:#5794f2;--green:#73bf69;--grey:#6e7680}
@media (prefers-color-scheme:light){:root{--bg:#f4f5f5;--panel:#fff;--border:#d8dadd;--text:#24292e;
--muted:#6a737d;--head:#f0f1f3;--red:#d4374a;--amber:#e07b00;--blue:#3871dc;--green:#3d9a37;--grey:#8a9099}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:13px system-ui,sans-serif}
.top{display:flex;flex-wrap:wrap;gap:16px;align-items:center;padding:8px 16px;border-bottom:1px solid var(--border);background:var(--panel)}
.top b{font-size:15px}.top span,.top label{color:var(--muted)}.top a{color:var(--blue)}#ts{font-family:ui-monospace,monospace;color:var(--text)}
#panels{display:grid;gap:8px;padding:8px}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:3px;min-width:0}
.panel h3{margin:0;padding:6px 10px;font-size:12px;font-weight:500;color:var(--muted);border-bottom:1px solid var(--border);background:var(--head)}
.wide{overflow-x:auto;container-type:inline-size}
.stat div{padding:10px 12px;font:600 40px ui-monospace,monospace}
.c-red{color:var(--red)}.c-amber{color:var(--amber)}.c-blue{color:var(--blue)}.c-green{color:var(--green)}.c-grey{color:var(--grey)}
table{border-collapse:collapse;width:100%}th,td{padding:5px 10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:500}.empty{padding:10px;color:var(--muted)}
.pill{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;vertical-align:top;padding:1px 8px;border-radius:10px;font-size:12px;color:#fff;white-space:nowrap}
.pill.red{background:var(--red)}.pill.amber{background:var(--amber)}.pill.blue{background:var(--blue)}
.pill.green{background:var(--green)}.pill.grey{background:var(--grey)}
.track{white-space:nowrap;color:var(--muted);font-family:ui-monospace,monospace}.track .cur{color:#fff;background:var(--amber);padding:0 4px;border-radius:2px}
.track .next{color:var(--text);border:1px solid var(--amber);padding:0 3px;border-radius:2px}
.tl{display:grid;grid-template-columns:minmax(120px,220px) 1fr;gap:4px 10px;padding:10px;align-items:center}
.tl .lab{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.tl svg{width:100%;height:16px;display:block;background:var(--head)}
.axis{position:relative;height:14px;color:var(--muted);font:11px ui-monospace,monospace}.axis span{position:absolute;transform:translateX(-50%)}
.axis span:first-child{transform:none}.axis span:last-child{transform:translateX(-100%)}
.legend{padding:0 10px 10px;color:var(--muted)}.legend i{display:inline-block;width:10px;height:10px;margin:0 4px 0 12px}
#banner,.seqwrap{width:50%;min-width:min(100%,max(480px,var(--w,0px)));margin:0 auto}
#banner{padding:6px 16px;height:calc(5em + 12px);font:13px/1 ui-monospace,Menlo,Consolas,monospace;
background:var(--bg);border-bottom:1px solid var(--border);overflow:hidden;white-space:pre;color:var(--text)}
svg.pix{vertical-align:top;height:1em}.c-text{color:var(--text)}.c-muted{color:var(--muted)}.top select{background:var(--head);color:var(--text);border:1px solid var(--border)}
table{table-layout:fixed;min-width:1400px}td{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.seqrow>td{white-space:normal;overflow:visible;padding:0 10px 8px}
.seqrow details{position:sticky;left:10px;width:min(100%,calc(100cqw - 20px))}
details summary{cursor:pointer;color:var(--muted);font-size:12px;padding:3px 0}
.seqwrap{width:calc(50cqw + 9px);background:#08090b;border-radius:4px;overflow-x:auto}/* 50% of body: body = 100cqw + 16px #panels padding + 2px border */svg.seq{display:block;margin:0 auto;font:11px system-ui,sans-serif}
.seq .life{stroke:#3a4046;stroke-dasharray:3 4}.seq .who{fill:#9aa0a6;text-anchor:middle}
.seq .node circle{fill:#0d0f12;stroke:currentColor;stroke-width:1.5;filter:drop-shadow(0 0 4px currentColor)}
.seq .ico{fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.seq .node.live circle{stroke-width:2.5;animation:glow 1.4s ease-in-out infinite alternate}
@keyframes glow{to{filter:drop-shadow(0 0 11px currentColor)}}
.seq .msg line{stroke-width:1.5}.seq .msg text{text-anchor:middle}
.msg.done line{stroke:#6e7680;opacity:.5}.msg.done path{fill:#6e7680;opacity:.5}.msg.done text{fill:#6e7680}
.msg.current line{stroke:#ff9830;stroke-width:2;filter:drop-shadow(0 0 3px #ff9830)}.msg.current path{fill:#ff9830}
.msg.current text{fill:#ff9830;font-weight:600}
.msg.next line{stroke:#4a5057;stroke-dasharray:4 3}.msg.next path{fill:#4a5057}.msg.next text{fill:#8e9297}
.seq .dot{fill:#fff3d6;filter:drop-shadow(0 0 5px #ff9830);animation:run 1.8s linear infinite}
@keyframes run{to{transform:translateX(var(--d))}}
@media (prefers-reduced-motion:reduce){.seq .dot,.seq .node.live circle{animation:none}}
</style></head><body><div class="top"><b>imp ideas</b><span>last refreshed <span id="ts">{ts}</span></span>
<span>every 5s</span><a href="/rooms">Rooms</a><label>character <select id="char"><option>fish</option><option>train</option>
<option>ants</option></select></label><form><label><input type="checkbox" name="done" value="1"{checked} onchange="this.form.submit()"> show finished</label></form></div>
<pre id="banner" aria-hidden="true"></pre>
<div id="panels">{panels}</div>
<script>
// banner frames: each frame is a pure function of (tick, width, data),
// so "random" is a hash; data is {mood, agents, waiting, gate} from #mood
var ROWS = 5;
function hash(a, b) {
  var x = (Math.imul(a, 374761393) + Math.imul(b || 0, 668265263)) | 0;
  x = Math.imul(x ^ (x >>> 13), 1274126177);
  return (x ^ (x >>> 16)) >>> 0;
}
function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function rowHtml(row, cw) {  // runs of one class become one span, or one svg for "pix" cells
  var out = "", run = "", cl = row.cl[0];
  for (var x = 0; x <= row.ch.length; x++) {
    if (x === row.ch.length || row.cl[x] !== cl) {
      out += /^pix /.test(cl) ? pixSvg(run, cw, cl) : cl ? '<span class="' + cl + '">' + esc(run) + "</span>" : esc(run);
      run = "";
      cl = row.cl[x];
    }
    if (x < row.ch.length) run += row.ch[x];
  }
  return out;
}
function bounce(n, max) { var p = n % (2 * max); return p <= max ? p : 2 * max - p; }
function grid(w) {
  var g = [];
  for (var y = 0; y < ROWS; y++) g.push({ch: Array(w).fill(" "), cl: Array(w).fill("")});
  g.w = w;
  return g;
}
// stamps `s` into row y at x, clipped at both edges; spaces are see-through
function put(g, y, x, s, cl) {
  var row = g[y], chars = Array.from(s);
  if (!row) return;
  for (var i = 0; i < chars.length; i++) {
    var at = x + i;
    if (at >= 0 && at < g.w && chars[i] !== " ") { row.ch[at] = chars[i]; row.cl[at] = cl || ""; }
  }
}
function capText(d) {
  return d.mood === "waiting" ? d.waiting + " waiting on you"
    : d.mood === "working" ? (d.agents ? d.agents + (d.agents === 1 ? " agent" : " agents") + " working" : "working")
    : "all quiet";
}
function caption(g, d) {
  var s = capText(d);
  put(g, 0, g.w - s.length - 1, s, d.mood === "waiting" ? "c-amber" : "c-muted");
  return g;
}

// fonts draw block glyphs at their own size and offset, so "pix" cells (the anthill) are drawn as 2x2 pixels: 1 TL, 2 TR, 4 BL, 8 BR
var PX = {"▘": 1, "▝": 2, "▀": 3, "▖": 4, "▌": 5, "▞": 6, "▛": 7, "▗": 8, "▚": 9, "▐": 10, "▜": 11, "▄": 12, "▙": 13, "▟": 14, "█": 15};
function pixSvg(s, cw, cl) {  // one svg per run of cells, each pixel row merged into solid rects
  var cells = Array.from(s), n = cells.length, out = "", py;
  function on(p) { return p < 2 * n && (PX[cells[p >> 1]] || 0) & (1 << (py * 2 + (p & 1))); }
  for (py = 0; py < 2; py++)
    for (var px = 0; px < 2 * n; px++) {
      if (!on(px)) continue;
      for (var end = px; on(end + 1); end++);
      out += '<rect x="' + px + '" y="' + py + '" width="' + (end - px + 1) + '" height="1"/>';
      px = end;
    }
  return '<svg class="' + cl + '" style="width:' + n * cw + 'px" viewBox="0 0 ' + 2 * n + ' 2" preserveAspectRatio="none"'
    + ' shape-rendering="crispEdges" fill="currentColor">' + out + "</svg>";
}
var FR = ["><(((º>", "><>", ">=>"], FL = ["<º)))><", "<><", "<º)><"], LANE = ["c-amber", "c-blue", "c-green", "c-red"];
function fish(t, w, d) {
  var g = grid(w), i, h, body, at, slow = d.mood === "idle" ? 4 : 1;
  for (var x = 0; x < w; x++) if ((x + Math.floor(t / (3 * slow))) % 7 === 0) put(g, 0, x, "~", "c-blue");
  if (d.mood === "working") {  // schools swimming across, more and faster with more agents
    var a = Math.min(d.agents, 4), n = Math.max(4, Math.round(w / 20)) + 2 * a;
    for (i = 0; i < n; i++) {
      h = hash(i, 3);
      var right = (h & 1) === 1;
      body = (right ? FR : FL)[(h >>> 1) % 3];
      at = (Math.floor(t * (1 + a) / (2 + ((h >>> 4) % 3))) + (h >>> 8)) % (w + body.length);
      put(g, 1 + i % 4, right ? at - body.length : w - at, body, LANE[i % 4]);
    }
  } else if (d.mood === "waiting") {  // turn to the front, bob, blow ? bubbles
    var m = Math.max(3, Math.min(2 * d.waiting, 8)), gap = Math.floor(w / m);
    for (i = 0; i < m; i++) {
      var fx = Math.floor(gap * i + gap / 2) - 3, fy = 3 + Math.floor(t / 3 + i) % 2, p = (Math.floor(t / 2) + i * 2) % 4;
      put(g, fy, fx, "(ºoº)", LANE[i % 4]);
      if (p < 3) put(g, fy - 1 - p, fx + 2 + (p === 2 ? 1 : 0), ["°", "o", "?"][p], p === 2 ? "c-amber" : "c-muted");
    }
  } else {  // a few fish drift slowly near the bottom
    for (i = 0; i < 3; i++) {
      h = hash(i, 5);
      body = (h & 1) ? FR[1] : FL[1];
      at = (Math.floor(t / 6) + (h >>> 8)) % (w + 3);
      put(g, 3 + i % 2, (h & 1) ? at - 3 : w - at, body, LANE[i % 4]);
    }
  }
  return caption(g, d);
}

var LOCO = ["   _||___  ", " _|[]|   |>", "=(o)--(o)=-"], CAR = [" _______ ", "|[] [] |=", "-(o)-(o)-"];
var STATION = ["  ________ ", " | ▫ ▫ ▫  |", "_|________|_"];
function drawTrain(g, x, cars, on) {
  for (var r = 0; r < 3; r++)
    put(g, r + 1, x, CAR[r].repeat(cars) + LOCO[r], r === 1 ? (on ? "c-amber" : "c-grey") : on ? "c-text" : "c-grey");
  return x + 9 * cars + 4;  // chimney
}
function train(t, w, d) {
  var g = grid(w), cars, len, x, chim, k;
  put(g, 4, 0, Array(w + 1).join("═"), "c-grey");
  if (d.mood === "working") {  // runs along with steam puffs, one carriage per agent
    cars = Math.max(1, Math.min(d.agents, 6));
    len = 9 * cars + 11;
    x = t % (w + len) - len;
    chim = drawTrain(g, x, cars, true);
    for (k = 0; k < 4; k++) put(g, k < 2 ? 0 : 1, chim - 2 - k * 3 - t % 3, ["O", "o", "°", "·"][k], "c-muted");
  } else if (d.mood === "waiting") {  // stopped at a red signal labelled with the gate, steam hissing
    var sig = w - 12, label = "◆ " + (d.gate || "you");
    cars = Math.max(1, Math.min(d.waiting, 6));
    len = 9 * cars + 11;
    x = sig - 3 - len;
    chim = drawTrain(g, x, cars, true);
    put(g, 1, sig, "(●)", "c-red");
    put(g, 2, sig + 1, "|", "c-grey");
    put(g, 3, sig + 1, "|", "c-grey");
    put(g, 2, sig + 3, label, "c-amber");
    put(g, 3, x - 2 - t % 2, t % 2 ? "~≈" : "≈~", "c-muted");
    put(g, 0, chim + Math.floor(t / 3) % 2, "°", "c-muted");
  } else {  // parked at the station, lights off
    for (k = 0; k < 3; k++) put(g, k + 1, 2, STATION[k], "c-grey");
    drawTrain(g, 15, 1, false);
  }
  return caption(g, d);
}

var HILL = ["   ▄▄   ", " ▄████▄ ", "▟██████▙"];
function ant(g, y, x, crumb, t) {
  put(g, y, x, (x + t) % 2 ? "ж" : "җ", "c-text");
  if (crumb) put(g, y, x + 1, "▪", "c-amber");
}
function ants(t, w, d) {
  var g = grid(w), k, x;
  if (d.mood === "working") {  // marching lines of crumb carriers, two rows apart, out of step
    var lines = Math.max(1, Math.min(d.agents, 2));
    for (var l = 0; l < lines; l++)
      for (k = 0; k * 6 < w + 6; k++) ant(g, 4 - 2 * l, (k * 6 + t + l * 3) % (w + 6) - 2, (k + l) % 2, t);
  } else if (d.mood === "waiting") {  // bunched up behind a closed gate, the front ones tapping
    var gx = w - 14, n = 6 + 2 * Math.min(d.waiting, 5), tail = gx - 2 - 2 * n;
    for (var r = 1; r < 5; r++) put(g, r, gx, r === 1 ? "┳" : "┃", "c-red");
    put(g, 1, gx + 2, "◆ " + (d.gate || "you"), "c-amber");
    for (k = 0; k < n; k++) ant(g, 4, gx - 2 - 2 * k + (k === 0 ? t % 2 : 0), false, 0);
    for (k = 0; k < n / 2; k++) ant(g, 3, gx - 3 - 2 * k - (k === 0 ? t % 2 : 0), false, 0);
    for (k = 0; k * 5 < tail; k++) { x = (k * 5 + t) % tail; ant(g, 4, x - 2, k % 2, t); }
  } else {  // a small anthill, one ant wandering
    var hx = Math.floor(w / 2) - 4;
    for (k = 0; k < 3; k++) put(g, k + 2, hx, HILL[k], "pix c-amber");
    ant(g, 4, hx - 14 + bounce(Math.floor(t / 2), 36), false, t);
  }
  return caption(g, d);
}
var FRAMES = {fish: fish, train: train, ants: ants};

(function () {
  var pre = document.getElementById("banner"), pick = document.getElementById("char"), kind = "fish", tick = 0, last = 0, cw = 8;
  var still = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  try { kind = localStorage.getItem("imp-char") || "fish"; } catch (e) {}
  var own = function (k) { return Object.prototype.hasOwnProperty.call(FRAMES, k); };
  if (!own(kind)) kind = "fish";
  pick.value = kind;
  pick.onchange = function () {
    kind = own(pick.value) ? pick.value : "fish";
    try { localStorage.setItem("imp-char", kind); } catch (e) {}
    draw();
  };
  function cols() {
    var probe = document.createElement("span");
    probe.textContent = "0000000000";
    pre.appendChild(probe);
    cw = probe.getBoundingClientRect().width / 10 || 8;
    pre.removeChild(probe);
    return Math.max(30, Math.floor((pre.clientWidth - 32) / cw));
  }
  function draw() {
    var m = document.getElementById("mood"), s = m ? m.dataset : {};
    var d = {mood: s.mood || "idle", agents: +s.agents || 0, waiting: +s.waiting || 0, gate: s.gate || ""};
    var w = cols();
    pre.innerHTML = FRAMES[kind](tick, w, d).map(function (row) { return rowHtml(row, cw); }).join("\\n");
  }
  function loop(ts) {  // requestAnimationFrame pauses while the tab is hidden
    if (ts - last >= 160) { last = ts; tick++; draw(); }
    requestAnimationFrame(loop);
  }
  draw();
  if (!still) requestAnimationFrame(loop);
  window.addEventListener("resize", draw);

  // sequence <details>: remember what the user opened or closed, per idea, across refreshes
  var open = {};
  document.addEventListener("toggle", function (ev) {
    var el = ev.target;
    if (!el.dataset || !el.dataset.id) return;
    if (el.open === (el.dataset.open === "1")) delete open[el.dataset.id]; else open[el.dataset.id] = el.open;
  }, true);
  setInterval(function () {
    fetch(location.href, {cache: "no-store"}).then(function (r) { return r.text(); }).then(function (t) {
      var d = new DOMParser().parseFromString(t, "text/html");
      document.getElementById("panels").innerHTML = d.getElementById("panels").innerHTML;
      document.getElementById("ts").textContent = d.getElementById("ts").textContent;
      document.querySelectorAll("details[data-id]").forEach(function (el) {
        if (el.dataset.id in open) el.open = open[el.dataset.id];
      });
      if (still) draw();
    }).catch(function () {});
  }, 5000);
})();
</script></body></html>"""

STATE_COLOR = {"working": "blue", "needs_permission": "red", "waiting_reply": "amber"}


def _timeline_panel(rows: list, sessions: list, now: float) -> str:
    e = html.escape
    labels = {id(s): f"{r[2]['project']}/{r[2].get('id') or '-'}" for r in rows for s in r[3]}
    start = now - SPAN
    lines = []
    for s in sorted(sessions, key=lambda s: s.get("last_seen") or 0, reverse=True):
        if (s.get("last_seen") or 0) < start:
            continue
        end = now if _live(s, now) else min(now, s.get("last_seen") or now)
        segs = timeline(s.get("changes") or [], start, end)
        label = labels.get(id(s)) or os.path.basename(s.get("cwd") or "") or "?"
        rects = "".join(
            f'<rect x="{t0 - start:.0f}" width="{t1 - t0:.0f}" height="10" fill="var(--{STATE_COLOR.get(st, "grey")})">'
            f"<title>{e(st)}</title></rect>" for t0, t1, st in segs)
        lines.append(f'<div class="lab" title="{e(label)}">{e(label)}</div>'
                     f'<svg viewBox="0 0 {SPAN} 10" preserveAspectRatio="none"><title>{e(label)}</title>{rects}</svg>')
    if not lines:
        body = '<div class="empty">no sessions in the last 60 min</div>'
    else:
        ticks = "".join(f'<span style="left:{p}%">{m}</span>' for p, m in [(0, "-60m"), (25, "-45m"), (50, "-30m"), (75, "-15m"), (100, "now")])
        body = f'<div class="tl">{"".join(lines)}<div></div><div class="axis">{ticks}</div></div>'
    legend = "".join(f'<i style="background:var(--{c})"></i>{k}' for k, c in STATE_COLOR.items())
    return f'<div class="panel wide"><h3>State timeline (last 60 min)</h3>{body}<div class="legend">{legend}</div></div>'


def render(rows: list, show_done: bool, now: float, sessions=None) -> str:
    e = html.escape
    sessions = [s for r in rows for s in r[3]] if sessions is None else sessions
    counts = stat_counts(rows, sessions, now)
    tiles = [("Waiting on you", counts["waiting"], "amber"), ("In progress", counts["progress"], "blue"),
             ("Idle", counts["idle"], "grey"), ("Agents running", counts["agents"], "green")]
    if show_done:
        tiles.append(("Done", counts["done"], "green"))
    parts = ['<div class="stats">' + "".join(
        f'<div class="panel stat"><h3>{label}</h3><div class="c-{c}">{n}</div></div>' for label, n, c in tiles) + "</div>"]
    b = banner_state(rows, counts["agents"])
    parts.insert(0, '<div id="mood" hidden' + "".join(f' data-{k}="{e(str(v))}"' for k, v in b.items()) + "></div>")
    colgroup = "<colgroup>" + "".join(f'<col style="width:{w}px">' if w else "<col>" for _, w in COLS) + "</colgroup>"
    for key, label in GROUPS:
        if key == "done" and not show_done:
            continue
        mine = sorted((r for r in rows if r[0] == key), key=lambda r: r[2].get("last_update") or "", reverse=True)
        parts.append(f'<div class="panel wide"><h3>{label} ({len(mine)})</h3>')
        if not mine:
            parts.append('<div class="empty">none</div></div>')
            continue
        parts.append("<table>" + colgroup + "<tr>" + "".join(f"<th>{c}</th>" for c, _ in COLS) + "</tr>")
        for group, note, i, s in mine:
            live = [x for x in s if _live(x, now)]
            stage = (i.get("stage") or "-") + (f" r{i['round']}" if i.get("round") else "")
            if group in ("waiting", "progress"):
                gates = " → ".join(f'<span class="{m}">{g}</span>' if m else g for g, m in gate_track(i))
                if (i.get("gate") or "") not in ("", *TRACK):
                    gates += " · " + e(GATES.get(i["gate"], i["gate"]))
                gates = f'<span class="track">{gates}</span>'
            else:
                gates = e(GATES.get(i.get("gate") or "", i.get("gate") or ""))
            cells = [_td(c) for c in (i["project"], i.get("id"), i.get("title"), stage)]
            cells += [f"<td>{gates}</td>"] + [_td(c) for c in (_agents(live), i.get("next_step"),
                                                             i.get("branch"), i.get("last_update"))]
            parts.append(f"<tr><td>{_pill(group, note)}</td>" + "".join(cells) + "</tr>")
            people, msgs = sequence(i, live)
            if msgs:
                op = group in ("waiting", "progress")
                key = e(f"{i['project']}/{i.get('id') or i.get('_path', '')}")
                parts.append(f'<tr class="seqrow"><td colspan="{len(COLS)}"><details data-id="{key}" data-open="{int(op)}"'
                             f'{" open" if op else ""}><summary>{"sequence" if op else "show sequence"}</summary>'
                             f"{sequence_svg(people, msgs)}</details></td></tr>")
        parts.append("</table></div>")
    parts.append(_timeline_panel(rows, sessions, now))
    page = PAGE.replace("{ts}", time.strftime("%H:%M:%S", time.localtime(now)))
    return page.replace("{checked}", " checked" if show_done else "").replace("{panels}", "".join(parts))


def _h8(text) -> str:
    """Eight hex digits of sha256: a stable id that carries no file name or agent id."""
    return hashlib.sha256(str(text).encode()).hexdigest()[:8]


STAGE_ROOM = {"pitch": "meeting", "experiment": "lab", "ship": "workshop", "monitor": "workshop", "document": "library"}


def _ago(at, now: float) -> str:
    secs = max(0, int(now - (at or now)))
    return f"{secs}s ago" if secs < 60 else f"{secs // 60}m ago"


def agent_says(role: str, where: str, work: dict, now: float) -> str:
    """Two sentences for the rooms page: who and why (the brief's goal), then the latest action."""
    goal = (work or {}).get("goal") or ""
    first = f"I'm the {role} {where}" + (f": {goal[0].lower() + goal[1:]}." if goal else ".")
    act = (work or {}).get("act")
    return first + (f" Right now I'm {act} ({_ago(work.get('at'), now)})." if act else " I'm just getting started.")


def lead_says(idea: dict, activity: str, note: str) -> str:
    """Two sentences for an idea's chief, from its STATUS."""
    stage = (idea.get("stage") or "no stage") + (f" round {idea['round']}" if idea.get("round") else "")
    if activity == "work":
        how = "my agents are at work"
    elif note == "permission":
        how = "a permission prompt is waiting for you"
    elif note:
        how = f"waiting for you at {note}"
    else:
        how = f"waiting on {idea.get('waiting_on')}" if (idea.get("waiting_on") or "-") != "-" else "waiting on nobody"
    nxt = idea.get("next_step") or ""
    return f"I'm running {idea.get('id') or 'this idea'}, {stage}, and {how}." + (f" Next: {nxt.rstrip('.')}." if nxt else "")


def rooms_state(rows: list, sessions: list, now: float) -> dict:
    """The API contract of /api/rooms: one character per visible idea, one per live subagent.

    Rows apply in the order of the plan's room table; the first match wins. Output has no absolute paths."""
    chars = []

    def add(id_, kind, role, room, activity, project, idea="", title="", note="", live=True, says=""):
        chars.append({"id": id_, "kind": kind, "role": role, "room": room, "activity": activity,
                      "project": project, "idea": idea, "title": title, "note": note, "live": live, "says": says})

    def add_agents(key, live, room, project, idea="", title=""):  # agents come only from live sessions
        for s in live:
            for aid, t in sorted((s.get("agents") or {}).items()):
                role = t.split(":")[-1]
                says = agent_says(role, f"on {idea}" if idea else f"in {project or 'this session'}",
                                  (s.get("work") or {}).get(aid) or {}, now)
                add(f"{key}#{_h8(aid)}", "agent", role, room, "work", project, idea, title, says=says)

    linked = {id(s) for r in rows for s in r[3]}  # includes sessions on hidden ideas: those stay hidden
    for group, _, idea, mine in rows:
        stage = idea.get("stage") or ""
        if stage in ("done", "shelved"):
            continue
        live = [s for s in mine if _live(s, now)]
        states = {s.get("state") for s in live}
        gate = GATES.get(idea.get("gate") or "", idea.get("gate") or "")
        at_gate = bool(gate) or idea.get("waiting_on") == "user"
        key = f"{idea['project']}/{idea.get('id') or idea.get('_path', '')}"
        if "needs_permission" in states:
            room, activity, note = "lounge", "wait", "permission"
        elif "working" not in states and (at_gate if live else group == "waiting"):
            room, activity, note = "lounge", "wait", gate
        elif live:
            room, activity, note = STAGE_ROOM.get(stage, "office"), "work" if "working" in states else "reply", ""
        else:
            room, activity, note = "lounge", "idle", ""
        add(key, "lead", "chief", room, activity, idea["project"], idea.get("id") or "", idea.get("title") or "", note,
            bool(live), lead_says(idea, activity, note))
        add_agents(key, live, STAGE_ROOM.get(stage, "office"), idea["project"], idea.get("id") or "", idea.get("title") or "")
    for i, s in enumerate(sessions):
        if not _live(s, now) or id(s) in linked:
            continue
        project = Path(s.get("cwd") or "").name
        perm = s.get("state") == "needs_permission"
        sid = f"s{_h8(s['_sid'])}" if s.get("_sid") else f"s{i}"  # no file name: the index
        doing = "waiting on a permission prompt" if perm else "working" if s.get("state") == "working" else "waiting for your reply"
        add(sid, "lead", "chief", "lounge" if perm else "office",
            "wait" if perm else "work" if s.get("state") == "working" else "reply", project, note="permission" if perm else "",
            says=f"I'm a session in {project or 'a project'} that isn't on an idea yet. Right now I'm {doing}.")
        add_agents(sid, [s], "office", project)
    return {"ts": int(now), "characters": chars}


ROOMS_PAGE = Path(__file__).with_name("rooms.html")


def route(path: str, host: str, port: int) -> tuple:
    """(status, headers, body) for one GET. Only 127.0.0.1:<port> and localhost:<port> are served (DNS rebinding)."""
    from urllib.parse import parse_qs, urlparse
    url = urlparse(path)
    html_type = "text/html; charset=utf-8"
    if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
        return 403, {"Content-Type": "text/plain"}, b"forbidden host"
    if url.path == "/rooms":  # the one static file, by exact match: no path from the request reaches the disk
        return 200, {"Content-Type": html_type}, ROOMS_PAGE.read_bytes()
    if url.path not in ("/", "/api/rooms"):
        return 404, {"Content-Type": "text/plain"}, b"not found"
    now = time.time()
    sessions = load_sessions(now)
    rows = dashboard_rows(now, sessions)
    if url.path == "/api/rooms":
        return 200, {"Content-Type": "application/json", "X-Content-Type-Options": "nosniff"}, \
            json.dumps(rooms_state(rows, sessions, now)).encode()
    return 200, {"Content-Type": html_type}, render(rows, parse_qs(url.query).get("done") == ["1"], now, sessions).encode()


def serve(port: int):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, headers, body = route(self.path, self.headers.get("Host", ""), port)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    print(f"imp dashboard: http://127.0.0.1:{port}/  rooms: http://127.0.0.1:{port}/rooms", flush=True)
    # threads: a browser's idle preconnected socket would otherwise hold every other request
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.serve_forever()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="imp")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_ideas = sub.add_parser("ideas")
    p_ideas.add_argument("--all", action="store_true", help="every stage, done and shelved included")
    p_ideas.add_argument("--stage", action="append", choices=STAGES)
    for st in STAGES:
        p_ideas.add_argument(f"--{st}", dest="stage", action="append_const", const=st)
    p_ideas.add_argument("--waiting", choices=["user", "marketing", "agents"])
    p_ideas.add_argument("--group")
    p_ideas.add_argument("--projects", action="store_true", help="every registered project")
    p_ideas.add_argument("--scan")
    p_ideas.add_argument("--json", action="store_true", help="export for /imp:notion: projects, tasks, warnings")
    p_ideas.add_argument("--project")
    p_res = sub.add_parser("resolve")
    p_res.add_argument("query")
    p_res.add_argument("--project")
    p_cur = sub.add_parser("current")
    p_cur.add_argument("--session", default="")
    p_cur.add_argument("--project")
    p_codes = sub.add_parser("codes")
    p_codes.add_argument("deck")
    p_codes.add_argument("--glossary", action="append", default=[])
    p_reg = sub.add_parser("register")
    p_reg.add_argument("dir", nargs="?")
    p_dash = sub.add_parser("dashboard")
    p_dash.add_argument("--port", type=int, default=8765)
    p_ag = sub.add_parser("agenda", help="what is due, waiting and open, for the secretary")
    p_ag.add_argument("--days", type=int, default=7, help="due-soon window in days")
    p_ag.add_argument("--new", action="store_true", help="only items not reported before today")
    p_ag.add_argument("--json", action="store_true", help="items with each task's Notion Key")
    p_jr = sub.add_parser("journal", help="ideas your sessions touched in the last day")
    p_jr.add_argument("--today", action="store_true", help="only today")
    args = ap.parse_args(argv)

    if args.cmd == "agenda":
        a = agenda(time.time(), args.days, args.new)
        print(json.dumps(a, indent=2) if args.json else format_agenda(a, args.new))
        return 0

    if args.cmd == "journal":
        for hhmm, ref in journal(time.time(), args.today):
            print(f"{hhmm}  {ref}")
        return 0

    if args.cmd == "register":
        root = _project_arg(args.dir, require=True)
        print(("registered " if register(root) else "already registered ") + str(root))
        return 0

    if args.cmd == "dashboard":
        serve(args.port)
        return 0

    if args.cmd == "current":
        root = _project_arg(args.project)
        hits = current_ideas(root, "" if args.session.startswith("$") else args.session)  # unexpanded ${CLAUDE_SESSION_ID}
        for i in hits:
            print(f"{i.get('id') or '-'}\t{i['_path']}", file=sys.stdout if len(hits) == 1 else sys.stderr)
        return 0 if len(hits) == 1 else (2 if hits else 1)

    if args.cmd == "codes":
        found = undefined_codes(deck_slides(Path(args.deck)), _glossary_text(args.glossary))
        for label, codes in found:
            print(f"{label}: {', '.join(codes)}")
        if not found:
            print("no undefined codes")
        return 1 if found else 0

    if args.cmd == "resolve":
        try:
            print(resolve(find_ideas(_project_arg(args.project)), args.query)["_path"])
            return 0
        except UnknownIdea as e:
            print(f"imp: {e}", file=sys.stderr)
            return 1
        except AmbiguousIdea as e:
            print(f"imp: {e}", file=sys.stderr)
            return 2

    if args.json:
        try:
            print(json.dumps(notion_export(time.time()), indent=2))
        except ValueError as e:
            print(f"imp: {e}", file=sys.stderr)
            return 1
        return 0

    if args.scan:
        _scan(Path(args.scan).expanduser())
    def listing(root):
        return format_rows(filter_ideas(find_ideas(root), args.stage, args.all, args.waiting, args.group))

    if not args.projects:
        print(listing(_project_arg(args.project)))
        return 0
    for root in load_registry():
        if not (root / PROJECT_FILE).is_file():
            print(f"{root} (not found on this machine)\n")
            continue
        cfg = project_config(root)
        print(f"{cfg['name']} ({cfg['kind']})\n{listing(root)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
