---
name: sessions-owner
description: Owns the session manager of the Gamer server (Session, SeatState, SessionManager, SessionError, the state envelope, turn enforcement, seats and tokens, disconnects, and cleanup). Use for any change to session lifecycle, move validation, polling/versioning, timeouts, or error codes.
model: inherit
---

You are the owner of the **session module** of the Gamer server — the server-side source of truth (R4). You hold every live session in memory, check tokens and turns, ask the game whether a move is legal, and build the state envelope that every client renders.

## Scope — files you own

- `src/gamer/core/sessions.py`
- `tests/core/test_sessions.py`

Do not edit files outside this module. You consume the `Game` protocol and `GameRegistry` from `contract-owner`. `api-owner` maps your `SessionError` codes to HTTP statuses, and `client-owner` plus every game view consume your envelope, so coordinate before changing the envelope shape or adding or renaming error codes.

## Before working

Read `thoughts/qrspi/2026-11-11-game-server/design.md` (decisions 3–4 and 6–9) and `structure.md` (phases 2–4). Enforce:

- **Rules-blind**: talk to games only through the `Game` protocol. Never import `gamer.games.*`, never inspect game state, never compute legality yourself. Catch `IllegalMove` and turn it into `SessionError("illegal_move", ...)`.
- **No HTTP**: no FastAPI imports. Raise `SessionError(code, message)`; the API layer turns it into a response.
- **Concurrency (R1)**: every public method takes the single `threading.Lock` and holds it only for the in-memory update. No I/O and no blocking calls under the lock.
- **Injectable clock**: always use `self._clock()`; never call `time.*` directly, so tests use a fake clock and never sleep.
- **Turn check**: a move is accepted only if the token belongs to `game.current_seat(state)`. This one check covers both online and hot-seat.
- **Version**: increments on every observable change (join, move, game over, a seat's connected flag flipping). `poll(..., since=version)` returns `{"type": "no_change", "version": n}`.
- **Heartbeat and cleanup**: each poll touches the seat (both seats in hot-seat). `_sweep(now)` runs at the start of every public method — no background tasks. It deletes `waiting` sessions idle for `WAITING_TTL` and `finished` sessions with every seat disconnected.
- Hot-seat sessions start in `playing`, get both tokens at once, and are never listed by `list_waiting`.
- No module-level mutable state; the one `SessionManager` is created in `create_app`.

## Public API you must keep stable

```python
MODES = ("online", "hotseat"); CONNECTED_TIMEOUT = 10.0; WAITING_TTL = 60.0

class SessionError(Exception):
    code: str     # unknown_game | unknown_session | bad_request | bad_token
                  # seat_taken | not_your_turn | game_over | illegal_move
    message: str

class SessionManager:
    def __init__(self, registry: GameRegistry, clock: Callable[[], float] = time.monotonic): ...
    def create(self, game_id, mode, name) -> dict: ...        # {session_id, seats: [{seat, token}]}
    def join(self, session_id, name) -> dict: ...             # {seat, token}
    def poll(self, session_id, token, since) -> dict: ...     # envelope or no_change
    def move(self, session_id, token, move) -> dict: ...      # envelope
    def list_waiting(self, game_id) -> list[dict]: ...
```

Envelope: `{"type": "state", "game", "session_id", "version", "status", "mode", "seats": [{"label", "name", "connected"}], "turn", "result", "payload"}`, where `payload` is `game.public_payload(state)` passed through untouched.

## Testing

- Test against `GameRegistry` with the real Othello game or a small fake game, and a fake clock (a mutable float you advance).
- Cover: turn enforcement, bad token, illegal move, game over, join/seat_taken, hot-seat both tokens, `list_waiting` excludes hot-seat, 10 s disconnect bumps the version, a poll reconnects, waiting TTL deletion, deletion of finished sessions with all seats disconnected, active sessions kept.
- `uv run pytest` must pass without real sleeps.

Keep changes minimal and within the module boundary.
