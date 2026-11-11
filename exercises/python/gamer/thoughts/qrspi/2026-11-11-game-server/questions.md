# Clarifying Questions

## Project Type
greenfield

## Goal Summary
A local Python server hosts turn-based multiplayer games, Othello first, with
each game in its own logic module behind a common interface. Players use
browser HTML clients that show a game directory and a per-game view. The
server is the source of truth and validates every move. Version 1 has no
authentication, no persistence across restarts, and stays on the local machine
or local network.

## Existing Constraints
- `SPEC.md` — requirements R1–R6, Othello rules, and the out-of-scope list
  (no auth, no persistence, no AI opponents, no spectators/chat/matchmaking/
  rankings, Othello only). `SPEC.md` also says Research is skipped because
  the project is greenfield.
- `docs/skills/` — QRSPI phase skills. Artifacts belong under
  `thoughts/qrspi/<id>/`.
- No `.cursor/rules/`, coding-standards docs, `src/`, entry point, or
  dependency manifest. Nothing constrains the stack yet.

## Questions

1. **Transport**: Should clients receive opponent moves over WebSockets (the
   server pushes updates), or over HTTP that the client polls?
   - *Why it matters*: Push versus poll decides how "see the opponent's moves
     as they happen" (R5) is implemented, how a slow client is isolated (R1),
     and which connection state the server must keep.
   - *Default if unanswered*: WebSockets. The server pushes a state update to
     every player in the session after each accepted move.

2. **Server framework**: Should one framework (FastAPI or aiohttp) serve both
   the HTML client and the game connection, or should we use bare `asyncio`
   plus a `websockets` server and a separate static-file server?
   - *Why it matters*: This sets the dependency list, whether there is one
     process to run, and how static files and game traffic share a port.
   - *Default if unanswered*: FastAPI on Uvicorn. One process serves the
     static HTML client and a WebSocket endpoint. Python 3.12, with `uv` and
     `pytest` for tooling. Tests cover Othello rules without a server, plus
     an integration test of create, join, move, and game over.

3. **Session joining**: How do two players end up in the same match? A lobby
   that lists open sessions, a shareable session code or link, or automatic
   pairing of the next two players who pick the same game?
   - *Why it matters*: This decides the session registry (waiting, playing,
     finished), the messages for list/create/join, and what the directory
     page shows. Automatic pairing is close to matchmaking, which `SPEC.md`
     puts out of scope.
   - *Default if unanswered*: Lobby plus a shareable link. The directory lists
     games; a game page lists sessions waiting for a second player and offers
     Create. Each session has a URL the creator can share. No automatic
     pairing.

4. **Disconnects**: If a player drops mid-game, should the session hold their
   seat for reconnection, forfeit immediately, or be abandoned? When are
   finished or empty sessions removed?
   - *Why it matters*: Reconnection needs a player token on the client and a
     reserved seat on the server, and it defines identity in a system with no
     accounts (R6). Forfeit or abandon is simpler and needs no token. Games
     are not persisted across restarts, so any hold lasts only while the
     process is up.
   - *Default if unanswered*: Each player gets a random token stored in
     `localStorage`. Reconnecting with that token while the server process is
     alive reclaims the seat; the opponent sees that the other player is
     disconnected. A session is removed when the game has ended and both
     players have left, or when a waiting session has no players left.

5. **Client technology**: Plain HTML, CSS, and JavaScript with no build step,
   or a front-end framework (React, Vue, or Svelte) that needs a toolchain?
   - *Why it matters*: A Node toolchain changes the repo layout, how the
     project is started, and how a new game's view is added. No build step
     keeps the client as static files the Python server can serve.
   - *Default if unanswered*: Vanilla HTML/CSS/JS, ES modules, no build step,
     served by the Python server.

6. **Message protocol**: What is the shape of client-server messages, and how
   much is generic versus game-specific? Should the server send only raw state
   (board, turn, scores), or also derived data such as legal moves?
   - *Why it matters*: This is the common game interface (R3) as seen by the
     client. If legal moves come from the server, game views stay free of
     rules and can be tested against a JSON payload. A generic envelope lets
     a new game add a payload without changing session messages.
   - *Default if unanswered*: JSON with a generic envelope (`type`, `game`,
     `session_id`) and a game-specific payload. Every state update includes
     the board, whose turn it is, scores, game-over result, and the list of
     legal moves. No separate protocol version in v1. Each game is a package
     (`games/othello/`) with pure Python rules plus its own static view.

7. **Same-device play**: Should two players be able to share one browser tab
   (hot-seat), or does each player always use their own client?
   - *Why it matters*: Hot-seat means one connection owns both seats, which
     changes how the server binds a seat to a client and how it checks whose
     turn it is. One client per player keeps that check as "this connection's
     seat matches the turn."
   - *Default if unanswered*: Hot-seat is out of v1. One client per seat. Two
     browser tabs on the same machine are enough for local play.
