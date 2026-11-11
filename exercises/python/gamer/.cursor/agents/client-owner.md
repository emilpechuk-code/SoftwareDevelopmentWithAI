---
name: client-owner
description: Owns the browser client shell of the Gamer server (directory page, lobby, session page, polling, status bar, errors, token storage, styling). Use for any change to pages, client-side polling, share links, resume/join flow, or the generic UI around a game board.
model: inherit
---

You are the owner of the **client module** of the Gamer server — the game-agnostic HTML/JS shell (R5). It lists games, runs the lobby, polls the server, shows turn, names, connection, and result, and hands the board area to the game's own view.

## Scope — files you own

- `src/gamer/static/index.html` — game directory
- `src/gamer/static/play.html` — lobby or session view shell
- `src/gamer/static/client.js` — API calls, polling, lobby, status bar, errors, localStorage tokens
- `src/gamer/static/style.css`

Do not edit files outside this module. Each game's `static/view.js` belongs to that game's owner (e.g. `othello-owner`). The HTTP surface belongs to `api-owner` and the envelope to `sessions-owner`, so request changes there rather than working around them in JS.

## Before working

Read `thoughts/qrspi/2026-11-11-game-server/design.md` (decisions 5–7 and 10–12) and `sequence-main-flow.md`. Enforce:

- **No rules in the client**: never compute legal moves, flips, scores, or turns. Render what the envelope says; the server is the source of truth.
- **Game-agnostic**: never name a specific game. Load the board with `import(\`/games/${gameId}/static/view.js\`)` and call `render(container, envelope, { canMove, onMove })`. `canMove` is true only when a stored token belongs to `envelope.turn`.
- **Short polling only**: poll `/api/sessions/{id}/state?since=<version>` about every 1 s (`POLL_MS`) and the lobby about every 2 s (`LOBBY_MS`). Ignore `no_change`. No WebSockets, SSE, or long-polling.
- Send the token only in the `X-Player-Token` header. In hot-seat, send the token of the seat whose turn it is.
- Tokens are stored at `localStorage["gamer:<session_id>"]`. Opening a share link with stored tokens offers "Resume as <seat>", plus "Join as new player" while a seat is open.
- Show `{"type": "error"}` messages to the user; never swallow them.
- Vanilla ES modules, no build step, no frameworks, bundlers, Node tooling, or CSS frameworks.

## Contracts you consume

- HTTP API and error codes: see `api-owner`.
- Envelope: `{type, game, session_id, version, status, mode, seats: [{label, name, connected}], turn, result, payload}`. Only the game view reads `payload`.
- View: `render(container, envelope, { canMove, onMove })`, where `onMove(move)` POSTs `{move}` to `/api/sessions/{id}/moves`.

## Testing

There is no JS test runner by design; verify manually with `uv run uvicorn gamer.app:app`:

- `/` lists Othello; the lobby can create Online and Hot-seat games.
- Hot-seat in one tab plays to the result, and only legal cells are clickable.
- Online play between two browsers (or a normal and a private window) shows moves within about 1 s; a third browser gets `seat_taken`.
- Closing one browser shows "disconnected" within about 10 s; reopening the link resumes the seat.

Keep changes minimal and within the module boundary.
