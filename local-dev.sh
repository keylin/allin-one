#!/bin/bash
# ============================================================
# Allin-One 本地一键开发部署脚本 (全容器化)
#
# 用法:
#   ./local-dev.sh              # 构建并启动所有服务
#   ./local-dev.sh start        # 启动 (不重新构建)
#   ./local-dev.sh stop         # 停止所有服务
#   ./local-dev.sh restart      # 重启所有服务
#   ./local-dev.sh status       # 查看运行状态
#   ./local-dev.sh logs [服务]  # 查看日志 (默认 backend)
# ============================================================
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.local.yml"
DC="docker compose -f $COMPOSE_FILE"
CHECKSUM_DIR="$ROOT_DIR/.cache/checksums"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ---- 构建优化 ----
needs_rebuild() {
    mkdir -p "$CHECKSUM_DIR"
    local current=$(cat "$ROOT_DIR/backend/requirements.txt" "$ROOT_DIR/frontend/package.json" 2>/dev/null | md5)
    local cached=$(cat "$CHECKSUM_DIR/deps.md5" 2>/dev/null)
    [ "$current" != "$cached" ]
}

save_checksum() {
    mkdir -p "$CHECKSUM_DIR"
    cat "$ROOT_DIR/backend/requirements.txt" "$ROOT_DIR/frontend/package.json" 2>/dev/null | md5 > "$CHECKSUM_DIR/deps.md5"
}

# ---- Worker 智能重启 ----
backend_code_changed() {
    mkdir -p "$CHECKSUM_DIR"
    local current=$(find "$ROOT_DIR/backend/app" -name "*.py" -type f -print0 | sort -z | xargs -0 cat 2>/dev/null | md5)
    local cached=$(cat "$CHECKSUM_DIR/backend_code.md5" 2>/dev/null)
    [ "$current" != "$cached" ]
}

save_backend_checksum() {
    mkdir -p "$CHECKSUM_DIR"
    find "$ROOT_DIR/backend/app" -name "*.py" -type f -print0 | sort -z | xargs -0 cat 2>/dev/null | md5 > "$CHECKSUM_DIR/backend_code.md5"
}

maybe_restart_worker() {
    if backend_code_changed; then
        info "检测到后端代码变化，重启 Worker 以加载新代码..."
        $DC restart worker
        save_backend_checksum
        ok "Worker 已重启"
    fi
}

# ---- 数据库安全 ----
DB_DIR="$ROOT_DIR/backend/data/db"
BACKUP_DIR="$ROOT_DIR/backend/data/backups"

backup_db() {
    local db_file="$DB_DIR/allin.db"
    [ -f "$db_file" ] || return 0

    mkdir -p "$BACKUP_DIR"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/allin_${timestamp}.db"

    # 用 sqlite3 的 .backup 命令安全导出（会自动合并 WAL）
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$db_file" ".backup '$backup_file'"
    else
        cp "$db_file" "$backup_file"
        # 同时拷贝 WAL 文件以保证完整性
        [ -f "${db_file}-wal" ] && cp "${db_file}-wal" "${backup_file}-wal"
        [ -f "${db_file}-shm" ] && cp "${db_file}-shm" "${backup_file}-shm"
    fi

    ok "数据库已备份: ${backup_file##*/}"

    # 只保留最近 5 个备份
    ls -t "$BACKUP_DIR"/allin_*.db 2>/dev/null | tail -n +6 | while read old; do
        rm -f "$old" "${old}-wal" "${old}-shm"
    done
}

safe_stop() {
    # 先停 worker 避免写入冲突，再停 backend 让 WAL checkpoint 完成
    $DC stop worker 2>/dev/null || true
    $DC stop backend 2>/dev/null || true
}

# ---- 前置检查 ----
check_deps() {
    local missing=()
    command -v docker >/dev/null 2>&1 || missing+=("docker")
    command -v colima >/dev/null 2>&1 || missing+=("colima")

    if [ ${#missing[@]} -gt 0 ]; then
        err "缺少依赖: ${missing[*]}"
        echo "  brew install ${missing[*]}"
        exit 1
    fi

    # 检查 Docker 是否运行，未运行则通过 Colima 启动
    if ! docker info >/dev/null 2>&1; then
        warn "Docker 未运行，正在通过 Colima 启动..."
        colima start --cpu 2 --memory 4 --disk 60 2>/dev/null || colima start

        if ! docker info >/dev/null 2>&1; then
            err "Colima 启动失败，请手动检查: colima status"
            exit 1
        fi
        ok "Colima 已启动"
    fi
}

# ---- .env 模板 ----
ensure_env() {
    if [ ! -f "$ROOT_DIR/backend/.env" ]; then
        warn "未找到 .env，生成默认配置..."
        cat > "$ROOT_DIR/backend/.env" << 'ENVEOF'
# LLM 配置 (必填)
LLM_API_KEY=your-api-key-here
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
SCHEDULER_ENABLED=true
ENVEOF
        warn "请编辑 backend/.env 填入 LLM_API_KEY"
    fi
}

# ---- 状态查看 ----
show_status() {
    echo ""
    echo "  Allin-One 本地服务状态"
    echo "  ──────────────────────────"
    $DC ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo "  访问地址:"
    echo "  ──────────────────────────"
    echo "  前端页面:    http://localhost:3000/"
    echo "  后端 API:    http://localhost:8000/api/"
    echo "  API 文档:    http://localhost:8000/docs"
    echo "  RSSHub:      http://localhost:1200/"
    echo "  Browserless: http://localhost:3001/"
    echo ""
}

# ---- 查看日志 ----
show_logs() {
    local svc="${1:-backend}"
    $DC logs -f "$svc"
}

# ============================================================
# 主入口
# ============================================================
case "${1:-}" in
    stop)
        info "停止所有服务..."
        safe_stop
        $DC down
        ok "所有服务已停止"
        ;;
    restart)
        info "重启所有服务..."
        safe_stop
        $DC down
        $DC up -d
        save_backend_checksum
        ok "所有服务已重启"
        show_status
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs "${2:-backend}"
        ;;
    start)
        check_deps
        ensure_env
        info "启动所有服务 (不重新构建)..."
        $DC up -d
        maybe_restart_worker
        ok "所有服务已启动"
        show_status
        ;;
    rebuild)
        check_deps
        ensure_env
        info "强制重新构建所有镜像..."
        safe_stop
        backup_db
        $DC down
        $DC build --no-cache
        $DC up -d
        save_checksum
        save_backend_checksum
        ok "所有服务已重新构建并启动"
        show_status
        ;;
    *)
        echo ""
        echo "  ╔═══════════════════════════════════════╗"
        echo "  ║   Allin-One 本地一键部署              ║"
        echo "  ╚═══════════════════════════════════════╝"
        echo ""

        check_deps
        ensure_env

        # 智能构建检测
        if needs_rebuild; then
            info "检测到依赖变化，重新构建镜像..."
            $DC up -d --build
            save_checksum
            save_backend_checksum
        else
            info "依赖未变化，跳过构建直接启动..."
            $DC up -d
            maybe_restart_worker
        fi

        ok "所有服务已启动"
        show_status

        echo "  提示:"
        echo "    ./local-dev.sh stop       停止所有服务"
        echo "    ./local-dev.sh restart    重启所有服务"
        echo "    ./local-dev.sh rebuild    强制重新构建"
        echo "    ./local-dev.sh status     查看状态"
        echo "    ./local-dev.sh logs       查看后端日志"
        echo "    ./local-dev.sh logs frontend  查看前端日志"
        echo ""
        ;;
esac
