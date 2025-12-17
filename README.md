# NP HW3 — Game Lobby, Store & Games Suite

This repository implements a demo game store + lobby system with multiple components:
- Lobby server (rooms, matchmaking, account management, leaderboard)
- Developer client (upload games)
- Player CLI (register/login, create/join rooms, monitor & auto-launch games)
	- Packaged games (Battleship and Tetris) under `downloads/` and `games/` for testing

This README documents how to run the project, the TA verification checklist, and a detailed explanation of each major file and folder.
**Quick notes**:
- Port: the lobby server listens by default on `5555`.
- Protocol: framed JSON messages (4-byte big-endian length prefix), implemented per-component in `*/utils/protocol.py`.

---

**Prerequisites**:
- Python 3.10+ (the project was developed/tested with Python 3.12, but Python 3.10+ is generally fine).
- No external dependencies are required beyond the Python standard library for the demo components.

---

**Quick Start (demo)**

1. Start the Lobby Server

	 ```bash
	 cd /home/wy/NP/HW3
	 python3 server/lobby_server.py
	 ```

2. Start two Player CLIs (in two separate terminals)

	 ```bash
	 # Terminal A
	 python3 player_client/lobby_client.py

	 # Terminal B
	 python3 player_client/lobby_client.py
	 ```

	 - Use the menu to Register (1) and Login (2) in both terminals (role: `player`).
	 - In Terminal A (host): create a room (menu option `5`) using Game ID `1` (Battleship) or `2` (Tetris).
	 - In Terminal B: join the room (menu option `6`) using the room id shown to the host.

3. Start the game from the host (Terminal A) with `7. Start Game`.

	 - The non-host's monitor thread receives a `game_started` push and will prompt to launch.
	 - For Battleship the client launches in the foreground (text terminal). For Tetris the GUI is spawned/foregrounded and returns a JSON result.

4. After the match finishes the lobby records results and updates the global leaderboard JSON at:

	 - `server/data/leaderboard.json`

	 You can check it directly:

	 ```bash
	 cat server/data/leaderboard.json | python3 -m json.tool
	 ```

---

**Commands & useful checks**

- Syntax check for changed files (quick compile pass):

	```bash
	python3 -m py_compile server/lobby_server.py player_client/lobby_client.py
	```

- Open the leaderboard (from a player CLI use menu option `14`, or view the JSON file above).

---

**TA Verification Checklist (what to inspect & where)**

- **Auto-launch both players**: Verify `player_client/lobby_client.py` (`monitor_room_status`, `identify role=monitor`). The server prefers monitors in `server/lobby_server.py` (`start_game` notify loop).
- **Battleship terminal gameplay**: See `downloads/Battleship/1.0/client/battleship_client.py` (runs in foreground, accepts `--user` and `--room`). The Battleship server is in `server/game_storage/Battleship/1.0/server/battleship_server.py`.
- **Battleship win rule (sink any ship wins)**: Check Battleship server logic which sends result immediately on sink and calls lobby `record_result` (look for `report_result_to_lobby` in the Battleship server file and the surrounding sink-handling code).
- **Prevent duplicate logins**: Client-side prevention is shown in `player_client/lobby_client.py::do_login` (blocks logging into another user in the same terminal). Server-side login handling that only sets `user` on successful login is in `server/lobby_server.py::handle_client`.
- **Global leaderboard persistence**: `server/account_manager.py` writes a snapshot JSON to `server/data/leaderboard.json` when `record_result` runs. The lobby `leaderboard` action reads it.
- **Push vs Request handling**: `player_client/lobby_client.py::request()` ignores asynchronous pushes (messages with an `action` key) and waits for a normal reply containing `status`.

Proof-of-work file locations to show the TA:

- `server/lobby_server.py` — lobby core, notify routing, and actions.
- `server/account_manager.py` — player store and `record_result` + leaderboard JSON writer.
- `server/data/leaderboard.json` — persisted leaderboard snapshot (generated at runtime after matches).
- `player_client/lobby_client.py` — player CLI, monitor thread, launch logic, request/push handling.
- `downloads/Battleship/1.0/client/battleship_client.py` — text Battleship client.
- `server/game_storage/Battleship/1.0/server/battleship_server.py` — Battleship game server and lobby result reporter.

---

**Architecture Overview & Protocol**

