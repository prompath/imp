# Gates

Fixed in the base. A project's slots can add checks but can never remove a gate.

| Gate | When | Show the user | Wait for |
|---|---|---|---|
| **G1 Plan** | Before any work beyond read-only recon | `plan.md`, already checked by the reviewer: plan, business-execution assumptions (separate section), other assumptions, risks, alternatives, data runs needed, what will be produced | An explicit go-ahead, or edits (then re-show) |
| **G-data** | Before every data or cluster run | The full script and the exact command (including cluster id where relevant) | Approval of that exact version; any change needs a new approval |
| **G2 Ready to push** | After code is committed locally and the reviewer passed | `change-summary.md`, the diff, test and sizing results, the branch name | The user pushes (directly, or by running `/imp:push` and saying yes) and tests; agents never push or open PRs on their own |
| **G3 Tested** | Before docs and the deployed slide of a ship | Nothing new | The user says it tested fine |
| **Meeting** | Between lifecycle stages, per the `meeting` slot | The deck to present | The user returns with `/notes` |

**Outward writes:** G-data extends to any write to an external workspace (Notion and the like). Show what will be created, updated or closed and wait for a yes before every write. Never delete there, except pages the user names one by one and confirms (moved to Trash). A yes covers that list only.

**Secretary exception** (the user's choice, 2026-11-09): the `/imp:secretary` session writes to Notion without a per-write yes and reports each batch right after, with links (`skills/secretary/SKILL.md`), except a Work Status change away from On hold, which waits for a yes (`references/notion.md`). Its deletes still name the exact pages and wait for a yes.

A go-ahead covers only the plan that was shown. A changed plan is a new G1.
Read-only recon (reading code, notes and the web) is allowed before G1.
