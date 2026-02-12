#!/bin/bash
# ============================================================
# Allin-One 日志查看工具
#
# 用法:
#   ./logs.sh                  # 交互式选择要查看的日志
#   ./logs.sh backend          # 后端 Docker 日志 (实时跟踪)
#   ./logs.sh worker           # Worker Docker 日志
#   ./logs.sh frontend         # 前端 Docker 日志
#   ./logs.sh rsshub           # RSSHub Docker 日志
#   ./logs.sh browserless      # Browserless Docker 日志
#   ./logs.sh all              # 所有容器日志 (混合输出)
#   ./logs.sh file backend     # 后端文件日志 (data/logs/)
#   ./logs.sh file frontend    # 前端文件日志
#   ./logs.sh error            # 仅显示所有容器的 ERROR 日志
#   ./logs.sh db               # 数据库状态概览
#
# 选项:
#   -n, --lines NUM   显示最近 N 行 (默认 100)
#   -f, --follow      实时跟踪 (Docker 日志默认开启)
#   --no-follow       不实时跟踪
#   --since TIME      起始时间 (如 "10m", "1h", "2026-02-12")
#   --grep PATTERN    过滤关键词
# ============================================================
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.local.yml"
DC="docker compose -f $COMPOSE_FILE"
LOG_DIR="$ROOT_DIR/backend/data/logs"
DB_FILE="$ROOT_DIR/backend/data/db/allin.db"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

# 默认参数
LINES=100
FOLLOW=true
SINCE=""
GREP_PATTERN=""

# ---- 参数解析 ----
parse_args() {
    local args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -n|--lines)   LINES="$2"; shift 2 ;;
            -f|--follow)  FOLLOW=true; shift ;;
            --no-follow)  FOLLOW=false; shift ;;
            --since)      SINCE="$2"; shift 2 ;;
            --grep)       GREP_PATTERN="$2"; shift 2 ;;
            *)            args+=("$1"); shift ;;
        esac
    done
    set -- "${args[@]}"
    CMD="${1:-}"
    SUB="${2:-}"
}

# ---- Docker 日志 ----
docker_logs() {
    local service="$1"
    local opts="--tail $LINES"

    [ "$FOLLOW" = true ] && opts="$opts -f"
    [ -n "$SINCE" ] && opts="$opts --since $SINCE"

    if [ -n "$GREP_PATTERN" ]; then
        $DC logs $opts "$service" 2>&1 | grep --color=always -i "$GREP_PATTERN"
    else
        $DC logs $opts "$service"
    fi
}

docker_logs_all() {
    local opts="--tail $LINES"

    [ "$FOLLOW" = true ] && opts="$opts -f"
    [ -n "$SINCE" ] && opts="$opts --since $SINCE"

    if [ -n "$GREP_PATTERN" ]; then
        $DC logs $opts 2>&1 | grep --color=always -i "$GREP_PATTERN"
    else
        $DC logs $opts
    fi
}

