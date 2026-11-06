# Notion mirror (`/imp:notion`)

imp mirrors its ideas to Notion, one way: imp to Notion. imp is the source of truth and Notion edits are overwritten. One Notion **Project** is one imp idea. **Tasks** are that idea's rounds and open questions. Ad-hoc Notion requests are not this command's job.

## Rules

- Find the Notion tools by name suffix (`notion-create-database`, `notion-update-data-source`, `notion-create-pages`, `notion-update-page`, `notion-create-view`, `notion-query-data-sources`, `notion-fetch`), never by a fixed prefix. If the connector isn't connected, say so and stop.
- Every Notion write follows `references/gates.md` (outward writes): show the list, wait for a yes, then write. A yes covers that list only.
- Never delete anything in Notion.
- IDs live in `~/.config/imp/notion.json`: `{"parent_page_id", "projects_ds", "tasks_ds"}` (data source ids). IDs only, never a token.
- The export is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/impctl.py" ideas --json`: `{"projects", "tasks", "warnings"}` for every registered project with `notion: on`. It reads only STATUS files and each round's plan Hypothesis line. Show its `warnings`. If it exits non-zero (two projects with one name), show the message and stop.

## setup

1. Ask which page holds the databases (the user names it; search for it with the search tool and confirm). If `notion.json` exists, show it and ask before creating anything new.
2. Show the plan (two databases, their columns and views, the parent page) and wait for a yes.
3. `notion-create-database` under the page: **Projects**.
   ```
   CREATE TABLE ("Name" TITLE, "imp_id" RICH_TEXT, "Repo" SELECT, "Kind" SELECT('personal':gray, 'company':blue),
     "Domain" SELECT, "Use-case" SELECT,
     "Stage" SELECT('backlog':gray, 'pitch':blue, 'experiment':purple, 'ship':orange, 'monitor':yellow, 'document':pink, 'done':green, 'shelved':brown, 'removed':red),
     "Gate" SELECT('G1':blue, 'G-data':orange, 'G2':purple, 'G3':green, 'meeting':yellow),
     "Waiting on" SELECT('user':red, 'marketing':yellow, 'agents':gray),
     "Round" NUMBER, "Next step" RICH_TEXT, "Branch" RICH_TEXT, "Start" DATE, "End" DATE)
   ```
   Every Stage option must exist: imp's eight stages plus `removed`. A select value not in the schema fails. Repo, Domain and Use-case start empty: before a sync writes a new value, add it to that column with `notion-update-data-source` (`ALTER COLUMN "Repo" SET SELECT(...)` with the full old and new list; *Assumed*, not probed). Put in the description: "Mirrored from imp. Edits here are overwritten."
4. Self-relation, with `notion-update-data-source` on Projects: `ADD COLUMN "Blocked by" RELATION('<projects ds>', DUAL 'Blocks' 'blocks')`.
5. `notion-create-database`: **Tasks**, same description warning.
   ```
   CREATE TABLE ("Name" TITLE, "task_id" RICH_TEXT, "Project" RELATION('<projects ds>', DUAL 'Tasks'),
     "Type" SELECT('round':blue, 'question':yellow), "Status" SELECT('Open':gray, 'Done':green),
     "Verdict" SELECT('worked':green, 'worse':red, 'no effect':gray, 'inconclusive':yellow, 'broken':orange),
     "Branch @ sha" RICH_TEXT, "Result" RICH_TEXT)
   ```
   The dual relation adds "Tasks" to Projects by itself.
6. `notion-create-view`:
   - Projects: Timeline `TIMELINE BY "Start" TO "End"`; Board `GROUP BY "Stage"`; Table `GROUP BY "Repo"`; Table `GROUP BY "Domain"`.
   - Tasks: Board `GROUP BY "Status"`; Table `GROUP BY "Project"`.
7. Write `notion.json` with the page and the two data source ids. Say what was created, with links.

## sync [id]

1. Read `notion.json`; if it's missing, say `/imp:notion setup` comes first.
2. Run the export. With an `id`, keep only the project whose `imp_id` ends in `/<id>` and its tasks.
3. Load what exists, with `notion-query-data-sources` in **rows mode** and a text filter. Never use SQL mode (workspace quota on lower plans). Projects: `imp_id string_starts_with "<repo>/"`. Tasks: `task_id string_starts_with "<repo>/"`. Run it once per repo in scope, with `limit: 100`, and page on until no rows are left. If rows mode has no cursor, split by idea instead (`<repo>/<id>/`) so no query returns more than 100 rows. Keep each row's page id and properties. Then match the export keys against these rows in memory; no per-key lookups. `string_starts_with` is *Assumed*: the probe verified only `string_is`. Check it live in step 8 (the first live sync).
4. Build the list, one line per row:
   - **create**: no page for the key.
   - **update**: a page exists and a property differs (name the property and both values).
   - **unchanged**.
   - **closed**: a Projects page whose idea is gone from imp, to get Stage `removed`; a Tasks page whose task is gone from STATUS (an answered question), to get Status `Done`. Never limit this to what was exported: compare against the existing rows of the repos in scope. With an `id`, only that idea's rows.
   Show counts first, then the list.
5. Wait for a yes. No yes, no write.
6. On a yes, write **projects first, then tasks**:
   - New Select values for Repo, Domain, Use-case: add them to the schema first (setup, step 3).
   - Create: `notion-create-pages` with `parent: {"data_source_id": "<ds>"}` and `allow_async: false`, so the page ids come back at once. Update: `notion-update-page`.
   - Dates: `"date:Start:start": "2026-11-01"` and `"date:Start:is_datetime": 0` (same for End). Skip the date when the export value is blank.
   - Relations are arrays of page ids: Tasks `Project` is `["<project page id>"]`; Projects `Blocked by` is `["<page id>"]` of the project whose `imp_id` is `blocked_by` (set it in a second pass, after all projects exist; skip it if that project isn't in Notion).
   - Round (number) is a number; blank values are left out.
7. Report counts of created, updated, unchanged and closed, and one link to the Projects database. A second sync with no STATUS change must show zero creates.

## Offers

After a rename, merge or shelve (`references/state.md`) and at the end of STATUS updates (SKILL.md section 3, step 7), offer `/imp:notion sync <id>` when `notion.json` exists and the project has `notion: on`. Offer only; never sync unasked.
