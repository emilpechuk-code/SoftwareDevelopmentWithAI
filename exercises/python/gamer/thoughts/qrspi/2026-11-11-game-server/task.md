# Task

Build a local Python game server that hosts turn-based multiplayer games, starting
with Othello. Each game lives in its own logic module behind a common interface,
so later games do not require changes to the server core. Players connect at the
same time from browser-based HTML clients, pick a game, and play in real time.
The server owns game state and rejects illegal or out-of-turn moves. Version 1
runs on the local machine or local network with no accounts or authentication.

Source: `SPEC.md`
