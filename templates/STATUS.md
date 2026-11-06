---
id: <short-kebab-id>
title: <Title>
project: <project name>
kind: <personal|company>
group:                     # <Domain> / <use-case> from the Idea groups slot; blank if the project has none
stage: pitch               # backlog | pitch | experiment | ship | monitor | document | done | shelved
round:                     # experiment round number
waiting_on: agents         # user | marketing | agents
gate:                      # G1 | G-data | G2 | G3 | meeting while stopped at it; blank once passed
next_step: <one line>
branch:
blocked_by:                # id of an idea that has to finish first
monitor_until:             # monitor stage: earliest date it can be called done
next_check:                # monitor stage: date the next check is due
ur:                        # UR id from the internal PM tool for an MKT request; blank = internal work
started:                   # YYYY-MM-DD the idea began; set on /idea
last_update: YYYY-MM-DD
---

# <Title>

## Decisions

- YYYY-MM-DD: <decision> (<who>)

## Feedback log

### YYYY-MM-DD meeting notes
<the user's notes, verbatim>

## Rounds

| Round | Hypothesis | Branch @ sha | Verdict | What we learned | Result |
|---|---|---|---|---|---|

## Monitoring

| Date | What we watch | How we check (query or run URL) | Pass rule | Result |
|---|---|---|---|---|

## Assumptions

| # | Assumption | Category (business execution / data / technical) | Evidence level | Checked against knowledge? | Impact if wrong | Who confirms | Status |
|---|---|---|---|---|---|---|---|

## Open questions

-

## Artifacts

- Plan: plan.md
- Rounds: rounds/r<n>/
- Research:
- Decks:
- Branches:
