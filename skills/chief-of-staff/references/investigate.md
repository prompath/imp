---
name: investigate
use_when: someone says a result looks wrong or surprising and wants it checked
entry: standalone
agents: code-investigator, data-analyst, reviewer
---

# Result investigation

Input: the cases the business team flagged (IDs or examples). Row-level case data goes in `local/`. If no result is in doubt and the user only wants a question answered from data, say so in one line and follow `references/analysis.md` instead.

1. Create an idea folder for the investigation (`stage: pitch`, id `inv-<topic>`) so it can be listed and resumed.
2. data-analyst drafts the queries to pull each case's data (current product, usage history, inputs, model scores, rules applied) → **G-data**.
3. code-investigator traces each case through the code and the rulebook, using the data the user handed back.
4. Verdict per case:
   - **misunderstanding**: the result is correct; include a plain explanation the business team can read (`explanation.md`)
   - **code bug**: location, why it diverges from the rulebook, proposed fix
   - **rulebook gap**: what decision is missing
5. reviewer checks the verdicts against the evidence → show the verdict table.
6. **Ask before opening new ideas**: a code bug → a lifecycle idea at `experiment`; a rulebook gap → a lifecycle idea at `pitch`. Open only the ones the user confirms. Then set the investigation `stage: done`.
