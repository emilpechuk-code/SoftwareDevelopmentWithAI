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
