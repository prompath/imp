# imp

imp (Idea-to-Merge Pipeline) is a Claude Code plugin, a home for agents and workflows: a **chief-of-staff** plans the work, hands it to specialist agents, and stops at fixed checkpoints for your go-ahead. Ideas move through **pitch → experiment rounds → ship → document**, and their state lives in each project's idea folders. Projects extend the base with a `.imp/project.md` settings file and, if needed, their own agents and workflows.

Full guide: [`docs/site/index.html`](docs/site/index.html).

## Install (once per machine)

In Claude Code:

```
/plugin marketplace add prompath/imp
/plugin install imp@imp
```

Restart Claude Code. imp needs `python3` on your `PATH`.

## Connect a project (once per project)

Run `/imp-init` inside the project. It drafts `.imp/project.md` from the project's `CLAUDE.md`/`README.md`, shows it to you, and writes it only after you approve. Commit the file with the project.

On a new machine, `/ideas --projects --scan ~/Projects` finds every connected project.

## Update

```
claude plugin marketplace update imp
claude plugin update imp@imp
```

Then restart Claude Code. Each project keeps its own `.imp/project.md`.

Maintainers: raise `version` in `.claude-plugin/plugin.json` for each release.

## Commands

| Command | Does |
|---|---|
| `/idea <description>` | Start an idea: pick a workflow, look around, show the plan, wait for go-ahead |
| `/continue [id]` | Resume an idea where it stopped |
| `/notes [id] <notes>` | File your meeting notes and propose the next round |
| `/ideas [--all] [--<stage>] [--waiting W] [--group G] [--projects] [--scan DIR]` | List open ideas in this project, or every project with `--projects`. Done and shelved ideas are hidden unless you pass `--all` or a stage flag (`--done`, `--pitch`, ...). Output is nested by domain and use-case if the project sets `Idea groups` |
| `/investigate <case>` | Check whether a result is a misunderstanding, a code bug or a rulebook gap |
| `/imp:push [note]` | Commit the repo's changes, summarize everything unpushed, and push once you say yes |
| `/imp-init` | Connect the current project |
| `/imp:dashboard [--port N]` | Open a live local page (`http://127.0.0.1:8765/`) of every registered project's ideas: waiting on you, in progress, idle, done. `/rooms` on the same server (`http://127.0.0.1:8765/rooms`) shows a pixel campus of who works where |

The commands are called `/ideas` and `/notes` because Claude Code's built-ins already use `/status` and `/feedback`.

## Tests

```
python3 -m unittest discover -s tests -v
```

## License

MIT. See [`LICENSE`](LICENSE).
