#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PID_DIR=".pids"

# Stop backend & frontend
for svc in backend frontend; do
    pid_file="$PID_DIR/$svc.pid"
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo "==> Stopping $svc (pid $pid)..."
            # Kill the entire process group so uvicorn worker children also die
            pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
            if [ -n "$pgid" ] && [ "$pgid" != "0" ]; then
                kill -- "-$pgid" 2>/dev/null || kill "$pid" 2>/dev/null || true
            else
                kill "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$pid_file"
    fi
done

# Stop MySQL & Redis
echo "==> Stopping MySQL & Redis..."
docker compose down mysql redis

echo "==> Done."
