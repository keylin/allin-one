---
name: bug-report
description: Bug 诊断报告 — 现象收集 → 日志分析 → 代码溯源 → 专家评审，产出可驱动 g-* 流水线的结论
argument-hint: <问题描述> (如 "worker 反复重启", "内容列表空白", "采集任务卡住")
model: opus
---

# Bug 诊断报告

对 **$ARGUMENTS** 进行问题诊断与专家评审，产出 Bug 报告。

**定位**: 只诊断不修代码。产出结论驱动 g-* 流水线（/g-develop、/g-design 等）。

## 四阶段工作流

### 阶段 1: 现象收集

- 理解问题描述（错误信息、异常行为、复现步骤）
- 确认影响范围（哪些功能受影响、是否影响生产环境）
- 明确紧急程度

### 阶段 2: 日志分析

**重要**: 日志脚本默认带 `-f` 实时跟踪和交互菜单，**必须**用非交互模式:
- 始终传具体子命令（不要裸调 `./logs-local.sh`）
- 始终加 `--no-follow` 避免挂起
- 用 `--grep PATTERN` 过滤关键词，用 `-n NUM` 控制行数

#### 本地日志

文件日志（直接用 Read 工具读取更快）:
- `data/logs/backend.log` — 后端应用日志
- `data/logs/worker.log` — Worker 任务日志
- `data/logs/error.log` — 错误日志

容器日志命令:
```bash
# 错误汇总（推荐首先执行）
./logs-local.sh error --no-follow

# 查看特定服务日志
./logs-local.sh app --no-follow -n 200
./logs-local.sh worker --no-follow -n 200
./logs-local.sh pipeline --no-follow -n 200
./logs-local.sh scheduled --no-follow -n 200

# 按关键词过滤
./logs-local.sh worker --no-follow --grep "error" -n 500

# 按时间过滤
./logs-local.sh app --no-follow --since "30m"
./logs-local.sh app --no-follow --since "1h"
```

#### 远程日志

远程服务器: `allin@192.168.1.103:2222`，项目目录: `~/allin-one`

```bash
# 错误汇总（推荐首先执行）
./logs-remote.sh error --no-follow

# 查看远程容器日志
./logs-remote.sh app --no-follow -n 200
./logs-remote.sh worker --no-follow -n 200
./logs-remote.sh pipeline --no-follow -n 200
./logs-remote.sh scheduled --no-follow -n 200

# 查看远程文件日志
./logs-remote.sh file backend --no-follow -n 200
./logs-remote.sh file worker --no-follow -n 200
./logs-remote.sh file error --no-follow -n 200

# 按关键词过滤
./logs-remote.sh worker --no-follow --grep "traceback" -n 500

# 直接 SSH 执行命令
ssh -T -p 2222 allin@192.168.1.103 "cd ~/allin-one && docker compose -f docker-compose.remote.yml ps"
ssh -T -p 2222 allin@192.168.1.103 "cd ~/allin-one && docker compose -f docker-compose.remote.yml logs --tail 100 allin-one"
```

容器名映射: `allin-one`(app), `allin-worker-pipeline`, `allin-worker-scheduled`, `allin-rsshub`, `allin-browserless`, `allin-postgres`

#### 分析要点
- 按时间线还原错误发生过程
- 识别错误堆栈中的关键帧
- 区分直接原因和根本原因
- 注意关联错误（一个问题可能触发多个错误日志）

### 阶段 3: 代码溯源

- 根据日志中的错误堆栈和关键字，定位到具体代码文件和行号
- 理解代码上下文和调用链路
- 分析根因（逻辑错误、边界条件、并发问题、配置错误等）
- 形成初步诊断和修复方向

### 阶段 4: 专家评审

**并行**启动两个 Agent（使用 Agent tool）:

1. **product-designer**:
   - 这是真实 bug 还是用户误用/预期行为？
   - 是否需要补充信息才能判断？
   - 产品逻辑本身是否需要调整？

2. **architect-designer**:
   - 初步修复方向是否合理？
   - 影响范围有多大？涉及哪些模块？
   - 是否存在架构层面的隐患？

综合两方意见，形成最终结论。

## 输出格式

```markdown
## Bug 报告: {问题简述}

### 现象
{问题表现，含复现步骤}

### 根因分析
{根本原因，附代码位置 file:line}

### 专家评审
- **产品评审**: {product-designer 的判断}
- **架构评审**: {architect-designer 的判断}

### 结论
{以下四种之一，含具体理由}

A. **非 Bug** — 用户误用或预期行为，附正确用法说明
B. **信息不足** — 列出需要补充的具体信息
C. **确认 Bug（简单修复）** — 明确根因和修复方向
D. **确认 Bug（需方案设计）** — 问题涉及架构调整或多模块改动

### 建议的下一步
{明确的行动指引}
- 结论 A → 给出正确用法
- 结论 B → 列出需补充的信息
- 结论 C → `/g-develop "修复 XX"`  → `/g-accept`
- 结论 D → `/g-design "重新设计 XX"` → `/g-develop` → `/g-accept`
```

## 常见问题模式速查

### 后端
- **时间戳问题**: 是否使用了 `utcnow()` 而非 `datetime.now(timezone.utc)`
- **ORM 模型未注册**: `models/__init__.py` 是否导入了所有模型
- **JSONB 查询失败**: 是否用了 `cast(column, JSONB)` 而非 `type_coerce`
- **异步阻塞**: async handler 中是否有同步阻塞调用
- **Worker 任务失败**: Procrastinate 任务参数和队列配置

### 前端
- **API 请求失败**: 路径、参数、响应格式是否与后端一致
- **响应式数据不更新**: ref/reactive 使用是否正确
- **组件渲染异常**: props/emits 定义与使用是否匹配

### 部署/环境
- **容器启动失败**: Dockerfile、docker-compose 配置、环境变量
- **数据库连接失败**: 连接字符串、网络配置、PG 容器状态
- **文件描述符耗尽**: "Too many open files" 错误，调整 ulimit 配置

## 工作原则

- **只诊断不修复**: 产出报告和结论，代码修改交给 g-* 流水线
- **治本不治标**: 找到根本原因，不做表面判断
- **证据驱动**: 每个结论基于日志和代码证据，不靠猜测
- **专家共识**: 结论需综合产品和架构两方视角
