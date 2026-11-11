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
