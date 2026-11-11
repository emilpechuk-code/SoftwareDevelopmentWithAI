# Gamer — Project Summary

A local, turn-based multiplayer game server with a browser client, built with the QRSPI
workflow (`docs/skills/`). Othello is the first game. The design lets you add a new game
without touching the server core.

## Run

```powershell
uv run uvicorn gamer.app:app        # or: .venv\Scripts\python.exe -m uvicorn gamer.app:app
uv run pytest                       # or: .venv\Scripts\python.exe -m pytest
```

Open `http://localhost:8000/`, pick Othello, then create an **Online** game (share the link
with a second browser or a private window) or a **Hot-seat** game (one tab plays both sides).

## Requirements met (`SPEC.md`)

| Req | What it means | How |
| --- | --- | --- |
| R1 | Slow clients don't block others | Short, independent requests; one lock held only for in-memory updates |
| R2 | Game directory, games plug in | `GAMES` list is the only place a game is named |
| R3 | Each game owns its rules | Pure `Game` protocol; rules unit-tested without a server |
| R4 | Parallel sessions, server is the source of truth | `SessionManager` checks the token, the turn and legality |
| R5 | HTML client | Directory, lobby, board, turn, scores, connection, result |
| R6 | Local, no accounts | Display names and per-seat tokens in `localStorage` |

## Architecture

There is one uvicorn process and all state lives in memory (no persistence). Clients poll
`/api/sessions/{id}/state?since=<version>` about every second, and each poll also acts as a
heartbeat. A seat counts as disconnected after 10 s without a poll, and stale sessions are
removed by a lazy sweep at the start of each request. There are no WebSockets and no
background tasks. Diagrams are in `thoughts/qrspi/2026-11-11-game-server/`
(`architecture.md`, `modules.md`, `sequence-main-flow.md`).

## Modules and owners

| Module | Files | Owner agent |
| --- | --- | --- |
| Game contract | `core/game.py`, `core/registry.py`, `games/__init__.py` | `contract-owner` |
| Sessions | `core/sessions.py` | `sessions-owner` |
| HTTP API | `app.py`, `pyproject.toml` | `api-owner` |
| Othello | `games/othello/**` (rules plus board view) | `othello-owner` |
| Client shell | `static/*.html`, `client.js`, `style.css` | `client-owner` |

The agent definitions are in `.cursor/agents/`. The main boundary rules are that the core
never imports a game, the rules never import FastAPI or the session code, and the client
never computes legality.

## History

| Commit / artifact | Content |
| --- | --- |
| `f1d6182` | Exercise starting point (`SPEC.md`, skills) |
| `fad27a9` | Phase 1: skeleton, Othello rules, game directory |
| `0566c91` | Phase 2: hot-seat game end to end |
| `4f6700b` | Phase 3: online play between two clients |
| `0fe4f11` | Phase 4: disconnects, reclaiming seats, cleanup |
| `.cursor/agents/` (uncommitted) | Per-module owner subagents |
| `thoughts/qrspi/2026-11-11-othello-board-size/plan.md` (uncommitted) | Plan for a 16x16 board as a second game, `othello-16` |

## Status

v1 is complete and all 47 tests pass. The 16x16 board is planned but not implemented. See
[HANDOFF.md](HANDOFF.md) for next steps.
