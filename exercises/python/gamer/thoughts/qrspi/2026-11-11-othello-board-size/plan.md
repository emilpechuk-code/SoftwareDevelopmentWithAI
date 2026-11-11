# Implementation Plan: Othello 16×16 as a second registered game

Paths are relative to `exercises/python/gamer/`. Prepared by `othello-owner`.

**Decision:** add 16x16 by registering a second game ("Othello 16×16", id `othello-16`),
not by adding per-session options to the `Game` protocol. This keeps the change inside the
Othello package plus one registration line, so `gamer/core`, `app.py` and the client do not
change. The trade-off is that the directory shows two entries with separate lobbies; revisit
generic per-session options if more variants are requested.

## Overview
The game directory lists two games: "Othello" (`othello`, 8x8, unchanged) and "Othello 16×16" (`othello-16`). Both are instances of one size-aware `OthelloGame(size=...)` class and share the same rules code and static view. Adding a game needs only the game module and one registration line (R2), so there are **no changes** to `gamer/core` (`game.py`, `registry.py`, `sessions.py`), `app.py`, or `client.js`.

### How existing code handles a second id (checked)
- **Static mounts:** `app.py:89-91` loops over `registry.all()` and mounts `/games/{game.id}/static` with `name=f"game-{game.id}"`. Two instances therefore get two mounts, `/games/othello/static` and `/games/othello-16/static`, with distinct route names. Both point at the same `static_dir`, and Starlette allows several mounts of one directory.
- **No path overlap:** a Starlette mount only matches its path followed by `/`. So `/games/othello/static` does not match `/games/othello-16/static/view.js`.
- **Directory and play page:** `index.html:15` links to `/play/${g.id}` and shows `g.name`. `app.py:82-86` serves `play.html` for any registered id, so `/play/othello-16` returns 200.
- **Client:** `client.js:1` gets the game id with `location.pathname.split("/")[2]`, which gives `othello-16` for `/play/othello-16`. The hyphen is safe because the split is on `/` only. The id is then used as-is at `client.js:53` (view import) and at lines 98, 113 and 132 (session endpoints).
- **Sessions and registry:** `registry.py:10-12` only rejects duplicate ids. `sessions.py:140` filters waiting sessions by game id, so each lobby lists only its own sessions. `sessions.py:82` calls `game.initial_state()` with no arguments, and that call gets the right size from the instance.
- **Core guard:** the new id and name live only in the Othello package and in `gamer/games/__init__.py`. The `test_pluggable.py:40-43` check that core never mentions "othello" stays green.

### Ownership of changes outside the Othello module
| Owner | File | Change |
|---|---|---|
| contract-owner (a game owner may add exactly one line here) | `src/gamer/games/__init__.py` | Add `othello.GAME_16` to `GAMES` |
| api-owner | `tests/test_directory.py` | Expect both games in `/api/games` |
| api-owner | `tests/test_api.py` | Add a move-limit parameter to `play_to_end`, a 16x16 game played to the end over HTTP, and checks that the `othello-16` page, view and lobby work |
| sessions-owner | — | No change |
| client-owner | — | No change |

The only visible quirk is that the play page heading shows the id (`client.js:160` sets it to `gameId`), so it reads "othello-16" rather than "Othello 16×16". That's cosmetic, and fixing it would change `client.js`, so this plan accepts it (see Risks).

---

## Phase 1: Size-aware Othello rules and view (othello-owner)

After this phase, `OthelloGame(size=16)` works and is fully tested. `OthelloGame()` behaves exactly as it does today. Nothing is registered yet, so the app is unchanged.

### Changes

#### 1. Rules
**File**: `src/gamer/games/othello/rules.py`
**Action**: modify

- Replace `SIZE = 8` (line 6) with `SIZES = (8, 16)`.
- Board helpers take their size from the board (the frozen `OthelloState` is unchanged):

