# Game Package Specification (game.json)

This document defines the minimal `game.json` manifest that every uploaded game package must include at the package root. The lobby server validates this file on upload and uses it to launch game servers and advise clients how to start clients.

Required top-level fields

- `name` (string): canonical game name, e.g. "Battleship".
- `version` (string): semantic version or simple version string, e.g. "1.0".
- `server` (object): server start specification.

server.start_cmd

- `start_cmd` (array|string): the command to run the game server. It must include placeholders for `{host}` and `{port}` which the `GameLauncher` will substitute. It may include `{room_id}` if your server needs it.

Examples:
- list form: `["python3", "server/battleship_server.py", "--host", "{host}", "--port", "{port}", "--room-id", "{room_id}"]`
- string form: `"python3 server/tetris_server.py --host {host} --port {port} --room-id {room_id}"`

Optional fields (recommended)

- `players` (object): `{ "min": 2, "max": 4 }` — number of players supported.
- `ui` (string): `"cli"` or `"gui"`.
- `description` (string): short description of the game.
- `author` (string): developer or organization name.
- `clients` (object): hints for client launches, example:

```
"clients": {
  "cli": { "launch_cmd": ["python3", "client/battleship_client.py", "--host", "{host}", "--port", "{port}", "--user", "{username}", "--room", "{room_id}"] },
  "gui": { "launch_cmd": ["python3", "client/tetris_gui.py", "--host", "{host}", "--port", "{port}"] }
}
```

- `metadata` (object): arbitrary marketplace metadata such as rating, tags.

Result reporting

Game servers must report results to the lobby by connecting to the lobby and sending `record_result` with payload `{ "winners": ["player1"], "players": ["player1","player2"] }`.

Security & packaging

- The uploaded package must be a zip containing the package root with `game.json` and `server/` and `client/` directories (if applicable).
- The lobby validates `game.json` presence and basic fields. The server performs path traversal checks on zip extraction.

Example `game.json`

```json
{
  "name": "ExampleGame",
  "version": "1.0",
  "players": {"min": 2, "max": 2},
  "ui": "cli",
  "server": {
    "start_cmd": ["python3", "server/example_server.py", "--host", "{host}", "--port", "{port}", "--room-id", "{room_id}"]
  },
  "clients": {
    "cli": {"launch_cmd": ["python3", "client/example_client.py", "--host", "{host}", "--port", "{port}", "--user", "{username}", "--room", "{room_id}"]}
  }
}
```

Follow this spec when packaging games for upload so the lobby can manage, start, and distribute them reliably.
