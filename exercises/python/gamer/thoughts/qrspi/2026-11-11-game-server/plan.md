# Implementation Plan

## Overview

One local FastAPI process (`uv run uvicorn gamer.app:app`) serves a vanilla-JS client and a JSON
polling API for turn-based games. Othello is the first game, and it plugs in through a `Game`
protocol the core never bypasses. Players can play hot-seat in one tab or online through a lobby
or a share link. The server enforces turns and legality, and shows disconnects after 10 s.

All paths are relative to `exercises/python/gamer/`. Run every command from that directory.

### Resolved details (not spelled out in `design.md`)

- **HTTP status per error code**: `unknown_game`/`unknown_session` 404, `bad_request` 400,
  `bad_token` 403, `seat_taken`/`not_your_turn`/`game_over` 409, `illegal_move` 422.
  A move while the session is still waiting returns `not_your_turn` ("Waiting for an opponent to join").
- **Token is required** on `state` and `moves`. Before joining, the share-link page uses the lobby
  list to decide whether a seat is open.
- **`Game.static_dir: Path | None`** tells the app which directory to mount at `/games/{id}/static`.
  This keeps the core free of game names.
- **Registry** is a `GameRegistry` class with `get` and `all`. `Session` holds the `Game` object
  rather than a `game_id`.
- **Client storage**: `localStorage["gamer:<id>"] = {mode, seats: [{seat, token}]}` holds the tokens.
  `sessionStorage["gamer:tab:<id>"] = [labels]` remembers which seats this tab plays, so the
  creator's own tab resumes without being asked to choose.
- **Python**: `uv` is not installed on this machine and the system Python is 3.15. `.python-version`
  pins 3.12, so `uv` downloads it, and there may be no wheels for 3.15 yet.

---

## Phase 1: Project skeleton, Othello rules, game directory

### Changes

#### 0. Tooling prerequisite
**Action**: install `uv` if `uv --version` fails:
`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
(or `py -m pip install --user uv`). Open a new terminal afterwards.

#### 1. Project files
**File**: `pyproject.toml` — **create**

```toml
[project]
name = "gamer"
version = "0.1.0"
description = "Local turn-based multiplayer game server"
requires-python = ">=3.12"
dependencies = ["fastapi>=0.115", "uvicorn>=0.30"]

