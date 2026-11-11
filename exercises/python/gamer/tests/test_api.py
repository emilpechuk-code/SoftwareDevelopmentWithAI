import pytest
from fastapi.testclient import TestClient

from gamer.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def play_to_end(client, sid, tokens: dict[str, str]) -> dict:
    res = client.get(f"/api/sessions/{sid}/state", headers={"X-Player-Token": next(iter(tokens.values()))})
    assert res.status_code == 200
    env = res.json()
    for _ in range(100):
        if env["status"] == "finished":
            break
        res = client.post(
            f"/api/sessions/{sid}/moves",
            json={"move": env["payload"]["legal_moves"][0]},
            headers={"X-Player-Token": tokens[env["turn"]]},
        )
        assert res.status_code == 200
        env = res.json()
    return env


def create_hotseat(client) -> tuple[str, dict[str, str]]:
    created = client.post("/api/games/othello/sessions", json={"mode": "hotseat"}).json()
    return created["session_id"], {s["seat"]: s["token"] for s in created["seats"]}


def test_hotseat_game_over_http(client):
    sid, tokens = create_hotseat(client)
    env = play_to_end(client, sid, tokens)
    assert env["status"] == "finished"
    assert env["result"] is not None


def test_error_status_codes(client):
    sid, tokens = create_hotseat(client)
    responses = [
        (client.get("/api/sessions/nope/state", headers={"X-Player-Token": tokens["black"]}), 404, "unknown_session"),
        (client.get(f"/api/sessions/{sid}/state", headers={"X-Player-Token": "wrong"}), 403, "bad_token"),
        (
            client.post(f"/api/sessions/{sid}/moves", json={"move": {"row": 2, "col": 3}},
                        headers={"X-Player-Token": tokens["white"]}),
            409,
            "not_your_turn",
        ),
        (
            client.post(f"/api/sessions/{sid}/moves", json={"move": {"row": 0, "col": 0}},
                        headers={"X-Player-Token": tokens["black"]}),
            422,
            "illegal_move",
        ),
    ]
    for res, status, code in responses:
        assert res.status_code == status
        assert res.json()["type"] == "error"
        assert res.json()["code"] == code


def test_online_game_over_http(client):
    created = client.post("/api/games/othello/sessions", json={"mode": "online", "name": "Ann"}).json()
    sid = created["session_id"]
    tokens = {s["seat"]: s["token"] for s in created["seats"]}
    listed = client.get("/api/games/othello/sessions").json()["sessions"]
    assert {"session_id": sid, "host": "Ann"} in listed
    res = client.post(f"/api/sessions/{sid}/join", json={"name": "Bob"})
    assert res.status_code == 200
    tokens[res.json()["seat"]] = res.json()["token"]
    listed = client.get("/api/games/othello/sessions").json()["sessions"]
    assert all(s["session_id"] != sid for s in listed)
    res = client.post(f"/api/sessions/{sid}/moves", json={"move": {"row": 2, "col": 3}},
                      headers={"X-Player-Token": tokens["white"]})
    assert res.status_code == 409
    assert res.json()["code"] == "not_your_turn"
    env = play_to_end(client, sid, tokens)
    assert env["status"] == "finished"


def test_join_full_session_409(client):
    sid = client.post("/api/games/othello/sessions", json={"mode": "online"}).json()["session_id"]
    assert client.post(f"/api/sessions/{sid}/join", json={}).status_code == 200
    res = client.post(f"/api/sessions/{sid}/join", json={})
    assert res.status_code == 409
    assert res.json()["code"] == "seat_taken"


def test_play_page_and_view_served(client):
    assert client.get("/play/othello").status_code == 200
    assert client.get("/play/nope").status_code == 404
    assert client.get("/games/othello/static/view.js").status_code == 200
