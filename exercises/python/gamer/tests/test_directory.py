from fastapi.testclient import TestClient

from gamer.app import create_app


def test_lists_games():
    client = TestClient(create_app())
    res = client.get("/api/games")
    assert res.status_code == 200
    assert res.json() == {
        "type": "games",
        "games": [{"id": "othello", "name": "Othello", "seats": ["black", "white"]}],
    }


def test_index_page_served():
    client = TestClient(create_app())
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