# ---- 文件日志 ----
file_logs() {
    local name="${1:-backend}"
    local file="$LOG_DIR/${name}.log"

    if [ ! -f "$file" ]; then
        echo -e "${RED}日志文件不存在: ${file}${NC}"
        echo -e "${DIM}可用的文件日志:${NC}"
        ls "$LOG_DIR"/*.log 2>/dev/null | while read f; do
            echo "  $(basename "$f")"
        done
        return 1
    fi

    echo -e "${CYAN}=== 文件日志: ${file} ===${NC}"
    echo -e "${DIM}大小: $(du -h "$file" | cut -f1)  行数: $(wc -l < "$file")${NC}"
    echo ""

    if [ "$FOLLOW" = true ]; then
        if [ -n "$GREP_PATTERN" ]; then
            tail -n "$LINES" -f "$file" | grep --color=always -i "$GREP_PATTERN"
        else
            tail -n "$LINES" -f "$file"
        fi
    else
        if [ -n "$GREP_PATTERN" ]; then
            tail -n "$LINES" "$file" | grep --color=always -i "$GREP_PATTERN"
        else
            tail -n "$LINES" "$file"
        fi
    fi
}

# ---- 错误日志汇总 ----
show_errors() {
    local opts="--tail 500"
    [ -n "$SINCE" ] && opts="$opts --since $SINCE"

    echo -e "${RED}${BOLD}=== 错误日志汇总 ===${NC}"
    echo ""

    for svc in backend worker; do
        local count
        count=$($DC logs $opts "$svc" 2>&1 | grep -ic "error\|exception\|traceback\|failed" || true)
        if [ "$count" -gt 0 ]; then
            echo -e "${RED}── $svc ($count 条错误) ──${NC}"
            $DC logs $opts "$svc" 2>&1 | grep --color=always -i "error\|exception\|traceback\|failed" | tail -n 20
            echo ""
        else
            echo -e "${GREEN}── $svc (无错误) ──${NC}"
        fi
    done

    # 文件日志中的错误
    for logfile in "$LOG_DIR"/*.log; do
        [ -f "$logfile" ] || continue
        local name
        name=$(basename "$logfile")
        local count
        count=$(grep -ic "error\|exception\|traceback\|failed" "$logfile" || true)
        if [ "$count" -gt 0 ]; then
            echo -e "${RED}── 文件: $name ($count 条错误) ──${NC}"
            grep --color=always -i "error\|exception\|traceback\|failed" "$logfile" | tail -n 10
            echo ""
        fi
    done
}

# ---- 数据库状态 ----
show_db_status() {
    if [ ! -f "$DB_FILE" ]; then
        echo -e "${RED}数据库文件不存在: $DB_FILE${NC}"
        return 1
    fi

    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo -e "${RED}sqlite3 未安装${NC}"
        return 1
    fi

    echo -e "${CYAN}${BOLD}=== 数据库状态 ===${NC}"
    echo ""

    # 文件信息
    echo -e "${BOLD}文件:${NC}"
    ls -lh "$DB_FILE" | awk '{print "  主库:  " $5 "  " $6 " " $7 " " $8}'
    local wal="${DB_FILE}-wal"
    [ -f "$wal" ] && ls -lh "$wal" | awk '{print "  WAL:   " $5 "  " $6 " " $7 " " $8}'
    echo ""

    # 各表行数
    echo -e "${BOLD}数据统计:${NC}"
    sqlite3 "$DB_FILE" "
        SELECT '  数据源:        ' || COUNT(*) FROM source_configs;
        SELECT '  内容条目:      ' || COUNT(*) FROM content_items;
        SELECT '  流水线模板:    ' || COUNT(*) FROM pipeline_templates;
        SELECT '  流水线执行:    ' || COUNT(*) FROM pipeline_executions;
        SELECT '  提示词模板:    ' || COUNT(*) FROM prompt_templates;
        SELECT '  系统设置:      ' || COUNT(*) FROM system_settings;
    "
    echo ""

    # 内容状态分布
    echo -e "${BOLD}内容状态:${NC}"
    sqlite3 "$DB_FILE" "
        SELECT '  ' || status || ': ' || COUNT(*) FROM content_items GROUP BY status ORDER BY COUNT(*) DESC;
    "
    echo ""

    # 最近 pipeline 执行
    echo -e "${BOLD}最近 5 次流水线执行:${NC}"
    sqlite3 -header -column "$DB_FILE" "
        SELECT
            pe.status,
            pt.name AS template,
            ci.title AS content,
            pe.started_at
        FROM pipeline_executions pe
        LEFT JOIN pipeline_templates pt ON pe.template_id = pt.id
        LEFT JOIN content_items ci ON pe.content_id = ci.id
        ORDER BY pe.created_at DESC
        LIMIT 5;
    "
}

# ---- 交互式菜单 ----
show_menu() {
    echo ""
    echo -e "  ${BOLD}Allin-One 日志查看工具${NC}"
    echo -e "  ──────────────────────────────"
    echo ""
    echo -e "  ${CYAN}Docker 容器日志:${NC}"
    echo "    1) backend       后端 API 服务"
    echo "    2) worker        Huey 异步任务"
    echo "    3) frontend      前端开发服务"
    echo "    4) rsshub        RSSHub 服务"
    echo "    5) browserless   无头浏览器"
    echo "    6) all           所有容器 (混合)"
    echo ""
    echo -e "  ${CYAN}文件日志:${NC}"
    echo "    7) file backend     后端文件日志"
    echo "    8) file frontend    前端文件日志"
    echo ""
    echo -e "  ${CYAN}诊断:${NC}"
    echo "    9) error         错误日志汇总"
    echo "    0) db            数据库状态"
    echo ""
    echo -e "  ${DIM}q) 退出${NC}"
    echo ""

    read -rp "  选择 [1-9,0,q]: " choice
    echo ""

    case "$choice" in
        1) docker_logs backend ;;
        2) docker_logs worker ;;
        3) docker_logs frontend ;;
        4) docker_logs rsshub ;;
        5) docker_logs browserless ;;
        6) docker_logs_all ;;
        7) file_logs backend ;;
        8) file_logs frontend ;;
        9) FOLLOW=false; show_errors ;;
        0) FOLLOW=false; show_db_status ;;
        q|Q) exit 0 ;;
        *) echo -e "${RED}无效选择${NC}"; show_menu ;;
    esac
}

# ============================================================
# 主入口
# ============================================================
parse_args "$@"

case "$CMD" in
    backend|worker|frontend|rsshub|browserless)
        docker_logs "$CMD"
        ;;
    all)
        docker_logs_all
        ;;
    file)
        file_logs "$SUB"
        ;;
    error|errors)
        FOLLOW=false
        show_errors
        ;;
    db)
        FOLLOW=false
        show_db_status
        ;;
    "")
        show_menu
        ;;
    *)
        echo -e "${RED}未知命令: $CMD${NC}"
        echo "用法: ./logs.sh [backend|worker|frontend|rsshub|browserless|all|file|error|db]"
        exit 1
        ;;
esac
