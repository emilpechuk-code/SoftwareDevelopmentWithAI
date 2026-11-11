import pytest

from gamer.core.registry import GameRegistry
from gamer.core.sessions import SessionError, SessionManager
from gamer.games.othello.rules import OthelloGame


@pytest.fixture
def manager():
    return SessionManager(GameRegistry([OthelloGame()]))


def tokens_of(created: dict) -> dict[str, str]:
    return {s["seat"]: s["token"] for s in created["seats"]}


def play_to_end(manager, sid, tokens: dict[str, str]) -> dict:
    env = manager.poll(sid, next(iter(tokens.values())), None)
    for _ in range(100):
        if env["status"] == "finished":
            break
        env = manager.move(sid, tokens[env["turn"]], env["payload"]["legal_moves"][0])
    return env


def test_create_hotseat_holds_both_seats(manager):
    created = manager.create("othello", "hotseat", None)
    assert len(created["seats"]) == 2
    env = manager.poll(created["session_id"], created["seats"][0]["token"], None)
    assert env["status"] == "playing"
    assert env["turn"] == "black"
    assert len(env["payload"]["legal_moves"]) == 4
    assert [s["name"] for s in env["seats"]] == ["Black", "White"]

    named = manager.create("othello", "hotseat", "Ann")
    env = manager.poll(named["session_id"], named["seats"][0]["token"], None)
    assert [s["name"] for s in env["seats"]] == ["Ann", "White"]


def test_poll_since_current_version_is_no_change(manager):
    created = manager.create("othello", "hotseat", None)
    token = created["seats"][0]["token"]
    env = manager.poll(created["session_id"], token, None)
    assert manager.poll(created["session_id"], token, env["version"]) == {
        "type": "no_change",
        "version": env["version"],
    }


def test_poll_rejects_unknown_session_and_bad_token(manager):
    created = manager.create("othello", "hotseat", None)
    with pytest.raises(SessionError) as exc:
        manager.poll("nope", created["seats"][0]["token"], None)
    assert exc.value.code == "unknown_session"
    for token in ("wrong", None):
        with pytest.raises(SessionError) as exc:
            manager.poll(created["session_id"], token, None)
        assert exc.value.code == "bad_token"


def test_create_rejects_unknown_game_and_mode(manager):
    with pytest.raises(SessionError) as exc:
        manager.create("chess", "hotseat", None)
    assert exc.value.code == "unknown_game"
    with pytest.raises(SessionError) as exc:
        manager.create("othello", "solo", None)
    assert exc.value.code == "bad_request"


def test_move_out_of_turn_rejected(manager):
    created = manager.create("othello", "hotseat", None)
    with pytest.raises(SessionError) as exc:
        manager.move(created["session_id"], tokens_of(created)["white"], {"row": 2, "col": 3})
    assert exc.value.code == "not_your_turn"


def test_illegal_move_rejected(manager):
    created = manager.create("othello", "hotseat", None)
    sid, black = created["session_id"], tokens_of(created)["black"]
    before = manager.poll(sid, black, None)["version"]
    with pytest.raises(SessionError) as exc:
        manager.move(sid, black, {"row": 0, "col": 0})
    assert exc.value.code == "illegal_move"
    assert manager.poll(sid, black, None)["version"] == before


def test_legal_move_advances_version_and_turn(manager):
    created = manager.create("othello", "hotseat", None)
    sid, black = created["session_id"], tokens_of(created)["black"]
    before = manager.poll(sid, black, None)
    after = manager.move(sid, black, before["payload"]["legal_moves"][0])
    assert after["version"] == before["version"] + 1
    assert after["turn"] == "white"


def test_game_finishes_and_rejects_further_moves(manager):
    created = manager.create("othello", "hotseat", None)
    sid, tokens = created["session_id"], tokens_of(created)
    env = play_to_end(manager, sid, tokens)
    assert env["status"] == "finished"
    assert env["result"] is not None
    with pytest.raises(SessionError) as exc:
        manager.move(sid, tokens["black"], {"row": 0, "col": 0})
    assert exc.value.code == "game_over"
