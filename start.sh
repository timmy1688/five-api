#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p data/mysql data/redis .pids logs

# 1. MySQL + Redis
echo "==> Starting MySQL & Redis..."
docker compose up -d mysql redis

# 2. Wait for MySQL to be ready
echo "==> Waiting for MySQL to be ready..."
until docker compose exec -T mysql mysqladmin ping -h 127.0.0.1 --silent 2>/dev/null; do
  sleep 1
done
echo "    MySQL is ready."

# 3. Backend (renumbered)
echo "==> Starting backend (port 5002)..."
# Force-free the port in case a stale uvicorn worker is still holding it
fuser -k 5002/tcp 2>/dev/null || true
sleep 0.5
cd backend
nohup uvicorn app.main:app --reload --host 0.0.0.0 --port 5002 > ../logs/backend.log 2>&1 &
echo $! > ../.pids/backend.pid
cd ..

# 4. Frontend
echo "==> Starting frontend (port 5001)..."
fuser -k 5001/tcp 2>/dev/null || true
sleep 0.5
cd frontend
nohup npx vite --port 5001 --host 0.0.0.0 --strictPort > ../logs/frontend.log 2>&1 &
echo $! > ../.pids/frontend.pid
cd ..

sleep 3
echo ""
echo "  Frontend: http://localhost:5001"
echo "  Backend:  http://localhost:5002"
echo "  Logs:     tail -f logs/backend.log"
echo "  Stop:     ./stop.sh"
