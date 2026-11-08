# Idea state

## STATUS fields

From `templates/STATUS.md`:
- `group`: `<Domain> / <use-case>`, exactly one, from the `Idea groups` slot. An idea that spans domains goes under its cross-domain domain. If nothing fits, ask the user before adding to the slot. Blank if the slot lists none.
- `stage`: `backlog | pitch | experiment | ship | monitor | document | done | shelved`
- `waiting_on`: `user | marketing | agents`. `marketing` means whoever the `meeting` slot names; with `meeting: self` it's `user`.
- `gate`: `G1 | G-data | G2 | G3 | meeting`. Set it when you stop at a gate; clear it (blank) once the user passes it. The dashboard shows it.
- `round`: the experiment round
- `branch`
- `blocked_by`: the id of an idea that has to finish first, or blank. `impctl.py ideas` shows it in place of `waiting_on`. Clear it when that idea reaches `done`, and say so.
- `ur`: the UR id from the internal PM tool, for an MKT request. Blank means internal work (ad-hoc, no UR id). The Notion export sets `Source` and `UR id` from it.
- `started`: the date the idea began, `YYYY-MM-DD`. Set it when you create the idea. If blank, the export uses the first date under `## Decisions`.
- `due`: the planned (or actual) end date, `YYYY-MM-DD`. It is the Notion Timeline end. If blank, the end is `monitor_until`, else `last_update`.
- `last_update`: today's date, `YYYY-MM-DD`
- `monitor_until`, `next_check`: dates for the `monitor` stage (`references/lifecycle.md`). The dashboard shows a monitored idea as waiting on you once `next_check` is today or earlier, and never marks it stale.
- `next_step`: one line

`impctl.py ideas` lists any `.md` under the ideas root whose frontmatter has `waiting_on`, nested by `group` once any idea has one.

## Where state lives

Follow the `Ideas layout` slot. Default: `ideas/<id>/STATUS.md`.

When a layout uses **flat files** for a stage (for example `ideas/inbox/<name>.md`):
- the STATUS keys go in that note's own frontmatter
- the note holds only its own text. When the idea gets its first other file (a plan, review, sizing, findings, queries or a deck), promote it to a folder in the same stage, named as the `Ideas layout` slot names folders, before writing that file: move the note into the folder, and update the links to it and the tracker
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
3. Commit only that idea's files (its folder, or a flat note and its `<id>-*` files) and the tracker the `Ideas layout` slot names, with a message saying what was saved. Leave everything else in the working tree as it is, and say that you did. Never push.
4. End with: `Saved <id> (<sha>). Resume with: /imp:continue <id>`.

## Housekeeping

Ask before each change, then keep the tracker and every link in step:
- **Rename**: new `id`, `title` and folder name (per the `Ideas layout` slot), the branch if it carries the id, and every mention in STATUS, plans and the tracker.
- **Merge** A into B: copy A's decisions, open questions, assumptions and artifact links into B's STATUS under a dated note, set A `stage: shelved` with `next_step: merged into <B>`.
- **Shelve**: `stage: shelved` and a one-line reason in `## Decisions`.
- **Block**: set `blocked_by` (above).

After a rename, merge or shelve, if `~/.config/imp/notion.json` exists and the project has `notion: on`, offer `/imp:notion sync <id>` for each idea touched (`references/notion.md`).

## Listing (`/ideas`)

`impctl.py ideas` with the user's flags. By default it hides `done` and `shelved` ideas. `--all` shows every stage; `--<stage>` (`--pitch`, `--done`, ...) or `--stage S` shows only those stages and can repeat; `--waiting W` and `--group G` (a prefix of `group`) narrow further; `--projects` lists every registered project; `--scan DIR` registers projects under DIR first. Show the output as-is, then at most one line pointing at the ideas waiting on the user.
