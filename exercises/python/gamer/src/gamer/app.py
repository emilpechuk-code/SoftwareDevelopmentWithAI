import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gamer.core.game import Game
from gamer.core.registry import GameRegistry
from gamer.core.sessions import SessionError, SessionManager
from gamer.games import GAMES

STATIC_DIR = Path(__file__).parent / "static"

ERROR_STATUS = {
    "bad_request": 400, "bad_token": 403, "unknown_game": 404, "unknown_session": 404,
    "seat_taken": 409, "not_your_turn": 409, "game_over": 409, "illegal_move": 422,
}
Token = Annotated[str | None, Header(alias="X-Player-Token")]


class CreateSession(BaseModel):
    mode: str = "online"
    name: str | None = None


class MoveRequest(BaseModel):
    move: dict


class JoinSession(BaseModel):
    name: str | None = None


def create_app(games: Iterable[Game] | None = None, clock: Callable[[], float] = time.monotonic) -> FastAPI:
    registry = GameRegistry(GAMES if games is None else games)
    app = FastAPI(title="Gamer")
    manager = SessionManager(registry, clock=clock)
    app.state.manager = manager

    @app.exception_handler(SessionError)
    async def session_error(request: Request, exc: SessionError):
        return JSONResponse(
            status_code=ERROR_STATUS[exc.code],
            content={"type": "error", "code": exc.code, "message": exc.message},
        )

    @app.get("/api/games")
    def list_games():
        return {
            "type": "games",
            "games": [{"id": g.id, "name": g.name, "seats": list(g.seats)} for g in registry.all()],
        }

    @app.get("/api/games/{game_id}/sessions")
    def waiting_sessions(game_id: str):
        return {"type": "sessions", "sessions": manager.list_waiting(game_id)}

    @app.post("/api/games/{game_id}/sessions")
    def create_session(game_id: str, body: CreateSession):
        return manager.create(game_id, body.mode, body.name)

    @app.post("/api/sessions/{session_id}/join")
    def join_session(session_id: str, body: JoinSession):
        return manager.join(session_id, body.name)

    @app.get("/api/sessions/{session_id}/state")
    def session_state(session_id: str, x_player_token: Token = None, since: int | None = None):
        return manager.poll(session_id, x_player_token, since)

    @app.post("/api/sessions/{session_id}/moves")
    def make_move(session_id: str, body: MoveRequest, x_player_token: Token = None):
        return manager.move(session_id, x_player_token, body.move)

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/play/{game_id}")
    def play(game_id: str):
        if registry.get(game_id) is None:
            raise SessionError("unknown_game", f"Unknown game: {game_id}")
        return FileResponse(STATIC_DIR / "play.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    for game in registry.all():
        if game.static_dir is not None:
            app.mount(f"/games/{game.id}/static", StaticFiles(directory=game.static_dir), name=f"game-{game.id}")
    return app


app = create_app()
