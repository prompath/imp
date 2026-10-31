---
description: Commit this repo's changes, summarize everything unpushed, and push after your go-ahead
argument-hint: "[note for the commit message]"
disable-model-invocation: true
---

Work in the git repo at the current directory, on the current branch. `$ARGUMENTS`, if any, is a note on what the commit message should say. Run the steps in order.

## 1. Read the changes

Run `git fetch`, then read `git status --short`, the current branch, the staged and unstaged diffs, and the unpushed commits (`git log --oneline @{u}..HEAD`; with no upstream, compare against the project's `integration_branch`, default `main`).

Tools such as RTK can condense terminal output, so write each diff to a temp file (`git diff > <file>`, `git diff --staged > <file>`) and read it in full.

Stop and say why if HEAD is detached, a merge or rebase is in progress, or the branch is behind its upstream. If there's nothing to commit and nothing unpushed, say so and stop.

## 2. Commit

Stage files by name, never with `git add -A` or `git add .`. Leave out row-level data (`local/`), secrets, generated output, system files like `.DS_Store`, and changes unrelated to the work. If you can't tell whether a file belongs, leave it out and list it in the summary.

Write the message in the style of `git log`, saying why as well as what. Use separate commits when the changes are separate pieces of work. If a commit hook fails, fix the cause and make a new commit; never use `--no-verify`.

## 3. Summarize

Show:
- the repo, the branch and where it will push to
- each unpushed commit, including earlier ones, as hash and subject
- what changed, in plain language
- anything left uncommitted, and why
- that tests weren't run, unless you ran them

If the branch belongs to an imp idea (`branch` in its STATUS) and its `review.md` has no `PASS`, say so. Warn if the branch is `main` or the `integration_branch`.

## 4. Ask

If the repo is under a `push_forbidden` glob in `.imp/project.md`, don't ask: the commits stay local, so give the user the push command and stop.

Otherwise ask for permission to push, then stop and wait for an explicit yes. This is the only step that needs it: a yes covers the commits shown, so any new commit means asking again.

## 5. Push

Run `git push`, or `git push -u origin <branch>` if there's no upstream. Never force-push and never open a PR. If the push is rejected or a hook blocks it, stop and show the error rather than working around it. Report what was pushed and where.
