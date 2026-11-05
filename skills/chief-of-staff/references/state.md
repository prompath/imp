# Idea state

## STATUS fields

From `templates/STATUS.md`:
- `group`: `<Domain> / <use-case>`, exactly one, from the `Idea groups` slot. An idea that spans domains goes under its cross-domain domain. If nothing fits, ask the user before adding to the slot. Blank if the slot lists none.
- `stage`: `backlog | pitch | experiment | ship | document | done | shelved`
- `waiting_on`: `user | marketing | agents`. `marketing` means whoever the `meeting` slot names; with `meeting: self` it's `user`.
- `gate`: `G1 | G-data | G2 | G3 | meeting`. Set it when you stop at a gate; clear it (blank) once the user passes it. The dashboard shows it.
- `round`: the experiment round
- `branch`
- `last_update`: today's date, `YYYY-MM-DD`
- `next_step`: one line

`impctl.py ideas` lists any `.md` under the ideas root whose frontmatter has `waiting_on`, nested by `group` once any idea has one.

## Where state lives

Follow the `Ideas layout` slot. Default: `ideas/<id>/STATUS.md`.

When a layout uses **flat files** for a stage (for example `ideas/inbox/<name>.md`):
- the STATUS keys go in that note's own frontmatter
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

## Listing (`/ideas`)

`impctl.py ideas [--all] [--scan DIR]`. Show the output as-is, then at most one line pointing at the ideas waiting on the user.
