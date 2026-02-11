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
SCHEDULER_ENABLED=false
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
        $DC down
        ok "所有服务已停止"
        ;;
    restart)
        info "重启所有服务..."
        $DC down
        $DC up -d
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
        ok "所有服务已启动"
        show_status
        ;;
    rebuild)
        check_deps
        ensure_env
        info "强制重新构建所有镜像..."
        $DC build --no-cache
        $DC up -d
        save_checksum
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
        else
            info "依赖未变化，跳过构建直接启动..."
            $DC up -d
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
