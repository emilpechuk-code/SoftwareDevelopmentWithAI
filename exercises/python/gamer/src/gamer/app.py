from collections.abc import Iterable
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gamer.core.game import Game
from gamer.core.registry import GameRegistry
from gamer.games import GAMES

STATIC_DIR = Path(__file__).parent / "static"


def create_app(games: Iterable[Game] | None = None) -> FastAPI:
    registry = GameRegistry(GAMES if games is None else games)
    app = FastAPI(title="Gamer")

    @app.get("/api/games")
    def list_games():
        return {
            "type": "games",
            "games": [{"id": g.id, "name": g.name, "seats": list(g.seats)} for g in registry.all()],
        }

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
