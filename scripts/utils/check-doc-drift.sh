#!/usr/bin/env bash
# check-doc-drift.sh — Stop hook: 检测代码变更但无文档更新的情况
# 用于 Claude Code Stop hook，在对话结束时提醒同步文档

set -euo pipefail

# 获取 git 变更文件（staged + unstaged vs HEAD）
changed_files=$(git diff --name-only HEAD 2>/dev/null; git diff --name-only --cached HEAD 2>/dev/null) || true
changed_files=$(echo "$changed_files" | sort -u | grep -v '^$' || true)

if [ -z "$changed_files" ]; then
  exit 0
fi

# 分类：代码文件 vs 文档文件
code_files=""
doc_files=""

while IFS= read -r file; do
  case "$file" in
    CLAUDE.md|*/CLAUDE.md|docs/*.md|scripts/README.md|.claude/skills/README.md)
      doc_files="$doc_files $file"
      ;;
    *.py|*.ts|*.js|*.vue|*.rs|*.sql|*.toml|*.yaml|*.yml|*.json|*.sh)
      code_files="$code_files $file"
      ;;
  esac
done <<< "$changed_files"

# 统计代码文件数量
code_count=0
code_list=""
if [ -n "$code_files" ]; then
  code_count=$(echo "$code_files" | wc -w | tr -d ' ')
  code_list=$(echo "$code_files" | tr ' ' '\n' | grep -v '^$' | paste -sd', ' -)
fi

# 有文档变更或代码变更 < 2 → 静默退出
if [ -n "$doc_files" ] || [ "$code_count" -lt 2 ]; then
  exit 0
fi

# 代码变更 >= 2 且无文档变更 → 输出指令
cat <<EOF
[doc-sync] 检测到 ${code_count} 个代码文件变更但无文档更新。
变更文件: ${code_list}
请立即评估是否需要同步更新项目文档（CLAUDE.md / docs/）。
- 有把握的文档更新：直接修改（随功能代码同 commit）
- 不确定是否需要更新：询问用户确认
- 确认无需更新：说明理由后结束
EOF
