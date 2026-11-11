# Design Discussion

Paths are relative to `exercises/python/gamer/`.

Diagrams: [architecture](architecture.md), [modules](modules.md),
[main-flow sequence](sequence-main-flow.md).

## Current State

Greenfield. The project contains only `SPEC.md`, the QRSPI phase skills in
`docs/skills/`, and this artifact directory. There is no `src/`, dependency
manifest, entry point, or `.cursor/rules/`. Constraints come from:

- `SPEC.md:12-15` — R1: many simultaneous clients; a slow or disconnected client
  must not block others.
- `SPEC.md:17-21` — R2: game directory; adding a game needs only a new module
  plus its registration, no server-core change.
- `SPEC.md:23-29` — R3: each game owns its rules behind a common interface; the
  core knows no rules; game logic is unit-testable without server or client.
- `SPEC.md:31-37` — R4: parallel sessions; server is the source of truth and
  rejects illegal / out-of-turn moves; all players see each update.
- `SPEC.md:39-46` — R5: HTML client with a directory view and a per-game view
  showing turn, score/status, and result.
- `SPEC.md:48-52` — R6: local only, no accounts; players identified by display
  name or session-assigned id.
- `SPEC.md:54-61` — Othello rules (8×8, Black first, must flip, pass, end when
  neither can move, most discs wins, equal is a draw).
- `SPEC.md:63-70` — out of scope list.
- `answers.md:3-25` — Q-phase decisions (polling, FastAPI, lobby + link, held
  seats with tokens, vanilla JS, JSON envelope, hot-seat in v1).

## Desired End State

`uv run uvicorn gamer.app:app` starts one process on `localhost:8000` that
serves the HTML client and a JSON HTTP API. A player opens `/`, sees the game
directory (Othello), opens the Othello lobby, and either creates a session
(Online or Hot-seat) or joins a waiting Online session. The creator of an Online
session gets a shareable link. Players see the board, whose turn it is, scores,
each player's connection status, and the final result. Moves appear for the
opponent within about one second. Illegal and out-of-turn moves are rejected by
the server with an error the client displays.

Verification:
- `uv run pytest` passes:
  - Othello rules tests with no server (initial position, flips in all 8
    directions, multi-line flips, no-flip rejection, pass, game over, win/draw).
  - Session manager tests with a fake clock (turn enforcement, bad token,
    seat taken, hot-seat, disconnect after 10 s, reclaim seat, cleanup).
  - API integration test via FastAPI `TestClient`: create → join → moves →
    game over, by always playing the first legal move until the game ends.
  - A test-only dummy game registered in a test proves a new game plugs in
    without touching core code (R2).
- Manual check: two browsers (or one normal + one private window) play an Online
  game end to end; one tab plays a Hot-seat game; closing a tab shows
  "disconnected" to the opponent within about 10 s and reopening reclaims the seat.

## Patterns to Follow

No existing code, so these are the conventions the implementation sets:

- **Pure rules, no I/O** (`SPEC.md:27-29`): `games/othello/rules.py` imports
  nothing from FastAPI or `gamer.core`'s session code. State is an immutable
  dataclass; `apply_move` returns a new state.
- **Core is rules-blind** (`SPEC.md:26-27`): `gamer/core/` talks to games only
  through the `Game` protocol. It never imports `gamer.games.othello`.
- **Single registration point** (`SPEC.md:20-21`): `gamer/games/__init__.py`
  holds `GAMES = [othello.GAME]`. Adding a game = new package + one line there.
- **Server-derived legality** (`answers.md:19-23`): the client never computes
  legal moves; it renders the `legal_moves` the server sends.
- **Injectable clock**: `SessionManager(clock=time.monotonic)` so timeouts are
  tested without sleeping.
- **Artifacts** live under `thoughts/qrspi/<id>/` (`SPEC.md:90-93`).

Do NOT follow:
- No rules logic in `app.py`, `sessions.py`, or any JS outside a game's view.
- No module-level mutable globals for sessions other than the single
  `SessionManager` created in the app factory (keeps tests isolated).
- No WebSockets, background tasks, or long-polling (`answers.md:3-4`).

## Design Decisions

1. **Layout**: `src/` package with `uv`, Python 3.12.
   ```
   pyproject.toml            # fastapi, uvicorn; dev: pytest, httpx
   src/gamer/
     app.py                  # create_app(), routes, static mounts
     core/game.py            # Game protocol, Seat labels, MoveResult, IllegalMove
     core/registry.py        # lookup by id, list for the directory
     core/sessions.py        # Session, SeatState, SessionManager
     games/__init__.py       # GAMES = [...]
     games/othello/__init__.py  # GAME = OthelloGame()
     games/othello/rules.py
     games/othello/static/view.js
     static/index.html, play.html, client.js, style.css
   tests/games/othello/, tests/core/, tests/test_api.py
   ```

2. **Game interface** (`core/game.py`, a `typing.Protocol`):
   `id`, `name`, `seats` (e.g. `("black", "white")`), `initial_state()`,
   `current_seat(state) -> int | None`, `legal_moves(state) -> list[dict]`,
   `apply_move(state, seat, move: dict) -> state` (raises `IllegalMove`),
   `result(state) -> {"winner": seat | None, "draw": bool} | None`,
   `public_payload(state) -> dict`. Moves are plain JSON dicts so the core can
   pass them through untouched. Othello's pass rule lives inside `apply_move`:
   if the next seat has no legal move but the other does, the turn stays.
   The payload records `last_pass` so the client can say "White passed".