[dependency-groups]
dev = ["pytest>=8", "httpx>=0.27"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/gamer"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

**File**: `.python-version` — **create** with the single line `3.12`.

**File**: `.gitignore` — **create** with `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`. Commit `uv.lock` (do not ignore it).

**Files**: `src/gamer/__init__.py`, `src/gamer/core/__init__.py` — **create** empty.

#### 2. Game protocol
**File**: `src/gamer/core/game.py` — **create**

```python
from pathlib import Path
from typing import Any, Protocol

Move = dict[str, Any]


class IllegalMove(Exception):
    """Raised by a game when a move breaks its rules."""


class Game(Protocol):
    id: str
    name: str
    seats: tuple[str, ...]
    static_dir: Path | None

    def initial_state(self) -> Any: ...
    def current_seat(self, state: Any) -> int | None: ...
    def legal_moves(self, state: Any) -> list[Move]: ...
    def apply_move(self, state: Any, seat: int, move: Move) -> Any: ...
    def result(self, state: Any) -> dict | None: ...
    def public_payload(self, state: Any) -> dict: ...
```

`result` returns `None` while the game is running, else `{"winner": <seat label> | None, "draw": bool}`.

#### 3. Registry
**File**: `src/gamer/core/registry.py` — **create**

```python
from collections.abc import Iterable

from gamer.core.game import Game


class GameRegistry:
    def __init__(self, games: Iterable[Game]) -> None:
        self._games: dict[str, Game] = {}
        for game in games:
            if game.id in self._games:
                raise ValueError(f"duplicate game id: {game.id}")
            self._games[game.id] = game

    def get(self, game_id: str) -> Game | None:
        return self._games.get(game_id)

    def all(self) -> list[Game]:
        return list(self._games.values())
```

#### 4. Othello rules
**File**: `src/gamer/games/othello/rules.py` — **create**

```python
from dataclasses import dataclass
from pathlib import Path

from gamer.core.game import IllegalMove, Move

SIZE = 8
BLACK, WHITE = 0, 1
SEATS = ("black", "white")
DIRECTIONS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

Board = tuple[tuple[int | None, ...], ...]


@dataclass(frozen=True)
class OthelloState:
    board: Board
    to_move: int | None  # None once neither player can move
    last_pass: int | None = None


def _on_board(row: int, col: int) -> bool:
    return 0 <= row < SIZE and 0 <= col < SIZE


def flips(board: Board, seat: int, row: int, col: int) -> list[tuple[int, int]]:
    if board[row][col] is not None:
        return []
    other = 1 - seat
    flipped: list[tuple[int, int]] = []
    for dr, dc in DIRECTIONS:
        line = []
        r, c = row + dr, col + dc
        while _on_board(r, c) and board[r][c] == other:
            line.append((r, c))
            r, c = r + dr, c + dc
        if line and _on_board(r, c) and board[r][c] == seat:
            flipped.extend(line)
    return flipped


def moves_for(board: Board, seat: int) -> list[tuple[int, int]]:
    return [(r, c) for r in range(SIZE) for c in range(SIZE) if flips(board, seat, r, c)]


def _parse_move(move: Move) -> tuple[int, int]:
    if not isinstance(move, dict):
        raise IllegalMove("A move must be an object with row and col")
    row, col = move.get("row"), move.get("col")
    if type(row) is not int or type(col) is not int:
        raise IllegalMove("row and col must be integers")
    if not _on_board(row, col):
        raise IllegalMove("That square is off the board")
    return row, col


def _scores(board: Board) -> dict[str, int]:
    return {label: sum(row.count(seat) for row in board) for seat, label in enumerate(SEATS)}


class OthelloGame:
    id = "othello"
    name = "Othello"
    seats = SEATS
    static_dir: Path | None = Path(__file__).parent / "static"

    def initial_state(self) -> OthelloState:
        rows: list[list[int | None]] = [[None] * SIZE for _ in range(SIZE)]
        rows[3][3] = rows[4][4] = WHITE
        rows[3][4] = rows[4][3] = BLACK
        return OthelloState(tuple(tuple(r) for r in rows), to_move=BLACK)

    def current_seat(self, state: OthelloState) -> int | None:
        return state.to_move

    def legal_moves(self, state: OthelloState) -> list[Move]:
        if state.to_move is None:
            return []
        return [{"row": r, "col": c} for r, c in moves_for(state.board, state.to_move)]

    def apply_move(self, state: OthelloState, seat: int, move: Move) -> OthelloState:
        if state.to_move is None:
            raise IllegalMove("The game is over")
        if seat != state.to_move:
            raise IllegalMove("It is not this seat's turn")
        row, col = _parse_move(move)
        flipped = flips(state.board, seat, row, col)
        if not flipped:
            raise IllegalMove("A move must flip at least one disc")
        rows = [list(r) for r in state.board]
        for r, c in [(row, col), *flipped]:
            rows[r][c] = seat
        board = tuple(tuple(r) for r in rows)
        other = 1 - seat
        if moves_for(board, other):
            return OthelloState(board, to_move=other)
        if moves_for(board, seat):
            return OthelloState(board, to_move=seat, last_pass=other)
        return OthelloState(board, to_move=None)

    def result(self, state: OthelloState) -> dict | None:
        if state.to_move is not None:
            return None
        scores = _scores(state.board)
        if scores["black"] == scores["white"]:
            return {"winner": None, "draw": True}
        return {"winner": max(scores, key=scores.get), "draw": False}

    def public_payload(self, state: OthelloState) -> dict:
        return {
            "board": [[None if cell is None else SEATS[cell] for cell in row] for row in state.board],
            "scores": _scores(state.board),
            "legal_moves": self.legal_moves(state),
            "last_pass": None if state.last_pass is None else SEATS[state.last_pass],
        }
```

**File**: `src/gamer/games/othello/__init__.py` — **create**

```python
from gamer.games.othello.rules import OthelloGame

GAME = OthelloGame()
```

**File**: `src/gamer/games/__init__.py` — **create** (the only place games are registered)

```python
from gamer.games import othello

GAMES = [othello.GAME]
```

#### 5. App with directory
**File**: `src/gamer/app.py` — **create**

```python
from collections.abc import Iterable
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gamer.core.game import Game
from gamer.core.registry import GameRegistry
from gamer.games import GAMES

STATIC_DIR = Path(__file__).parent / "static"


def create_app(games: Iterable[Game] | None = None) -> FastAPI:
    registry = GameRegistry(GAMES if games is None else games)
    app = FastAPI(title="Gamer")

    @app.get("/api/games")
    def list_games():
        return {
            "type": "games",
            "games": [{"id": g.id, "name": g.name, "seats": list(g.seats)} for g in registry.all()],
        }

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
```

All route handlers are plain `def`. Phase 2 makes the session manager thread-safe for FastAPI's threadpool.

#### 6. Directory page
**File**: `src/gamer/static/index.html` — **create**: the page links `/static/style.css`, has an `<h1>Gamer</h1>` header and `<ul id="games">`, and includes this inline module script:

```html
<script type="module">
  const list = document.getElementById("games");
  const { games } = await (await fetch("/api/games")).json();
  list.replaceChildren(...games.map((g) => {
    const link = Object.assign(document.createElement("a"), { href: `/play/${g.id}`, textContent: g.name });
    const item = document.createElement("li");
    item.append(link);
    return item;
  }));
</script>
```

**File**: `src/gamer/static/style.css` — **create**

```css
body { font-family: system-ui, sans-serif; margin: 2rem; color: #222; }
header { display: flex; gap: 1rem; align-items: baseline; }
section { margin-bottom: 1.5rem; }
input, select, button { font: inherit; margin: 0.25rem 0.5rem 0.25rem 0; }
#error { color: #b00020; min-height: 1.5em; }
.status .seat { margin-right: 1rem; }
.status .to-move { font-weight: bold; }
```

#### 7. Tests
**File**: `tests/games/othello/test_rules.py` — **create**

```python
import pytest

from gamer.core.game import IllegalMove
from gamer.games.othello.rules import BLACK, DIRECTIONS, WHITE, OthelloGame, OthelloState

GAME = OthelloGame()
EMPTY = "........"


def board_from(rows: list[str]):
    cells = {".": None, "B": BLACK, "W": WHITE}
    return tuple(tuple(cells[ch] for ch in row) for row in rows)
```

Tests (one function each):
- `test_initial_position`: `board[3][3] == board[4][4] == WHITE`, `board[3][4] == board[4][3] == BLACK`; current seat is `BLACK`; the legal moves are exactly `{(2,3), (3,2), (4,5), (5,4)}`; scores are `{"black": 2, "white": 2}`; `result` is `None`.
- `test_flips_in_each_direction` (`@pytest.mark.parametrize("dr,dc", DIRECTIONS)`): empty board, `W` at `(4+dr, 4+dc)`, `B` at `(4+2dr, 4+2dc)`, Black plays `(4,4)`; check that `(4+dr, 4+dc)` is now `BLACK`.
- `test_flips_multiple_lines`: row 0 `"BWW.WWB."`, Black plays `(0,3)`; check that all of `(0,1)`, `(0,2)`, `(0,4)` and `(0,5)` are flipped and that the Black score is 7.
- `test_rejects_illegal_moves` (parametrized): on the initial state, each of `{"row":0,"col":0}` (no flip), `{"row":3,"col":3}` (occupied), `{"row":8,"col":0}` (off board), `{"row":"2","col":3}` (bad type), and `{}` raises `IllegalMove`.
- `test_rejects_wrong_seat`: `apply_move(initial, WHITE, {"row":2,"col":3})` raises `IllegalMove`.
- `test_pass_keeps_turn`: rows `[".WB.....", EMPTY*6, "BW......"]` with Black to move; Black plays `(0,0)` → `to_move == BLACK`, `last_pass == WHITE`, and payload `last_pass == "white"`.
- `test_wipeout_ends_game`: rows `[".WB.....", EMPTY*7]`; Black plays `(0,0)` → `current_seat` is `None`, `legal_moves == []`, `result == {"winner": "black", "draw": False}`, and `apply_move` again raises `IllegalMove`.
- `test_equal_discs_is_draw`: `OthelloState(board_from(["BW......", "WB......", *[EMPTY]*6]), to_move=None)` → `{"winner": None, "draw": True}`.
- `test_first_legal_move_game_ends`: starting from the initial state, apply `legal_moves(state)[0]` for the current seat in a loop of at most 64 moves; check that `result` is not `None` and that the scores sum to at most 64.

**File**: `tests/test_directory.py` — **create**: with `TestClient(create_app())`, `GET /api/games` returns
`{"type": "games", "games": [{"id": "othello", "name": "Othello", "seats": ["black", "white"]}]}`, and `GET /` returns 200 with `text/html`.

### Verification
#### Automated
- [x] `uv sync` succeeds and creates `.venv` with Python 3.12
- [x] `uv run pytest tests/games/othello -q` passes
- [x] `uv run pytest -q` passes

#### Manual
- [ ] `uv run uvicorn gamer.app:app --reload`, open `http://localhost:8000/`: "Othello" is listed and links to `/play/othello` (that page returns 404 until Phase 2)

---

## Phase 2: Hot-seat game end to end

### Changes

#### 1. Session manager
**File**: `src/gamer/core/sessions.py` — **create**

```python
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gamer.core.game import Game, IllegalMove, Move
from gamer.core.registry import GameRegistry

MODES = ("online", "hotseat")
MAX_NAME = 40


class SessionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class SeatState:
    label: str
    name: str | None = None
    token: str | None = None
    last_seen: float | None = None
    was_connected: bool = False

    def connected(self, now: float) -> bool:
        return self.token is not None


@dataclass
class Session:
    id: str
    game: Game
    mode: str
    seats: list[SeatState]
    state: Any
    status: str = "waiting"
    version: int = 1
    created_at: float = 0.0

    def envelope(self, now: float) -> dict:
        seat = self.game.current_seat(self.state)
        return {
            "type": "state",
            "game": self.game.id,
            "session_id": self.id,
            "version": self.version,
            "status": self.status,
            "mode": self.mode,
            "seats": [{"label": s.label, "name": s.name, "connected": s.connected(now)} for s in self.seats],
            "turn": self.game.seats[seat] if seat is not None and self.status == "playing" else None,
            "result": self.game.result(self.state),
            "payload": self.game.public_payload(self.state),
        }


class SessionManager:
    def __init__(self, registry: GameRegistry, clock: Callable[[], float] = time.monotonic) -> None:
        self._registry = registry
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def create(self, game_id: str, mode: str, name: str | None) -> dict:
        with self._lock:
            now = self._clock()
            game = self._game(game_id)
            if mode not in MODES:
                raise SessionError("bad_request", f"mode must be one of: {', '.join(MODES)}")
            seats = [SeatState(label) for label in game.seats]
            owned = seats if mode == "hotseat" else seats[:1]
            for i, seat in enumerate(owned):
                self._claim(seat, name if i == 0 else None, now)
            session = Session(
                id=self._new_id(), game=game, mode=mode, seats=seats, state=game.initial_state(),
                status="playing" if len(owned) == len(seats) else "waiting", created_at=now,
            )
            self._sessions[session.id] = session
            return {"session_id": session.id, "seats": [{"seat": s.label, "token": s.token} for s in owned]}

    def poll(self, session_id: str, token: str | None, since: int | None) -> dict:
        with self._lock:
            now = self._clock()
            session = self._session(session_id)
            self._seat_index(session, token)
            if since == session.version:
                return {"type": "no_change", "version": session.version}
            return session.envelope(now)

    def move(self, session_id: str, token: str | None, move: Move) -> dict:
        with self._lock:
            now = self._clock()
            session = self._session(session_id)
            seat = self._seat_index(session, token)
            if session.status == "waiting":
                raise SessionError("not_your_turn", "Waiting for an opponent to join")
            if session.status == "finished":
                raise SessionError("game_over", "The game is over")
            if session.game.current_seat(session.state) != seat:
                raise SessionError("not_your_turn", "It is not your turn")
            try:
                session.state = session.game.apply_move(session.state, seat, move)
            except IllegalMove as exc:
                raise SessionError("illegal_move", str(exc)) from exc
            if session.game.result(session.state) is not None:
                session.status = "finished"
            session.version += 1
            return session.envelope(now)

    def _claim(self, seat: SeatState, name: str | None, now: float) -> None:
        cleaned = (name or "").strip()[:MAX_NAME]
        seat.name = cleaned or seat.label.title()
        seat.token = secrets.token_urlsafe(16)
        seat.last_seen = now
        seat.was_connected = True

    def _game(self, game_id: str) -> Game:
        game = self._registry.get(game_id)
        if game is None:
            raise SessionError("unknown_game", f"Unknown game: {game_id}")
        return game

    def _session(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionError("unknown_session", "Session not found")
        return session

    def _seat_index(self, session: Session, token: str | None) -> int:
        if token:
            for i, seat in enumerate(session.seats):
                if seat.token is not None and secrets.compare_digest(seat.token, token):
                    return i
        raise SessionError("bad_token", "This token does not hold a seat in the session")

    def _new_id(self) -> str:
        while True:
            session_id = secrets.token_urlsafe(6)
            if session_id not in self._sessions:
                return session_id
```

#### 2. API routes
**File**: `src/gamer/app.py` — **modify**

- New imports: `time`, `Callable` from `collections.abc`, `Annotated` from `typing`, `Header` and `Request` from `fastapi`, `JSONResponse`,
  `BaseModel` from `pydantic`, and `SessionError` and `SessionManager` from `gamer.core.sessions`.
- Signature: `def create_app(games: Iterable[Game] | None = None, clock: Callable[[], float] = time.monotonic) -> FastAPI`.

```python
ERROR_STATUS = {
    "bad_request": 400, "bad_token": 403, "unknown_game": 404, "unknown_session": 404,
    "seat_taken": 409, "not_your_turn": 409, "game_over": 409, "illegal_move": 422,
}
Token = Annotated[str | None, Header(alias="X-Player-Token")]


class CreateSession(BaseModel):
    mode: str = "online"
    name: str | None = None


class MoveRequest(BaseModel):
    move: dict


# inside create_app, after the registry:
    manager = SessionManager(registry, clock=clock)
    app.state.manager = manager

    @app.exception_handler(SessionError)
    async def session_error(request: Request, exc: SessionError):
        return JSONResponse(
            status_code=ERROR_STATUS[exc.code],
            content={"type": "error", "code": exc.code, "message": exc.message},
        )

    @app.post("/api/games/{game_id}/sessions")
    def create_session(game_id: str, body: CreateSession):
        return manager.create(game_id, body.mode, body.name)

    @app.get("/api/sessions/{session_id}/state")
    def session_state(session_id: str, x_player_token: Token = None, since: int | None = None):
        return manager.poll(session_id, x_player_token, since)

    @app.post("/api/sessions/{session_id}/moves")
    def make_move(session_id: str, body: MoveRequest, x_player_token: Token = None):
        return manager.move(session_id, x_player_token, body.move)

    @app.get("/play/{game_id}")
    def play(game_id: str):
        if registry.get(game_id) is None:
            raise SessionError("unknown_game", f"Unknown game: {game_id}")
        return FileResponse(STATIC_DIR / "play.html")

# after the /static mount:
    for game in registry.all():
        if game.static_dir is not None:
            app.mount(f"/games/{game.id}/static", StaticFiles(directory=game.static_dir), name=f"game-{game.id}")
```

#### 3. Play page and client
**File**: `src/gamer/static/play.html` — **create**: links `/static/style.css`; body contains
`<header><a href="/">All games</a><h1 id="title"></h1></header>`, `<p id="error" role="alert"></p>`,
`<main id="app"></main>`, `<script type="module" src="/static/client.js"></script>`.

**File**: `src/gamer/static/client.js` — **create**

```js
const gameId = location.pathname.split("/")[2];
const sessionId = new URLSearchParams(location.search).get("session");
const app = document.getElementById("app");
const POLL_MS = 1000;

async function api(path, { method = "GET", body, token } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-Player-Token"] = token;
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message ?? JSON.stringify(data.detail ?? res.statusText));
  return data;
}

const storageKey = (id) => `gamer:${id}`;
const loadEntry = (id) => JSON.parse(localStorage.getItem(storageKey(id)) ?? "null");
const saveEntry = (id, entry) => localStorage.setItem(storageKey(id), JSON.stringify(entry));

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

function showError(message) {
  document.getElementById("error").textContent = message ?? "";
}

function statusMessage(env) {
  const name = (label) => env.seats.find((s) => s.label === label)?.name ?? label;
  if (env.result) return env.result.draw ? "Game over: draw" : `Game over: ${name(env.result.winner)} wins`;
  if (env.status === "waiting") return "Waiting for an opponent to join…";
  return `${name(env.turn)} to move`;
}

function statusLines(env, seats) {
  const mine = new Set(seats.map((s) => s.seat));
  const players = env.seats.map((s) => el("span", {
    className: `seat ${s.label}${env.turn === s.label ? " to-move" : ""}`,
    textContent: `${s.name} (${s.label})${mine.has(s.label) ? " – you" : ""}`,
  }));
  return [el("p", {}, ...players), el("p", { textContent: statusMessage(env) })];
}

async function startSession(seats) {
  const view = await import(`/games/${gameId}/static/view.js`);
  const status = el("div", { className: "status" });
  const board = el("div");
  app.replaceChildren(status, board);
  const tokenFor = (label) => seats.find((s) => s.seat === label)?.token;
  let latest = null;

  function accept(env) {
    if (latest && env.version < latest.version) return;
    latest = env;
    status.replaceChildren(...statusLines(latest, seats));
    view.render(board, latest, {
      canMove: latest.status === "playing" && Boolean(tokenFor(latest.turn)),
      onMove: async (move) => {
        try {
          accept(await api(`/api/sessions/${sessionId}/moves`, { method: "POST", body: { move }, token: tokenFor(latest.turn) }));
          showError("");
        } catch (e) {
          showError(e.message);
        }
      },
    });
  }

  async function poll() {
    try {
      const since = latest ? `?since=${latest.version}` : "";
      const res = await api(`/api/sessions/${sessionId}/state${since}`, { token: seats[0].token });
      if (res.type === "state") accept(res);
    } catch (e) {
      showError(e.message);
    }
    setTimeout(poll, POLL_MS);
  }
  poll();
}

function renderLobby() {
  const name = el("input", { placeholder: "Your name (optional)", maxLength: 40 });
  const create = el("button", { textContent: "Create hot-seat game" });
  create.addEventListener("click", async () => {
    try {
      const res = await api(`/api/games/${gameId}/sessions`, { method: "POST", body: { mode: "hotseat", name: name.value } });
      saveEntry(res.session_id, { mode: "hotseat", seats: res.seats });
      location.search = `?session=${res.session_id}`;
    } catch (e) {
      showError(e.message);
    }
  });
  app.replaceChildren(el("section", {}, el("h2", { textContent: "New game" }), name, create));
}

document.getElementById("title").textContent = gameId;
if (!sessionId) {
  renderLobby();
} else {
  const entry = loadEntry(sessionId);
  if (entry) startSession(entry.seats);
  else showError("You do not hold a seat in this game.");
}
```

#### 4. Othello view
**File**: `src/gamer/games/othello/static/view.js` — **create**

```js
const css = document.createElement("link");
css.rel = "stylesheet";
css.href = new URL("./view.css", import.meta.url).href;
document.head.append(css);

const title = (label) => label[0].toUpperCase() + label.slice(1);

export function render(container, envelope, { canMove, onMove }) {
  const { board, scores, legal_moves: legalMoves, last_pass: lastPass } = envelope.payload;
  const legal = new Set(canMove ? legalMoves.map((m) => `${m.row},${m.col}`) : []);
  const grid = document.createElement("div");
  grid.className = "othello-board";
  board.forEach((row, r) => row.forEach((cell, c) => {
    const square = document.createElement("button");
    square.className = "othello-cell";
    if (cell) {
      const disc = document.createElement("span");
      disc.className = `disc ${cell}`;
      square.append(disc);
    }
    if (legal.has(`${r},${c}`)) {
      square.classList.add("legal");
      square.addEventListener("click", () => onMove({ row: r, col: c }));
    } else {
      square.disabled = true;
    }
    grid.append(square);
  }));
  const info = document.createElement("p");
  info.textContent = `Black ${scores.black} – White ${scores.white}` + (lastPass ? ` · ${title(lastPass)} passed` : "");
  container.replaceChildren(info, grid);
}
```

**File**: `src/gamer/games/othello/static/view.css` — **create**

```css
.othello-board { display: grid; grid-template-columns: repeat(8, 3rem); gap: 2px; padding: 4px; background: #1b5e20; width: max-content; }
.othello-cell { width: 3rem; height: 3rem; padding: 0; border: none; background: #2e7d32; display: grid; place-items: center; }
.othello-cell:disabled { opacity: 1; cursor: default; }
.othello-cell.legal { cursor: pointer; box-shadow: inset 0 0 0 3px #a5d6a7; }
.disc { width: 80%; height: 80%; border-radius: 50%; }
.disc.black { background: #111; }
.disc.white { background: #f5f5f5; border: 1px solid #999; }
```

#### 5. Tests
**File**: `tests/core/test_sessions.py` — **create**. Fixture `manager = SessionManager(GameRegistry([OthelloGame()]))`.
Helper `play_to_end(manager, sid, tokens: dict[str, str]) -> dict`: poll with any token, then for at most 100 iterations
`move(sid, tokens[env["turn"]], env["payload"]["legal_moves"][0])` until `env["status"] == "finished"`.
Assert error codes with `pytest.raises(SessionError)` and `exc.value.code`. Tests:
- `test_create_hotseat_holds_both_seats`: 2 tokens returned; `status == "playing"`; `turn == "black"`; 4 legal moves; default names `"Black"`/`"White"`, or the given name for the first seat.
- `test_poll_since_current_version_is_no_change`
- `test_poll_rejects_unknown_session_and_bad_token`: codes `unknown_session` and `bad_token` (also for a `None` token).
- `test_create_rejects_unknown_game_and_mode`: codes `unknown_game` and `bad_request`.
- `test_move_out_of_turn_rejected`: the white token on Black's turn gives `not_your_turn`.
- `test_illegal_move_rejected`: `{"row":0,"col":0}` gives `illegal_move`, and the version is unchanged.
- `test_legal_move_advances_version_and_turn`
- `test_game_finishes_and_rejects_further_moves`: after `play_to_end`, `status == "finished"`, `result` is set, and another move gives `game_over`.

**File**: `tests/test_api.py` — **create**. `client = TestClient(create_app())`. Helper `play_to_end(client, sid, tokens)`, the same loop over HTTP with the `X-Player-Token` header and checking `status_code == 200`. Tests:
- `test_hotseat_game_over_http`: `POST /api/games/othello/sessions {"mode": "hotseat"}` → play to the end → `status == "finished"` and `result` is set.
- `test_error_status_codes`: unknown session 404, bad token 403, out of turn 409 `not_your_turn`, illegal move 422 `illegal_move`; every body has `type == "error"`.
- `test_play_page_and_view_served`: `/play/othello` 200, `/play/nope` 404, `/games/othello/static/view.js` 200.

**File**: `tests/test_pluggable.py` — **create**

```python
from pathlib import Path

from fastapi.testclient import TestClient

from gamer.app import create_app
from gamer.core.game import IllegalMove


class CountToThree:
    id = "count"
    name = "Count to three"
    seats = ("a", "b")
    static_dir = None

    def initial_state(self): return 0
    def current_seat(self, state): return None if state >= 3 else state % 2
    def legal_moves(self, state): return [] if state >= 3 else [{"step": 1}]
    def result(self, state): return {"winner": "a", "draw": False} if state >= 3 else None
    def public_payload(self, state): return {"count": state, "legal_moves": self.legal_moves(state)}

    def apply_move(self, state, seat, move):
        if move != {"step": 1}:
            raise IllegalMove("Only {'step': 1} is allowed")
        return state + 1


def test_new_game_plugs_in_without_core_changes():
    client = TestClient(create_app(games=[CountToThree()]))
    assert [g["id"] for g in client.get("/api/games").json()["games"]] == ["count"]
    created = client.post("/api/games/count/sessions", json={"mode": "hotseat"}).json()
    tokens = {s["seat"]: s["token"] for s in created["seats"]}
    for seat in ["a", "b", "a"]:
        res = client.post(f"/api/sessions/{created['session_id']}/moves",
                          json={"move": {"step": 1}}, headers={"X-Player-Token": tokens[seat]})
        assert res.status_code == 200
    assert res.json()["status"] == "finished"
    assert res.json()["result"] == {"winner": "a", "draw": False}


def test_core_never_names_a_concrete_game():
    core = Path(__file__).parents[1] / "src" / "gamer" / "core"
    for path in core.glob("*.py"):
        assert "othello" not in path.read_text(encoding="utf-8").lower(), path
```

### Verification
#### Automated
- [x] `uv run pytest tests/core tests/test_api.py tests/test_pluggable.py -q` passes
- [x] `uv run pytest -q` passes (Phase 1 tests still green)

#### Manual
- [ ] `uv run uvicorn gamer.app:app --reload`; `/` → Othello → "Create hot-seat game" opens `/play/othello?session=<id>`
- [ ] Only legal squares are highlighted and clickable; the side to move is bold; scores update after each move
- [ ] Play to the end and check that "Game over: … wins" or "draw" appears and the board stops accepting clicks
- [ ] Reload the page: the same game resumes from `localStorage`

---

## Phase 3: Online play between two clients

### Changes

#### 1. Join and lobby in the manager
**File**: `src/gamer/core/sessions.py` — **modify**: add these methods to `SessionManager`

```python
    def join(self, session_id: str, name: str | None) -> dict:
        with self._lock:
            now = self._clock()
            session = self._session(session_id)
            free = next((s for s in session.seats if s.token is None), None)
            if session.mode != "online" or free is None:
                raise SessionError("seat_taken", "This game has no open seat")
            self._claim(free, name, now)
            if all(s.token is not None for s in session.seats):
                session.status = "playing"
            session.version += 1
            return {"seat": free.label, "token": free.token}

    def list_waiting(self, game_id: str) -> list[dict]:
        with self._lock:
            self._game(game_id)
            waiting = [s for s in self._sessions.values()
                       if s.game.id == game_id and s.mode == "online" and s.status == "waiting"]
            return [{"session_id": s.id, "host": s.seats[0].name}
                    for s in sorted(waiting, key=lambda s: s.created_at)]
```

#### 2. API routes
**File**: `src/gamer/app.py` — **modify**

```python
class JoinSession(BaseModel):
    name: str | None = None

    @app.get("/api/games/{game_id}/sessions")
    def waiting_sessions(game_id: str):
        return {"type": "sessions", "sessions": manager.list_waiting(game_id)}

    @app.post("/api/sessions/{session_id}/join")
    def join_session(session_id: str, body: JoinSession):
        return manager.join(session_id, body.name)
```

#### 3. Client: online create, lobby list, share link, join/resume
**File**: `src/gamer/static/client.js` — **modify**

- Add `const LOBBY_MS = 2000;`, plus a tab-local seat memory:
  ```js
  const tabKey = (id) => `gamer:tab:${id}`;
  ```
  At the top of `startSession(seats)`, add `sessionStorage.setItem(tabKey(sessionId), JSON.stringify(seats.map((s) => s.seat)));`.
- In `statusLines`, when `env.mode === "online" && env.status === "waiting"`, append
  `el("p", { className: "share" }, "Share this link: ", el("input", { readOnly: true, value: location.href }))`.
- Replace `renderLobby` with:
  ```js
  function renderLobby() {
    const name = el("input", { placeholder: "Your name (optional)", maxLength: 40 });
    const mode = el("select", {},
      el("option", { value: "online", textContent: "Online (share a link)" }),
      el("option", { value: "hotseat", textContent: "Hot-seat (this tab plays both)" }));
    const create = el("button", { textContent: "Create game" });
    create.addEventListener("click", async () => {
      try {
        const res = await api(`/api/games/${gameId}/sessions`, { method: "POST", body: { mode: mode.value, name: name.value } });
        saveEntry(res.session_id, { mode: mode.value, seats: res.seats });
        sessionStorage.setItem(tabKey(res.session_id), JSON.stringify(res.seats.map((s) => s.seat)));
        location.search = `?session=${res.session_id}`;
      } catch (e) {
        showError(e.message);
      }
    });
    const waiting = el("ul", {}, el("li", { textContent: "Loading…" }));
    app.replaceChildren(
      el("section", {}, el("h2", { textContent: "New game" }), name, mode, create),
      el("section", {}, el("h2", { textContent: "Open games" }), waiting),
    );
    async function refresh() {
      try {
        const { sessions } = await api(`/api/games/${gameId}/sessions`);
        waiting.replaceChildren(...(sessions.length
          ? sessions.map((s) => el("li", {}, el("a", { href: `?session=${s.session_id}`, textContent: `${s.host}'s game` })))
          : [el("li", { textContent: "No open games yet." })]));
      } catch (e) {
        showError(e.message);
      }
      setTimeout(refresh, LOBBY_MS);
    }
    refresh();
  }
  ```
- Add `openSession` and `joinForm`, and replace the `else` branch of the entry point with `openSession().catch((e) => showError(e.message));`:
  ```js
  async function openSession() {
    const entry = loadEntry(sessionId);
    const stored = entry?.seats ?? [];
    const tabSeats = JSON.parse(sessionStorage.getItem(tabKey(sessionId)) ?? "[]");
    const mine = stored.filter((s) => tabSeats.includes(s.seat));
    if (mine.length) return startSession(mine);
    if (entry?.mode === "hotseat") return startSession(stored);
    const { sessions } = await api(`/api/games/${gameId}/sessions`);
    const open = sessions.some((s) => s.session_id === sessionId);
    if (!open && stored.length === 1) return startSession(stored);
    if (!open && stored.length === 0) return showError("This game is full or no longer exists.");
    const choices = stored.map((s) => {
      const resume = el("button", { textContent: `Resume as ${s.seat}` });
      resume.addEventListener("click", () => startSession([s]));
      return resume;
    });
    if (open) choices.push(joinForm(stored));
    app.replaceChildren(el("section", {}, el("h2", { textContent: "Join game" }), ...choices));
  }

  function joinForm(stored) {
    const name = el("input", { placeholder: "Your name (optional)", maxLength: 40 });
    const join = el("button", { textContent: "Join as new player" });
    join.addEventListener("click", async () => {
      try {
        const seat = await api(`/api/sessions/${sessionId}/join`, { method: "POST", body: { name: name.value } });
        saveEntry(sessionId, { mode: "online", seats: [...stored, seat] });
        startSession([seat]);
      } catch (e) {
        showError(e.message);
      }
    });
    return el("div", {}, name, join);
  }
  ```

**File**: `src/gamer/static/style.css` — **modify**: add `.share input { width: 100%; max-width: 32rem; }`.

#### 4. Tests
**File**: `tests/core/test_sessions.py` — **modify**: add
- `test_join_fills_second_seat`: create online `"Ann"` → `status == "waiting"`, `turn is None`; a move by Ann gives `not_your_turn`; join `"Bob"` → seat `"white"`, `status == "playing"`, version bumped.
- `test_third_join_is_seat_taken`, and `test_join_hotseat_is_seat_taken`.
- `test_list_waiting_shows_only_open_online_sessions`: one online waiting session (listed with `host == "Ann"`), one hot-seat (not listed), one joined (not listed); an unknown game gives `unknown_game`.

**File**: `tests/test_api.py` — **modify**: add
- `test_online_game_over_http`: create online → `GET /api/games/othello/sessions` lists it → `POST join` → no longer listed →
  the white token on Black's turn gives 409 `not_your_turn` → `play_to_end` with both tokens → `finished`.
- `test_join_full_session_409`.

### Verification
#### Automated
- [ ] `uv run pytest tests/core tests/test_api.py -q` passes
- [ ] `uv run pytest -q` passes

#### Manual
- [ ] Browser 1 creates an Online game: the session page shows "Waiting for an opponent" and a share link; reloading resumes without a prompt
- [ ] Browser 2 (a different browser or a private window) sees "Ann's game" in the lobby, or opens the share link, and joins
- [ ] Moves made in one browser appear in the other within about 1 s; clicking during the opponent's turn does nothing (no legal highlights)
- [ ] A third browser opening the link sees "This game is full or no longer exists."
- [ ] In the same browser, opening the link in a new tab offers "Resume as black" plus "Join as new player"

---

## Phase 4: Disconnects, reclaiming seats, cleanup

### Changes

#### 1. Heartbeat, sweep, and time-based connection
**File**: `src/gamer/core/sessions.py` — **modify**

```python
CONNECTED_TIMEOUT = 10.0
WAITING_TTL = 60.0

