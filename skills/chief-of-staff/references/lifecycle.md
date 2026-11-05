---
name: lifecycle
use_when: a new idea or a change to existing logic that needs a pitch, experiments, shipping and docs
entry: pitch
agents: business-researcher, tech-researcher, code-investigator, data-analyst, builder, verifier, claim-checker, presenter, reviewer
---

# Idea lifecycle

Stages run in order. The user can enter at any stage. Every stage that does work starts with G1.

## 1. Pitch (`stage: pitch`)

- Recon: code-investigator (where it lives, what it touches), business-researcher (business case, psychology, examples), data-analyst (sizing drafts). Reuse any existing research note on the topic.
- G1 → after go-ahead: G-data for sizing → presenter builds the **pitch deck** (`templates/deck-outlines.md` → Pitch) → reviewer → show the deck.
- Set `waiting_on: marketing` (or `user` if `meeting: self`). Next: the user presents and comes back with `/notes`.
- Folder: follow the `Ideas layout` slot (for example inbox → active).

## 2. Experiment, round n (`stage: experiment`, `round: n`)

A round is one try. Rounds and meetings don't line up: several rounds can pass between meetings, and a round that didn't work may never reach one. Every round is documented anyway.

- G1 for round n, built from the latest feedback, decisions and the `## Rounds` table in STATUS. The plan fixes the hypothesis and the success and kill criteria before any data comes back.
- The round's files go in `rounds/r<n>/` (`references/state.md`).
- builder works on `exp/<id>-r<n>` and commits locally. data-analyst drafts before/after queries. reviewer checks the change against the plan.
- **G2**: summary + diff + branch. `waiting_on: user`. The user pushes and runs it, then hands back results (G-data for any query).
- data-analyst writes the round's `sizing.md`. Propose the verdict (`references/state.md` → *Verdict*), and once the user confirms it, write the round's `result.md` from `templates/result.md` and add its row to `## Rounds`. Every round gets both, including rounds that failed.
- Show the result and ask: **another round** (G1 for r(n+1)), **take it to the meeting**, or **ship**. `waiting_on: user`. If there's no go decision in `## Decisions`, say so before the user picks ship.
- To the meeting: presenter builds one **results deck** covering the rounds since the last meeting (`decks/results-r<first>-r<n>`, kept) → reviewer → show it. `waiting_on: marketing`. Feedback via `/notes` → round n+1, or a go decision → ship, or a final round to apply the decision first.

## 3. Ship (`stage: ship`)

- G1 (what goes in, from which rounds, per the `## Rounds` table).
- builder creates `feature/<id>` from the final round, rebased on the latest local `integration_branch`, with tidy commits. reviewer checks it.
- **G2**: summary + diff + branch. The user merges it into the integration branch and opens any PR themselves (for example `develop` → `main`). `waiting_on: user`.
- **G3**: wait for the user to say it tested fine.

## 4. Document (`stage: document` → `done`)

- Update the project's notes (rulebook, change log, model/pipeline notes) per the `Knowledge` slot, including a short *what we tried* from the `## Rounds` table, dead ends too.
- presenter builds the **deployed slide** (`templates/deck-outlines.md` → Deployed): one slide telling the business team it's done and live from the deploy date. reviewer checks it, including the project's extra checks. Show it.
- Move the idea folder to its final place per the `Ideas layout` slot, update the tracker, and set `stage: done`.

## Transitions

| From | Event | To | waiting_on |
|---|---|---|---|
| pitch | deck shown | pitch | marketing |
| pitch | notes say go | experiment r1 | agents |
| experiment rn | G2 shown | experiment rn | user |
| experiment rn | result.md shown | experiment rn | user |
| experiment rn | user asks for another round | experiment r(n+1) | agents |
| experiment rn | results deck shown | experiment rn | marketing |
| experiment rn | notes ask for changes | experiment r(n+1) | agents |
| experiment rn | user picks ship | ship | agents |
| ship | G2 shown | ship | user |
| ship | user says tested | document | agents |
| document | done | done | - |
| any | user parks it | shelved | - |
