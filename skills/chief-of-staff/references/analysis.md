---
name: analysis
use_when: a question to answer from data (a rate, a trend, a size, a breakdown) with no result in doubt
entry: standalone
agents: code-investigator, data-analyst, reviewer
---

# Data analysis

Input: the question, in the user's words. Row-level data goes in `local/`.

1. Create an idea for it (`stage: pitch`, id `ana-<topic>`) so it can be listed and resumed.
2. Restate the question as numbered sub-questions with the metric, population and period for each, and confirm them with the user before recon.
3. Recon: code-investigator finds how the project already defines each metric (tables, filters, existing notebooks); data-analyst drafts the queries.
4. **G1** (the plan: sub-questions, definitions, queries) → **G-data** for each query.
5. data-analyst writes `sizing.md` from the results the user hands back, one section per sub-question, with the caveats.
6. reviewer checks `sizing.md` against the queries → show the answers. Ask whether any finding should become an idea (`references/lifecycle.md`). Then set `stage: done`.
