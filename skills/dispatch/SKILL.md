---
name: dispatch
description: Dispatch mode for imp - one dedicated session that is the gate for a project's run tunnel. Push gate - take an inventory of queued notebooks, check each has a G-data approval for its current version, build the batch sheet and push it. Pull gate - fetch, compare what came back with what the batch expected, and hand each result to the idea that owns it. It never approves, never runs on a cluster, never writes result.md. Invoked by /imp:dispatch only.
---

# Dispatch

This session is the project's dispatch gate. It **pushes queued batches and pulls results back**. It **never approves, never runs, never writes a result**.

`${CLAUDE_PLUGIN_ROOT}` is this plugin's folder. The CLI is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/impctl.py"`. If `${CLAUDE_PLUGIN_ROOT}` is empty or unexpanded, the plugin folder is two levels above this skill's base directory (shown when the skill loads); use that path instead.

The project's own commands live in its `## Dispatch` slot (`.imp/project.md`): Inventory, Build sheet, Push, Pull, Fingerprint, Tests. Run them from the project root, exactly as the slot gives them. imp knows nothing about the runs themselves. If the project has no `## Dispatch` slot, or it says "None", say so and stop.

## 1. Role rules

- **Never grant or record G-data.** An approval covers the exact notebook the user saw in a work session, and the work session records it. Here you only check that it exists (section 2).
- **Never run anything on a cluster**, by any route. Never use the Agent tool. Never load the `imp:chief-of-staff` skill or any other imp skill. Never edit code or notebooks.
- **Never write `result.md`.** The session that owns the idea writes it (section 4).
- **Push only through the slot's Push command**, never by `git push` or any other route. Never push a sheet the user did not see. Never open a PR.
- **Local writes, only these:** in an idea's STATUS, the `## Handover` and `waiting_on` lines of section 4. Re-read the file right before each edit. Leave every other line as it is.
- **One gate at a time.** Report what you did and stop; the user says "push" or "pull" (or "sync").

## 2. Push gate

1. **Inventory.** Run the slot's Inventory command. Show it in the report format of section 5.
2. **Stop on a mismatch.** A notebook with no approval for its current fingerprint is blocked: list it with the reason ("changed after approval", "no approval") and ask the user to approve it in its work session. Never push around it. Dirty or untracked notebooks and changed helpers are listed too; they are for the work session to commit.
3. **Build the sheet.** Run the slot's Build sheet command. Show the sheet.
4. **Fill placeholders.** Fill any placeholder in the sheet the user has already given you. Ask for the rest. Never invent one.
5. **Push.** Wait for the user's yes on the sheet, then run the slot's Push command with the sheet path. Never retry a refused push: report the refusal.
6. **Report.** Give the pushed head SHA and the batch id. Say that the user runs the batch in the Databricks UI and hands the results back.

## 3. Pull gate

1. **Pull.** Run the slot's Pull command (it prints JSON). Do not edit the tree by hand. If the JSON field `pulled` is false, report `problems` and stop; write no Handover lines.
2. **Expected against received.** For each batch in the output, list what it expected, what came back, and what is missing.
3. **Route.** Each result names its idea and round. List `unrouted` results and `problems` as they are; the user routes them. Never guess an idea.
4. **Hand over.** Section 4, for each routed result.
5. **Pasted results.** When the user says a batch's results were pasted (not pushed through git), first hand the pasted results to the owning session (section 4). Then run the Pull command with `--mark-synced <bid>`. Never use that flag otherwise.
6. **Report** in the format of section 5.

## 4. Handover to the owning idea

For each idea with results back, once per batch:

1. Re-read its STATUS. If a `results back for batch <bid>` line for this batch id is already there, skip this idea (no duplicates). Otherwise add under `## Handover`: `- YYYY-MM-DD: results back for batch <bid>: <comma-separated result paths>; next: write result.md (dispatch)`. A STATUS without `## Handover` gets it right above `## Decisions`.
2. Set `waiting_on: agents`.
3. Run `impctl.py bookkeeping <path> --project <root>`. Only on exit 0, commit that one file: `git -C <root> commit -m "<id>: results back for batch <bid>" -- <path>`. On exit 1, show the blocking lines and leave the file. Commit only on the project's `integration_branch`. Never push.

The work session's `/imp:continue` reads the line and writes `result.md`.

## 5. Report format

Used for both gates, one block per item, in this order:

```
Inventory (push):  queued <n> | dirty <n> | helpers changed <n>
  <notebook>  approved | BLOCKED: <reason>
Batch <bid>  expected <n> | received <n> | missing <n>
  missing: <path>
Routed:    <idea> <round>  <paths>   (Handover written, committed | not committed: <reason>)
Unrouted:  <path>
Problems:  <text>
Head:      <sha>
```

Leave out lines with nothing to say. End with the one thing the user does next.
