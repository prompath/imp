# Notion mirror (`/imp:notion`)

imp syncs its ideas, one way, into an **existing** Notion tracker with three linked databases: **Areas** → **User Requests** → **Tasks** (the Team Tracker layout). imp never creates these databases. One User Request (UR) is one imp idea, its Area comes from the idea's `group`, and its Tasks are the idea's rounds and open questions. imp is the source of truth for the properties it owns; the tracker's own rows and the other properties stay the user's. Ad-hoc Notion requests are not this command's job.

Calls marked *Assumed (live check)* were not covered by the probe (`ideas/notion-workspace/rounds/r1/probe.md`); check them on the first live run and stop if one fails.

## Rules

- Find the Notion tools by name suffix (`notion-fetch`, `notion-search`, `notion-update-data-source`, `notion-create-pages`, `notion-update-page`, `notion-create-view`, `notion-query-data-sources`, `notion-delete-pages`), never by a fixed prefix. If the connector isn't connected, say so and stop.
- Every Notion write follows `references/gates.md` (outward writes): show the list, wait for a yes, then write. A yes covers that list only.
- Schema changes are additive only: add properties, options and rows. Never rename or drop a property or an option. The one user-approved exception: setup renames the User Requests database title to "Work" (title only; property names stay).
- **Ownership rule.** Write only to rows that have an `imp_id` (URs) or a `task_id` (Tasks), and only these properties:
  - URs: `Request` (title), `Area`, `Project type`, `Status`, `Stage`, `Gate`, `Waiting on`, `Next step`, `Branch`, `Round`, `Timeline`, `Blocked by`, `Source`, `UR id`, plus `imp_id` on create.
  - Tasks: `Name`, `Status`, `Kind`, `User Request`, `task_id`.
  - Never write `Priority`, `Owner`, `Mandays`, `Requested by`, `Type`, `Assigned` or `Due`. Never touch a row without an `imp_id`/`task_id`, and never touch an Areas row except to create one in setup.
- Never delete, except in `cleanup`, and there only the exact pages the user confirms.
- IDs live in `~/.config/imp/notion.json`, written by setup. IDs only, never a token:
  ```
  {"page_id": "<Team Tracker page>", "areas_ds": "collection://…", "requests_ds": "collection://…", "tasks_ds": "collection://…",
   "areas": {"<group>": "<Area page id>"}, "area_names": {"<group>": "<Area name>"}}
  ```
  `<group>` is the export's `group` string exactly (blank group: key `""`). `area_names` holds the Area title, which is also the `Project type` option.
- The export is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/impctl.py" ideas --json`: `{"projects", "tasks", "warnings"}` for every registered project with `notion: on`. It reads only each idea's own file (STATUS.md or flat note) and each round's plan Hypothesis line. Show its `warnings`. If it exits non-zero (two projects with one name), show the message and stop. "project" in the export is an imp idea, a UR in Notion.

## Maps

**Source / UR id:** export `source` (`MKT request` or `Internal`, from the STATUS `ur:` key) and `ur_id`. "UR" in this doc means a row of the requests database (now titled Work).

**UR Status** (first match wins):

| imp | Status | Stage |
|---|---|---|
| stage `done` | Done | done |
| stage `shelved` | Done | shelved |
| gone from imp (closed) | Done | removed |
| `blocked_by` set | Blocked | the stage |
| stage `backlog` (or blank) | Not started | backlog |
| stage `pitch`, `experiment`, `ship`, `monitor`, `document` | In progress | the stage |

**Task Status:** round with export status `Done` → Done, round `Open` → In progress; question `Open` → Not started; a task gone from the export (answered question) → Done. `Kind` = the export `type` (`round` or `question`).

**Area:** `areas[group]`. A group with no entry stops the sync before any write: "group '<group>' has no Area; rerun `/imp:notion setup` to map it."

## setup <page>

