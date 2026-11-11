import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from gamer.app import create_app
from mock_client import MockPlayer, stalled_connection


def http_client(server) -> httpx.Client:
    host, port = server
    return httpx.Client(base_url=f"http://{host}:{port}", timeout=5)


def start_online_game(server, seed: int, poll_delay: float = 0.0) -> tuple[MockPlayer, MockPlayer]:
    host = MockPlayer(http_client(server), name=f"Host{seed}", seed=seed, poll_delay=poll_delay)
    guest = MockPlayer(http_client(server), name=f"Guest{seed}", seed=seed + 1000, poll_delay=poll_delay)
    guest.join(host.create())
    return host, guest


def assert_consistent_finish(*envs: dict) -> None:
    first = envs[0]
    assert first["status"] == "finished" and first["result"] is not None
    for env in envs[1:]:
        assert env["version"] == first["version"]
        assert env["payload"] == first["payload"]
        assert env["result"] == first["result"]
    scores = first["payload"]["scores"]
    discs = sum(cell is not None for row in first["payload"]["board"] for cell in row)
    assert scores["black"] + scores["white"] == discs <= 64


# --- Concurrency on a real server --------------------------------------------------------


def test_many_parallel_online_games(live_server):
    games = [start_online_game(live_server, seed) for seed in range(8)]
    players = [p for game in games for p in game]
    with ThreadPoolExecutor(max_workers=len(players)) as pool:
        finals = list(pool.map(lambda p: p.play(timeout=60), players))
    for i in range(0, len(finals), 2):
        assert_consistent_finish(finals[i], finals[i + 1])
    for p in players:
        assert p.rejected == []
        assert p.versions == sorted(p.versions)
    assert len({p.session_id for p in players}) == len(games)


def test_stalled_and_slow_clients_do_not_block_others(live_server):
    stalled = [stalled_connection(*live_server) for _ in range(20)]
    slow_host, slow_guest = start_online_game(live_server, seed=99, poll_delay=0.5)
    stop = threading.Event()
    slow_threads = [threading.Thread(target=p.play, kwargs={"timeout": 120, "stop": stop})
                    for p in (slow_host, slow_guest)]
    for t in slow_threads:
        t.start()
    try:
        fast = MockPlayer(http_client(live_server), seed=7)
        fast.create(mode="hotseat")
        worst = 0.0
        started = time.monotonic()
        while fast.poll()["status"] != "finished":
            t0 = time.monotonic()
            assert fast.move(fast.choose_move()).status_code == 200
            worst = max(worst, time.monotonic() - t0)
        assert time.monotonic() - started < 10
        assert worst < 1.0
        assert slow_host.latest["status"] == "playing"
    finally:
        stop.set()
        for t in slow_threads:
            t.join(timeout=5)
        for sock in stalled:
            sock.close()


def test_racing_duplicate_moves_apply_once(live_server):
    player = MockPlayer(http_client(live_server))
    player.create(mode="hotseat")
    before = player.poll()
    move = before["payload"]["legal_moves"][0]
    barrier = threading.Barrier(10)
    clients = [http_client(live_server) for _ in range(10)]

    def send(client):
        barrier.wait()
        return client.post(f"/api/sessions/{player.session_id}/moves", json={"move": move},
                           headers=player.headers(player.tokens["black"]))

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(send, clients))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200] + [409] * 9
    assert {r.json()["code"] for r in results if r.status_code == 409} == {"not_your_turn"}
    after = player.poll()
    assert after["version"] == before["version"] + 1
    assert after["turn"] == "white"
    assert sum(c is not None for row in after["payload"]["board"] for c in row) == 5


def test_racing_joins_fill_exactly_one_seat(live_server):
    host = MockPlayer(http_client(live_server), name="Host")
    sid = host.create()
    barrier = threading.Barrier(10)

    def join(i):
        guest = MockPlayer(http_client(live_server), name=f"G{i}")
        barrier.wait()
        return guest.join(sid)

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(join, range(10)))
    assert sorted(r.status_code for r in results) == [200] + [409] * 9
    assert host.poll()["status"] == "playing"
    assert [s["label"] for s in host.latest["seats"]] == ["black", "white"]


# --- Hostile and malformed input (in-process, deterministic) -----------------------------


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def hotseat(client):
    player = MockPlayer(client)
    player.create(mode="hotseat")
    player.poll()
    return player


@pytest.mark.parametrize("move", [
    {}, {"row": 2}, {"col": 3}, {"row": None, "col": None}, {"row": "2", "col": "3"},
    {"row": 2.0, "col": 3.0}, {"row": True, "col": 3}, {"row": [2], "col": 3},
    {"row": -1, "col": 0}, {"row": 8, "col": 8}, {"row": 10**20, "col": 0}, {"row": 0, "col": 0},
])
def test_malformed_move_objects_are_illegal_and_change_nothing(hotseat, move):
    version = hotseat.latest["version"]
    res = hotseat.move(move)
    assert res.status_code == 422
    assert res.json()["code"] == "illegal_move"
    assert hotseat.poll()["version"] == version


