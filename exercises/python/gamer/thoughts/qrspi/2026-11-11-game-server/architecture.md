# Architecture

Companion to `design.md`. One Python process serves both the static HTML client
and the JSON API. All session state lives in memory inside that process.

```mermaid
flowchart LR
    subgraph Browsers["Browsers (localhost / LAN)"]
        direction TB
        A["Player A tab<br/>index.html, play.html<br/>client.js + othello view.js"]
        B["Player B tab<br/>(second browser or private window)"]
        H["Hot-seat tab<br/>holds both seat tokens"]
    end

    subgraph Server["uvicorn process: gamer.app"]
        direction TB
        Routes["FastAPI routes<br/>/api/games, /api/sessions"]
        Static["Static mounts<br/>/static, /games/{id}/static"]
        SM["SessionManager<br/>threading.Lock + lazy sweep<br/>clock = time.monotonic"]
        Reg["Game registry<br/>GAMES list"]
        subgraph Games["Game modules (pure rules)"]
            Oth["othello.rules<br/>OthelloGame"]
        end
        Mem[("In-memory sessions<br/>dict id -> Session")]
    end

    A -- "HTTP GET pages and JS" --> Static
    B -- "HTTP GET pages and JS" --> Static
    H -- "HTTP GET pages and JS" --> Static
    A -- "JSON: poll every ~1s, moves<br/>X-Player-Token header" --> Routes
    B -- "JSON: poll every ~1s, moves" --> Routes
    H -- "JSON: poll every ~1s, moves" --> Routes

    Routes --> SM
    Routes --> Reg
    Static -. "mounts each game's static dir" .-> Reg
    SM --> Mem
    SM -- "Game protocol only" --> Reg
    Reg --> Oth
```

## Key properties

| Concern | How it is handled |
| --- | --- |
| Real-time updates | Short polling every ~1 s with `since=<version>`. There is no server push. |
| Source of truth | `SessionManager` validates the token, the turn, and legality (via the game) before applying a move. |
| Isolation of slow clients (R1) | Every request is short and independent. The lock is held only for the in-memory update. |
| Pluggability (R2, R3) | The core sees games only through the `Game` protocol. The registry is the only place a game is named. |
| Disconnects | Each poll acts as a heartbeat. A seat with no poll for more than 10 s shows as disconnected. The seat is held while the process runs. |
| Cleanup | A lazy sweep runs at the start of each API request. There are no background tasks. |
| Persistence | None. Restarting the process clears all sessions. |
