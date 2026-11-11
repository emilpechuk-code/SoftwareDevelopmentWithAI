"""A scriptable stand-in for the browser client, used to stress the server."""

import random
import socket
import threading
import time

import httpx

TOKEN_HEADER = "X-Player-Token"


class ProtocolViolation(AssertionError):
    """The server answered in a way a correct client could not handle."""


class MockPlayer:
    """Speaks the same protocol as `static/client.js`.

    It polls with `since=<version>`, ignores `no_change`, applies only newer versions,
    and moves only on its own turn with a move taken from the server's `legal_moves`.
    `http` is anything with httpx's request API: a FastAPI `TestClient` or an
    `httpx.Client(base_url=...)` pointed at a live server.
    """

    def __init__(self, http, name: str | None = None, seed: int = 0, poll_delay: float = 0.0) -> None:
        self.http = http
        self.name = name
        self.rng = random.Random(seed)
        self.poll_delay = poll_delay
        self.session_id: str | None = None
        self.tokens: dict[str, str] = {}
        self.latest: dict | None = None
        self.versions: list[int] = []
        self.rejected: list[httpx.Response] = []

    def create(self, game: str = "othello", mode: str = "online") -> str:
        res = self.http.post(f"/api/games/{game}/sessions", json={"mode": mode, "name": self.name})
        res.raise_for_status()
        body = res.json()
        self.session_id = body["session_id"]
        self.tokens = {s["seat"]: s["token"] for s in body["seats"]}
        return self.session_id

    def join(self, session_id: str) -> httpx.Response:
        res = self.http.post(f"/api/sessions/{session_id}/join", json={"name": self.name})
        if res.status_code == 200:
            self.session_id = session_id
            self.tokens[res.json()["seat"]] = res.json()["token"]
        return res

    def headers(self, token: str | None = None) -> dict[str, str]:
        token = token or next(iter(self.tokens.values()), None)
        return {TOKEN_HEADER: token} if token else {}

    def poll(self) -> dict | None:
        since = f"?since={self.latest['version']}" if self.latest else ""
        res = self.http.get(f"/api/sessions/{self.session_id}/state{since}", headers=self.headers())
        res.raise_for_status()
        body = res.json()
        if body["type"] == "state":
            self._accept(body)
        elif body["type"] != "no_change" or body["version"] != self.latest["version"]:
            raise ProtocolViolation(f"unexpected poll reply {body}")
        return self.latest

    def my_turn(self) -> bool:
        env = self.latest
        return env is not None and env["status"] == "playing" and env["turn"] in self.tokens

    def choose_move(self) -> dict:
        return self.rng.choice(self.latest["payload"]["legal_moves"])

    def move(self, move, token: str | None = None) -> httpx.Response:
        token = token or self.tokens[self.latest["turn"]]
        res = self.http.post(f"/api/sessions/{self.session_id}/moves", json={"move": move},
                             headers=self.headers(token))
        if res.status_code == 200:
            self._accept(res.json())
        return res

    def play(self, timeout: float = 30.0, stop: threading.Event | None = None) -> dict | None:
        """Poll and move until the game is finished (or `stop` is set); return the last envelope."""
        deadline = time.monotonic() + timeout
        while True:
            if stop is not None and stop.is_set():
                return self.latest
            env = self.poll()
            if env is not None and env["status"] == "finished":
                return env
            if self.my_turn():
                res = self.move(self.choose_move())
                if res.status_code != 200:
                    self.rejected.append(res)
            else:
                time.sleep(self.poll_delay or 0.002)
            if time.monotonic() > deadline:
                raise TimeoutError(f"{self.name} did not finish {self.session_id}; last={self.latest}")

    def _accept(self, env: dict) -> None:
        if self.latest is not None and env["version"] < self.latest["version"]:
            raise ProtocolViolation(f"version went backwards: {self.latest['version']} -> {env['version']}")
        self.latest = env
        self.versions.append(env["version"])


def stalled_connection(host: str, port: int) -> socket.socket:
    """Open a connection that sends half a request and then never finishes it."""
    sock = socket.create_connection((host, port), timeout=5)
    sock.sendall(b"POST /api/games/othello/sessions HTTP/1.1\r\nHost: x\r\n"
                 b"Content-Type: application/json\r\nContent-Length: 1000\r\n\r\n{\"mode\":")
    return sock