@pytest.mark.parametrize("move", [[2, 3], "d3", None, 42])
def test_non_object_moves_are_rejected_by_validation(hotseat, move):
    version = hotseat.latest["version"]
    assert hotseat.move(move).status_code == 422
    assert hotseat.poll()["version"] == version


def test_malformed_requests_never_500(client, hotseat):
    sid, black = hotseat.session_id, hotseat.tokens["black"]
    other = MockPlayer(client)
    other.create(mode="hotseat")
    cases = [
        (client.post(f"/api/sessions/{sid}/moves", content=b"{not json",
                     headers={"Content-Type": "application/json", "X-Player-Token": black}), 422),
        (client.post(f"/api/sessions/{sid}/moves", json={}, headers={"X-Player-Token": black}), 422),
        (client.get(f"/api/sessions/{sid}/state?since=abc", headers={"X-Player-Token": black}), 422),
        (client.get(f"/api/sessions/{sid}/state?since=-1", headers={"X-Player-Token": black}), 200),
        (client.get(f"/api/sessions/{sid}/state?since={10**30}", headers={"X-Player-Token": black}), 200),
        (client.get(f"/api/sessions/{sid}/state"), 403),
        (client.get(f"/api/sessions/{sid}/state", headers={"X-Player-Token": ""}), 403),
        (client.get(f"/api/sessions/{sid}/state", headers={"X-Player-Token": "x" * 10_000}), 403),
        (client.get(f"/api/sessions/{sid}/state", headers={"X-Player-Token": other.tokens["black"]}), 403),
        (client.get("/api/sessions/../../etc/passwd/state", headers={"X-Player-Token": black}), 404),
        (client.post("/api/games/othello/sessions", json={"mode": "spectator"}), 400),
        (client.post("/api/games/othello/sessions", json={"mode": 1}), 422),
        (client.post("/api/games/nope/sessions", json={"mode": "online"}), 404),
        (client.post(f"/api/sessions/{sid}/join", json={}), 409),
        (client.get(f"/api/sessions/{sid}/moves"), 405),
        (client.get("/games/othello/static/../rules.py"), 404),
    ]
    for res, expected in cases:
        assert res.status_code == expected, (res.request.method, str(res.request.url)[:80], res.text[:200])


@pytest.mark.parametrize("name, shown", [
    ("x" * 10_000, "x" * 40),
    ("   ", "Black"),
    ("<script>alert(1)</script>", "<script>alert(1)</script>"),
    ("Zoë 🎲", "Zoë 🎲"),
])
def test_odd_display_names_are_stored_safely(client, name, shown):
    player = MockPlayer(client, name=name)
    player.create(mode="hotseat")
    assert player.poll()["seats"][0]["name"] == shown


# --- Disconnects and cleanup through the HTTP API (fake clock) ----------------------------


def test_disconnect_reconnect_and_cleanup_over_http():
    now = [0.0]
    client = TestClient(create_app(clock=lambda: now[0]))
    ann, bob = MockPlayer(client, name="Ann"), MockPlayer(client, name="Bob")
    bob.join(ann.create())
    ann.poll()
    now[0] = 11.0
    seen = ann.poll()
    assert [s["connected"] for s in seen["seats"]] == [True, False]
    bob.poll()
    assert [s["connected"] for s in ann.poll()["seats"]] == [True, True]
    assert ann.latest["version"] > seen["version"]

    stale = MockPlayer(client, name="Gone")
    sid = stale.create()
    now[0] += 61.0
    res = client.get(f"/api/sessions/{sid}/state", headers=stale.headers())
    assert res.status_code == 404
    assert ann.poll()["status"] == "playing"


# --- Soak: many random games, checking invariants after every move ------------------------


@pytest.mark.parametrize("seed", range(20))
def test_random_games_keep_invariants(client, seed):
    player = MockPlayer(client, seed=seed)
    player.create(mode="hotseat")
    env = player.poll()
    discs = 4
    while env["status"] == "playing":
        assert env["payload"]["legal_moves"], "a playing game must offer a legal move"
        mover = env["turn"]
        res = player.move(player.choose_move())
        assert res.status_code == 200
        env = res.json()
        board = env["payload"]["board"]
        discs += 1
        assert sum(c is not None for row in board for c in row) == discs
        assert sum(env["payload"]["scores"].values()) == discs
        if env["status"] == "playing" and env["turn"] == mover:
            assert env["payload"]["last_pass"] not in (None, mover)
    scores = env["payload"]["scores"]
    if scores["black"] == scores["white"]:
        assert env["result"] == {"winner": None, "draw": True}
    else:
        assert env["result"] == {"winner": max(scores, key=scores.get), "draw": False}
    assert player.move({"row": 0, "col": 0}, token=player.tokens["black"]).json()["code"] == "game_over"
