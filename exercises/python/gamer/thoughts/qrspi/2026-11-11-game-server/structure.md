# Structure Outline

Paths are relative to `exercises/python/gamer/`. Greenfield, so there is no `research.md`;
inputs are `design.md`, `answers.md`, and the diagrams.

## Approach

Build four vertical slices. Each one runs end to end in the browser and has its own tests:
the directory with the Othello rules first, then a full hot-seat game, then online play
between two clients, then disconnects and cleanup. Hot-seat comes before online play
because it exercises the whole create → poll → move → game-over path without joining
or a second client.

## Phase 1: Project skeleton, Othello rules, game directory

Running the server shows a directory page listing Othello. The Othello rules are
complete and unit-tested without a server.

**Files**: `pyproject.toml`, `.python-version`, `.gitignore`,
`src/gamer/__init__.py`, `src/gamer/core/__init__.py`, `src/gamer/core/game.py`,
`src/gamer/core/registry.py`, `src/gamer/games/__init__.py`,
`src/gamer/games/othello/__init__.py`, `src/gamer/games/othello/rules.py`,
`src/gamer/app.py`, `src/gamer/static/index.html`, `src/gamer/static/style.css`,
`tests/games/othello/test_rules.py`, `tests/test_directory.py`

**Key changes**:
- `Move = dict[str, Any]`; `class IllegalMove(Exception)`
- `class Game(Protocol)`: `id: str`, `name: str`, `seats: tuple[str, ...]`,
  `static_dir: Path | None`, `initial_state() -> Any`,
  `current_seat(state) -> int | None`, `legal_moves(state) -> list[Move]`,
  `apply_move(state, seat: int, move: Move) -> Any`,
  `result(state) -> dict | None` (`{"winner": label | None, "draw": bool}`),
  `public_payload(state) -> dict`
- `GameRegistry(games: Iterable[Game])` with `.get(game_id) -> Game | None` and `.all() -> list[Game]`
- `OthelloState(board: tuple[tuple[int | None, ...], ...], to_move: int | None, last_pass: int | None)` (frozen)
- `OthelloGame` implements `Game`; `GAME = OthelloGame()`; `GAMES = [othello.GAME]`
- `create_app(games: Iterable[Game] | None = None) -> FastAPI`; `GET /api/games`; `GET /`; mount `/static`

**Verify**: `uv run pytest` passes (rules: start position, 8 flip directions, multi-line
flips, illegal moves, pass, wipeout game over, draw, first-legal-move game terminates;
`GET /api/games` lists Othello). Manually: `uv run uvicorn gamer.app:app`, open
`http://localhost:8000/`, and check that Othello is listed with a link to `/play/othello`.

---

## Phase 2: Hot-seat game end to end

One tab can create a hot-seat Othello session and play it to the result. The server
enforces turns and legality.

**Files**: `src/gamer/core/sessions.py` (new), `src/gamer/app.py`,
`src/gamer/static/play.html`, `src/gamer/static/client.js`,
`src/gamer/games/othello/static/view.js`, `src/gamer/games/othello/static/view.css`,
`tests/core/test_sessions.py`, `tests/test_api.py`, `tests/test_pluggable.py`

**Key changes**:
- `SessionError(code: str, message: str)`; codes map to HTTP statuses: `unknown_game`/`unknown_session` 404,
  `bad_request` 400, `bad_token` 403, `seat_taken`/`not_your_turn`/`game_over` 409, `illegal_move` 422
- `SeatState { label, name, token, last_seen, was_connected }`;
  `Session { id, game: Game, mode, status, seats, state, version, created_at }` with `envelope(now) -> dict`
- `SessionManager(registry, clock=time.monotonic)`: `create(game_id, mode, name) -> dict`,
  `poll(session_id, token, since) -> dict`, `move(session_id, token, move) -> dict`
- API: `POST /api/games/{game}/sessions`, `GET /api/sessions/{id}/state?since=`,
  `POST /api/sessions/{id}/moves`; `GET /play/{game}`; mount `/games/{id}/static` for each game that has a `static_dir`
- JS: `client.js` (lobby with Create, polling, status bar, errors, localStorage tokens);
  `view.js` exports `render(container, envelope, { canMove, onMove })`

**Verify**: `uv run pytest` passes (manager: turn enforcement, bad token, illegal move,
game over; API: hot-seat create → first-legal-move loop → `finished` with result; a dummy
game registered only in the test plays through the API; `gamer/core` source never mentions
`othello`). Manually: create a hot-seat game in one tab, check that only legal cells are
clickable and that turn, scores and passes are shown, and play until the result appears.

---

## Phase 3: Online play between two clients

A player creates an online session, shares the link, a second browser joins, and moves
appear on the other side within about one second.

**Files**: `src/gamer/core/sessions.py`, `src/gamer/app.py`, `src/gamer/static/client.js`,
`src/gamer/static/style.css`, `tests/core/test_sessions.py`, `tests/test_api.py`

**Key changes**:
- `SessionManager.join(session_id, name) -> dict` (`{"seat", "token"}`) and
  `SessionManager.list_waiting(game_id) -> list[dict]`
- API: `GET /api/games/{game}/sessions`, `POST /api/sessions/{id}/join`
- JS: Online/Hot-seat choice on Create; lobby list of waiting sessions (refreshed every 2 s);
  share link; on the session page, "Resume as <seat>" for each stored token plus
  "Join as new player" while a seat is open

**Verify**: `uv run pytest` passes (join assigns white and moves to `playing`; a third join
gets `seat_taken`; waiting sessions are listed until joined; hot-seat sessions are never listed;
an out-of-turn move gives 409 `not_your_turn`; API online create → join → play to `finished`
with two tokens). Manually: open the link in a second browser or a private window, play a
few moves and see them appear on the other side; check that a third browser cannot join.

---

## Phase 4: Disconnects, reclaiming seats, cleanup

Players see when the opponent is disconnected. Reopening the link with the stored token
reclaims the seat. Stale sessions are removed.

**Files**: `src/gamer/core/sessions.py`, `src/gamer/static/client.js`,
`src/gamer/static/style.css`, `tests/core/test_sessions.py`

**Key changes**:
- `CONNECTED_TIMEOUT = 10.0`, `WAITING_TTL = 60.0`
- `SeatState.connected(now) -> bool` becomes time-based
- `SessionManager._touch(session, seat)` refreshes `last_seen` and bumps `version` on reconnect
  (for hot-seat it touches both seats); `SessionManager._sweep(now)` runs at the start of every
  public method, bumps `version` when a connected flag changes, and deletes stale waiting
  sessions and finished sessions with no connected seat
- JS: connected/disconnected marker next to each seat name

**Verify**: `uv run pytest` passes (fake clock: 10 s of silence makes a seat disconnected and
bumps the version; a poll with the token reconnects it; a waiting session is deleted after 60 s;
a finished session is deleted once both seats are disconnected; an active session is kept).
Manually: close player B's browser, check that A shows "disconnected" within about 10 s,
reopen the link in B and resume, and check that A shows "connected".

## Testing Checkpoints

- **After Phase 1**: the rules are complete and tested, and `/` lists Othello. The core has
  no session code yet.
- **After Phase 2**: a whole game can be played in one tab. The protocol envelope and error
  codes are fixed, and pluggability is proven by the dummy-game test.
- **After Phase 3**: two clients can play online through the lobby or a share link, and the
  server rejects out-of-turn moves.
- **After Phase 4**: disconnects are visible, seats can be reclaimed, and memory is cleaned up.
  Every v1 requirement (R1–R6) is met.