```python
def _on_board(board: Board, row: int, col: int) -> bool:
    return 0 <= row < len(board) and 0 <= col < len(board)


def flips(board: Board, seat: int, row: int, col: int) -> list[tuple[int, int]]:
    ...  # unchanged except: _on_board(board, r, c) in both checks


def moves_for(board: Board, seat: int) -> list[tuple[int, int]]:
    size = len(board)
    return [(r, c) for r in range(size) for c in range(size) if flips(board, seat, r, c)]


def _parse_move(move: Move, board: Board) -> tuple[int, int]:
    ...  # unchanged except: if not _on_board(board, row, col): raise IllegalMove(...)
```

- Each instance sets its own `id`, `name` and size:

```python
class OthelloGame:
    seats = SEATS
    static_dir: Path | None = Path(__file__).parent / "static"

    def __init__(self, size: int = 8) -> None:
        if size not in SIZES:
            raise ValueError(f"size must be one of {SIZES}")
        self.size = size
        self.id = "othello" if size == 8 else f"othello-{size}"
        self.name = "Othello" if size == 8 else f"Othello {size}×{size}"

    def initial_state(self) -> OthelloState:
        n, m = self.size, self.size // 2
        rows: list[list[int | None]] = [[None] * n for _ in range(n)]
        rows[m - 1][m - 1] = rows[m][m] = WHITE
        rows[m - 1][m] = rows[m][m - 1] = BLACK
        return OthelloState(tuple(tuple(r) for r in rows), to_move=BLACK)
```

For 8x8, `m = 4` gives today's squares (3,3), (4,4), (3,4), (4,3). For 16x16, `m = 8` puts White on (7,7) and (8,8) and Black on (7,8) and (8,7).

- In `apply_move`, change the call to `row, col = _parse_move(move, state.board)`.
- `current_seat`, `legal_moves`, `result`, `public_payload` and `_scores` don't change. They already work for any board size, so the payload shape is the same.

#### 2. Package exports
**File**: `src/gamer/games/othello/__init__.py`
**Action**: modify

```python
from gamer.games.othello.rules import OthelloGame

GAME = OthelloGame()
GAME_16 = OthelloGame(size=16)
```

#### 3. View script
**File**: `src/gamer/games/othello/static/view.js`
**Action**: modify. After `grid.className = "othello-board";`, add one line:

```js
grid.style.setProperty("--size", board.length);
```

The view still only renders. Legal cells still come from `payload.legal_moves` and are clickable only when `canMove` is true.

#### 4. View styles
**File**: `src/gamer/games/othello/static/view.css`
**Action**: modify lines 1-2. Cells shrink to fit the window on both axes. 8x8 keeps its 3rem cells on normal screens.

```css
.othello-board { --n: var(--size, 8); --cell: min(3rem, calc((100vw - 4rem - 40px) / var(--n)), calc((100vh - 12rem) / var(--n)));
                 display: grid; grid-template-columns: repeat(var(--n), var(--cell)); gap: 2px; padding: 4px; background: #1b5e20; width: max-content; }
.othello-cell { width: var(--cell); height: var(--cell); padding: 0; border: none; background: #2e7d32; display: grid; place-items: center; }
```

Lines 3-7 stay as they are.

#### 5. Rules tests
**File**: `tests/games/othello/test_rules.py`
**Action**: modify. All existing tests stay unchanged and keep using `GAME = OthelloGame()`, which shows 8x8 behavior hasn't changed. Add:

```python
GAME16 = OthelloGame(size=16)
EMPTY16 = "." * 16
```

