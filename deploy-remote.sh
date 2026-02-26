#!/bin/bash
set -e

REMOTE_HOST="${DEPLOY_HOST:-allin@192.168.31.158}"
REMOTE_DIR="${DEPLOY_DIR:-~/allin-one}"
SYNC_DATA="${SYNC_DATA:-}"
SSH="ssh -T -p 2222 ${REMOTE_HOST}"
SCP_CMD="scp -P 2222"

# 提取 IP 用于部署说明
REMOTE_IP="${REMOTE_HOST#*@}"

echo "=== Deploying Allin-One to ${REMOTE_HOST}:${REMOTE_DIR} ==="
echo ""

# 1. Check remote .env
echo ">> [1/3] Checking remote .env..."
ENV_EXISTS=$(${SSH} "test -f ${REMOTE_DIR}/.env && echo y || echo n")
if [ "${ENV_EXISTS}" = "n" ]; then
    ${SCP_CMD} .env ${REMOTE_HOST}:${REMOTE_DIR}/.env
    echo "   .env synced (first deploy)"
else
    echo "   .env exists, skipped"
fi

# 2. Sync files
echo ">> [2/3] Syncing files..."
rsync -avz --delete -e 'ssh -p 2222' \
    --exclude '.git' \
    --exclude 'venv' \
    --exclude 'data' \
    --exclude 'node_modules' \
    --exclude '__pycache__' \
    --exclude '.env' \
    ./ ${REMOTE_HOST}:${REMOTE_DIR}/ --quiet

# 3. Remote build & restart
echo ">> [3/4] Building and restarting..."
${SSH} "cd ${REMOTE_DIR} && docker compose -f docker-compose.remote.yml build allin-one" 2>&1 | tail -20
${SSH} "cd ${REMOTE_DIR} && docker compose -f docker-compose.remote.yml up -d" 2>&1 | tail -10

# 4. Wait for app healthy & run migrations
echo ">> [4/4] Waiting for app to be healthy..."
HEALTHY=false
for i in $(seq 1 30); do
    STATUS=$(${SSH} "cd ${REMOTE_DIR} && docker compose -f docker-compose.remote.yml ps allin-one --format '{{.Status}}'" 2>/dev/null || echo "")
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
    ${SSH} "cd ${REMOTE_DIR} && docker compose -f docker-compose.remote.yml exec -T allin-one alembic upgrade head" || echo "   ⚠ Migration failed, check manually"
else
    echo "   ⚠ Container not healthy after 60s, skipping migrations"
fi

${SSH} "docker image prune -f" > /dev/null 2>&1

# 修正 data/ 目录权限（Docker 以 root 创建，需要让宿主用户可写以便 rsync 同步）
${SSH} "HOST_UID=\$(id -u) HOST_GID=\$(id -g) && cd ${REMOTE_DIR} && docker compose -f docker-compose.remote.yml exec -T allin-one chown -R \${HOST_UID}:\${HOST_GID} /app/data" 2>/dev/null || true

# 获取容器状态（单独命令，避免 heredoc 解析问题）
CONTAINER_STATUS=$(${SSH} "cd ${REMOTE_DIR} && docker compose -f docker-compose.remote.yml ps --format '{{.Name}}|{{.Status}}'")

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

# 4. Data sync
if [ -n "${SYNC_DATA}" ]; then
    bash "$(dirname "$0")/scripts/migration/sync-data.sh" "${SYNC_DATA}"
elif [ -t 0 ]; then
    echo ""
    read -p ">> Sync data to remote? (db/media/all) [Enter=skip] " answer
    case "${answer}" in
        db|media|all)
            bash "$(dirname "$0")/scripts/migration/sync-data.sh" "${answer}"
            ;;
        *)
            echo "   Skipped data sync"
            ;;
    esac
fi

# 5. Deploy summary
echo ""
echo "==========================================="
if ${ALL_UP}; then
    echo "  ✅ Deploy succeeded"
else
    echo "  ⚠️  Deploy completed with issues"
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
