#!/bin/bash
set -e

REMOTE_HOST="${DEPLOY_HOST:-allin@192.168.1.103}"
REMOTE_DIR="${DEPLOY_DIR:-~/allin-one}"
SYNC_DATA="${SYNC_DATA:-}"
SSH="ssh -T -p 2222 ${REMOTE_HOST}"
SCP_CMD="scp -P 2222"
DEPLOY_MODE="${1:-quick}"
COMPOSE_FILE="docker-compose.remote.yml"

# 提取 IP 用于部署说明
REMOTE_IP="${REMOTE_HOST#*@}"

if [ "${DEPLOY_MODE}" = "build" ]; then
    echo "=== [BUILD] Deploying Allin-One to ${REMOTE_HOST}:${REMOTE_DIR} ==="
else
    echo "=== [QUICK] Deploying Allin-One to ${REMOTE_HOST}:${REMOTE_DIR} ==="
fi
echo ""

# 1. Check remote .env
echo ">> [1] Checking remote .env..."
ENV_EXISTS=$(${SSH} "test -f ${REMOTE_DIR}/.env && echo y || echo n")
if [ "${ENV_EXISTS}" = "n" ]; then
    ${SCP_CMD} .env ${REMOTE_HOST}:${REMOTE_DIR}/.env
    echo "   .env synced (first deploy)"
else
    echo "   .env exists, skipped"
fi

if [ "${DEPLOY_MODE}" = "build" ]; then
    # ── BUILD 模式：rsync + docker build + up ──
    echo ">> [2] Syncing files..."
    rsync -avz --delete -e 'ssh -p 2222' \
        --exclude '.git' \
        --exclude 'venv' \
        --exclude 'data' \
        --exclude 'node_modules' \
        --exclude '__pycache__' \
        --exclude '.env' \
        --exclude 'fountain' \
        ./ ${REMOTE_HOST}:${REMOTE_DIR}/ --quiet

    echo ">> [3] Building and restarting..."
    ${SSH} "cd ${REMOTE_DIR} && DOCKER_BUILDKIT=1 docker compose -f ${COMPOSE_FILE} build allin-one" 2>&1
    ${SSH} "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} up -d" 2>&1
else
    # ── QUICK 模式：本地前端编译 + rsync + restart ──
    echo ">> [2] Building frontend locally..."
    (cd frontend && npm run build) 2>&1

    echo ">> [3] Syncing files..."
    rsync -avz --delete -e 'ssh -p 2222' \
        --exclude '.git' \
        --exclude 'venv' \
        --exclude 'data' \
        --exclude 'node_modules' \
        --exclude '__pycache__' \
        --exclude '.env' \
        --exclude 'fountain' \
        ./ ${REMOTE_HOST}:${REMOTE_DIR}/ --quiet

    echo ">> [4] Restarting containers..."
    ${SSH} "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} up -d allin-one allin-worker-pipeline allin-worker-scheduled allin-mcp" 2>&1
    # MCP 容器通过 volume mount 加载代码，up -d 不会检测文件变更，需显式 restart
    ${SSH} "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} restart allin-mcp" 2>&1
fi

# Health check & migration
echo ">> Waiting for app to be healthy..."
HEALTHY=false
for i in $(seq 1 30); do
    STATUS=$(${SSH} "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} ps allin-one --format '{{.Status}}'" 2>/dev/null || echo "")
    case "${STATUS}" in
        *healthy*)
            HEALTHY=true
            break
            ;;
        *unhealthy*)
            echo "   Container unhealthy, check logs"
            break
            ;;
    esac
    sleep 2
done

if ${HEALTHY}; then
    echo "   Running database migrations..."
    ${SSH} "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} exec -T allin-one alembic upgrade head" || echo "   ⚠ Migration failed, check manually"
else
    echo "   ⚠ Container not healthy after 60s, skipping migrations"
fi

if [ "${DEPLOY_MODE}" = "build" ]; then
    ${SSH} "docker image prune -f" > /dev/null 2>&1
fi

# 修正 data/ 目录权限（Docker 以 root 创建，需要让宿主用户可写以便 rsync 同步）
${SSH} "HOST_UID=\$(id -u) HOST_GID=\$(id -g) && cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} exec -T allin-one chown -R \${HOST_UID}:\${HOST_GID} /app/data" 2>/dev/null || true

# 获取容器状态
CONTAINER_STATUS=$(${SSH} "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} ps --format '{{.Name}}|{{.Status}}'")

# 检查是否所有容器都在运行
ALL_UP=true
UNHEALTHY=""
while IFS='|' read -r name status; do
    [ -z "${name}" ] && continue
    case "${status}" in
        *healthy*|*Up*) ;;
        *) ALL_UP=false; UNHEALTHY="${UNHEALTHY}    ${name}: ${status}\n" ;;
    esac
done <<< "${CONTAINER_STATUS}"

# Data sync
if [ -n "${SYNC_DATA}" ]; then
    bash "$(dirname "$0")/scripts/migration/sync-data.sh" "${SYNC_DATA}"
elif [ -t 0 ]; then
    echo ""
    read -t 8 -p ">> Sync data to remote? (db/media/all) [Enter=skip, auto-skip in 8s] " answer || true
    case "${answer}" in
        db|media|all)
            bash "$(dirname "$0")/scripts/migration/sync-data.sh" "${answer}"
            ;;
        *)
            echo ""
            echo "   Skipped data sync"
            ;;
    esac
fi

# Deploy summary
echo ""
echo "==========================================="
if ${ALL_UP}; then
    echo "  ✅ Deploy succeeded (${DEPLOY_MODE})"
else
    echo "  ⚠️  Deploy completed with issues (${DEPLOY_MODE})"
    echo ""
    echo -e "${UNHEALTHY}"
fi
echo ""
echo "  Services:"
while IFS='|' read -r name status; do
    [ -z "${name}" ] && continue
    case "${status}" in
        *healthy*)  icon="✓" ;;
        *starting*) icon="…" ;;
        *Up*)       icon="✓" ;;
        *)          icon="✗" ;;
    esac
    printf "    %s %s\n" "${icon}" "${name}"
done <<< "${CONTAINER_STATUS}"
echo ""
echo "  Access:"
echo "    Web UI   http://${REMOTE_IP}:8000"
echo "    API      http://${REMOTE_IP}:8000/api"
echo "    Health   http://${REMOTE_IP}:8000/health"
echo "    RSSHub   http://${REMOTE_IP}:1200"
echo "==========================================="
