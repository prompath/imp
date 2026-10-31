# Brief: <agent role> for <idea id>

**Goal:** <one or two sentences>

**Inputs (read these files):**
- <path>

**Project slots (only the relevant ones):**
- <slot>: <value>

**Constraints:**
- Tag every claim with an evidence level: Verified (our code/data, with location or query), Sourced (external, with link), Inferred (reasoning from the above), Assumed (no evidence).
- List business-execution assumptions separately.
- Web searches may contain public product info (product names, public prices, features). Never internal numbers, segment sizes, rule logic, model details or customer data.
- Never push, never open PRs, never run anything on a cluster.
- Committed files hold aggregates only; row-level data goes in `<idea>/local/`.

**Output:** write `<path>` in this format: <format>

**Return:** a summary of at most 10 lines: what you found, open questions, and anything that blocks you.
