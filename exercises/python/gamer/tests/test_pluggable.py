from pathlib import Path

from fastapi.testclient import TestClient

from gamer.app import create_app
from gamer.core.game import IllegalMove


class CountToThree:
    id = "count"
    name = "Count to three"
    seats = ("a", "b")
    static_dir = None

    def initial_state(self): return 0
    def current_seat(self, state): return None if state >= 3 else state % 2
    def legal_moves(self, state): return [] if state >= 3 else [{"step": 1}]
    def result(self, state): return {"winner": "a", "draw": False} if state >= 3 else None
    def public_payload(self, state): return {"count": state, "legal_moves": self.legal_moves(state)}

    def apply_move(self, state, seat, move):
        if move != {"step": 1}:
            raise IllegalMove("Only {'step': 1} is allowed")
        return state + 1


def test_new_game_plugs_in_without_core_changes():
    client = TestClient(create_app(games=[CountToThree()]))
    assert [g["id"] for g in client.get("/api/games").json()["games"]] == ["count"]
    created = client.post("/api/games/count/sessions", json={"mode": "hotseat"}).json()
    tokens = {s["seat"]: s["token"] for s in created["seats"]}
    for seat in ["a", "b", "a"]:
        res = client.post(f"/api/sessions/{created['session_id']}/moves",
                          json={"move": {"step": 1}}, headers={"X-Player-Token": tokens[seat]})
        assert res.status_code == 200
    assert res.json()["status"] == "finished"
    assert res.json()["result"] == {"winner": "a", "draw": False}


def test_core_never_names_a_concrete_game():
    core = Path(__file__).parents[1] / "src" / "gamer" / "core"
    for path in core.glob("*.py"):
        assert "othello" not in path.read_text(encoding="utf-8").lower(), path
