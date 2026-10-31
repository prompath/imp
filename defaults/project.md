---
name:                      # blank = folder name
kind: personal             # personal | company
ideas_root: ideas
integration_branch: main
push_forbidden:            # comma-separated globs relative to the project root, e.g. projects/*/service-*
meeting: self              # who reviews between stages
deck: html-slides
agent_overrides:           # role=agent, role=agent  e.g. presenter=acme-deck-builder
---

# Project settings (imp defaults)

These are the defaults imp uses when a project has no `.imp/project.md`, or leaves a slot out. A project's own file overrides any of them. A project can add rules but can't remove a gate or the evidence rules.

## Ideas layout

One folder per idea: `ideas/<id>/STATUS.md`, plus the idea's research, plan, decks and a git-ignored `local/` folder. The stage is recorded only in STATUS; folders don't move between stages.

## Knowledge

Look first in `README.md`, `CLAUDE.md` and `docs/`.

## Code

The code is in the repo root. Agents commit only to `exp/<id>-r<n>` (experiment rounds) and `feature/<id>` (ship, rebased on `integration_branch`). Agents never push and never open PRs. The user does that.

## Data execution

None. Data queries are drafts for the user to run; every run needs the user's approval of the exact script and command.

## Deck

HTML slides: use the frontend-slides plugin if it's installed; otherwise one self-contained HTML file per deck in `<idea>/decks/`.

## Meeting

`self`: the user reviews between stages. There's no external meeting, so `waiting_on: marketing` isn't used.

## Reviewer extra checks

None.
