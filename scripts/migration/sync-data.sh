#!/bin/bash
set -e

# 数据迁移/同步脚本（本地 → 远程，单向覆盖）
# 用法:
#   bash scripts/migration/sync-data.sh [db|media|all]
#
# 环境变量:
#   DEPLOY_HOST  — 目标主机 (默认 allin@192.168.1.103)
#   DEPLOY_DIR   — 目标目录 (默认 ~/allin-one)
#   SSH_PORT     — SSH 端口 (默认 2222)
#   SKIP_BACKUP  — 设为 1 跳过备份 (默认备份)

REMOTE_HOST="${DEPLOY_HOST:-allin@192.168.1.103}"
REMOTE_DIR="${DEPLOY_DIR:-~/allin-one}"
SSH_PORT="${SSH_PORT:-2222}"
SSH_CMD="ssh -T -p ${SSH_PORT}"

MODE="${1:-all}"

backup_remote_db() {
    echo ">> 备份远程数据库..."
    local backup_name="allinone_backup_$(date +%Y%m%d_%H%M%S).sql.gz"
    ${SSH_CMD} ${REMOTE_HOST} << REMOTE_EOF
cd ${REMOTE_DIR}
docker compose exec -T postgres pg_dump -U postgres allinone | gzip > /tmp/${backup_name}
echo "   备份已保存到远程: /tmp/${backup_name} (\$(du -h /tmp/${backup_name} | cut -f1))"
REMOTE_EOF
    echo "   远程数据库备份完成: /tmp/${backup_name}"
}

sync_db() {
    echo "=== 同步数据库 ==="

    # 默认先备份远程数据库
    if [ "${SKIP_BACKUP}" != "1" ]; then
        backup_remote_db
    else
        echo ">> 跳过远程数据库备份 (SKIP_BACKUP=1)"
    fi

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

    # 询问是否备份远程媒体
    if [ -t 0 ] && [ "${SKIP_BACKUP}" != "1" ]; then
        read -t 15 -p ">> 是否备份远程 data/ 目录？(y/N, 15秒后自动跳过) " backup_answer || true
        if [ "${backup_answer}" = "y" ] || [ "${backup_answer}" = "Y" ]; then
            echo ">> 备份远程媒体文件..."
            local backup_name="data_backup_$(date +%Y%m%d_%H%M%S).tar.gz"
            ${SSH_CMD} ${REMOTE_HOST} "cd ${REMOTE_DIR} && tar czf /tmp/${backup_name} --exclude='logs' --exclude='*.db' data/ 2>/dev/null && echo \"   备份已保存: /tmp/${backup_name} (\$(du -h /tmp/${backup_name} | cut -f1))\"" || echo "   ⚠ 备份失败，继续同步"
        else
            echo "   跳过媒体备份"
        fi
    fi

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
        echo "  db    — 仅同步 PostgreSQL 数据库（自动备份远程库）"
        echo "  media — 仅同步 data/ 媒体文件（可选备份）"
        echo "  all   — 同步数据库 + 媒体文件"
        echo ""
        echo "环境变量:"
        echo "  SKIP_BACKUP=1  — 跳过备份"
        exit 1
        ;;
esac

echo ""
echo "=== 数据同步全部完成 ==="
