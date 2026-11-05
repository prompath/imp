---
name: explore
use_when: a personal or exploratory ML idea that needs research, a POC and short docs
entry: pitch
agents: tech-researcher, builder, verifier, claim-checker, presenter, reviewer
---

# Explore an ML idea

The lifecycle with `meeting: self`: the user is the reviewer between stages.

1. **Pitch:** tech-researcher gathers papers, designs and prior implementations with trade-offs, and proposes the smallest POC that would show whether the idea works. Use public data unless the user says otherwise. presenter makes a short HTML summary deck. `waiting_on: user`.
2. **Experiment:** G1 → builder makes the POC on `exp/<id>-r<n>`: a notebook or script plus **a simple webpage or HTML slides that show how it works** (for example inputs on one side, the model's output on the other) → reviewer → G2. The user tries it.
3. **Document:** a short README: what, why, how it works, results, what we tried (from the `## Rounds` table), limits, next steps.
