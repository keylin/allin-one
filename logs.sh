#!/bin/bash
# ============================================================
# Allin-One 日志查看工具
#
# 用法:
#   ./logs.sh                  # 交互式选择要查看的日志
#   ./logs.sh backend          # 后端 Docker 日志 (实时跟踪)
#   ./logs.sh worker-pipeline  # 流水线 Worker 日志
#   ./logs.sh worker-scheduled # 调度 Worker 日志
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
LOG_DIR="$ROOT_DIR/data/logs"

# Colima Docker socket
if [ -S "$HOME/.colima/default/docker.sock" ]; then
    export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
fi

DC="docker compose -f $COMPOSE_FILE"

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

    for svc in backend worker-pipeline worker-scheduled; do
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
    echo -e "  ${BOLD}Allin-One 日志查看工具${NC}"
    echo -e "  ──────────────────────────────"
    echo ""
    echo -e "  ${CYAN}Docker 容器日志:${NC}"
    echo "    1) backend            后端 API 服务"
    echo "    2) worker-pipeline    流水线 Worker"
    echo "    3) worker-scheduled   调度 Worker"
    echo "    4) frontend           前端开发服务"
    echo "    5) rsshub             RSSHub 服务"
    echo "    6) browserless        无头浏览器"
    echo "    7) all                所有容器 (混合)"
    echo ""
    echo -e "  ${CYAN}文件日志:${NC}"
    echo "    8) file backend       后端文件日志"
    echo "    9) file worker        Worker 文件日志"
    echo ""
    echo -e "  ${CYAN}诊断:${NC}"
    echo "    0) error              错误日志汇总"
    echo ""
    echo -e "  ${DIM}q) 退出${NC}"
    echo ""

    read -rp "  选择 [0-9,q]: " choice
    echo ""

    case "$choice" in
        1) docker_logs backend ;;
        2) docker_logs worker-pipeline ;;
        3) docker_logs worker-scheduled ;;
        4) docker_logs frontend ;;
        5) docker_logs rsshub ;;
        6) docker_logs browserless ;;
        7) docker_logs_all ;;
        8) file_logs backend ;;
        9) file_logs worker ;;
        0) FOLLOW=false; show_errors ;;
        q|Q) exit 0 ;;
        *) echo -e "${RED}无效选择${NC}"; show_menu ;;
    esac
}

# ============================================================
# 主入口
# ============================================================
parse_args "$@"

case "$CMD" in
    backend|worker-pipeline|worker-scheduled|frontend|rsshub|browserless)
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
        echo "用法: ./logs.sh [backend|worker-pipeline|worker-scheduled|frontend|rsshub|browserless|all|file|error]"
        exit 1
        ;;
esac