3. **Session model**: `Session` has `id` (short random URL-safe), `game_id`,
   `mode` (`online` | `hotseat`), `status` (`waiting` | `playing` | `finished`),
   `seats: list[SeatState]` (`name`, `token`, `last_seen`), `state`, `version`.
   `version` increments on every observable change: join, move, game over,
   or a seat's connected flag flipping.

4. **Hot-seat**: chosen at creation. A hot-seat session gets both tokens
   immediately, starts in `playing`, is never listed in the lobby, and has no
   share link. The same check works for both modes: a move is accepted only if
   the request's token belongs to `current_seat`. The hot-seat tab simply sends
   the token of whichever seat is to move. A poll with either token refreshes
   both seats' `last_seen`.

5. **HTTP API** (all JSON, token in `X-Player-Token` header):
   - `GET  /api/games` → directory list.
   - `GET  /api/games/{game}/sessions` → waiting Online sessions.
   - `POST /api/games/{game}/sessions` `{mode, name}` → `{session_id, seats:[{seat, token}]}`.
   - `POST /api/sessions/{id}/join` `{name}` → `{seat, token}`.
   - `GET  /api/sessions/{id}/state?since=<version>` → state envelope, or
     `{"type": "no_change", "version": n}` when `since == version`.
   - `POST /api/sessions/{id}/moves` `{move}` → state envelope or error.

6. **Envelope** (`answers.md:19-23`):
   ```json
   {"type": "state", "game": "othello", "session_id": "k3x9",
    "version": 7, "status": "playing", "mode": "online",
    "seats": [{"label": "black", "name": "Ann", "connected": true}, ...],
    "turn": "white", "result": null,
    "payload": {"board": [[...]], "scores": {"black": 3, "white": 2},
                "legal_moves": [{"row": 2, "col": 4}], "last_pass": null}}
   ```
   Errors: HTTP 4xx with `{"type": "error", "code": ..., "message": ...}`,
   codes `unknown_game`, `unknown_session`, `bad_token`, `seat_taken`,
   `not_your_turn`, `illegal_move`, `game_over`.

7. **Polling**: short poll every ~1 s with `since=<last version>`. Each poll
   is also the heartbeat. No server push, no held requests.

8. **Disconnects and cleanup**: a seat is `connected` if seen within 10 s.
   Seats are held for the life of the process; reconnecting with the stored
   token reclaims the seat. Cleanup runs as a lazy sweep at the start of
   every API request (no background task): bump `version` for sessions whose
   connected flags changed; delete `waiting` sessions with no seat seen for
   60 s; delete `finished` sessions with every seat disconnected.

9. **Concurrency** (R1): the `SessionManager` guards all mutation with one
   `threading.Lock`, so it stays correct whether FastAPI runs handlers on the
   event loop or in its threadpool. Each request is short and independent, so
   a slow client only delays its own requests.

10. **Client**: vanilla ES modules, no build. `/` → `index.html` (directory).
    `/play/{game}` → `play.html` shell, which shows the lobby, or the session
    view when `?session=<id>` is present (this is the share link). `client.js`
    owns polling, the envelope, the status bar (turn, names, connection, result)
    and errors. It dynamically imports `/games/{game}/static/view.js`, which
    exports `render(container, envelope, {canMove, onMove})`. The app mounts
    each registered game's `static/` directory, so core never names a game.

11. **Token storage**: `localStorage["gamer:<session_id>"] = [{seat, token}, ...]`.
    Because tabs in one browser share `localStorage`, opening a share link
    with a stored token offers "Resume as <seat>", plus "Join as new player"
    if a seat is still open. Same-machine Online play should use a second
    browser or a private window; Hot-seat covers one-tab play.

12. **Display names**: optional text field on create/join; default to the
    seat label ("Black", "White"). Names are not unique and not persisted.

## What We're NOT Doing

- WebSockets, server-sent events, long-polling, or background sweep tasks.
- Accounts, login, persistent profiles, or persisting sessions across restarts.
- AI opponents, spectators, chat, matchmaking/auto-pairing, rankings.
- Games other than Othello (the dummy game exists only in tests).
- A "Leave" button or forfeit; seats are held until the process exits or cleanup.
- Protocol versioning, undo, move history replay, timers/clocks per move.
- Front-end frameworks, bundlers, Node tooling, or CSS frameworks.
- Binding to anything other than localhost / LAN; no TLS.

## Open Risks

- **Background tab throttling**: browsers slow timers in hidden tabs, so a
  player who switches tabs may briefly show as disconnected. The seat stays
  held, so this is cosmetic, but expect it during manual testing.
- **Same-browser tests**: two tabs in one browser share tokens (decision 11);
  testers may be confused if they skip the second-browser advice.
- **Threadpool vs async handlers**: the lock covers correctness, but mixing
  `def` and `async def` handlers inconsistently could surprise later readers;
  Structure should pick one style.
- **Othello edge cases**: double pass ending the game early and full-board
  endings need explicit tests; the first-legal-move integration game exercises
  only one path.
- **Lazy sweep** only runs when some request arrives; with zero traffic, stale
  sessions linger in memory. Acceptable for a local v1.
