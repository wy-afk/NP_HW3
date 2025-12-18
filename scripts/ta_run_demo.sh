#!/usr/bin/env bash
set -euo pipefail
# TA demo runner: uses tmux if available to start lobby + two player shells

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGDIR="$REPO_ROOT/logs"
mkdir -p "$LOGDIR"

if command -v tmux >/dev/null 2>&1; then
  SESSION="ta_demo"
  # ensure no old session
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  tmux new-session -d -s "$SESSION" -c "$REPO_ROOT"
  tmux rename-window -t "$SESSION:0" "lobby"
  tmux send-keys -t "$SESSION:0" "python3 server/lobby_server.py 2>&1 | tee $LOGDIR/lobby.log" C-m

  tmux new-window -t "$SESSION" -n "player1" -c "$REPO_ROOT"
  tmux send-keys -t "$SESSION:1" "python3 player_client/lobby_client.py" C-m

  tmux new-window -t "$SESSION" -n "player2" -c "$REPO_ROOT"
  tmux send-keys -t "$SESSION:2" "python3 player_client/lobby_client.py" C-m

  echo "Started tmux session '$SESSION'. Attach with: tmux attach -t $SESSION"
  echo "Logs: $LOGDIR"
else
  cat <<'MSG'
tmux not found — run the following manually in three terminals:

1) Start the lobby (terminal #1):
   mkdir -p logs
   python3 server/lobby_server.py > logs/lobby.log 2>&1 &

2) Start Player1 (terminal #2):
   python3 player_client/lobby_client.py

3) Start Player2 (terminal #3):
   python3 player_client/lobby_client.py

When ready: register/login two users, create a room, then start the game from the host.
Use the seeded per-player clients in `downloads/Player1` and `downloads/Player2` if you prefer direct client launches.
MSG
fi

exit 0
