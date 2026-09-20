#!/usr/bin/env bash
# 模型 / 真实库 / 文档 三方漂移检查（在家庭服务器本机、仓库根目录执行）
#
#   scripts/verify/drift/check.sh           # 两项检查，有漂移则退出码 1
#   scripts/verify/drift/check.sh --write   # 用当前模型重新生成 docs/system_design.md 的表结构段
#
# 1. 模型 vs 真实库：在线上 allin-one 容器里跑（用的是已部署的代码 + 生产库）。
#    刚改完模型、还没部署时，这一项反映的是线上代码的状态。
# 2. 文档 vs 模型：用工作区的模型生成表结构 Markdown，与 docs/system_design.md 里
#    <!-- BEGIN/END GENERATED: schema --> 之间的内容比对。
set -euo pipefail
cd "$(dirname "$0")/../../.."

SCRIPT=scripts/verify/drift/schema_drift.py
DOC=docs/system_design.md
IMAGE="${IMAGE:-allin-one:home-server}"
rc=0

gen_doc() {
    docker run --rm -i -v "$PWD/backend":/app -w /app \
        -e DATABASE_URL=postgresql://x:x@localhost/x "$IMAGE" python - doc < "$SCRIPT" 2>/dev/null
}

if [ "${1:-}" = "--write" ]; then
    gen_doc > /tmp/allin-schema.md
    python3 - "$DOC" /tmp/allin-schema.md <<'PY'
import sys
doc, gen = sys.argv[1], open(sys.argv[2], encoding="utf-8").read()
s = open(doc, encoding="utf-8").read()
b, e = "<!-- BEGIN GENERATED: schema -->", "<!-- END GENERATED: schema -->"
i, j = s.index(b) + len(b), s.index(e)
open(doc, "w", encoding="utf-8").write(s[:i] + "\n\n" + gen + "\n" + s[j:])
print(f"已更新 {doc} 的表结构段")
PY
    rm -f /tmp/allin-schema.md
    exit 0
fi

echo "== 1/2 模型 vs 真实库（线上容器）"
docker exec -i allin-one python - check < "$SCRIPT" 2>/dev/null || rc=1

echo "== 2/2 文档 vs 模型（工作区）"
gen_doc > /tmp/allin-schema.md
python3 - "$DOC" /tmp/allin-schema.md <<'PY' || rc=1
import sys, difflib
doc, gen = open(sys.argv[1], encoding="utf-8").read(), open(sys.argv[2], encoding="utf-8").read()
b, e = "<!-- BEGIN GENERATED: schema -->", "<!-- END GENERATED: schema -->"
cur = doc[doc.index(b) + len(b):doc.index(e)].strip()
if cur == gen.strip():
    print("文档的表结构段与模型一致")
else:
    diff = list(difflib.unified_diff(cur.splitlines(), gen.strip().splitlines(), "docs", "models", lineterm="", n=0))
    print(f"文档的表结构段已过期（{len(diff)} 行差异），运行 scripts/verify/drift/check.sh --write 更新:")
    print("\n".join(diff[:30]))
    sys.exit(1)
PY
rm -f /tmp/allin-schema.md
exit $rc
