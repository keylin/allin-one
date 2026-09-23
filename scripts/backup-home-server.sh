#!/usr/bin/env bash
# backup-home-server.sh — allin-one 每日备份：pg_dump（-Fc）+ data/ + 机器本地配置，打进同一个 restic 快照。
#
# 用法:
#   scripts/backup-home-server.sh            # 备份 + forget/prune；周日额外 restic check
#   scripts/backup-home-server.sh check      # 只跑 restic check
#   scripts/backup-home-server.sh snapshots  # 列出快照
#   scripts/backup-home-server.sh restore-db <snapshot|latest> <目标目录>   # 取出 dump 文件，不动生产库
#
# 真相单元（docs/design_data_model.md §3.1）：Postgres + data/。两者进同一快照，任一时刻的快照即完整状态。
# 机器本地文件（.env、docker-compose.home-server.yml、restic 密码不含）一并带上，换机器恢复不缺件。
#
# 环境（可在 /opt/allin-one/.backup.env 覆盖）:
#   RESTIC_REPOSITORY     默认 /mnt/sda2/backup/restic-allin-one（与根盘不同的物理盘）
#   RESTIC_PASSWORD_FILE  默认 /opt/allin-one/.restic-password（0600；丢了备份就读不出来，务必另存一份）
#   PROD_DIR              默认 /opt/allin-one
#   STAGING_DIR           默认 /var/backups/allin-one（dump 落点；在 rsync --delete 范围之外）
#   PG_CONTAINER / PG_USER / PG_DB   默认 allin-postgres / allinone / allinone
#   KEEP_DAILY / KEEP_WEEKLY / KEEP_MONTHLY   默认 30 / 8 / 12
#
# 成功后写 $STAGING_DIR/last-success（ISO 时间），供 /health-check 判断"备份还在出快照吗"。

set -euo pipefail

PROD_DIR="${PROD_DIR:-/opt/allin-one}"
[ -f "$PROD_DIR/.backup.env" ] && . "$PROD_DIR/.backup.env"

export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-/mnt/sda2/backup/restic-allin-one}"
export RESTIC_PASSWORD_FILE="${RESTIC_PASSWORD_FILE:-$PROD_DIR/.restic-password}"
STAGING_DIR="${STAGING_DIR:-/var/backups/allin-one}"
PG_CONTAINER="${PG_CONTAINER:-allin-postgres}"
PG_USER="${PG_USER:-allinone}"
PG_DB="${PG_DB:-allinone}"
KEEP_DAILY="${KEEP_DAILY:-30}"
KEEP_WEEKLY="${KEEP_WEEKLY:-8}"
KEEP_MONTHLY="${KEEP_MONTHLY:-12}"
TAG="allin-one"

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
die() { log "ERROR: $*"; exit 1; }

preflight() {
  command -v restic >/dev/null || die "restic 未安装"
  [ -r "$RESTIC_PASSWORD_FILE" ] || die "密码文件不可读: $RESTIC_PASSWORD_FILE"
  [ -d "$(dirname "$RESTIC_REPOSITORY")" ] || die "备份盘未挂载: $(dirname "$RESTIC_REPOSITORY")"
  docker inspect "$PG_CONTAINER" >/dev/null 2>&1 || die "容器不存在: $PG_CONTAINER"
  if ! restic cat config >/dev/null 2>&1; then
    log "restic repo 未初始化，初始化: $RESTIC_REPOSITORY"
    restic init
  fi
}

cmd_backup() {
  preflight
  mkdir -p "$STAGING_DIR"; chmod 700 "$STAGING_DIR"
  local dump="$STAGING_DIR/$PG_DB.dump"
  log "pg_dump -Fc → $dump"
  docker exec "$PG_CONTAINER" pg_dump -Fc -U "$PG_USER" "$PG_DB" > "$dump.tmp"
  mv "$dump.tmp" "$dump"
  # dump 有效性：能列出目录即可解析
  docker exec -i "$PG_CONTAINER" pg_restore --list < "$dump" >/dev/null || die "dump 无法被 pg_restore 解析"
  log "dump $(du -h "$dump" | cut -f1)"

  local weekday; weekday=$(date +%u)
  log "restic backup"
  restic backup \
    --tag "$TAG" --tag daily \
    --exclude "$PROD_DIR/data/logs" \
    "$dump" \
    "$PROD_DIR/data" \
    "$PROD_DIR/.env" \
    "$PROD_DIR/docker-compose.home-server.yml"

  log "restic forget --prune (daily $KEEP_DAILY / weekly $KEEP_WEEKLY / monthly $KEEP_MONTHLY)"
  restic forget --tag "$TAG" --prune \
    --keep-daily "$KEEP_DAILY" --keep-weekly "$KEEP_WEEKLY" --keep-monthly "$KEEP_MONTHLY" >/dev/null

  if [ "$weekday" = "7" ]; then
    log "周日：restic check"
    restic check
  fi
  date -u +%FT%TZ > "$STAGING_DIR/last-success"
  log "done"
}

cmd_restore_db() {
  local snap="${1:-latest}" dest="${2:?目标目录}"
  preflight
  mkdir -p "$dest"
  restic restore "$snap" --target "$dest" --include "$STAGING_DIR/$PG_DB.dump"
  log "dump 已取出到 $dest$STAGING_DIR/$PG_DB.dump"
  log "恢复到库（会覆盖！）: docker exec -i $PG_CONTAINER pg_restore -U $PG_USER -d $PG_DB --clean --if-exists < <dump>"
}

case "${1:-backup}" in
  backup)     cmd_backup ;;
  check)      preflight; restic check ;;
  snapshots)  preflight; restic snapshots --tag "$TAG" ;;
  restore-db) shift; cmd_restore_db "$@" ;;
  *) echo "用法: $0 {backup|check|snapshots|restore-db <snapshot|latest> <目标目录>}" >&2; exit 2 ;;
esac