- `test_default_instance_identity`: `OthelloGame()` has `id == "othello"`, `name == "Othello"`, `size == 8`, and a board of length 8.
- `test_16_instance_identity`: `id == "othello-16"`, `name == "Othello 16×16"`, and a board of length 16. `GAME16.static_dir == GAME.static_dir`.
- `test_rejects_unsupported_size`: parametrized over `[0, 7, 9, 10, 32]`, each raises `ValueError`.
- `test_package_exports_both_games`: `from gamer.games.othello import GAME, GAME_16`, and their ids are `othello` and `othello-16`.
- `test_initial_position_16`: White on (7,7) and (8,8), Black on (7,8) and (8,7). Black to move, with legal moves exactly `{(6,7), (7,6), (8,9), (9,8)}`. Scores are `{"black": 2, "white": 2}`, `result` is `None`, and the payload board is 16 rows of 16.
- `test_flips_in_each_direction_16`: parametrized over `DIRECTIONS`. Start from a blank 16x16 board with White at (8+dr, 8+dc) and Black at (8+2dr, 8+2dc). Black plays (8,8), and (8+dr, 8+dc) becomes Black.
- `test_flips_full_row_at_edge_16`: Black at (15,0) and White on (15,1) to (15,14). Black plays (15,15), and all 14 discs flip.
- `test_flips_long_diagonal_corner_16`: Black at (0,0) and White on (i,i) for i from 1 to 14. Black plays (15,15), and all 14 flip.
- `test_bounds_16`: `{"row": 15, "col": 15}` on the 16x16 start position raises `IllegalMove` because it flips nothing, not because it's off the board (check the message contains "flip"). `{"row": 16, "col": 0}` and `{"row": 0, "col": -1}` raise `IllegalMove` with "off the board". The existing `{"row": 8, "col": 0}` case keeps checking that 8x8 rejects row 8.
- `test_pass_keeps_turn_16`: row 0 `".WB" + "." * 13`, row 15 `"BW" + "." * 14`, and empty rows between. After Black plays (0,0), `to_move == BLACK` and `last_pass == WHITE`.
- `test_wipeout_ends_game_16`: row 0 `".WB" + "." * 13` and every other row empty. After Black plays (0,0), `current_seat` is `None`, `legal_moves` is empty, and `result` is `{"winner": "black", "draw": False}`.
- `test_first_legal_move_game_ends_16`: play the first legal move for at most 256 turns. Then `result` is not `None` and the score total is at most 256.

### Verification
#### Automated
- [ ] `uv run pytest tests/games/othello` passes with no server running.
- [ ] `uv run pytest` passes in full. Nothing is registered yet, so the API, directory, sessions and pluggable tests are unaffected.

#### Manual
- [ ] Run `uv run uvicorn gamer.app:app`, open `http://localhost:8000/`, then Othello, then create a hot-seat game. The 8x8 board looks the same as before (3rem cells, 8 columns, 4 clickable cells) and plays to a result.

---

## Phase 2: Register Othello 16×16 and update the outside tests

After this phase, the game directory lists both games and every test passes. The registration line and the `test_directory.py` update must land together, because `test_directory` compares the whole response.

### Changes

#### 1. Registration (contract-owner; this is the one line a game owner may add)
**File**: `src/gamer/games/__init__.py`
**Action**: modify

```python
from gamer.games import othello

GAMES = [othello.GAME, othello.GAME_16]
```

#### 2. Directory test (api-owner)
**File**: `tests/test_directory.py`
**Action**: modify the expected response:

```python
assert res.json() == {
    "type": "games",
    "games": [
        {"id": "othello", "name": "Othello", "seats": ["black", "white"]},
        {"id": "othello-16", "name": "Othello 16×16", "seats": ["black", "white"]},
    ],
}
```

#### 3. API tests (api-owner)
**File**: `tests/test_api.py`
**Action**: modify

- `play_to_end` (line 12) gets a move limit: `def play_to_end(client, sid, tokens, max_moves: int = 100)`, with `range(max_moves)` at line 16. Existing callers keep the default. A 16x16 game can take up to 252 moves.
- `create_hotseat` (line 29) gets a game parameter: `def create_hotseat(client, game: str = "othello")`, which posts to `f"/api/games/{game}/sessions"`.
- New `test_hotseat_16_game_over_http`: `sid, tokens = create_hotseat(client, "othello-16")`. The first state has a board of length 16 with legal moves `{(6,7), (7,6), (8,9), (9,8)}`. Then `play_to_end(client, sid, tokens, max_moves=300)` ends with `status == "finished"` and a non-null `result`.
- New `test_lobbies_are_separate_per_game`: an online session on `othello-16` appears in `/api/games/othello-16/sessions` but not in `/api/games/othello/sessions`.
- Extend `test_play_page_and_view_served`: `/play/othello-16`, `/games/othello-16/static/view.js` and `/games/othello-16/static/view.css` all return 200.

