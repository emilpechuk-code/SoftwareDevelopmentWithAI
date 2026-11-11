# Handoff — 2026-11-11

Paths are relative to `exercises/python/gamer/`. For what the project is, see [SUMMARY.md](SUMMARY.md).

## Where things stand

- **v1 game server is done.** All four phases of `thoughts/qrspi/2026-11-11-game-server/plan.md`
  are committed (`fad27a9`, `0566c91`, `4f6700b`, `0fe4f11`). Requirements R1–R6 are met.
- **Tests:** 47 pass (`.venv\Scripts\python.exe -m pytest -q`). One harmless Starlette
  deprecation warning about `httpx`.
- **Per-module subagents are defined** in `.cursor/agents/` (uncommitted): `contract-owner`,
  `sessions-owner`, `api-owner`, `othello-owner`, `client-owner`. Each lists the files it owns,
  its boundary rules, its public API, and its tests.
- **Next feature is planned, not started:** a 16x16 Othello board, in
  `thoughts/qrspi/2026-11-11-othello-board-size/plan.md` (uncommitted).

## Uncommitted work

| Path | What it is |
| --- | --- |
| `.cursor/agents/*.md` | The five module owner agents |
| `thoughts/qrspi/2026-11-11-othello-board-size/plan.md` | The 16x16 plan |
| `thoughts/qrspi/2026-11-11-game-server/Untitled` | A leftover one-line prompt, safe to delete |

## Decisions made in this session

- **Module split:** five owners, following the import boundaries in `modules.md`. Each game
  package owns its own `view.js`/`view.css`. `games/__init__.py` belongs to `contract-owner`,
  and game owners may add exactly one registration line to it. `test_pluggable.py` belongs to
  `contract-owner`. `pyproject.toml` belongs to `api-owner`.
- **16x16 design:** register a second game, `othello-16` ("Othello 16×16"), from a size-aware
  `OthelloGame(size=...)`. This was chosen instead of generic per-session options on the
  `Game` protocol. As a result, `gamer/core`, `app.py` and `client.js` don't change. The
  trade-off is a second directory entry with its own lobby. Revisit generic options if more
  variants are requested.

## Next steps

1. **Phase 1 (`othello-owner`):** make `rules.py` size-aware, export `GAME_16`, let the view
   size its grid from `--size` with CSS that fits the viewport, and add the 16x16 rules tests.
   The app doesn't change yet.
2. **Phase 2:** add `othello.GAME_16` to `GAMES` (`contract-owner` line). In the same change,
   update `tests/test_directory.py` and `tests/test_api.py` (`api-owner`), including
   `max_moves=300` for the 16x16 HTTP game.
3. **Phase 3:** run the manual browser checks for both board sizes in hot-seat and online play.
4. Update `SPEC.md:56` ("Standard 8×8"), `design.md`, and the `othello-owner.md` wording
   (it still describes a single 8x8 game with `id = "othello"`). No agent owns these files.
5. Commit the agents and the plan.

## Gotchas

- **`uv` is not on PATH** in the current PowerShell. Use `.venv\Scripts\python.exe -m pytest`,
  or install `uv`.
- **The agents in `.cursor/agents/` are not auto-loaded as subagent types**, because they sit in
  a nested `.cursor` folder below the workspace root. To use one, launch a general-purpose
  subagent and tell it to read and follow its `.cursor/agents/<name>.md` file first.
- **`test_directory.py` compares the whole response exactly.** Registering a game without
  updating it breaks the test suite.
- **The play page heading shows the game id** (`client.js:160`), so it reads "othello-16". This
  is accepted as cosmetic in the plan.
