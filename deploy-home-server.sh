#!/bin/bash
# ============================================================
# Allin-One 家庭服务器本机部署脚本
#
# 在家庭服务器（源码仓库与生产目录同机）上执行：
#   源码目录（本脚本所在处） --rsync--> 生产目录 --docker build--> 镜像 --迁移--> --up -d--> 容器
#
# 用法:
#   ./deploy-home-server.sh              # 同步 + 构建 + 重启 + 迁移 + 健康检查
#   ./deploy-home-server.sh sync         # 只同步源码到生产目录，不构建
#   ./deploy-home-server.sh status       # 查看容器状态
#   ./deploy-home-server.sh logs [服务]  # 查看日志（默认 allin-one）
#
# 环境变量:
#   DEPLOY_DIR       生产目录（默认 /opt/allin-one）。其中 docker-compose.home-server.yml
#                    与 .env 是机器本地文件，不在仓库内，不会被同步覆盖
#   REGISTRY         指定基础镜像仓库前缀（含结尾斜杠，空串=直连 Docker Hub），跳过探测
#   REGISTRY_CANDIDATES  探测顺序（空格分隔），默认见下
#   PULL_TIMEOUT     单个镜像源拉取超时秒数（默认 120）
#   HEALTH_URL       健康检查地址（默认 http://192.168.1.103:8000/health）
# ============================================================
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/allin-one}"
COMPOSE_FILE="docker-compose.home-server.yml"
DC="docker compose -f $DEPLOY_DIR/$COMPOSE_FILE"
PULL_TIMEOUT="${PULL_TIMEOUT:-120}"
HEALTH_URL="${HEALTH_URL:-http://192.168.1.103:8000/health}"
# 空串表示直连 Docker Hub，放最后兜底
REGISTRY_CANDIDATES="${REGISTRY_CANDIDATES-docker.1ms.run/ docker.m.daocloud.io/ }"
BASE_IMAGES="node:22-alpine docker:cli python:3.11-slim"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ---- 前置检查 ----
check_env() {
    command -v docker >/dev/null 2>&1 || { err "缺少 docker"; exit 1; }
    command -v rsync  >/dev/null 2>&1 || { err "缺少 rsync"; exit 1; }
    [ -d "$DEPLOY_DIR" ] || { err "生产目录不存在: $DEPLOY_DIR"; exit 1; }
    [ -f "$DEPLOY_DIR/$COMPOSE_FILE" ] || { err "缺少 $DEPLOY_DIR/$COMPOSE_FILE（机器本地文件，需手工准备）"; exit 1; }
    [ -f "$DEPLOY_DIR/.env" ] || { err "缺少 $DEPLOY_DIR/.env"; exit 1; }
}

# ---- 同步源码 ----
# --delete 让生产目录成为仓库的镜像（仓库里删掉的文件也从生产删掉）；
# 机器本地文件（.env、compose、证书、数据、备份还原目录）全部排除，不受影响
sync_source() {
    info "同步源码 $SRC_DIR -> $DEPLOY_DIR ..."
    local changed
    changed=$(rsync -ai --delete \
        --exclude '.git' \
        --exclude '.env' \
        --exclude '.restic-password' \
        --exclude '.backup.env' \
        --exclude 'data' \
        --exclude 'certs' \
        --exclude 'restore' \
        --exclude '.cache' \
        --exclude '.claude' \
        --exclude '.mcp.json' \
        --exclude 'node_modules' \
        --exclude 'dist' \
        --exclude '__pycache__' \
        --exclude '.DS_Store' \
        --exclude 'fountain' \
        --exclude 'docker-compose.home-server.yml*' \
        "$SRC_DIR/" "$DEPLOY_DIR/" | grep -v '^\.d' || true)
    if [ -z "$changed" ]; then
        ok "源码无变化"
    else
        echo "$changed" | sed 's/^/        /'
        ok "已同步 $(echo "$changed" | wc -l | tr -d ' ') 个文件"
    fi
}

