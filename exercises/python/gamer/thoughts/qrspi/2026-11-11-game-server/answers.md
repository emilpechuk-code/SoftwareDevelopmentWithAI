# Answers

1. **Transport**: HTTP polling. The client asks the server for updates on a
   timer. No WebSockets.
2. **Server framework**: FastAPI on Uvicorn. One process serves the static
   HTML client and the HTTP poll endpoints. Python 3.12, `uv`, and `pytest`.
   Tests cover Othello rules without a server, plus an integration test of
   create, join, move, and game over.
3. **Session joining**: Lobby plus a shareable link. The game page lists
   sessions waiting for a second player and offers Create. Each session has
   a URL the creator can share. No automatic pairing.
4. **Disconnects**: Hold the seat. Each player gets a random token stored in
   `localStorage`. Reconnecting with that token while the server process is
   alive reclaims the seat; the opponent sees that the other player is
   disconnected. A session is removed when the game has ended and both
   players have left, or when a waiting session has no players left.
5. **Client technology**: Plain HTML, CSS, and JavaScript (ES modules), no
   build step, served by the Python server.
6. **Message protocol**: JSON with a generic envelope (`type`, `game`,
   `session_id`) and a game-specific payload. Every state update includes
   the board, whose turn it is, scores, the game-over result, and the list
   of legal moves. No protocol version in v1. Each game is a package
   (`games/othello/`) with pure Python rules and its own static view.
7. **Same-device play**: Hot-seat is in v1. Two players can take turns in
   one browser tab.
