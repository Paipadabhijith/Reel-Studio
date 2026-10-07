#!/bin/zsh
# Double-click to start Reel Studio and open it in your browser. Close this window to stop it.
cd "$(dirname "$0")"
if curl -s -o /dev/null http://127.0.0.1:7788/; then
  echo "Reel Studio is already running."
  open http://127.0.0.1:7788/
  exit 0
fi
exec ./.venv/bin/reel studio
