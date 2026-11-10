# Idea state

## STATUS fields

From `templates/STATUS.md`:
- `group`: `<Domain> / <use-case>`, exactly one, from the `Idea groups` slot. An idea that spans domains goes under its cross-domain domain. If nothing fits, ask the user before adding to the slot. Blank if the slot lists none.
- `stage`: `backlog | pitch | experiment | ship | monitor | document | on-hold | done | shelved`. `on-hold` is parked by the user: listed by `/ideas`, idle on the dashboard, never due, and On hold in Notion. Change `backlog`, `done`, `shelved` and `on-hold` with `impctl.py stage` (*Stage changes*).
- `waiting_on`: `user | marketing | agents`. `marketing` means whoever the `meeting` slot names; with `meeting: self` it's `user`.
- `gate`: `G1 | G-data | G2 | G3 | meeting`. Set it when you stop at a gate; clear it (blank) once the user passes it. The dashboard shows it.
- `round`: the experiment round
- `branch`
- `blocked_by`: the id of an idea that has to finish first, or blank. `impctl.py ideas` shows it in place of `waiting_on`. Clear it when that idea reaches `done`, and say so.
- `ur`: the UR id from the internal PM tool, for an MKT request. Blank means internal work (ad-hoc, no UR id). The Notion export sets `Source` and `UR id` from it.
- `started`: the date the idea began, `YYYY-MM-DD`. Set it when you create the idea. If blank, the export uses the first date under `## Decisions`. The secretary may move it on request.
- `due`: the planned (or actual) end date, `YYYY-MM-DD`. It is the Notion Timeline end. If blank, the end is `monitor_until`, else `last_update`. Once it has passed, the dashboard shows the idea as waiting on you ("due <date>"), unless it is backlog, on hold, shelved, done or monitored.
- `last_update`: today's date, `YYYY-MM-DD`
- `monitor_until`, `next_check`: dates for the `monitor` stage (`references/lifecycle.md`). The dashboard shows a monitored idea as waiting on you once `next_check` is today or earlier, and never marks it stale. Waiting on you means: a permission prompt, a session waiting for your reply, `waiting_on: user` (with the gate), a monitor check due, or a passed `due`.
- `next_step`: one line

`impctl.py ideas` lists any `.md` under the ideas root whose frontmatter has `waiting_on`, nested by `group` once any idea has one.

## Tasks

`## Tasks` in STATUS holds the idea's dated to-dos, written by the `/imp:secretary` session: `- [ ] T1: <text> (start YYYY-MM-DD) (due YYYY-MM-DD) (remind YYYY-MM-DD HH:MM)`, done `- [x] T1: <text> (done YYYY-MM-DD)`. `T<n>` labels go up per file and are never reused; `start`, `due` and `remind` are optional. The secretary also writes `started`, `due`, `next_check`, `waiting_on`, `gate`, `next_step`, `stage` (only through `impctl.py stage`), `## Open questions`, `## Handover` and new dated lines at the end of `## Decisions`, and nothing else in STATUS. It commits a STATUS file only when `impctl.py bookkeeping <path>` exits 0 (its changes are only those), on the `integration_branch`, with `git commit -- <path>`. Re-read the file before editing it in a work session too. Its own files are in `~/.config/imp/secretary/` (`IMP_SECRETARY` overrides): `journal/YYYY-MM-DD.md`, loose tasks in `tasks.md` (same line format), and a per-day seen-file for `impctl.py agenda --new`. `impctl.py agenda [--days N] [--new] [--json]` lists overdue and due-soon ideas and tasks, monitor checks, gates waiting on you and open tasks, and reports malformed dates.

## Handover

`## Handover` in STATUS holds decisions the `/imp:secretary` session took with the user for the idea's next work session: `- YYYY-MM-DD: <decision>; next: <step>[; by YYYY-MM-DD]`. It sits right after the title, before `## Decisions` (the secretary inserts it above `## Decisions` when missing). The secretary only adds lines. `/imp:continue` reads them first and acts on them; a line acted on is removed and logged as `- YYYY-MM-DD: handover done: <decision> (user)` under `## Decisions`. A line not acted on stays.

## Where state lives

Follow the `Ideas layout` slot. Default: `ideas/<id>/STATUS.md`.

When a layout uses **flat files** for a stage (for example `ideas/inbox/<name>.md`):
- the STATUS keys go in that note's own frontmatter
- the note holds only its own text, plus a `## Handover` section if the secretary adds one (above). When the idea gets its first other file (a plan, review, sizing, findings, queries or a deck), promote it to a folder in the same stage, named as the `Ideas layout` slot names folders, before writing that file: move the note into the folder, and update the links to it and the tracker
- when the idea is promoted to a folder, move the keys into the folder's `STATUS.md` and remove them from the note, so the idea is listed once

Existing ideas without STATUS get it the first time imp touches them. There's no up-front migration.

## Experiment rounds

Each round's files go in `<idea folder>/rounds/r<n>/`: `plan.md`, `review-plan.md`, `change-summary.md`, `verify.md`, `review.md`, `queries/`, `sizing.md` and `result.md` (from `templates/result.md`). Give agents that folder as their output path. Earlier rounds are never overwritten, so a results deck can compare rounds.

