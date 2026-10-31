#!/usr/bin/env python3
"""PreToolUse hook: block git push and PR commands where a project sets push_forbidden.

Exit 2 blocks the Bash call and shows stderr to Claude. Anything unexpected exits 0
so the hook never gets in the way of normal work.
"""
import fnmatch
import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from impctl import find_project_root, project_config  # noqa: E402

# shortcut: regex check of the shell text, misses pushes hidden in scripts or aliases, upgrade to a git pre-push hook in the clones if that matters
GIT_PUSH = re.compile(r"\bgit\b(?:\s+-C\s+\S+|\s+-c\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+push\b")
GH_PR = re.compile(r"\bgh\s+pr\s+(?!(?:view|list|status|diff|checks|checkout)\b)[a-z]")
GH_API_PULLS = re.compile(r"\bgh\s+api\b[^;&|]*(/pulls|(create|update|merge|close|reopen)PullRequest)")


def is_push_command(cmd: str) -> bool:
    return bool(GIT_PUSH.search(cmd) or GH_PR.search(cmd) or GH_API_PULLS.search(cmd))


def _tokens(cmd: str) -> list:
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return cmd.split()


def target_dirs(cmd: str, cwd: Path) -> list:
    """Every directory the command could act in: cwd, each cd/pushd (chained), git -C/--git-dir/--work-tree."""
    dirs, cur = [cwd], cwd
    tokens = _tokens(cmd)
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if tok in ("cd", "pushd") and nxt:
            # subshells don't restore cur afterwards; that only over-blocks
            cur = (cur / Path(nxt).expanduser()).resolve()
            dirs.append(cur)
        elif tok == "-C" and nxt:
            dirs.append((cur / Path(nxt).expanduser()).resolve())
        elif tok.startswith(("--git-dir=", "--work-tree=")):
            dirs.append((cur / Path(tok.split("=", 1)[1]).expanduser()).resolve())
        elif " " in tok:  # a quoted command string, e.g. bash -c "cd x && git push"
            dirs += target_dirs(tok, cur)
    return dirs


def is_forbidden(d: Path) -> bool:
    root = find_project_root(d)
    if root is None:
        return False
    globs = [g.strip() for g in project_config(root).get("push_forbidden", "").split(",") if g.strip()]
    try:
        parts = d.resolve().relative_to(root).parts
    except ValueError:
        return False
    prefixes = ["/".join(parts[:n]) for n in range(1, len(parts) + 1)]
    return any(fnmatch.fnmatch(p, g) for p in prefixes for g in globs)


def main(stdin_text: str) -> int:
    try:
        data = json.loads(stdin_text)
        if data.get("tool_name") != "Bash":
            return 0
        cmd = data.get("tool_input", {}).get("command", "")
        if not is_push_command(cmd):
            return 0
        cwd = Path(data.get("cwd") or ".").resolve()
        for d in target_dirs(cmd, cwd):
            if is_forbidden(d):
                print(
                    f"imp: push/PR blocked in {d} (push_forbidden in {find_project_root(d)}/.imp/project.md). "
                    "Stop and hand over to the user.",
                    file=sys.stderr,
                )
                return 2
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin.read()))