1. The user names the Team Tracker page. Find it with `notion-search` if it's a name, confirm it, then `notion-fetch` it. If `notion.json` exists, show it and ask before changing anything.
2. Locate the three data sources on the page by title: **Areas**, **User Requests** (or **Work**, if already renamed; with `notion.json`, use the stored `requests_ds`), **Tasks**. `notion-fetch` each `collection://` url and read its schema. Stop and say which is missing if one isn't found, or if a required property is absent: Areas `Area` (title); URs `Request` (title), `Area` relation, `Status` status, `Timeline` date, `Blocked by` relation, `Project type` select; Tasks `Name` (title), `Status` status, `User Request` relation. Note every existing option of `Project type`, with its color.
3. Run the export and list its distinct `group` values. Propose an Area for each: an existing Area whose name matches it, else a **new Area** named after it. Already-mapped groups in `notion.json` keep their Area. The user corrects the map.
4. Show the plan and wait for a yes. It lists:
   - New UR properties, skipping any that already exist (`notion-update-data-source` on User Requests; `ADD COLUMN` is probe-verified):
     ```
     ADD COLUMN "imp_id" RICH_TEXT,
     ADD COLUMN "Stage" SELECT('backlog':gray, 'pitch':blue, 'experiment':purple, 'ship':orange, 'monitor':yellow, 'document':pink, 'done':green, 'shelved':brown, 'removed':red),
     ADD COLUMN "Gate" SELECT('G1':blue, 'G-data':orange, 'G2':purple, 'G3':green, 'meeting':yellow),
     ADD COLUMN "Waiting on" SELECT('user':red, 'marketing':yellow, 'agents':gray),
     ADD COLUMN "Next step" RICH_TEXT, ADD COLUMN "Branch" RICH_TEXT, ADD COLUMN "Round" NUMBER
     ```
     Also `ADD COLUMN "Source" SELECT('MKT request':blue, 'Internal':gray), ADD COLUMN "UR id" RICH_TEXT`.
     Several `ADD COLUMN` clauses in one statement are *Assumed (live check)*; else send one call per column.
   - Rename the database title to **Work**: `notion-update-data-source` with `title` (*Assumed (live check)*). This is the one user-approved exception to "never rename". It changes the title only; properties keep their names (the Tasks relation stays `User Request`). Skip it if the title is already Work.
   - New Tasks properties: `ADD COLUMN "task_id" RICH_TEXT, ADD COLUMN "Kind" SELECT('round':blue, 'question':yellow, 'manual':gray)`.
   - Four new views on the requests database (`notion-create-view`):
     - **Timeline**: `TIMELINE BY "Timeline"`, grouped by `Area`, and also grouped or coloured by `Source` if the DSL allows it; otherwise keep the Area grouping and tell the user. The probe verified `TIMELINE BY "Start" TO "End"` only: one date-range property, grouping a timeline and colouring by Source are *Assumed (live check)*.
     - **imp pipeline**: board `GROUP BY "Stage"`, filtered to `"imp_id" IS NOT EMPTY`. The filter is *Assumed (live check)*: if the call rejects it, create the board unfiltered and tell the user that the Stage-blank column holds the hand-made URs.
     - **MKT requests**: `FILTER "Source" = "MKT request"; SORT BY "UR id" ASC`.
     - **Internal work**: `FILTER "Source" = "Internal"`. Both filters are *Assumed (live check)*.
   - One line added to the page's callout, with `notion-update-page` on the page (*Assumed (live check)*: editing inside a callout): "Rows with an imp_id are synced from imp (everything-ais); edit them in imp, except Priority/Owner/Mandays/Requested by/Type. Source tells MKT requests (with a UR id) from internal work."
   Existing views, rows and properties are not changed.
5. On a yes, run the steps in that order: properties, views, callout.
6. Then ask a **separate yes** for the Area rows and the `Project type` options, shown with the snapshot below. The ALTER can blank values on the live select, so it comes last and is guarded:
   - New Area rows, one per unmapped group: `notion-create-pages` with `parent: {"data_source_id": "<areas ds>"}`, `allow_async: false`, properties `{"Area": "<name>"}`. Keep the returned page ids.
   - `ALTER COLUMN "Project type" SET SELECT('<every existing option>':<its color>, …, '<new Area>':<color>)`. List **every** existing option: options left out are removed. *Assumed (live check)*: the ALTER syntax.
   - Before the ALTER, snapshot every User Request's `Project type` (rows mode, url → value) and show it. After the ALTER, re-read the values and compare, and fetch the schema to check no option was lost. If any value or option changed, stop, report the rows to the user and continue nothing.
   - Skip this step if no group needs a new Area.
7. Write `notion.json`: page id, the three data source urls, `areas` (group → Area page id, existing and new) and `area_names` (group → Area name). Say what was added, with links.

## sync [id]

