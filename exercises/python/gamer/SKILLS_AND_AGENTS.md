# Skills and Agents

Paths are relative to `exercises/python/gamer/`. There are two kinds of AI helpers in this
project:
- **Skills** (`docs/skills/`) are workflow phases. You run them in order to go from a task to a PR.
- **Agents** (`.cursor/agents/`) are module owners. Each one is allowed to change only its own
  part of the code.

## Skills — the QRSPI workflow

Each skill reads the artifacts from the previous phase and writes the next one into
`thoughts/qrspi/<id>/`.

| # | Skill | Purpose | Reads | Writes |
| --- | --- | --- | --- | --- |
| 1 | `1_questions.md` | Breaks the task into clarifying questions (greenfield) or neutral research questions (brownfield) | Task description, `goal.md` | `task.md`, `questions.md` |
| 2 | `2_research.md` | Answers the questions with facts and code references, with no opinions. Brownfield only; it stops on greenfield | `questions.md` only | `research.md` |
| 3 | `3_design.md` | A design discussion of about 200 lines: current state, desired end state, decisions, patterns. This is the cheapest point to change direction | `task.md`, `questions.md`, `answers.md` or `research.md` | `design.md` |
| 4 | `4_structure.md` | Splits the design into vertical slices, each with signatures and a test checkpoint | `design.md`, `research.md` | `structure.md` |
| 5 | `5_plan.md` | A tactical plan per phase, with exact files, code snippets, and automated and manual checks | `structure.md`, `design.md`, `research.md` | `plan.md` |
| 6 | `6_worktree.md` | Creates an isolated git worktree and branch for the implementation | Artifact directory | Worktree at `~/wt/<repo>/<branch>` |
| 7 | `7_implement.md` | Implements one phase at a time, verifies it, and ticks the plan's checkboxes. Stops and reports if the code doesn't match the plan | `plan.md` | Code, tests, updated `plan.md` |
| 8 | `8_pr.md` | Opens a PR with `gh pr create`, using the design for the "why" and the diff for the "what" | `design.md`, the diff | Pull request |

Greenfield projects skip phase 2 and use `answers.md` instead. The skills refer to helper
research agents (`codebase-locator`, `codebase-analyzer`, `codebase-pattern-finder`) for
exploration. Those helpers are not defined in this project.

### Runs so far

| Artifact directory | Phases done |
| --- | --- |
| `thoughts/qrspi/2026-11-11-game-server/` | 1, 3, 4, 5, 7. All 4 phases are implemented and committed; the diagrams are in `architecture.md`, `modules.md`, `sequence-main-flow.md` |
| `thoughts/qrspi/2026-11-11-othello-board-size/` | 5 (`plan.md` for a 16x16 board as the second game `othello-16`). Not implemented yet |

## Agents — module owners

Each agent file defines the files the agent owns, the boundary rules it must enforce, the
public API it must keep stable, and how to test its module. An agent edits only its own files.
For changes elsewhere, it hands the work to the owner of that module.

| Agent | Owns | Key boundary rules | Provides to others |
| --- | --- | --- | --- |
| `contract-owner` | `core/game.py`, `core/registry.py`, `games/__init__.py`, `tests/test_pluggable.py` | The core never imports or names a concrete game. `GAMES` is the only place a game is named | `Game` protocol, `IllegalMove`, `GameRegistry` |
| `sessions-owner` | `core/sessions.py`, `tests/core/test_sessions.py` | No game rules and no FastAPI. One lock, and an injectable clock. Turn and token checks. The version bumps on every visible change. A lazy sweep instead of background tasks | `SessionManager`, `SessionError` codes, the state envelope |
| `api-owner` | `app.py`, `tests/test_api.py`, `tests/test_directory.py`, `pyproject.toml` | A thin adapter: each route calls one manager method. Static files are mounted for each game. Errors are always `{"type": "error", ...}` | The HTTP routes, the `X-Player-Token` header, HTTP status codes |
| `othello-owner` | `games/othello/**` (rules, `view.js`, `view.css`), `tests/games/othello/` | Pure rules with an immutable state. Imports only `gamer.core.game`. The view only renders what the server sends | `OthelloGame`, its payload, the `render(container, envelope, opts)` view |
| `client-owner` | `static/index.html`, `play.html`, `client.js`, `style.css` | No game rules and never names a game. Short polling only. Plain JavaScript with no build step | The directory, lobby, status bar and token storage |

### Shared contracts (coordinate before changing)

- **`Game` protocol:** `contract-owner` defines it, and `sessions-owner` and every game owner use it.
- **Envelope and error codes:** `sessions-owner` defines them. `api-owner` maps the codes to HTTP
  statuses, and `client-owner` and each game view read the envelope.
- **HTTP routes:** `api-owner` defines them and `client-owner` calls them.
- **Board view function** `render(container, envelope, { canMove, onMove })`: each game owner
  writes it and `client-owner` calls it.

### Using the agents

These agents sit in a `.cursor` folder below the workspace root, so Cursor doesn't load them
automatically as subagent types. To use one, start a general-purpose subagent and tell it to
read `.cursor/agents/<name>.md` first and follow it. That is how `othello-owner` produced the
16x16 plan.

Adding a new game means adding a `<game>-owner.md` agent modeled on `othello-owner.md`.
