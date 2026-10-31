---
name: imp-init
description: Connect a project to imp - draft .imp/project.md from the project's CLAUDE.md and README, show it for review, write it after approval, git-ignore row-level data folders, and register the project. Invoked by /imp-init.
---

# Connect a project to imp

`${CLAUDE_PLUGIN_ROOT}` is the imp plugin folder. If `${CLAUDE_PLUGIN_ROOT}` is empty or unexpanded, the plugin folder is two levels above this skill's base directory (shown when the skill loads); use that path instead. Work in the project root (the git root of the current directory, or the current directory if it isn't a repo).

## 1. Check for an existing file

If `.imp/project.md` already exists, show it and ask whether to keep it, edit specific slots, or redraft. Never overwrite it without a yes.

## 2. Read the project

Read `CLAUDE.md`, `README.md`, any `.claude/agents/*.md` and `.claude/settings.json`, and list the top-level folders. Don't read data files.

## 3. Draft every slot

Start from `${CLAUDE_PLUGIN_ROOT}/defaults/project.md`: the same frontmatter keys and the same prose sections. Fill each slot from what the project says. Anything not found keeps its default and gets a trailing `# default` comment so the user can see it.

Slots: `name`, `kind`, `ideas_root`, `integration_branch`, `push_forbidden`, `meeting`, `deck`, `agent_overrides`, plus the sections `Ideas layout`, `Idea groups`, `Knowledge`, `Code`, `Data execution`, `Deck`, `Meeting`, `Reviewer extra checks`.

Signals to look for:
- Rules against pushing or opening PRs anywhere → `push_forbidden` globs for those paths (relative to the project root, comma-separated)
- A branch the work merges into first → `integration_branch`
- Rules about running code on clusters or databases → `Data execution` (the approval rule stays in force either way)
- Existing deck tooling and themes → `deck` and `Deck`
- Existing idea or task folders and trackers → `ideas_root` and `Ideas layout`

## 4. Review with the user

Show the full draft. Point out every `# default` slot, and any slot you inferred rather than read. Apply the user's edits. **Write nothing until the user approves.**

## 5. Write and register

1. Write `.imp/project.md`.
2. Add `<ideas_root>/**/local/` to the project's `.gitignore` if no existing line already covers it, so row-level data never gets committed.
3. Register the project: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/impctl.py" register`.
4. Commit only if the user says to, and only at the project root. Never commit inside a path matching `push_forbidden`. Never push.

Finish with one line: the project is connected, and `/idea` starts the first idea.
