#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PID_DIR=".pids"
LOG_DIR="logs"
BACKEND_PORT=5002
FRONTEND_PORT=5001
SERVICES=(backend frontend)

install_deps() {
    command -v python3 >/dev/null 2>&1 || {
        echo "ERROR: 未找到 python3（需要 Python 3.12+）" >&2
        exit 1
    }
    command -v npm >/dev/null 2>&1 || {
        echo "ERROR: 未找到 npm（需要 Node.js 20+）" >&2
        exit 1
    }

    if [ ! -x .venv/bin/python ]; then
        echo "==> Creating Python virtual environment..."
        python3 -m venv .venv
    fi

    echo "==> Installing backend dependencies..."
    (
        cd backend
        ../.venv/bin/python -m pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt
    )

    echo "==> Installing frontend dependencies..."
    npm --prefix frontend ci --registry=https://registry.npmmirror.com --no-audit

    echo "==> Dependencies installed."
}

check_deps() {
    if [ ! -x .venv/bin/uvicorn ] || [ ! -x frontend/node_modules/.bin/vite ]; then
        echo "ERROR: 项目依赖尚未安装，请先运行：./service.sh install" >&2
        exit 1
    fi
}

stop_apps() {
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

}

secret_from_file() {
    # Reuse data/secrets.json so local runs and the container decrypt the same data.
    [ -f data/secrets.json ] || return 0
    sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" data/secrets.json 2>/dev/null | head -n 1
}

random_secret() {
    head -c 48 /dev/urandom | base64 | tr -d '\n/+='
}

ensure_secrets() {
    touch .env
    chmod 600 .env
    if grep -q '^SECRET_KEY=.' .env && grep -q '^ENCRYPTION_KEY=.' .env; then
        return
    fi
    if grep -q '^\(SECRET_KEY\|ENCRYPTION_KEY\)=' .env; then
        echo "ERROR: .env 中的 SECRET_KEY/ENCRYPTION_KEY 不完整。请从备份恢复，不要重新生成已用于加密的密钥" >&2
        exit 1
    fi
    local jwt enc
    jwt=$(secret_from_file jwt_secret)
    enc=$(secret_from_file encryption_key)
    if [ -z "$jwt" ] || [ -z "$enc" ]; then
        if [ -f data/secrets.json ]; then
            echo "ERROR: data/secrets.json 无法读取，请修复后重试" >&2
            exit 1
        fi
        jwt=$(random_secret)
        enc=$(random_secret)
    fi
    printf '\n# Gateway secrets. Back up separately from the database; never regenerate.\nSECRET_KEY=%s\nENCRYPTION_KEY=%s\n' "$jwt" "$enc" >> .env
    echo "==> 网关密钥已写入 .env，请与数据库分开备份"
}

start() {
    check_deps
    ensure_secrets
    stop_apps
    export NO_PROXY="${NO_PROXY:-${no_proxy:-}},127.0.0.1,localhost,::1"
    export no_proxy="$NO_PROXY"
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
    echo "==> Applying database migrations..."
    ../.venv/bin/aerich upgrade
    nohup setsid ../.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port "${BACKEND_PORT}" < /dev/null > "../${LOG_DIR}/backend.log" 2>&1 &
    echo $! > "../${PID_DIR}/backend.pid"
    cd ..

    # 4. Frontend
    echo "==> Starting frontend (port ${FRONTEND_PORT})..."
    fuser -k "${FRONTEND_PORT}/tcp" 2>/dev/null || true
    sleep 0.5
    cd frontend
    nohup setsid ./node_modules/.bin/vite --port "${FRONTEND_PORT}" --host 0.0.0.0 --strictPort < /dev/null > "../${LOG_DIR}/frontend.log" 2>&1 &
    echo $! > "../${PID_DIR}/frontend.pid"
    cd ..

    sleep 3
    if ! curl -fsS --noproxy '*' --max-time 2 "http://127.0.0.1:${BACKEND_PORT}/docs" >/dev/null ||
       ! curl -fsS --noproxy '*' --max-time 2 "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null; then
        echo "ERROR: 服务启动后未通过访问检查，请查看 ./service.sh logs" >&2
        exit 1
    fi
    echo ""
    echo "  Frontend: http://localhost:${FRONTEND_PORT}"
    echo "  Backend:  http://localhost:${BACKEND_PORT}"
    echo "  Logs:     ./service.sh logs"
    echo "  Stop:     ./service.sh stop"
}

stop() {
    stop_apps

    # Stop MySQL & Redis (use `stop` not `down`: older compose rejects service args to `down`)
    echo "==> Stopping MySQL & Redis..."
    docker compose stop mysql redis

    echo "==> Done."
}

deploy() {
    ensure_secrets
    mkdir -p data/mysql data/redis
    echo "==> Building and starting gateway, MySQL & Redis..."
    docker compose up -d --build
    echo "==> Gateway: http://127.0.0.1:8080 (first login: admin / admin123)"
}

restart() {
    stop
    echo ""
    start
}

status() {
    local ports=("$BACKEND_PORT" "$FRONTEND_PORT")
    local paths=("/docs" "")
    local index=0
    for svc in "${SERVICES[@]}"; do
        pid_file="$PID_DIR/$svc.pid"
        if [ -f "$pid_file" ] &&
           kill -0 "$(cat "$pid_file")" 2>/dev/null &&
           curl -fsS --noproxy '*' --max-time 2 "http://127.0.0.1:${ports[$index]}${paths[$index]}" >/dev/null; then
            echo "  $svc: running (pid $(cat "$pid_file"))"
        else
            echo "  $svc: stopped"
        fi
        index=$((index + 1))
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
Usage: ./service.sh {deploy|install|secrets|start|stop|restart|status|logs [backend|frontend]}

  deploy    生产部署：生成 .env 密钥（已有则不变），构建并启动网关容器、MySQL、Redis
  install   创建 .venv 并安装后端、前端依赖
  secrets   在 .env 写入网关密钥（已有 data/secrets.json 时沿用），已存在则不变
  start     启动 MySQL/Redis + 后端(:${BACKEND_PORT}) + 前端(:${FRONTEND_PORT})
  stop      停止后端/前端并关闭 MySQL/Redis
  restart   先 stop 再 start
  status    查看各进程与 docker 服务状态
  logs      跟踪日志（默认后端+前端，可指定 backend / frontend）
EOF
}

cmd="${1:-}"
case "$cmd" in
    deploy)  deploy ;;
    install) install_deps ;;
    secrets) ensure_secrets ;;
    start)   start ;;
    stop)    stop ;;
    restart) restart ;;
    status)  status ;;
    logs)    shift || true; logs "${1:-}" ;;
    *)       usage; exit 1 ;;
esac
