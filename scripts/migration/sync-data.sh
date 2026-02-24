#!/bin/bash
set -e

# 数据迁移/同步脚本
# 用法:
#   bash scripts/migration/sync-data.sh [db|media|all]
#
# 环境变量:
#   DEPLOY_HOST  — 目标主机 (默认 allin@192.168.31.158)
#   DEPLOY_DIR   — 目标目录 (默认 ~/allin-one)
#   SSH_PORT     — SSH 端口 (默认 2222)

REMOTE_HOST="${DEPLOY_HOST:-allin@192.168.31.158}"
REMOTE_DIR="${DEPLOY_DIR:-~/allin-one}"
SSH_PORT="${SSH_PORT:-2222}"
SSH_CMD="ssh -T -p ${SSH_PORT}"

MODE="${1:-all}"

sync_db() {
    echo "=== 同步数据库 ==="
    local dump_file="/tmp/allinone_$(date +%Y%m%d_%H%M%S).sql.gz"

    echo ">> 导出本地数据库..."
    docker compose exec -T postgres pg_dump -U postgres --clean --if-exists allinone | gzip > "${dump_file}"
    echo "   导出完成: ${dump_file} ($(du -h "${dump_file}" | cut -f1))"

    echo ">> 传输到远程服务器..."
    scp -P ${SSH_PORT} "${dump_file}" ${REMOTE_HOST}:/tmp/allinone_sync.sql.gz

    echo ">> 在远程服务器导入..."
    ${SSH_CMD} ${REMOTE_HOST} << 'REMOTE_EOF'
cd ~/allin-one
gunzip -c /tmp/allinone_sync.sql.gz | docker compose exec -T postgres psql -U postgres -d allinone --quiet
rm -f /tmp/allinone_sync.sql.gz
echo "   远程导入完成"
REMOTE_EOF

    rm -f "${dump_file}"
    echo "=== 数据库同步完成 ==="
}

sync_media() {
    echo "=== 同步媒体文件 ==="
    echo ">> rsync data/ -> ${REMOTE_HOST}:${REMOTE_DIR}/data/"
    rsync -avz --progress -e "ssh -T -p ${SSH_PORT}" \
        --exclude '.DS_Store' \
        --exclude 'logs' \
        --exclude '*.db' \
        ./data/ ${REMOTE_HOST}:${REMOTE_DIR}/data/
    echo "=== 媒体文件同步完成 ==="
}

case "${MODE}" in
    db)
        sync_db
        ;;
    media)
        sync_media
        ;;
    all)
        sync_db
        sync_media
        ;;
    *)
        echo "用法: $0 [db|media|all]"
        echo "  db    — 仅同步 PostgreSQL 数据库"
        echo "  media — 仅同步 data/ 媒体文件"
        echo "  all   — 同步数据库 + 媒体文件"
        exit 1
        ;;
esac

echo ""
echo "=== 数据同步全部完成 ==="