# SeatState.connected becomes:
    def connected(self, now: float) -> bool:
        return self.last_seen is not None and now - self.last_seen <= CONNECTED_TIMEOUT

# new SessionManager methods:
    def _touch(self, session: Session, seat_index: int, now: float) -> None:
        seats = session.seats if session.mode == "hotseat" else [session.seats[seat_index]]
        reconnected = False
        for seat in seats:
            seat.last_seen = now
            if not seat.was_connected:
                seat.was_connected = True
                reconnected = True
        if reconnected:
            session.version += 1

    def _sweep(self, now: float) -> None:
        for session_id, session in list(self._sessions.items()):
            claimed = [s for s in session.seats if s.token is not None]
            changed = False
            for seat in claimed:
                connected = seat.connected(now)
                if connected != seat.was_connected:
                    seat.was_connected = connected
                    changed = True
            if changed:
                session.version += 1
            if session.status == "waiting" and all(now - s.last_seen > WAITING_TTL for s in claimed):
                del self._sessions[session_id]
            elif session.status == "finished" and not any(s.was_connected for s in claimed):
                del self._sessions[session_id]
```

- In `create`, `join`, `poll`, `move`: call `self._sweep(now)` right after `now = self._clock()`.
- In `list_waiting`: add `self._sweep(self._clock())` as the first line inside the lock.
- In `poll` and `move`: replace the bare `self._seat_index(...)` call with
  `seat = self._seat_index(session, token)` followed by `self._touch(session, seat, now)`, **before**
  the `since` comparison in `poll` and before the status checks in `move`.

#### 2. Client marker
**File**: `src/gamer/static/client.js` — **modify**: in `statusLines`, add `${s.connected ? "" : " disconnected"}` to each seat's
`className` and `${s.connected ? "" : " (disconnected)"}` to its `textContent`.

**File**: `src/gamer/static/style.css` — **modify**: add `.status .disconnected { color: #888; }`.

#### 3. Tests
**File**: `tests/core/test_sessions.py` — **modify**: add a `FakeClock` (`now = 1000.0`, `__call__` returns it,
`advance(seconds)`), and build these tests' managers with `SessionManager(registry, clock=clock)`. Tests:
- `test_silent_seat_becomes_disconnected`: online create (A) + join (B); `advance(5)`; A polls; `advance(6)`; A polls with
  `since=<last version>` → full envelope (version bumped), `seats[1]["connected"] is False`, `seats[0]["connected"] is True`.
- `test_poll_with_token_reclaims_seat`: continuing from above, B polls → `seats[1]["connected"] is True` and the version is bumped again.
- `test_hotseat_poll_keeps_both_seats_connected`: hot-seat create; `advance(5)`; poll with Black's token; `advance(6)`; poll → both connected.
- `test_waiting_session_removed_after_ttl`: online create; `advance(61)`; `list_waiting` is `[]`; poll gives `unknown_session`.
- `test_waiting_session_kept_while_host_polls`: create; `advance(30)`; poll; `advance(40)`; poll succeeds.
- `test_finished_session_removed_when_everyone_gone`: hot-seat `play_to_end`; poll succeeds; `advance(11)`;
  `list_waiting("othello")` (triggers the sweep); poll gives `unknown_session`.

### Verification
#### Automated
- [ ] `uv run pytest tests/core -q` passes
- [ ] `uv run pytest -q` passes (all phases)

#### Manual
- [ ] Online game in two browsers; close browser B: within about 10 s browser A shows B's name greyed with "(disconnected)"
- [ ] Reopen the share link in browser B: the game resumes as B's seat (one stored token, seat not open) and A shows B connected again
- [ ] Create an Online game and close the tab: after about 60 s it disappears from another browser's lobby list