### Verdict

Propose it from the round's `sizing.md` against the criteria fixed in its `plan.md`, checking in this order, and stop at the first that applies:

1. **broken**: the round didn't test the hypothesis: verifier `FAIL`, the change didn't do what the plan said, or the data-analyst flagged numbers that don't reconcile.
2. **inconclusive**: it ran, but below the plan's minimum sample, or the difference is within what the plan called noise.
3. **worse**: a kill criterion is met.
4. **worked**: the success criterion is met.
5. **no effect**: none of the above.

Show the proposal with the numbers behind it. The user confirms or overrides. An override is kept in `result.md` with its reason. The criteria are never edited after the data is in.

STATUS `## Rounds` gets one row per round when its `result.md` is written, whatever the verdict. Don't delete `exp/` branches before the idea is done; the commit sha in `result.md` ties the result to its code.

## Row-level data

Goes in `<idea folder>/local/`, or `<stage dir>/local/<id>/` for a flat-file idea. This folder is git-ignored by `/imp-init`. Never commit row-level data.

## Filing notes (`/notes [id] <notes>`)

1. Resolve the idea (SKILL.md section 5) and say which idea the notes are going into.
2. Append the notes verbatim under `## Feedback log` → `### YYYY-MM-DD meeting notes`.
3. Turn them into decisions (`## Decisions`), assumption updates (confirmed or rejected), and new open questions.
4. Decide the transition from `references/lifecycle.md` and propose the next plan as **G1**. Don't start work before the go-ahead.

## Saving (`/save [id]`)

1. Resolve the idea (SKILL.md section 5) and name it.
2. Update its STATUS: `next_step`, `gate`, `waiting_on`, `last_update`, and the open decisions waiting on the user under `## Open questions`, each with its plan label.
3. Commit only that idea's files (its folder, or a flat note and its `<id>-*` files) and the tracker the `Ideas layout` slot names, with a message saying what was saved. Leave everything else in the working tree as it is, and say that you did. This also commits the STATUS edits the secretary's bookkeeping check refused. Never push.
4. End with: `Saved <id> (<sha>). Resume with: /imp:continue <id>`.

## Housekeeping

Ask before each change, then keep the tracker and every link in step:
- **Rename**: new `id`, `title` and folder name (per the `Ideas layout` slot), the branch if it carries the id, and every mention in STATUS, plans and the tracker.
- **Merge** A into B: copy A's decisions, open questions, assumptions and artifact links into B's STATUS under a dated note, set A `stage: shelved` with `next_step: merged into <B>`.
- **Shelve**: `impctl.py stage <id> shelved --reason "<one line>"` (*Stage changes*): show the dry run, wait for the user's yes, then run it again with `--apply`.
- **Block**: set `blocked_by` (above).

After a rename, merge, shelve or other stage change, if `~/.config/imp/notion.json` exists and the project has `notion: on`, offer `/imp:notion sync <id>` for each idea touched (`references/notion.md`).

## Stage changes

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/impctl.py" stage <id> <backlog|done|shelved|on-hold|resume> [--reason TEXT] [--apply]` changes an idea's stage the same way every time. Without `--apply` it only prints the changes, one per line, and writes nothing. Show that, wait for the user's yes, then run it with `--apply`.

In the `/imp:secretary` session the user's request is the yes for a frontmatter-only change; a change with a `move` line still waits for a yes on the dry run.

- Frontmatter: `stage`, `last_update`, `gate` cleared; for `done` and `shelved` also `waiting_on` cleared and `next_step` set (`done`, or `shelved: <reason>`). `shelved` needs `--reason`. Every other byte of the file is kept.
- `## Decisions` gets `- YYYY-MM-DD: <stage> (from <old stage>[; moved from <old folder>])[: <reason>] (user)`. `resume` reads the latest such line, sets that old stage back and, if the folder moved, moves it back.
- Folder: moved only if `.imp/project.md` has `stage_folders` naming the stage (e.g. `stage_folders: done=implemented`, a comma list of `stage=folder` under the ideas root) and the idea is a folder with `STATUS.md`. Flat notes never move. Tracked files move with `git mv`. If the target exists, nothing is done.
- Links: after a move, root-absolute links to the old folder (`](/ideas/…/A B/…)`, `](</…>)`, `%20`) in the project's tracked `.md` files are rewritten. Then the `link_check` command from `.imp/project.md` runs at the project root, if set, and its output and exit code are shown. A failure is reported, not rolled back.
- By hand afterwards: the tracker the `Ideas layout` slot names, then offer `/imp:notion sync <id>` (below).

## Listing (`/ideas`)

`impctl.py ideas` with the user's flags. By default it hides `done` and `shelved` ideas. `--all` shows every stage; `--<stage>` (`--pitch`, `--on-hold`, `--done`, ...) or `--stage S` shows only those stages and can repeat; `--waiting W` and `--group G` (a prefix of `group`) narrow further; `--projects` lists every registered project; `--scan DIR` registers projects under DIR first. Show the output as-is, then at most one line pointing at the ideas waiting on the user.
