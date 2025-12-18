#!/usr/bin/env bash
# Helper: start server + two player CLIs in tmux panes, or print manual commands.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEMO_SCRIPT="$ROOT_DIR/scripts/ta_run_demo.sh"

if command -v tmux >/dev/null 2>&1; then
  echo "Using tmux via scripts/ta_run_demo.sh to launch server + two clients"
  bash "$DEMO_SCRIPT"
else
  cat <<'EOF'
No tmux detected. Run these three commands in separate terminals:

cd /home/wy/NP/HW3
python3 server/lobby_server.py

cd /home/wy/NP/HW3
python3 player_client/lobby_client.py

cd /home/wy/NP/HW3
python3 player_client/lobby_client.py
EOF
fi
