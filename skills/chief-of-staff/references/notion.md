# Notion mirror (`/imp:notion`)

The sync copies ideas, one way, into the **Work** database on the **Team Tracker** page in Notion. One idea is one Work item. Its Area comes from the idea's `group`. The sync owns the Work properties listed below; every other property and row stays with the team. **The sync writes Work items only.** It never creates, updates or closes Tasks: Tasks are hand-made (by people, or by the chief-of-staff on request) and carry no Key. The layout (properties, views, callout) is kept by hand. The sync never creates or changes it, except that `setup` may add Area options.

Layout verified 2026-11-08. Calls marked *Assumed (live check)* were not tried live; check them on first use and stop if one fails.

## Rules

- **Nothing the sync writes may mention imp.** That covers every row, option, text and page. The Notion side calls these rows Work items.
- Find the Notion tools by name suffix (`notion-fetch`, `notion-search`, `notion-update-data-source`, `notion-create-pages`, `notion-update-page`, `notion-query-data-sources`, `notion-delete-pages`), never by a fixed prefix. If the connector isn't connected, say so and stop.
- Every Notion write follows `references/gates.md` (outward writes): show the list, wait for a yes, then write. A yes covers that list only. If the user grants standing permission, still show the list, then write.
- **Ownership rule.** Write only to Work rows that have a `Key`, and only these properties: `Request` (title), `Area`, `Source`, `UR id`, `Status`, `Next step`, `Timeline`, `Blocked by`, and `Key` (on create). Never write `Owner`, `Priority`, `Mandays`, `Requested by` or `Type`. Never write to the Tasks database. Rows without a `Key` (hand-made) are never read, compared or written.
- Never delete, except in `cleanup`, and there only the exact pages the user confirms.
- Do not reference removed properties: Stage, Gate, Waiting on, Branch, Round, Project type, imp_id, Kind, task_id, or an Area relation. There is no Areas database in use (the old one is in the Archive page).
- IDs live in `~/.config/imp/notion.json`, written by setup. IDs only, never a token:
  ```
  {"page_id": "<Team Tracker page>", "requests_ds": "collection://…", "tasks_ds": "collection://…",
   "skill_page": "<page id>", "area_names": {"<group>": "<Area option>"}}
  ```
  `<group>` is the export's `group` string exactly (blank group: key `""`). The Area options are whatever the Work `Area` select holds; the map lives in `area_names`. `skill_page` is the id of the team's "How to use Claude with Team Tracker" page; setup records it if present, and the sync never writes to it. `tasks_ds` is used by `cleanup` only.
- The export is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/impctl.py" ideas --json`: `{"projects", "tasks", "warnings"}` for every registered project with `notion: on`. It reads only each idea's own file (STATUS.md or flat note) and each round's plan Hypothesis line. Show its `warnings`. If it exits non-zero (two projects with one name), show the message and stop. Use `projects` only; ignore `tasks`. A "project" in the export is an idea, a Work item in Notion. Its `imp_id` (export field, not a Notion property) is the Notion `Key` (`<repo>/<id>`).

## Layout

**Work** (title `Request`): `Area` select, `Source` select (MKT request, Internal), `UR id` text, `Status` status (Not started, On hold, In progress, Blocked, Monitoring, Done), `Next step` text, `Timeline` date range, `Blocked by` self-relation (back-relation `Blocking`), `Tasks` relation, `Key` text (hidden). Owned by people: Owner, Priority, Mandays, Requested by, Type. Views: Board, Timeline, MKT, All requests.

**Tasks** (title `Name`): `Status`, `User Request` relation to Work, `Key`, Assigned, Due. The sync does not touch it.

## Maps

**Work Status** (first match wins):

| idea | Status |
|---|---|
| stage `done` or `shelved` | Done |
| gone from imp (closed) | Done |
| `blocked_by` set | Blocked |
| stage `monitor` | Monitoring |
| stage `backlog` (or blank) | Not started |
| stage `pitch`, `experiment`, `ship`, `document` | In progress |

Never write On hold; people set it. A synced row whose Notion Status is On hold is **skipped entirely**: no property updates, and not closed either. Show it in the list as "left alone (On hold)".

**Area:** `area_names[group]`. A group with no entry stops the sync before any write: tell the user to add it to `notion.json` and, if it is a new option, to the Area select (or run `setup`).

**Request:** the idea title. If the title contains "imp" or a gate code (G1, G-data, G2, G3), reword it in plain English and show the rewording in the confirmation list.

**Next step:** plain English for the team. No gate codes (G1, G-data, G2, G3), no "imp", no agent words. You write a short rewrite (at most 100 characters) of the STATUS `next_step`, and only when you **create** a row and on `sync <id>` (a single-idea sync, which runs right after a STATUS update). A full sync never updates Next step on existing rows and never lists it as a difference.

## setup <page>

