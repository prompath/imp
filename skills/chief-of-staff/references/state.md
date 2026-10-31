# Idea state

## STATUS fields

From `templates/STATUS.md`:
- `stage`: `backlog | pitch | experiment | ship | document | done | shelved`
- `waiting_on`: `user | marketing | agents`. `marketing` means whoever the `meeting` slot names; with `meeting: self` it's `user`.
- `gate`: `G1 | G-data | G2 | G3 | meeting`. Set it when you stop at a gate; clear it (blank) once the user passes it. The dashboard shows it.
- `round`: the experiment round
- `branch`
- `last_update`: today's date, `YYYY-MM-DD`
- `next_step`: one line

`impctl.py ideas` lists any `.md` under the ideas root whose frontmatter has `waiting_on`.

## Where state lives

Follow the `Ideas layout` slot. Default: `ideas/<id>/STATUS.md`.

When a layout uses **flat files** for a stage (for example `ideas/inbox/<name>.md`):
- the STATUS keys go in that note's own frontmatter
- when the idea is promoted to a folder, move the keys into the folder's `STATUS.md` and remove them from the note, so the idea is listed once

Existing ideas without STATUS get it the first time imp touches them. There's no up-front migration.

## Row-level data

Goes in `<idea folder>/local/`, or `<stage dir>/local/<id>/` for a flat-file idea. This folder is git-ignored by `/imp-init`. Never commit row-level data.

## Filing notes (`/notes [id] <notes>`)

1. Resolve the idea (SKILL.md section 5) and say which idea the notes are going into.
2. Append the notes verbatim under `## Feedback log` → `### YYYY-MM-DD meeting notes`.
3. Turn them into decisions (`## Decisions`), assumption updates (confirmed or rejected), and new open questions.
4. Decide the transition from `references/lifecycle.md` and propose the next plan as **G1**. Don't start work before the go-ahead.

## Listing (`/ideas`)

`impctl.py ideas [--all] [--scan DIR]`. Show the output as-is, then at most one line pointing at the ideas waiting on the user.
