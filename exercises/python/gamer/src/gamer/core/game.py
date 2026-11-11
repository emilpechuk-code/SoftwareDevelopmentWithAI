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
