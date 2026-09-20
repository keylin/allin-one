---
name: mcp-deploy
description: MCP Server 更新部署 — 开发工具 → 本地验证 → 同步至 /opt 部署 → 重建镜像重启容器 → 验证工具注册
argument-hint: [可选: dev|deploy|verify] (默认全流程)
model: sonnet
---

# MCP Server 更新部署

管理 MCP Server 的工具开发、测试与部署。用户指定阶段: **$ARGUMENTS**（默认全流程）。

## 架构概览

```
backend/mcp_server.py          ← MCP 工具定义（FastMCP 3.x）
backend/app/services/source_service.py  ← 共享校验函数（MCP + FastAPI 复用）
backend/app/models/             ← ORM 模型（直接复用）
docker-compose.remote.yml       ← 仓库内 compose 模板（含 bind mount，本地/远程开发用）
~/.claude.json                  ← Claude Code 全局 MCP 配置（user scope）
.mcp.json                       ← 项目级 MCP 配置（gitignored）
```

**关键约束**:
- MCP Server 独立进程，不在 FastAPI 内运行
- **开发环境**（`docker-compose.remote.yml` / `.local.yml`）用 bind mount 挂载代码（`./backend/app:/app/app:ro`、`./backend/mcp_server.py:/app/mcp_server.py:ro`），改代码后 restart 容器即可生效，无需重建镜像
- **生产环境**（home-server 本机 `/opt/allin-one`）不同：`allin-mcp` 容器只 bind mount `.env`，代码打包进镜像 `allin-one:home-server`，改代码必须重建镜像，仅 restart 无效。详见 2.1
- FastMCP `@mcp.tool(annotations={...})` 声明工具元数据（readOnlyHint / destructiveHint / idempotentHint）

## 阶段 1: 开发 (dev)

### 1.1 添加/修改 MCP 工具

编辑 `backend/mcp_server.py`，遵循以下模式:

```python
@mcp.tool(annotations={"readOnlyHint": True})  # 或 False + destructiveHint/idempotentHint
def my_tool(
    param1: str,
    param2: str = "",       # 可选参数给默认值
    limit: int = 20,
) -> str:
    """工具描述（会展示给 AI 客户端）。

    Args:
        param1: 参数说明。
        param2: 可选参数说明。
        limit: 数量限制 (default 20, max 50)。
    """
    with get_db_session() as db:
        # 业务逻辑...
        return "结果文本"
```

**规范**:
- 返回类型始终为 `str`（MCP 协议要求文本）
- 使用 `with get_db_session() as db:` 管理数据库会话
- 复杂查询用辅助函数（如 `_resolve_source(db, source_id, source_name)`）
- JSONB 字段直接作为 dict 读取，不用 `json.loads()`
- 失败一律用 `_err(code, message, **extra)`，未预期异常用 `_internal_error("工具名", e)`，不要手写 `json.dumps({"error": ...})`；`error_code` 取值与附加字段约定见 `docs/system_design.md` §10.3
- annotations 声明:
  - 只读查询: `{"readOnlyHint": True}`
  - 写入操作: `{"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True/False}`
  - 删除操作: `{"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False}`

### 1.2 共享校验逻辑

如果 MCP 工具和 FastAPI 路由共用校验逻辑，提取到 `backend/app/services/source_service.py`:

```python
# source_service.py
def validate_source_type(source_type: str) -> None: ...
def validate_source_config(source_type: str, url: str, config_json: dict) -> None: ...
```

MCP 和 Router 都从 service 层导入，避免重复代码。

### 1.3 本地测试

