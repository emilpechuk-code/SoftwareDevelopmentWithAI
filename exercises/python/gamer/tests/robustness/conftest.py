import socket
import threading
import time

import pytest
import uvicorn

from gamer.app import create_app


@pytest.fixture
def live_server():
    """A real uvicorn server in a background thread, so requests truly run concurrently."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    server = uvicorn.Server(uvicorn.Config(create_app(), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("live server did not start")
        time.sleep(0.01)
    yield host, port
    server.should_exit = True
    thread.join(timeout=10)
