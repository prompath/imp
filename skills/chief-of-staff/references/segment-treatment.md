---
name: segment-treatment
use_when: the business team has a group of customers and wants a treatment suggested, or wants their own treatment verified
entry: pitch
agents: data-analyst, business-researcher, code-investigator, claim-checker, presenter, reviewer
---

# Segment treatment

Runs as a **pitch** stage of the lifecycle and can continue into experiments.

**Mode:** *suggest* (propose treatments) or *verify* (critique the business team's proposal). Ask if the request doesn't say.

1. Recon:
   - data-analyst drafts queries to size and profile the segment (activity, account age, current product, past campaigns, response history)
   - business-researcher: the business case, consumer psychology and other companies' examples for treating such a segment
   - code-investigator, if the segment comes from a model or rule: how it is defined and what it receives today
2. G1, with the business-execution assumptions (channels, timing, who contacts the customer, what happens when a promotion ends) listed for the user to check.
3. After go-ahead and G-data:
   - **suggest:** 2–3 treatment options with pros, cons, evidence and a recommendation
   - **verify:** an honest critique of the proposal: strengths, weaknesses, risks, likely side effects (for example the regular price feeling like a loss once a discount ends), and 1–2 alternatives
4. presenter builds the pitch deck (assumptions slide first among the closing slides) → reviewer → show it. `waiting_on: marketing`.