```bash
# stdio 模式测试（默认）
cd backend && python mcp_server.py

# 或 HTTP 模式测试
cd backend && MCP_TRANSPORT=http python mcp_server.py
# 然后 curl 验证:
curl -s -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

## 阶段 2: 部署 (deploy)

生产部署在 home-server 本机 `/opt/allin-one`（**非 git 仓库**，不是远程主机，无需 SSH/rsync 到别处），开发目录是 `/root/workspace/allin-one`。容器用的镜像是 `allin-one:home-server`，由 `/opt/allin-one/docker-compose.home-server.yml` 定义——该文件独立维护，不在开发仓库中，与 `docker-compose.remote.yml` 已分叉（最主要区别: `allin-mcp` 只 bind mount `.env`，其余代码烘焙进镜像）。

### 2.1 代码同步

部署 = 把开发目录代码同步到 `/opt/allin-one` + 重建镜像 + 重启容器，三步都在本机完成:

```bash
# 1. 同步代码（本机内拷贝，不经 SSH）
rsync -av --delete \
    --exclude '.git' --exclude 'venv' --exclude 'data' \
    --exclude 'node_modules' --exclude '__pycache__' --exclude '.env' \
    /root/workspace/allin-one/ /opt/allin-one/

# 2. 重建镜像（allin-one / allin-worker-* / allin-mcp 共用同一镜像）
cd /opt/allin-one && docker compose -f docker-compose.home-server.yml build allin-one

# 3. 重启相关容器
docker compose -f docker-compose.home-server.yml up -d allin-one allin-worker-pipeline allin-worker-scheduled allin-mcp
```

### 2.2 手动部署（仅 MCP 变更）

只改了 MCP 相关文件（`mcp_server.py` / `app/services/*` / `app/models/*`）时，同样必须重建镜像——`allin-mcp` 不再 bind mount 代码，仅 restart 不会加载新代码:

```bash
cd /opt/allin-one && docker compose -f docker-compose.home-server.yml build allin-one
docker compose -f docker-compose.home-server.yml up -d allin-mcp
```

### 2.3 常见陷阱

| 问题 | 原因 | 解决 |
|------|------|------|
| 连接成功但新工具不显示 | 只 restart 未重建镜像，`allin-mcp` 不再 bind mount 代码 | 先 `build allin-one` 再 `up -d allin-mcp` |
| 工具注册数量不对 | 代码未同步到 `/opt/allin-one`（rsync 步骤漏做或路径写错） | 检查 `/opt/allin-one` 下文件 mtime |
| 导入报错但无日志 | FastMCP 静默跳过注册失败的工具 | 查容器启动日志 `docker compose logs allin-mcp` |
| Claude Code 看不到新工具 | 客户端缓存了 tools/list | 重启 Claude Code 或 `/mcp` 重连 |

## 阶段 3: 验证 (verify)

### 3.1 容器日志

```bash
cd /opt/allin-one && docker compose -f docker-compose.home-server.yml logs allin-mcp --tail=30
```

确认:
- 无 import error 或 traceback
- 启动时间是最新的（非旧时间戳）
- 有 `Starting MCP server 'allin-one'` 日志

### 3.2 工具列表验证

通过 MCP 协议直接查询:

```bash
# 初始化 + 获取 session
SESSION_ID=$(curl -s -D - -X POST http://192.168.1.103:8001/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' 2>/dev/null \
  | grep -i mcp-session-id | tr -d '\r' | awk '{print $2}')

# 列出所有工具
curl -s -X POST http://192.168.1.103:8001/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | grep '"name"'
```

### 3.3 验证清单

- [ ] 容器启动无报错
- [ ] 启动时间为最新（确认已重启）
- [ ] tools/list 返回预期数量的工具
- [ ] 每个新工具的 annotations 正确
- [ ] Claude Code 中可通过 ToolSearch 找到新工具

## MCP 客户端配置

### 全局配置（所有目录生效）

```bash
claude mcp add --transport http -s user allin-one http://192.168.1.103:8001/mcp
```

写入 `~/.claude.json`:
```json
{
  "mcpServers": {
    "allin-one": {
      "type": "http",
      "url": "http://192.168.1.103:8001/mcp"
    }
  }
}
```

### 项目配置（仅当前项目）

`.mcp.json`（已 gitignored）:
```json
{
  "mcpServers": {
    "allin-one": {
      "type": "http",
      "url": "http://192.168.1.103:8001/mcp"
    }
  }
}
```

**注意**: `type` 必须是 `"http"`（不是 `"streamable-http"`），这是 Claude Code 的配置格式要求。