# ---- 选择可用的基础镜像源 ----
# 依次尝试各镜像源拉取 Dockerfile 用到的三个基础镜像，全部在超时内成功的第一个即采用。
# 已在本地的镜像会秒过，所以正常情况下首选源即命中；镜像源抽风时自动换下一个。
pick_registry() {
    if [ -n "${REGISTRY+x}" ]; then
        info "使用指定镜像源: '${REGISTRY:-Docker Hub}'"
        return
    fi
    local cand
    for cand in $REGISTRY_CANDIDATES ""; do
        local label="${cand:-Docker Hub(直连)}"
        info "探测镜像源 $label ..."
        local all_ok=true img
        for img in $BASE_IMAGES; do
            if ! timeout "$PULL_TIMEOUT" docker pull -q "${cand}${img}" >/dev/null 2>&1; then
                warn "  拉取 ${cand}${img} 失败或超过 ${PULL_TIMEOUT}s"
                all_ok=false
                break
            fi
        done
        if $all_ok; then
            REGISTRY="$cand"
            ok "采用镜像源: $label"
            return
        fi
    done
    err "所有镜像源都拉不到基础镜像: $BASE_IMAGES"
    exit 1
}

# ---- 构建 ----
build_image() {
    info "构建镜像 allin-one:home-server（REGISTRY='${REGISTRY}'）..."
    (cd "$DEPLOY_DIR" && DOCKER_BUILDKIT=1 $DC build --build-arg "REGISTRY=${REGISTRY}" allin-one)
    ok "镜像构建完成"
}

# ---- 重启 + 迁移 + 健康检查 ----
restart_services() {
    info "重建容器..."
    (cd "$DEPLOY_DIR" && $DC up -d)
    ok "容器已更新"
}

wait_healthy() {
    info "等待 allin-one 健康..."
    local i status
    for i in $(seq 1 45); do
        status=$($DC ps allin-one --format '{{.Status}}' 2>/dev/null || echo "")
        case "$status" in
            *healthy*)   ok "容器健康"; return 0 ;;
            *unhealthy*) err "容器 unhealthy: $status"; return 1 ;;
        esac
        sleep 2
    done
    err "90s 内未变为 healthy（当前: $status）"
    return 1
}

# 迁移在切换容器「之前」用新镜像跑：迁移应对旧代码向后兼容（加列/加表/加索引），
# 这样新代码启动时库结构已就绪，不会出现「新代码查询尚不存在的列」的窗口；
# 迁移失败则中止部署，线上仍是旧容器。
run_migrations() {
    info "执行数据库迁移（新镜像、一次性容器）..."
    if (cd "$DEPLOY_DIR" && $DC run --rm --no-deps -T allin-one alembic upgrade head); then
        ok "迁移完成"
    else
        err "迁移失败，已中止部署（线上仍为旧版本）。手工排查: $DC run --rm --no-deps allin-one alembic upgrade head"
        exit 1
    fi
}

verify_deploy() {
    local body
    body=$(curl -s -m 10 "$HEALTH_URL" || true)
    if echo "$body" | grep -q '"status":"ok"'; then
        ok "健康检查通过: $HEALTH_URL"
    else
        warn "健康检查异常: ${body:-无响应}"
    fi
    # 镜像里的前端产物应与仓库当前提交一致：用源码里的 index.html 引用的 hash 反查
    local built
    built=$($DC exec -T allin-one sh -c 'ls /app/static/assets/index-*.js 2>/dev/null | head -1' 2>/dev/null || true)
    [ -n "$built" ] && info "线上前端入口: $(basename "$built")"
}

show_status() {
    echo ""
    $DC ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
    echo ""
}

# ============================================================
# 主入口
# ============================================================
check_env

case "${1:-}" in
    sync)
        sync_source
        ;;
    status)
        show_status
        ;;
    logs)
        $DC logs -f --tail 200 "${2:-allin-one}"
        ;;
    ""|deploy|build)
        sync_source
        pick_registry
        build_image
        run_migrations
        restart_services
        wait_healthy
        docker image prune -f >/dev/null 2>&1 || true
        verify_deploy
        show_status
        ;;
    *)
        echo "用法: $0 [deploy|sync|status|logs [服务]]"
        exit 1
        ;;
esac
