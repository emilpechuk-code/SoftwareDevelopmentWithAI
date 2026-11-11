# Sequence: Main Flow (Online Othello Game)

Companion to `design.md`. Player A creates an Online session and shares the
link. Player B joins, both players poll, A moves, B sees the move, an
out-of-turn move is rejected, and the game ends.

```mermaid
sequenceDiagram
    autonumber
    actor A as Player A (browser)
    actor B as Player B (browser)
    participant API as FastAPI routes
    participant SM as SessionManager
    participant G as OthelloGame

    Note over A,G: Create session
    A->>API: POST /api/games/othello/sessions {mode: online, name: Ann}
    API->>SM: create("othello", online, "Ann")
    SM->>G: initial_state()
    G-->>SM: state (Black to move)
    SM-->>API: session k3x9, seat black, token tA
    API-->>A: {session_id: k3x9, seats: [black, tA]}
    A->>A: store tA in localStorage, show share link /play/othello?session=k3x9

    loop every ~1s while waiting
        A->>API: GET /api/sessions/k3x9/state?since=v (X-Player-Token: tA)
        API->>SM: poll (sweep first, refresh last_seen)
        SM-->>A: status waiting, or no_change
    end

    Note over B,G: Join via share link
    B->>API: POST /api/sessions/k3x9/join {name: Bob}
    API->>SM: join(k3x9, "Bob")
    SM->>SM: assign white, token tB, status playing, version++
    SM-->>B: {seat: white, token: tB}
    B->>B: store tB in localStorage

    A->>API: GET state?since=v (tA)
    API->>SM: poll
    SM->>G: current_seat, legal_moves, public_payload
    SM-->>A: state envelope (turn black, legal_moves, can move)

    Note over A,G: Accepted move
    A->>API: POST /api/sessions/k3x9/moves {move: row 2, col 3} (tA)
    API->>SM: move(k3x9, tA, move)
    SM->>SM: token tA owns seat black == current_seat
    SM->>G: apply_move(state, black, move)
    G-->>SM: new state (discs flipped, White to move)
    SM->>SM: version++
    SM-->>A: state envelope (turn white)

    B->>API: GET state?since=v (tB)
    API->>SM: poll
    SM-->>B: state envelope with A's move, turn white

    Note over A,G: Rejected out-of-turn move
    A->>API: POST moves {move} (tA)
    API->>SM: move(k3x9, tA, move)
    SM-->>API: seat black != current_seat
    API-->>A: 409 {type: error, code: not_your_turn}

    Note over A,G: Moves continue until neither player can move
    B->>API: POST moves {move} (tB)
    API->>SM: move(k3x9, tB, move)
    SM->>G: apply_move(state, white, move)
    G-->>SM: final state
    SM->>G: result(state)
    G-->>SM: {winner: black, draw: false}
    SM->>SM: status finished, version++
    SM-->>B: state envelope (result: Black wins)
    A->>API: GET state?since=v (tA)
    SM-->>A: state envelope (result: Black wins)

    Note over SM: Later sweep: both seats unseen for 10s, so the finished session is deleted
```

## Variations (not drawn)

- **Illegal move**: same path as the rejected out-of-turn move, but the error
  comes from `G.apply_move` raising `IllegalMove`. The response is 422 with
  `code: illegal_move`.
- **Pass**: inside `apply_move`, if the next seat has no legal move but the
  other seat does, `to_move` stays the same and `last_pass` is set. The
  client shows "White passed".
- **Hot-seat**: step 1 sends `mode: hotseat`. The response contains both
  tokens, there is no join step, and the one tab sends whichever token
  matches `turn`.
- **Disconnect and reclaim**: when B stops polling for more than 10 s, the
  next sweep sets B to disconnected and bumps the version, so A's next poll
  shows it. B reopens the link and polls with the stored `tB`, which
  reclaims the seat.
