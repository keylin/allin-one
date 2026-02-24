#!/bin/bash
# ============================================================
# Allin-One 远程服务器日志查看工具
#
# 用法:
#   ./logs-remote.sh                  # 交互式选择要查看的日志
#   ./logs-remote.sh app              # 主应用 Docker 日志 (实时跟踪)
#   ./logs-remote.sh worker           # 全部 Worker 日志
#   ./logs-remote.sh pipeline         # Pipeline Worker 日志
#   ./logs-remote.sh scheduled        # Scheduled Worker 日志
#   ./logs-remote.sh rsshub           # RSSHub Docker 日志
#   ./logs-remote.sh browserless      # Browserless Docker 日志
#   ./logs-remote.sh db               # PostgreSQL Docker 日志
#   ./logs-remote.sh all              # 所有容器日志 (混合输出)
#   ./logs-remote.sh file backend     # 后端文件日志 (data/logs/)
#   ./logs-remote.sh file worker      # Worker 文件日志
#   ./logs-remote.sh file error       # 错误文件日志
#   ./logs-remote.sh error            # 错误日志汇总 (容器 + 文件)
#
# 选项:
#   -n, --lines NUM   显示最近 N 行 (默认 100)
#   -f, --follow      实时跟踪 (Docker 日志默认开启)
#   --no-follow       不实时跟踪
#   --since TIME      起始时间 (如 "10m", "1h", "2026-02-12")
#   --grep PATTERN    过滤关键词
# ============================================================
set -e

REMOTE_HOST="${DEPLOY_HOST:-allin@192.168.31.158}"
REMOTE_DIR="${DEPLOY_DIR:-~/allin-one}"
SSH="ssh -t -p ${SSH_PORT:-2222} ${REMOTE_HOST}"
SSH_NT="ssh -T -p ${SSH_PORT:-2222} ${REMOTE_HOST}"
REMOTE_LOG_DIR="${REMOTE_DIR}/data/logs"

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

    local remote_cmd="cd ${REMOTE_DIR} && docker compose logs $opts $services"

    if [ -n "$GREP_PATTERN" ]; then
        remote_cmd="$remote_cmd 2>&1 | grep --color=always -i '$GREP_PATTERN'"
    fi

    if [ "$FOLLOW" = true ]; then
        ${SSH} "$remote_cmd"
    else
        ${SSH_NT} "$remote_cmd"
    fi
}

docker_logs_all() {
    local opts="--tail $LINES"

    [ "$FOLLOW" = true ] && opts="$opts -f"
    [ -n "$SINCE" ] && opts="$opts --since $SINCE"

    local remote_cmd="cd ${REMOTE_DIR} && docker compose logs $opts"

    if [ -n "$GREP_PATTERN" ]; then
        remote_cmd="$remote_cmd 2>&1 | grep --color=always -i '$GREP_PATTERN'"
    fi

    if [ "$FOLLOW" = true ]; then
        ${SSH} "$remote_cmd"
    else
        ${SSH_NT} "$remote_cmd"
    fi
}

# ---- 文件日志 ----
file_logs() {
    local name="${1:-backend}"
    local file="${REMOTE_LOG_DIR}/${name}.log"

    # 检查远程文件是否存在
    if ! ${SSH_NT} "test -f ${file}" 2>/dev/null; then
        echo -e "${RED}远程日志文件不存在: ${file}${NC}"
        echo -e "${DIM}可用的文件日志:${NC}"
        ${SSH_NT} "ls ${REMOTE_LOG_DIR}/*.log 2>/dev/null" | while read f; do
            echo "  $(basename "$f")"
        done
        return 1
    fi

    local meta
    meta=$(${SSH_NT} "du -h '${file}' | cut -f1; wc -l < '${file}'")
    local fsize
    fsize=$(echo "$meta" | head -1)
    local flines
    flines=$(echo "$meta" | tail -1 | tr -d ' ')

    echo -e "${CYAN}=== 远程文件日志: ${file} ===${NC}"
    echo -e "${DIM}大小: ${fsize}  行数: ${flines}${NC}"
    echo ""

    local tail_cmd="tail -n $LINES"
    [ "$FOLLOW" = true ] && tail_cmd="tail -n $LINES -f"

    if [ -n "$GREP_PATTERN" ]; then
        tail_cmd="$tail_cmd '${file}' | grep --color=always -i '$GREP_PATTERN'"
    else
        tail_cmd="$tail_cmd '${file}'"
    fi

    if [ "$FOLLOW" = true ]; then
        ${SSH} "$tail_cmd"
    else
        ${SSH_NT} "$tail_cmd"
    fi
}

# ---- 错误日志汇总 ----
show_errors() {
    local opts="--tail 500"
    [ -n "$SINCE" ] && opts="$opts --since $SINCE"

    echo -e "${RED}${BOLD}=== 错误日志汇总 (远程) ===${NC}"
    echo ""

    for svc in allin-one allin-worker-pipeline allin-worker-scheduled; do
        local count
        count=$(${SSH_NT} "cd ${REMOTE_DIR} && docker compose logs $opts $svc 2>&1 | grep -ic 'error\|exception\|traceback\|failed'" || true)
        count=$(echo "$count" | tr -d '[:space:]')
        if [ -n "$count" ] && [ "$count" -gt 0 ] 2>/dev/null; then
            echo -e "${RED}── $svc ($count 条错误) ──${NC}"
            ${SSH_NT} "cd ${REMOTE_DIR} && docker compose logs $opts $svc 2>&1 | grep --color=always -i 'error\|exception\|traceback\|failed' | tail -n 20"
            echo ""
        else
            echo -e "${GREEN}── $svc (无错误) ──${NC}"
        fi
    done

    # 远程文件日志中的错误
    local logfiles
    logfiles=$(${SSH_NT} "ls ${REMOTE_LOG_DIR}/*.log 2>/dev/null" || true)
    for logfile in $logfiles; do
        [ -z "$logfile" ] && continue
        local name
        name=$(basename "$logfile")
        local count
        count=$(${SSH_NT} "grep -ic 'error\|exception\|traceback\|failed' '${logfile}'" || true)
        count=$(echo "$count" | tr -d '[:space:]')
        if [ -n "$count" ] && [ "$count" -gt 0 ] 2>/dev/null; then
            echo -e "${RED}── 文件: $name ($count 条错误) ──${NC}"
            ${SSH_NT} "grep --color=always -i 'error\|exception\|traceback\|failed' '${logfile}' | tail -n 10"
            echo ""
        fi
    done
}

# ---- 交互式菜单 ----
show_menu() {
    echo ""
    echo -e "  ${BOLD}Allin-One 日志查看工具 (远程 ${REMOTE_HOST})${NC}"
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
        echo "用法: ./logs-remote.sh [app|worker|pipeline|scheduled|rsshub|browserless|db|all|file|error]"
        exit 1
        ;;
esac
