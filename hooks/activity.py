#!/usr/bin/env python3
"""Activity hook: keep one small JSON per session so `impctl.py dashboard` can show what's live.

Runs on every tool call, so it stays cheap: json/os/time only, and the file is rewritten
only when the state changes or 10s have passed. It never prints and always exits 0.
"""
import json
import os
import sys
import time

HEARTBEAT = 10  # seconds between rewrites when nothing changed
MAX_CHANGES = 50  # state history kept for the dashboard timeline


def activity_dir() -> str:
    return os.environ.get("IMP_ACTIVITY") or os.path.join(os.path.expanduser("~"), ".config", "imp", "activity")


def find_ideas_dir(cwd: str) -> str:
    """Absolute ideas root of the project around cwd, or '' if it isn't connected. Once per session."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    from impctl import find_project_root, project_config

    root = find_project_root(cwd)
    return str(root / project_config(root)["ideas_root"]) if root else ""


def _brief_idea(prompt: str) -> str:
    """`# Brief: <role> for <id>` on the first line of an Agent prompt -> id."""
    first = prompt.strip().split("\n", 1)[0].strip().lstrip("#").strip().strip("*").strip()
    if first.startswith("Brief:") and " for " in first:
        return first.rsplit(" for ", 1)[1].strip().strip("*`. ")
    return ""


PATH_KEYS = ("file_path", "path", "notebook_path")


def idea_from_tool(tool_name: str, tool_input: dict, ideas_dir: str, cwd: str) -> str:
    """Path (absolute) under the ideas root a tool call touches, or ''. The dashboard maps it to an idea."""
    if not ideas_dir or not isinstance(tool_input, dict):
        return ""
    if tool_name in ("Agent", "Task"):
        idea = _brief_idea(str(tool_input.get("prompt") or ""))
        if idea:
            return os.path.join(ideas_dir, idea)
    prefixes = [(ideas_dir + "/", False)]
    rel = os.path.relpath(ideas_dir, cwd) if cwd else ".."
    if not rel.startswith("."):
        prefixes.append((rel + "/", True))
    for key, value in tool_input.items():
        if not isinstance(value, str):
            continue
        for p, relative in prefixes:
            i = value.find(p)
            # a relative prefix must start a word, so "myideas/" isn't "ideas/"
            while relative and i > 0 and value[i - 1] not in " \t\n'\"=(":
                i = value.find(p, i + 1)
            if i < 0:
                continue
            rest = value[i + len(p):]
            # the whole path: a path argument as is, a quoted one up to its quote (folder names have spaces)
            if not (key in PATH_KEYS and i == 0):
                q = value[i - 1] if i > 0 and value[i - 1] in "'\"" else ""
                stops = q or " \t\n'\"`;)|&"
                for j, c in enumerate(rest):
                    if c in stops:
                        rest = rest[:j]
                        break
            rest = rest.rstrip("/")
            first = rest.split("/", 1)[0]
            if first and not first.startswith(".") and first != "local":
                return os.path.join(ideas_dir, rest)
    return ""


def reduce(state: dict, event: dict, now: float) -> dict:
    """Pure: previous session state + one hook payload -> new state. `state['ideas_dir']` must be set."""
    s = dict(state)
    s["agents"] = dict(state.get("agents") or {})
    s.setdefault("state", "working")
    name = event.get("hook_event_name")
    agent_id, agent_type = event.get("agent_id"), event.get("agent_type") or ""
    if event.get("cwd") and not agent_id:  # a subagent's cwd isn't the session's folder
        s["cwd"] = event["cwd"]

    if name == "SessionEnd":
        s["state"] = "ended"
    elif name == "SubagentStop":
        s["agents"].pop(agent_id, None)
    elif name == "Stop":
        # a main-session Stop with background work still running isn't waiting on you yet
        if not agent_id and not event.get("background_tasks"):
            s["state"] = "waiting_reply"
    elif name == "Notification":
        kind = event.get("notification_type")
        if kind == "permission_prompt":
            s["state"] = "needs_permission"
        elif kind == "idle_prompt":
            s["state"] = "waiting_reply"
    elif name in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart"):
        s["state"] = "working"
        if agent_id and agent_type:
            s["agents"].setdefault(agent_id, agent_type)
        if name in ("PreToolUse", "PostToolUse") and not agent_id:  # a subagent's reads must not relink the session
            idea = idea_from_tool(event.get("tool_name") or "", event.get("tool_input") or {},
                                  s.get("ideas_dir") or "", s.get("cwd") or "")
            if idea:
                s["idea"] = idea
    changes = list(state.get("changes") or [])
    if not changes or changes[-1][1] != s["state"]:
        s["changes"] = (changes + [[now, s["state"]]])[-MAX_CHANGES:]
    s["last_seen"] = now
    return s


def main(stdin_text: str) -> int:
    try:
        event = json.loads(stdin_text)
        sid = str(event.get("session_id") or "")
        if not sid or "/" in sid:
            return 0
        d = activity_dir()
        path = os.path.join(d, sid + ".json")
        try:
            with open(path) as f:
                old = json.load(f)
        except (OSError, ValueError):
            old = {}
        if "ideas_dir" not in old:
            try:
                old["ideas_dir"] = find_ideas_dir(event.get("cwd") or os.getcwd())
            except Exception:
                old["ideas_dir"] = ""
        now = time.time()
        new = reduce(old, event, now)
        same = {k: v for k, v in new.items() if k != "last_seen"} == {k: v for k, v in old.items() if k != "last_seen"}
        if same and now - (old.get("last_seen") or 0) < HEARTBEAT:
            return 0
        os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(new, f)
        os.replace(tmp, path)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.stdin.read()))
    except Exception:
        sys.exit(0)
