# Routing

Pick one workflow, then **say which one and why in one line** before recon. If two fit equally, ask one question. Project workflows from `.imp/workflows/*.md` join this table; their `use_when` line is matched the same way.

| Workflow | Use when | Entry |
|---|---|---|
| `lifecycle` | A new idea or a change to existing logic (business rule, mapping, model behaviour) that needs a pitch, experiments, shipping and docs | `pitch`, or `experiment` when the change is already agreed |
| `segment-treatment` | The business team has a group of customers and wants a treatment suggested, or wants their own treatment checked | `pitch` (suggest or verify mode) |
| `investigate` | Someone says a result looks wrong or surprising and wants it checked | standalone |
| `analysis` | A question to answer from data (a rate, a trend, a size, a breakdown) with no result in doubt | standalone |
| `explore` | A personal or exploratory ML idea: research, a POC and short docs | `pitch` with `meeting: self` |

Signals:
- "verify", "check their idea", "they proposed" → segment-treatment, verify mode
- "suggest", "how should we treat/offer" → segment-treatment, suggest mode
- "looks wrong", "weird", "why did customer X get" → investigate
- "how much", "how does X change over", "what's the rate", "break down by" → analysis
- rename, merge, combine, shelve an idea, or "after X is done" → no workflow: `references/state.md` → *Housekeeping*
- "change the rule", "add a condition", "implement X in the pipeline" → lifecycle
- "new model", "try a design", "POC", "learn about" → explore
