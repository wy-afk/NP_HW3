# NP HW3 — TA Step-by-Step Run Guide

This repo implements a lobby server, a player CLI, a developer CLI, and two packaged games (Battleship + Tetris).

The goal of this README is: a TA can follow it end-to-end without needing the author to guide them.

## 0) Prerequisites

- OS: Linux
- Python: 3.10+ (tested with 3.12)
- No third-party packages required.

All commands below assume you are in the repo root:

```bash
cd /home/wy/NP/HW3
```

## 1) Repo Layout (what matters)

- `server/` — lobby server + storage
	- `server/lobby_server.py` (main server)
	- `server/game_launcher.py` (starts game servers from `server/game_storage/...`)
	- `server/game_storage/<Game>/<Version>/` (runtime-installed game packages)
	- `server/data/` (persistent JSON db)
- `player_client/` — Player CLI (`player_client/lobby_client.py`)
	- installs to `player_client/downloads/<username>/<Game>/<Version>/`
- `developer_client/` — Developer CLI (`developer_client/dev_client.py`)
	- local packages live in `developer_client/games/<Game>/<Version>/`

## 2) Start the Lobby Server

In terminal #1:

```bash
cd /home/wy/NP/HW3
python3 server/lobby_server.py
```

Expected:

```
[LOBBY SERVER] Listening on 0.0.0.0:5555
```

If it says “Address already in use”, kill the old server:

```bash
ss -ltnp | grep ':5555'
kill <PID>
```

## 3) Player CLI (menus)

Run a player client in terminal #2 (and more terminals for more players):

```bash
cd /home/wy/NP/HW3
python3 player_client/lobby_client.py
```

### 3.1 Welcome menu (install/delete is ONLY here)

You should see:

```
=== Welcome ===
1. Register
2. Login
3. Leaderboard
4. Download / Install game
5. Delete installed game
0. Exit
```

Notes:
- “Download / Install game” downloads a published game ZIP from the server and extracts it into:
	- `player_client/downloads/<username>/<Game>/<Version>/`

### 3.2 After login (authenticated home)

After you login, you should see:

```
=== Hello, <username> ===
1. Create room
2. Join room
3. Invite user to your private room
4. Accept invite
5. List invites
6. Logout
0. Back
```

Important behavior:
- When a player logs in, the client starts a second “monitor” socket.
- When a host starts a game, the server pushes a `game_started` event to other players.
- The monitor auto-downloads the game client (if missing) and auto-launches it.

## 4) Developer CLI (upload/update/remove)

Optional for demo (games may already exist in the server catalog), but required if grading includes the upload flow.

In terminal #3:

```bash
cd /home/wy/NP/HW3
python3 developer_client/dev_client.py
```

Key behaviors:
- “List Games” shows LOCAL packages from `developer_client/games/`.
- “Upload Game Folder” and “Update Game Folder” use a numbered picker (choose 1/2…).
- “Remove Game” is done by server game ID.

## 5) End-to-end demo: Battleship multiplayer (3 players)

This section demonstrates:
- room join works with >2 for Battleship
- server launches game server correctly from `server/game_storage/...`
- non-host players auto-launch from the `game_started` push

### 5.1 Start three player clients

Open 3 terminals:

Terminal A:
```bash
python3 player_client/lobby_client.py
```

Terminal B:
```bash
python3 player_client/lobby_client.py
```

Terminal C:
```bash
python3 player_client/lobby_client.py
```

### 5.2 Register/Login three users

In each terminal:
- Welcome → `1` Register (pick usernames like `u1`, `u2`, `u3`)
- Welcome → `2` Login

### 5.3 (Recommended) Install Battleship for each user once

In each terminal, from Welcome:
- `4` Download / Install game
- enter the Battleship game ID (usually 1)

This installs to:

`player_client/downloads/<username>/Battleship/1.0/`

### 5.4 Create room + join (Battleship)

Terminal A (host):
- Authenticated home → `1` Create room
- `Game ID: 1` (Battleship)
- room type `public`

Terminal B and C:
- Authenticated home → `2` Join room
- enter the room id created by host

### 5.5 Start game

Terminal A (host):
- Once inside Room Actions menu → `1` Start room game (as host)

Expected on terminals B and C:
- A monitor push prints something like:

```
[Monitor] game_started push: {'room_id': <id>, 'port': <port>, 'game_id': 1, 'game_name': 'Battleship', 'game_version': '1.0'}
[Monitor] game ready; switching to game...
```

Then the Battleship client starts and connects.

### 5.6 Battleship multiplayer rules (as implemented)

- 2+ players are supported (default cap: 8).
- Turn order is a ring: P1 attacks P2, P2 attacks P3, ... last attacks P1.
- Win condition: the first player to fully sink any single ship wins.

## 6) End-to-end demo: Tetris (2 players)

Follow the same steps as above but choose Tetris game ID.

## 7) What to check for grading (artifacts)

- `server/data/players.json` — accounts + wins/played
- `server/data/games.json` — published games catalog
- `server/game_storage/<Game>/<Version>/` — extracted runtime game package
- `player_client/downloads/<username>/<Game>/<Version>/` — player installs

## 8) Troubleshooting (common)

### 8.1 Server port 5555 already in use

```bash
ss -ltnp | grep ':5555'
kill <PID>
python3 server/lobby_server.py
```

### 8.2 Game fails to start with “can't open file .../server/battleship_server.py”

Fixed in this repo by launching game servers with `cwd` set to the game runtime directory.
If you see this, ensure you are running the latest code and restarted the lobby server.

### 8.3 Player joined room but didn’t auto-launch

Checklist:
- Player must have logged in (login starts the monitor socket).
- The lobby server should log `[NOTIFY] Sent game_started ...`.
- The player terminal should show `[Monitor] game_started push: ...`.

### 8.4 Reset state (optional)

If you want a fresh state (accounts/games/rooms), stop the server and remove server JSONs:

```bash
rm -f server/data/players.json server/data/games.json server/data/reviews.json
```

Then restart the server.