1. Read `notion.json`; if it's missing, say `/imp:notion setup` comes first.
2. Run the export. With an `id`, keep only the project whose `imp_id` ends in `/<id>` and its tasks. If any project's `group` is not in `areas`, stop (see Maps).
3. Load what exists, with `notion-query-data-sources` in **rows mode** and a text filter. Never use SQL mode (workspace quota on lower plans). URs: `imp_id string_starts_with "<repo>/"`. Tasks: `task_id string_starts_with "<repo>/"`. Run it once per repo in scope, with `limit: 100`, and page on until no rows are left. If rows mode has no cursor, split by idea instead (`<repo>/<id>/`) so no query returns more than 100 rows. Keep each row's page id and owned properties. Then match the export keys against these rows in memory; no per-key lookups. `string_starts_with` is *Assumed (live check)*: the probe verified only `string_is`. Rows without an `imp_id`/`task_id` never come back from these queries, so they are never compared or written.
4. Build the target values from the export and the Maps:
   - UR: `Request` = name; `Area` = `[areas[group]]`; `Project type` = `area_names[group]`; `Status` and `Stage` from the UR Status map; `Source` = export `source`; `UR id` = export `ur_id` (blank left out); `Gate`, `Waiting on`, `Next step`, `Branch`, `Round`; `Timeline` = start → end; `Blocked by` = the UR whose `imp_id` is `blocked_by`.
   - Task: `Name`; `Status` and `Kind` from the Task Status map; `User Request` = `[<UR page id of its project>]`; `task_id`.
   - A `Gate` or `Waiting on` value that isn't a setup option is left blank and listed under the counts.
5. Build the list, one line per row, comparing owned properties only:
   - **create**: no page for the key.
   - **update**: a page exists and an owned property differs (name the property and both values).
   - **unchanged**.
   - **closed**: a UR whose idea is gone from imp, to get Stage `removed`, Status Done; a Task whose task is gone from the export (an answered question), to get Status Done. Compare against the existing rows of the repos in scope, not only what was exported. With an `id`, only that idea's rows.
   Show counts first, then the list.
6. Wait for a yes. No yes, no write.
7. On a yes, write **URs first, then Tasks**:
   - Create: `notion-create-pages` with `parent: {"data_source_id": "<ds>"}` and `allow_async: false`, so the page ids come back at once. Update: `notion-update-page` with the changed owned properties only. *Assumed (live check)*: the probe never updated properties. Run the first update on one row, fetch it back and check it, then do the rest.
   - Batch creates: at most 50 pages per `notion-create-pages` call (the hard limit is 100), or one call per idea.
   - Tasks of new URs use the page ids returned by the UR create call.
   - Status (a **status** property) by option name, e.g. `"Status": "In progress"`. *Assumed (live check)*: the probe wrote selects only.
   - Timeline: `"date:Timeline:start": "2026-11-01"`, `"date:Timeline:end": "2026-11-20"`, `"date:Timeline:is_datetime": 0`. `start` and `is_datetime` are probe-verified; `end` on a range is *Assumed (live check)*. Leave the end out if the export `end` is blank, and the whole Timeline if `start` is blank. A blank export end therefore leaves the old Timeline end in Notion.
   - Relations are arrays of page ids: `Area`, the Task `User Request`, and `Blocked by` (set it in a second pass, after all URs exist; skip it if that UR isn't in Notion).
   - Round (number) is a number; blank values are left out.
8. Report counts of created, updated, unchanged and closed, and one link to the User Requests database. A second sync with no STATUS change must show zero creates. The hand-made rows must be untouched: count the URs and Tasks without an `imp_id`/`task_id` before and after the first live sync.

## cleanup

Optional, list-only helper for an untidy tracker. It changes nothing by itself.

1. Read `notion.json`. Query Tasks (rows mode) and list two groups: Tasks with no `User Request`, and Tasks with an empty `Name`. Show each row's page id, name, Status and Assigned. Rows with a `task_id` are not listed (a sync will fix them).
2. The user picks rows, one by one or by listed id, and says what to do with each: trash, or leave. Attaching a Task to a UR is the user's edit in Notion; imp doesn't do it.
3. Repeat the exact ids back and wait for a yes. Then `notion-delete-pages` on those ids only, with `user_confirmed` set only after that yes (*Assumed (live check)*: the probe never deleted). It moves them to Trash, which the user can restore.

## Offers

After a rename, merge or shelve (`references/state.md`) and at the end of STATUS updates (SKILL.md section 3, step 7), offer `/imp:notion sync <id>` when `notion.json` exists and the project has `notion: on`. Offer only; never sync unasked.
