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


def test_join_fills_second_seat(manager):
    created = manager.create("othello", "online", "Ann")
    sid, ann = created["session_id"], created["seats"][0]["token"]
    env = manager.poll(sid, ann, None)
    assert env["status"] == "waiting"
    assert env["turn"] is None
    with pytest.raises(SessionError) as exc:
        manager.move(sid, ann, {"row": 2, "col": 3})
    assert exc.value.code == "not_your_turn"
    joined = manager.join(sid, "Bob")
    assert joined["seat"] == "white"
    after = manager.poll(sid, joined["token"], None)
    assert after["status"] == "playing"
    assert after["version"] == env["version"] + 1


def test_third_join_is_seat_taken(manager):
    sid = manager.create("othello", "online", "Ann")["session_id"]
    manager.join(sid, "Bob")
    with pytest.raises(SessionError) as exc:
        manager.join(sid, "Cat")
    assert exc.value.code == "seat_taken"


def test_join_hotseat_is_seat_taken(manager):
    sid = manager.create("othello", "hotseat", None)["session_id"]
    with pytest.raises(SessionError) as exc:
        manager.join(sid, "Bob")
    assert exc.value.code == "seat_taken"


def test_list_waiting_shows_only_open_online_sessions(manager):
    waiting = manager.create("othello", "online", "Ann")["session_id"]
    manager.create("othello", "hotseat", "Hal")
    joined = manager.create("othello", "online", "Jo")["session_id"]
    manager.join(joined, "Bob")
    assert manager.list_waiting("othello") == [{"session_id": waiting, "host": "Ann"}]
    with pytest.raises(SessionError) as exc:
        manager.list_waiting("chess")
    assert exc.value.code == "unknown_game"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def timed(clock):
    return SessionManager(GameRegistry([OthelloGame()]), clock=clock)


def online_pair(timed) -> tuple[str, str, str]:
    created = timed.create("othello", "online", "Ann")
    sid = created["session_id"]
    return sid, created["seats"][0]["token"], timed.join(sid, "Bob")["token"]


def test_silent_seat_becomes_disconnected(timed, clock):
    sid, a, _ = online_pair(timed)
    clock.advance(5)
    version = timed.poll(sid, a, None)["version"]
    clock.advance(6)
    env = timed.poll(sid, a, version)
    assert env["type"] == "state"
    assert env["version"] > version
    assert env["seats"][1]["connected"] is False
    assert env["seats"][0]["connected"] is True


def test_poll_with_token_reclaims_seat(timed, clock):
    sid, a, b = online_pair(timed)
    clock.advance(5)
    timed.poll(sid, a, None)
    clock.advance(6)
    version = timed.poll(sid, a, None)["version"]
    env = timed.poll(sid, b, None)
    assert env["seats"][1]["connected"] is True
    assert env["version"] == version + 1


def test_hotseat_poll_keeps_both_seats_connected(timed, clock):
    created = timed.create("othello", "hotseat", None)
    sid, black = created["session_id"], tokens_of(created)["black"]
    clock.advance(5)
    timed.poll(sid, black, None)
    clock.advance(6)
    env = timed.poll(sid, black, None)
    assert [s["connected"] for s in env["seats"]] == [True, True]


def test_waiting_session_removed_after_ttl(timed, clock):
    created = timed.create("othello", "online", "Ann")
    clock.advance(61)
    assert timed.list_waiting("othello") == []
    with pytest.raises(SessionError) as exc:
        timed.poll(created["session_id"], created["seats"][0]["token"], None)
    assert exc.value.code == "unknown_session"


def test_waiting_session_kept_while_host_polls(timed, clock):
    created = timed.create("othello", "online", "Ann")
    sid, token = created["session_id"], created["seats"][0]["token"]
    clock.advance(30)
    timed.poll(sid, token, None)
    clock.advance(40)
    assert timed.poll(sid, token, None)["status"] == "waiting"


def test_finished_session_removed_when_everyone_gone(timed, clock):
    created = timed.create("othello", "hotseat", None)
    sid, tokens = created["session_id"], tokens_of(created)
    play_to_end(timed, sid, tokens)
    assert timed.poll(sid, tokens["black"], None)["status"] == "finished"
    clock.advance(11)
    timed.list_waiting("othello")
    with pytest.raises(SessionError) as exc:
        timed.poll(sid, tokens["black"], None)
    assert exc.value.code == "unknown_session"