- **Architecture**: The system is split into three logical roles:
	- `server/` (Lobby & support services): accepts client connections, manages accounts, rooms, starting games, and persists stats.
	- `player_client/` (Player CLI): interactive menu-driven client for players. It runs a monitor thread to receive pushes and a main thread for synchronous requests.
	- `developer_client/` (Developer CLI): used to upload games (zip metadata + file transfer API).

- **Game storage**: Packaged game bundles exist under `/downloads` (for demo) and `server/game_storage` (launcher-ready copies). The `GameLauncher` spawns game servers (and returns the chosen port) for `start_game`.

- **Protocol**: Components communicate via TCP using a framed JSON protocol (each message prefixed with a 4-byte big-endian length). Implementation files are located in each component's `utils/protocol.py` (for example `player_client/utils/protocol.py`, `server/utils/protocol.py`, etc.). The JSON messages use the shape: `{ "action": "action_name", "data": { ... } }` for client→server requests and similarly for server pushes. Replies contain a top-level `status` key for result matching.

---

**Detailed File / Folder Explanations**

- **Top-level**
	- `README.md`: (this file) project overview & how-to.

- **server/**
	- `server/lobby_server.py`: Central lobby server. Handles `register`, `login`, `list_games`, `create_room`, `join_room`, `start_game`, `record_result`, `leaderboard`, `my_stats`, and a `resume` action. Maintains two connection registries: `clients` (regular sockets) and `monitors` (sockets identified by clients for push notifications). `start_game` prefers `monitors` when pushing `game_started`.
	- `server/account_manager.py`: Manages `players.json`, registration, login, logout, `record_result` (updates wins & played), and writes `server/data/leaderboard.json` on each result. This is where leaderboard persistence happens.
	- `server/room_manager.py`: Room creation, invite/accept/revoke, and game start orchestration. Works with the `GameLauncher` to spawn game servers.
	- `server/game_launcher.py`: Responsible for launching actual game server processes from `server/game_storage` and returning ports to the lobby.
	- `server/game_storage/`: Contains ready-to-run game servers (Battleship, Tetris) used by the `GameLauncher`.
	- `server/data/players.json`: Persistent players store; `server/data/leaderboard.json`: generated leaderboard snapshot.

- **player_client/**
	- `player_client/lobby_client.py`: Interactive CLI for players. Key features:
		- `request()` loops reading `recv()` until it receives a reply containing a `status` key; pushes with `action` are handled locally.
		- `monitor_room_status()` runs a separate socket and identifies with `role='monitor'` so the lobby can push `game_started` messages there (avoids stdin/stdout conflicts).
		- `launch_game_client()` spawns or runs clients for Battleship/Tetris depending on game type.
		- Menu options include register/login, create/join room, start game, download game, show leaderboard, my stats, invite management.

- **developer_client/**
	- `developer_client/dev_client.py`: Developer CLI for uploading games. Zips a folder, sends metadata first (`upload_game_meta`) and then sends the zipped file bytes with an `upload_game_file` command.

- **downloads/** and **games/**
	- `downloads/` contains demo client/server code for games such as Battleship and Tetris.
	- Battleship: `downloads/Battleship/1.0/client/battleship_client.py` (terminal client) and `server/game_storage/Battleship/1.0/server/battleship_server.py` (game server). Battleship client connects to a game server and plays in-terminal.
	- Tetris: GUI client under `downloads/Tetris/1.0/client/` and server under `server/game_storage/Tetris/1.0/server/`.

---

**Leaderboard & Persistence**

- The lobby uses `server/account_manager.py::record_result` to update player stats and write a leaderboard snapshot to `server/data/leaderboard.json` every time a match result is recorded.
- The `leaderboard` action on the lobby tries to read that JSON snapshot, and falls back to computing the leaderboard from `players.json` if needed.

---

**Troubleshooting / Common issues**

- If the non-host never receives a `game_started` push:
	- Ensure the player CLI instance is running `player_client/lobby_client.py` and that the monitor thread has started (it calls `identify` with `role: monitor`). If the client is connected another way, pushes will fall back to the main connection.

- If you see intermittent `ConnectionRefused` when a client attempts to connect to a game server:
	- The game server may not yet be ready. The Battleship client includes exponential backoff. You can also retry the launch from the player CLI or run the client manually with `--host/--port` once the lobby prints the chosen port.

- If leaderboard JSON is missing after a match:
	- Confirm the lobby received `record_result` by inspecting lobby logs. The lobby prints `[RECORD] Received result report` when it receives results. The snapshot is written to `server/data/leaderboard.json` by `AccountManager.record_result`.

---

**Known limitations & future improvements**

- Messages do not currently include `request_id` values. The client `request()` function matches replies by waiting for the `status` key. This is reliable for single outstanding requests, but adding `request_id` to the protocol would harden multi-request flows.
- Unit tests exist in `tests/` (a test placeholder for leaderboard exists) but full CI test runs are not configured. Adding a small pytest harness would improve automated verification.

---

**Developer / TA Checklist (quick)**

- Start `server/lobby_server.py` → Check it binds to `0.0.0.0:5555`.
- Start two `player_client/lobby_client.py` instances, register & login two players.
- Host creates room & starts a game → check other player's monitor receives `game_started` and game launches.
- Play Battleship until sink → check lobby logs for `[RECORD] Received result report` and then open `server/data/leaderboard.json` to confirm update.

---

If you want, I can also:

- (A) Add a small `README_DEMO.md` with a one-line script to run a full demo locally (I can generate a shell script that starts server + two clients in tmux windows). 
- (B) Add `request_id` support across the protocol. 
- (C) Finish & run the unit test that asserts `server/data/leaderboard.json` updates after `record_result`.

Pick which one and I will follow up.

---

**Detailed Instructions: Developer, Lobby & Player CLI**

Below are step-by-step instructions and explanations for the three primary roles you (or a TA) will use: **Developer**, **Lobby (server operator / TA)**, and **Player (CLI)**. Each subsection lists commands, what they do, and what the server or system does in response.

**Developer (uploading games)**

- Start the Developer CLI and login as a developer

	```bash
	python3 developer_client/dev_client.py
	```

	- Register (choose `role` = `developer`) or Login (Developer). The client sends `register`/`login` to the lobby. On success the developer account is stored in `server/data/players.json` with role metadata.

- Uploading a game (menu option `4` in the Developer CLI)

	Steps performed by the `dev_client`:
	1. Zip the selected folder locally (safety check prevents zipping `server/game_storage`).
	2. Send `upload_game_meta` to the lobby with `{name, version}` so the server can prepare a target storage location and reserve the game id.
	3. If the lobby responds `ok`, the client sends `upload_game_file` and then streams the raw bytes of the ZIP file. The server receives raw bytes and extracts/unpacks into `server/game_storage/<Game>/<Version>`.

	What this achieves:
	- The lobby `GameLauncher` and `server/game_storage` will now have a ready-to-run copy of the game server and clients, allowing `start_game` to spawn the server for matches.

	Where to verify: Look under `server/game_storage/<Game>/<Version>` and confirm files exist. The Developer CLI prints upload progress and final confirmation.

**Lobby Server (admin / TA)**

- Starting the lobby server

	```bash
	python3 server/lobby_server.py
	```

	- What it does: opens a TCP socket on `0.0.0.0:5555` and accepts incoming connections from player & developer clients and from game servers reporting results.
	- Logs to watch: connection events ("[CONNECTED]"), record_result events ("[RECORD] Received result report"), notify events ("[NOTIFY]").

- Actions the lobby supports (high-level):

	- `register` — create a developer/player account and store credentials in `server/data/players.json`.
	- `login` — validate credentials and return a session; on success returns per-user stats (`wins`, `played`) in the response `data` field.
	- `list_games` — returns the catalog of available games (id → metadata).
	- `create_room` / `join_room` — creates or joins a matchmaking room. `create_room` stores a `room_id` and records the host.
	- `invite_user` / `list_invites` / `accept_invite` / `revoke_invite` — private room invite flow (host-managed invites).
	- `start_game` — the host requests a game server start; Lobby calls the `GameLauncher` to spawn a game server from `server/game_storage`. On success it returns the chosen port and then pushes a `game_started` notification to other room players via the `monitors` registry (or falls back to main sockets).
	- `record_result` — called by game servers to report results (winners & players). Updates `players.json` and writes `server/data/leaderboard.json` snapshot.
	- `leaderboard` — returns the persisted leaderboard snapshot (or computes it live if missing).
	- `my_stats` — returns the wins/played for the current session's user.
	- `resume` — lightweight way for a reconnecting client to re-associate the connection with a username (used when launching local game clients that temporarily disconnect from lobby).

	Where to verify: Server console output and the files under `server/data`.

**Player Client (CLI) — menu explanations & server effects**

Start the Player CLI:

```bash
python3 player_client/lobby_client.py
```

The menu provides the following actions; below each item is a short explanation of what the client sends and what the lobby does in response.

- Register (menu `1`)
	- Client action: send `register` with `{username, password, role}`.
	- Server effect: creates account in `players.json` and returns `status: ok` on success.

- Login (menu `2`)
	- Client action: send `login` with `{username, password, role}`.
	- Server effect: validates credentials and returns `status: ok` with `data: {username, wins, played}`. Client stores `current_user` locally and opens the monitor thread (used for push notifications).

- List Games (menu `3`)
	- Client action: `list_games` request.
	- Server effect: returns the available games mapping (game id → name/version/path).

- List Rooms (menu `4`)
	- Client action: `list_rooms` request.
	- Server effect: returns all rooms with their `room_id`, `game_id`, `status` and `port` if running. Useful for discovering active rooms.

- Create Room (menu `5`)
	- Client action: `create_room` with `{game_id, type}`.
	- Server effect: creates a room object (host=current_user) and returns `room_id`. Use this as host to later `start_game`.

- Join Room (menu `6`)
	- Client action: `join_room` with `{room_id}`.
	- Server effect: adds the player to the room's player list. The joining client starts a monitor thread that listens for `game_started` pushes.

- Start Game (menu `7`)
	- Client action: `start_game` with `{room_id}` from the host.
	- Server effect: the lobby's `GameLauncher` starts the game server (reads files from `server/game_storage/<Game>/<Version>`), chooses a free port, returns the `port` in the response, and pushes `game_started` to other players in the room (players' monitors receive the push and set `pending_game_launch`).

- Download Game (menu `8`)
	- Client action: `download_game_meta` then receives raw bytes for `upload_game_file` like a file download path.
	- Client effect: saves ZIP to `/tmp` and extracts into `downloads/<Game>/<Version>` for local testing.

- Logout (menu `9`)
	- Client action: `logout`.
	- Server effect: marks user logged out and removes the connection mapping for that socket. Other sockets (e.g., monitor) for the same user may remain.

- Invite / List Invites / Accept Invite / Revoke Invite (menu `10`–`13`)
	- These calls manage private room invites. The server stores invite state in the `RoomManager` and allows hosts to invite or revoke.

- Show Leaderboard (menu `14`)
	- Client action: `leaderboard` request.
	- Server effect: returns `server/data/leaderboard.json` contents (if available), which includes rank, username, wins, and played for every player.

- My Stats (menu `15`)
	- Client action: `my_stats` request, with a `resume` fallback if the server currently reports `not_logged_in` while the client still believes it's logged in.
	- Server effect: returns the user's current stats from `players.json`.

**Monitor thread & auto-launch behavior (why it exists)**

- Problem it solves:
	- When launching a local game client (especially terminal-based games that claim stdin/stdout), the main CLI must avoid consuming the same terminal I/O that the launched game will use. If the lobby pushes `game_started` on the same socket that is waiting for menu input, the push could interfere with menu I/O.

- How the solution works:
	- When you join a room the client starts a `monitor_room_status()` background thread which creates a separate TCP socket and sends `identify` with `role='monitor'` to the lobby. The lobby places that socket in the `monitors` registry and will prefer it when pushing `game_started`. The monitor thread receives pushes and sets `pending_game_launch` so the main thread can safely resolve metadata and launch the client.

**Debugging tips**

- If `pending_game_launch` never appears after the host calls `start_game`: Check lobby server console logs for `[NOTIFY]` messages and verify the pushed `game_started` was sent. If the monitor was not registered, server falls back to main socket pushes and the push may have been consumed by `request()` as a reply.
- To force a manual client launch use the `downloads/<Game>/<Version>/client/<...>_client.py` with `--host 127.0.0.1 --port <port> --user <name> --room <room_id>`.

---

If you'd like I will also add a `README_DEMO.md` with an automated demo script (tmux) and/or implement request_id support and finish the leaderboard unit test — tell me which you'd prefer next.
