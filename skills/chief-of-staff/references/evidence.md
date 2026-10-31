# Evidence and assumptions

## Evidence levels

Every claim in research, plans and decks carries exactly one:
- **Verified**: our code or our data, with the location or query
- **Sourced**: an external source, with a link
- **Inferred**: reasoning from Verified or Sourced claims
- **Assumed**: no evidence

## Assumption register

Kept in STATUS (`## Assumptions`). Each assumption has a category (business execution / data / technical), whether it was checked against the project's `Knowledge` sources, its impact if wrong, who can confirm it, and a status. Business-execution assumptions get a dedicated section in every G1 and a dedicated slide in every deck. When the user confirms or rejects one (often via `/notes`), update its status.

## Language follows evidence

Recommendations resting on Inferred or Assumed claims use hedged wording and say what would change the conclusion. Psychology and other companies' results are "evidence suggests", never a promise for this customer base.

## The reviewer blocks

Any deck or recommendation with an unsourced claim, a number not traceable to a sizing output, or an execution assumption that isn't surfaced. One automatic revision, then escalate to the user.

## Web searches

Searches may include public product information (product names, public prices, features). Never internal numbers, segment sizes, rule logic, model details or customer data.

## Data

Committed files hold aggregates only. Row-level data (flagged customers, query output) goes in the idea's git-ignored `local/` folder. Decks and `sizing.md` cite aggregates.
