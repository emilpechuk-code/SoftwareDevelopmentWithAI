import pytest

from gamer.core.game import IllegalMove
from gamer.games.othello.rules import BLACK, DIRECTIONS, WHITE, OthelloGame, OthelloState

GAME = OthelloGame()
EMPTY = "........"


def board_from(rows: list[str]):
    cells = {".": None, "B": BLACK, "W": WHITE}
    return tuple(tuple(cells[ch] for ch in row) for row in rows)


def test_initial_position():
    state = GAME.initial_state()
    board = state.board
    assert board[3][3] == board[4][4] == WHITE
    assert board[3][4] == board[4][3] == BLACK
    assert GAME.current_seat(state) == BLACK
    assert {(m["row"], m["col"]) for m in GAME.legal_moves(state)} == {(2, 3), (3, 2), (4, 5), (5, 4)}
    assert GAME.public_payload(state)["scores"] == {"black": 2, "white": 2}
    assert GAME.result(state) is None


@pytest.mark.parametrize("dr,dc", DIRECTIONS)
def test_flips_in_each_direction(dr, dc):
    rows = [[None] * 8 for _ in range(8)]
    rows[4 + dr][4 + dc] = WHITE
    rows[4 + 2 * dr][4 + 2 * dc] = BLACK
    state = OthelloState(tuple(tuple(r) for r in rows), to_move=BLACK)
    after = GAME.apply_move(state, BLACK, {"row": 4, "col": 4})
    assert after.board[4 + dr][4 + dc] == BLACK


def test_flips_multiple_lines():
    state = OthelloState(board_from(["BWW.WWB.", *[EMPTY] * 7]), to_move=BLACK)
    after = GAME.apply_move(state, BLACK, {"row": 0, "col": 3})
    for col in (1, 2, 4, 5):
        assert after.board[0][col] == BLACK
    assert GAME.public_payload(after)["scores"]["black"] == 7


@pytest.mark.parametrize(
    "move",
    [
        {"row": 0, "col": 0},
        {"row": 3, "col": 3},
        {"row": 8, "col": 0},
        {"row": "2", "col": 3},
        {},
    ],
)
def test_rejects_illegal_moves(move):
    with pytest.raises(IllegalMove):
        GAME.apply_move(GAME.initial_state(), BLACK, move)


def test_rejects_wrong_seat():
    with pytest.raises(IllegalMove):
        GAME.apply_move(GAME.initial_state(), WHITE, {"row": 2, "col": 3})


def test_pass_keeps_turn():
    state = OthelloState(board_from([".WB.....", *[EMPTY] * 6, "BW......"]), to_move=BLACK)
    after = GAME.apply_move(state, BLACK, {"row": 0, "col": 0})
    assert after.to_move == BLACK
    assert after.last_pass == WHITE
    assert GAME.public_payload(after)["last_pass"] == "white"


def test_wipeout_ends_game():
    state = OthelloState(board_from([".WB.....", *[EMPTY] * 7]), to_move=BLACK)
    after = GAME.apply_move(state, BLACK, {"row": 0, "col": 0})
    assert GAME.current_seat(after) is None
    assert GAME.legal_moves(after) == []
    assert GAME.result(after) == {"winner": "black", "draw": False}
    with pytest.raises(IllegalMove):
        GAME.apply_move(after, BLACK, {"row": 0, "col": 3})


def test_equal_discs_is_draw():
    state = OthelloState(board_from(["BW......", "WB......", *[EMPTY] * 6]), to_move=None)
    assert GAME.result(state) == {"winner": None, "draw": True}


def test_first_legal_move_game_ends():
    state = GAME.initial_state()
    for _ in range(64):
        seat = GAME.current_seat(state)
        if seat is None:
            break
        state = GAME.apply_move(state, seat, GAME.legal_moves(state)[0])
    assert GAME.result(state) is not None
    assert sum(GAME.public_payload(state)["scores"].values()) <= 64