1. The user names the Team Tracker page. Find it with `notion-search` if it's a name, confirm it, then `notion-fetch` it. If `notion.json` exists, show it and ask before changing anything.
2. Find the **Work** and **Tasks** data sources on the page and `notion-fetch` each `collection://` url. Stop and name what is missing if a data source or a required property is absent: Work `Request`, `Area`, `Source`, `UR id`, `Status`, `Next step`, `Timeline`, `Blocked by`, `Key`; Tasks `Name`, `Status`, `User Request`. Find the "How to use Claude with Team Tracker" page for `skill_page` (leave it out if absent).
3. Run the export and list its distinct `group` values. Propose an Area option for each: an existing option that matches, else a new option named after the group. Groups already in `notion.json` keep their option. The user corrects the map.
4. If a group needs a new Area option, show it and wait for a separate yes. Then `notion-update-data-source` with `ALTER COLUMN "Area" SET SELECT(…)`. List **every** existing option with its color; options left out are removed. Snapshot every Work row's Area first, and compare after; if anything changed, stop and tell the user.
5. Write `notion.json` in the shape above. Say what was added.
6. Say the layout (views, properties, callout) is maintained by hand; setup changes none of it.

## sync [id]

1. Read `notion.json`; if it's missing, say `/imp:notion setup` comes first.
2. Run the export. With an `id`, keep only the project whose `imp_id` ends in `/<id>`. If any group is not in `area_names`, stop (see Maps).
3. Load what exists from the Work database with `notion-query-data-sources` in **rows mode** and a text filter. Never use SQL mode (workspace quota on lower plans). Filter `Key string_starts_with "<repo>/"` (verified live). Run it once per repo in scope, with `limit: 100`, and page on until no rows are left; if there is no cursor, split by idea (`<repo>/<id>/`). Keep each row's page id, Status and owned properties. Match the export keys in memory; no per-key lookups. Rows without a Key never come back, so they are never compared or written. Count the Work rows without a Key before you write: query `Key is_empty` (*Assumed (live check)*); if that fails, use total rows minus keyed rows.
4. Build the target values: `Request` (see Maps); `Area` = `area_names[group]`; `Source` = export `source`; `UR id` = export `ur_id` (blank left out); `Status` from the map; `Timeline` = `start` → `end` (end only if set; the whole Timeline left out if `start` is blank); `Blocked by` = the Work item whose Key is `blocked_by` (second pass); `Key`; `Next step` as in Maps.
5. Build the list, one line per row, comparing owned properties only (not Next step on existing rows during a full sync):
   - **create**: no page for the key.
   - **update**: a page exists and an owned property differs (name the property and both values).
   - **unchanged**.
   - **closed**: a Work item whose idea is gone from imp, to get Status Done. Compare against the existing rows of the repos in scope, not only what was exported. With an `id`, only that idea's row.
   - **left alone (On hold)**: see Maps.
   Show counts first, then the list.
6. Wait for a yes (see Rules for standing permission). No yes, no write.
7. Write:
   - Create: `notion-create-pages` with `parent: {"data_source_id": "<requests_ds>"}` and `allow_async: false`, so page ids come back at once. At most 50 pages per call (the hard limit is 100). Update: `notion-update-page` with the changed owned properties only. *Assumed (live check)*: the first update. Run it on one row, fetch it back, then do the rest.
   - Status by option name, e.g. `"Status": "In progress"`.
   - Timeline: `"date:Timeline:start": "2026-11-01"`, `"date:Timeline:end": "2026-11-20"`, `"date:Timeline:is_datetime": 0`. An end on create works (verified). Leave the end out if blank. A blank export end leaves the old end in Notion.
   - `Blocked by` is an array of page ids, set in a second pass after all Work items exist (*Assumed (live check)*); skip it if that item isn't in Notion.
   - Blank values are left out.
8. Verify: query the written rows back and compare. Report counts of created, updated, unchanged, closed and left alone, and one link to the Work database. A second sync with no STATUS change must show **0 creates**. Count the Work rows without a Key again: the number must match the count from step 3.

## Verified facts

- DDL: a drop and a rename to the same name must be separate calls (in one call the rename landed as "Area 1").
- `page_layout` changes and property changes need separate calls.
- A Timeline range end works on create.
- Rows mode `string_starts_with` works; multi-clause `ADD COLUMN` and a database title change work.

## cleanup

Optional, list-only helper for an untidy tracker. It changes nothing by itself.

1. Read `notion.json`. Query Tasks (rows mode) and list two groups: Tasks with no `User Request`, and Tasks with an empty `Name`. Show each row's page id, name, Status and Assigned. Rows with a `Key` are not listed.
2. The user picks rows, one by one or by listed id, and says what to do with each: trash, or leave. Attaching a Task to a Work item is the user's edit in Notion.
3. Repeat the exact ids back and wait for a yes. Then `notion-delete-pages` on those ids only, with `user_confirmed` set only after that yes (*Assumed (live check)*: never tried live). It moves them to Trash, which the user can restore.

## Offers

After a rename, merge or shelve (`references/state.md`) and at the end of STATUS updates (SKILL.md section 3, step 7), offer `/imp:notion sync <id>` when `notion.json` exists and the project has `notion: on`. Offer only; never sync unasked.
