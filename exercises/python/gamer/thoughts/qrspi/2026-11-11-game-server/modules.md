# Modules

Companion to `design.md`. Paths are relative to `exercises/python/gamer/`.

## Module dependencies

Arrows point from importer to imported. The core never imports a concrete game.

```mermaid
flowchart TD
    app["gamer.app<br/>create_app, routes, static mounts"]
    sessions["gamer.core.sessions<br/>Session, SeatState, SessionManager"]
    registry["gamer.core.registry<br/>GameRegistry: get, all"]
    game["gamer.core.game<br/>Game protocol, IllegalMove"]
    games_init["gamer.games<br/>GAMES = [othello.GAME]"]
    othello["gamer.games.othello<br/>GAME = OthelloGame()"]
    rules["gamer.games.othello.rules<br/>OthelloState, OthelloGame"]

    app --> sessions
    app --> registry
    app --> games_init
    sessions --> game
    registry --> game
    games_init --> othello
    othello --> rules
    rules --> game

    sessions -. "FORBIDDEN" .-x othello
    registry -. "FORBIDDEN" .-x othello

    subgraph client["Static client (no build step)"]
        index["static/index.html<br/>game directory"]
        play["static/play.html<br/>lobby or session view"]
        clientjs["static/client.js<br/>polling, envelope, status bar, errors"]
        view["games/othello/static/view.js<br/>render(container, envelope, opts)"]
    end

    play --> clientjs
    clientjs -- "dynamic import by game id" --> view
```

Adding a game means creating a `gamer.games.<new>` package and adding one line
to `gamer.games`. Nothing under `gamer.core` or `gamer.app` changes.

## Core types

```mermaid
classDiagram
    class Game {
        <<Protocol>>
        +id: str
        +name: str
        +seats: tuple~str~
        +static_dir: Optional~Path~
        +initial_state() State
        +current_seat(state) Optional~int~
        +legal_moves(state) list~dict~
        +apply_move(state, seat, move) State
        +result(state) Optional~dict~
        +public_payload(state) dict
    }

    class IllegalMove {
        <<Exception>>
        +message: str
    }

    class OthelloState {
        <<frozen dataclass>>
        +board: tuple
        +to_move: int
        +last_pass: Optional~int~
    }

    class OthelloGame {
        +id = "othello"
        +seats = ("black", "white")
    }

    class SeatState {
        +label: str
        +name: Optional~str~
        +token: Optional~str~
        +last_seen: float
        +was_connected: bool
        +connected(now) bool
    }

    class Session {
        +id: str
        +game: Game
        +mode: online or hotseat
        +status: waiting, playing, finished
        +seats: list~SeatState~
        +state: State
        +version: int
        +envelope(game, now) dict
    }

    class SessionManager {
        -lock: threading.Lock
        -clock: Callable
        -sessions: dict of id to Session
        +create(game_id, mode, name) Session
        +join(session_id, name) SeatState
        +poll(session_id, token, since) dict
        +move(session_id, token, move) dict
        +list_waiting(game_id) list~Session~
        -_touch(session, seat, now) None
        -_sweep(now) None
    }

    Game <|.. OthelloGame : implements
    OthelloGame ..> OthelloState : creates
    OthelloGame ..> IllegalMove : raises
    SessionManager "1" o-- "*" Session
    Session "1" *-- "2" SeatState
    SessionManager ..> Game : uses via registry
```
