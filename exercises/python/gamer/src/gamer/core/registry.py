from collections.abc import Iterable

from gamer.core.game import Game


class GameRegistry:
    def __init__(self, games: Iterable[Game]) -> None:
        self._games: dict[str, Game] = {}
        for game in games:
            if game.id in self._games:
                raise ValueError(f"duplicate game id: {game.id}")
            self._games[game.id] = game

    def get(self, game_id: str) -> Game | None:
        return self._games.get(game_id)

    def all(self) -> list[Game]:
        return list(self._games.values())