#### 4. Files that do not change (checked)
- `src/gamer/core/game.py`, `src/gamer/core/registry.py`, `src/gamer/core/sessions.py`
- `src/gamer/app.py` (the mount loop already handles both ids)
- `src/gamer/static/client.js`, `index.html`, `play.html`, `style.css`
- `tests/core/test_sessions.py`, `tests/test_pluggable.py`

### Verification
#### Automated
- [ ] `uv run pytest` passes in full, including the directory, API, sessions, Othello rules and pluggable tests.
- [ ] `uv run pytest tests/test_pluggable.py::test_core_never_names_a_concrete_game` passes.
- [ ] `git diff --stat` touches only `src/gamer/games/othello/*`, `src/gamer/games/__init__.py`, `tests/games/othello/test_rules.py`, `tests/test_directory.py` and `tests/test_api.py`.

#### Manual
- [ ] Run `uv run uvicorn gamer.app:app`. `http://localhost:8000/` lists "Othello" and "Othello 16×16", linking to `/play/othello` and `/play/othello-16`.
- [ ] `curl http://localhost:8000/games/othello-16/static/view.js` returns the view script.

---

## Phase 3: End-to-end check in the browser

Both games are checked by hand in the browser. There are no code changes in this phase.

### Verification
#### Automated
- [ ] `uv run pytest` passes.

#### Manual
- [ ] In `/play/othello-16`, create a hot-seat game. A 16x16 board shows the 4 center discs and exactly 4 clickable cells, fits a laptop-sized window without scrolling sideways, and plays to a result.
- [ ] Create an online game on `/play/othello-16` in one browser. It appears in the `othello-16` open-games list in a second browser (or a private window), but not in `/play/othello`. After joining, each browser sees the other's moves within about 1 second. A third browser gets `seat_taken`.
- [ ] Closing one browser shows "disconnected" to the other within about 10 seconds. Reopening the share link resumes the seat.
- [ ] `/play/othello` still works end to end with an 8x8 board and 3rem cells, in both hot-seat and online play.

---

## Risks
- **Play page heading shows the id:** `client.js:160` sets the heading to `gameId`, so it reads "othello-16" rather than "Othello 16×16". This is cosmetic and out of scope (it would change `client.js`, owned by client-owner).
- **Exact-match directory test:** the `GAMES` line and the `test_directory.py` update must be in the same change.
- **Move-loop limits:** a 16x16 game over HTTP can take up to 252 moves, more than the current 100 in `play_to_end`. The new test passes `max_moves=300`, and the rules test loops up to 256.
- **Instance attributes instead of class attributes:** `id` and `name` move from class level to the instance. Nothing in `src/` or `tests/` reads `OthelloGame.id` from the class.
- **Same static files, two URLs:** `view.js` and `view.css` are cached twice by the browser. That's harmless, and any later view change affects both games, which is the intent.
- **Doesn't scale to more options:** each new variant means another directory entry and another lobby. Revisit generic per-session options if more variants are requested.
- **Performance:** at 16x16, each legal-move check scans 256 cells in 8 directions, up to 3 times per request. That's acceptable, and a full test game should run in well under a second.
- **Screen fit:** cell size is capped by both window width and height. On very small windows, cells below about 1.5rem may be hard to click.
- **Outdated documents:** `SPEC.md:56` ("Standard 8×8"), the `othello-owner` role definition ("8x8 board", a single `id = "othello"`) and `design.md` still describe one 8x8 game, and no agent owns them.
