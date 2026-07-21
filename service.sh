#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PID_DIR=".pids"
LOG_DIR="logs"
BACKEND_PORT=5002
FRONTEND_PORT=5001
SERVICES=(backend frontend)

start() {
    mkdir -p data/mysql data/redis "$PID_DIR" "$LOG_DIR"

    # 1. MySQL + Redis
    echo "==> Starting MySQL & Redis..."
    docker compose up -d mysql redis

    # 2. Wait for MySQL to be ready
    echo "==> Waiting for MySQL to be ready..."
    until docker compose exec -T mysql mysqladmin ping -h 127.0.0.1 --silent 2>/dev/null; do
        sleep 1
    done
    echo "    MySQL is ready."

    # 3. Backend
    echo "==> Starting backend (port ${BACKEND_PORT})..."
    # Force-free the port in case a stale uvicorn worker is still holding it
    fuser -k "${BACKEND_PORT}/tcp" 2>/dev/null || true
    sleep 0.5
    cd backend
    nohup uvicorn app.main:app --reload --host 0.0.0.0 --port "${BACKEND_PORT}" > "../${LOG_DIR}/backend.log" 2>&1 &
    echo $! > "../${PID_DIR}/backend.pid"
    cd ..

    # 4. Frontend
    echo "==> Starting frontend (port ${FRONTEND_PORT})..."
    fuser -k "${FRONTEND_PORT}/tcp" 2>/dev/null || true
    sleep 0.5
    cd frontend
    nohup npx vite --port "${FRONTEND_PORT}" --host 0.0.0.0 --strictPort > "../${LOG_DIR}/frontend.log" 2>&1 &
    echo $! > "../${PID_DIR}/frontend.pid"
    cd ..

    sleep 3
    echo ""
    echo "  Frontend: http://localhost:${FRONTEND_PORT}"
    echo "  Backend:  http://localhost:${BACKEND_PORT}"
    echo "  Logs:     ./service.sh logs"
    echo "  Stop:     ./service.sh stop"
}

stop() {
    # Stop backend & frontend
    for svc in "${SERVICES[@]}"; do
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

    # Stop MySQL & Redis (use `stop` not `down`: older compose rejects service args to `down`)
    echo "==> Stopping MySQL & Redis..."
    docker compose stop mysql redis

    echo "==> Done."
}

restart() {
    stop
    echo ""
    start
}

status() {
    for svc in "${SERVICES[@]}"; do
        pid_file="$PID_DIR/$svc.pid"
        if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
            echo "  $svc: running (pid $(cat "$pid_file"))"
        else
            echo "  $svc: stopped"
        fi
    done
    echo "==> Docker services:"
    docker compose ps mysql redis
}

logs() {
    local target="${1:-}"
    case "$target" in
        backend)  tail -f "${LOG_DIR}/backend.log" ;;
        frontend) tail -f "${LOG_DIR}/frontend.log" ;;
        *)        tail -f "${LOG_DIR}/backend.log" "${LOG_DIR}/frontend.log" ;;
    esac
}

usage() {
    cat <<EOF
Usage: ./service.sh {start|stop|restart|status|logs [backend|frontend]}

  start     启动 MySQL/Redis + 后端(:${BACKEND_PORT}) + 前端(:${FRONTEND_PORT})
  stop      停止后端/前端并关闭 MySQL/Redis
  restart   先 stop 再 start
  status    查看各进程与 docker 服务状态
  logs      跟踪日志（默认后端+前端，可指定 backend / frontend）
EOF
}

cmd="${1:-}"
case "$cmd" in
    start)   start ;;
    stop)    stop ;;
    restart) restart ;;
    status)  status ;;
    logs)    shift || true; logs "${1:-}" ;;
    *)       usage; exit 1 ;;
esac
