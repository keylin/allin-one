#!/bin/bash
# ============================================================
# Allin-One 本地日志查看工具
#
# 用法:
#   ./logs-local.sh                  # 交互式选择要查看的日志
#   ./logs-local.sh app              # 主应用 Docker 日志 (实时跟踪)
#   ./logs-local.sh worker           # 全部 Worker 日志
#   ./logs-local.sh pipeline         # Pipeline Worker 日志
#   ./logs-local.sh scheduled        # Scheduled Worker 日志
#   ./logs-local.sh rsshub           # RSSHub Docker 日志
#   ./logs-local.sh browserless      # Browserless Docker 日志
#   ./logs-local.sh db               # PostgreSQL Docker 日志
#   ./logs-local.sh all              # 所有容器日志 (混合输出)
#   ./logs-local.sh file backend     # 后端文件日志 (data/logs/)
#   ./logs-local.sh file worker      # Worker 文件日志
#   ./logs-local.sh file error       # 错误文件日志
#   ./logs-local.sh error            # 错误日志汇总 (容器 + 文件)
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
DC="docker compose"
LOG_DIR="$ROOT_DIR/data/logs"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
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

# ---- 容器名映射 ----
resolve_services() {
    case "$1" in
        app)          echo "allin-one" ;;
        worker)       echo "allin-worker-pipeline allin-worker-scheduled" ;;
        pipeline)     echo "allin-worker-pipeline" ;;
        scheduled)    echo "allin-worker-scheduled" ;;
        rsshub)       echo "allin-rsshub" ;;
        browserless)  echo "allin-browserless" ;;
        db|postgres)  echo "allin-postgres" ;;
        *)            echo "$1" ;;
    esac
}

# ---- Docker 日志 ----
docker_logs() {
    local services
    services=$(resolve_services "$1")
    local opts="--tail $LINES"

    [ "$FOLLOW" = true ] && opts="$opts -f"
    [ -n "$SINCE" ] && opts="$opts --since $SINCE"

    if [ -n "$GREP_PATTERN" ]; then
        $DC logs $opts $services 2>&1 | grep --color=always -i "$GREP_PATTERN"
    else
        $DC logs $opts $services
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

    for svc in allin-one allin-worker-pipeline allin-worker-scheduled; do
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

# ---- 交互式菜单 ----
show_menu() {
    echo ""
    echo -e "  ${BOLD}Allin-One 日志查看工具 (本地)${NC}"
    echo -e "  ──────────────────────────────"
    echo ""
    echo -e "  ${CYAN}Docker 容器日志:${NC}"
    echo "    1) app           主应用 API"
    echo "    2) worker        全部 Worker"
    echo "    3) pipeline      Pipeline Worker"
    echo "    4) scheduled     Scheduled Worker"
    echo "    5) rsshub        RSSHub"
    echo "    6) browserless   无头浏览器"
    echo "    7) db            PostgreSQL"
    echo "    8) all           所有容器 (混合)"
    echo ""
    echo -e "  ${CYAN}文件日志:${NC}"
    echo "    a) file backend     后端文件日志"
    echo "    b) file worker      Worker 文件日志"
    echo "    c) file error       错误文件日志"
    echo ""
    echo -e "  ${CYAN}诊断:${NC}"
    echo "    e) error         错误日志汇总"
    echo ""
    echo -e "  ${DIM}q) 退出${NC}"
    echo ""

    read -rp "  选择 [1-8,a-c,e,q]: " choice
    echo ""

    case "$choice" in
        1) docker_logs app ;;
        2) docker_logs worker ;;
        3) docker_logs pipeline ;;
        4) docker_logs scheduled ;;
        5) docker_logs rsshub ;;
        6) docker_logs browserless ;;
        7) docker_logs db ;;
        8) docker_logs_all ;;
        a) file_logs backend ;;
        b) file_logs worker ;;
        c) file_logs error ;;
        e) FOLLOW=false; show_errors ;;
        q|Q) exit 0 ;;
        *) echo -e "${RED}无效选择${NC}"; show_menu ;;
    esac
}

# ============================================================
# 主入口
# ============================================================
parse_args "$@"

case "$CMD" in
    app|worker|pipeline|scheduled|rsshub|browserless|db|postgres)
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
    "")
        show_menu
        ;;
    *)
        echo -e "${RED}未知命令: $CMD${NC}"
        echo "用法: ./logs-local.sh [app|worker|pipeline|scheduled|rsshub|browserless|db|all|file|error]"
        exit 1
        ;;
esac
