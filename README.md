# imp

imp (Idea-to-Merge Pipeline) is a Claude Code plugin, a home for agents and workflows: a **chief-of-staff** plans the work, hands it to specialist agents, and stops at fixed checkpoints for your go-ahead. Ideas move through **pitch → experiment rounds → ship → monitor → document**, and their state lives in each project's idea folders. Projects extend the base with a `.imp/project.md` settings file and, if needed, their own agents and workflows.

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
| `/investigate <case>` | Check whether a result is a misunderstanding, a code bug or a rulebook gap. A plain question about the data goes to the analysis workflow instead |
| `/save [id]` | Save progress on the idea this session is working on: update STATUS with the open decisions, commit only that idea's files, and print the `/imp:continue <id>` line. With no id, it works out the idea from this session's activity, or from idea files with uncommitted changes |
| `/imp:push [note]` | Commit the repo's changes, summarize everything unpushed, and push once you say yes |
| `/imp:notion setup <page> \| sync [id] \| cleanup` | Sync ideas one way into the Team Tracker Work database in Notion, through the Notion connector. `setup` checks the layout, adds missing Area options with your yes, and maps each idea `group` to an Area; the layout itself is kept by hand. One idea is one Work item: an MKT request if its STATUS has `ur:` (the UR id), else Internal. Tasks in Notion are hand-made; the sync never writes them. Timeline runs from `started:` to `due:`. Only projects with `notion: on` in `.imp/project.md` are exported, and only each idea's own file. `sync` shows a create/update/unchanged/closed list and writes after your yes. It writes only rows with a Key and only its own properties: Owner, Priority, Mandays and your hand-made rows and Tasks stay yours. Nothing it writes mentions imp. It never deletes; `cleanup` lists Tasks with no Work item or no name and trashes only the ones you confirm |
| `/imp-init` | Connect the current project |
| `/imp:retro [session]` | Run a retrospective on a coding session (this one by default) and suggest changes to the agent's environment, most severe first: navigation, automated checks, coding standards, steering files, tool economy, information access. Adapted from [mattpocock/skills](https://github.com/mattpocock/skills) |
| `/imp:dashboard [--port N]` | Open a live local page (`http://127.0.0.1:8765/`) of every registered project's ideas: waiting on you, in progress, idle, done. `/rooms` on the same server (`http://127.0.0.1:8765/rooms`) shows a pixel campus of who works where, with a Zoom button and an Ideas chooser: live ideas and the ones you tick are in the building, the rest lounge at the pool |

The commands are called `/ideas` and `/notes` because Claude Code's built-ins already use `/status` and `/feedback`.

## Tests

```
python3 -m unittest discover -s tests -v
```

## License

MIT. See [`LICENSE`](LICENSE).
