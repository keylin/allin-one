---
name: db-migrate
description: 数据库迁移管理 — 检测变更 → 生成迁移 → 安全分析 → 测试 up/down → 应用
argument-hint: [可选: 描述] (如 "添加 tags 表", "content_items 增加 priority 字段")
model: sonnet
---

# 数据库迁移管理

管理 Alembic 数据库迁移的完整生命周期。当前任务: **$ARGUMENTS**

## 工作前准备

1. 阅读 `backend/CLAUDE.md` — 后端开发规范（时间戳陷阱等）
2. 确认当前迁移状态: `cd backend && alembic current`
3. 确认迁移历史无断裂: `cd backend && alembic history --verbose -r -3:`

## 四阶段工作流

### 阶段 1: 变更检测

比对 SQLAlchemy model 定义与当前数据库 schema:

1. 读取 `backend/app/models/` 下所有 model 文件，理解当前 ORM 定义
2. 运行 `cd backend && alembic check` 检测是否有未生成的迁移
3. 如果用户描述了具体变更，确认 model 代码已修改到位
4. 如果 model 尚未修改，先完成 model 修改再继续

### 阶段 2: 生成迁移

```bash
cd backend && alembic revision --autogenerate -m "{描述}"
```

生成后立即审查迁移文件:

- `upgrade()` 是否完整覆盖所有变更
- `downgrade()` 是否能完全回滚
- 自动生成是否遗漏了索引、约束、默认值
- 手动补充 autogenerate 无法检测的变更（数据迁移、自定义类型等）

### 阶段 3: 安全分析

对生成的迁移文件进行风险评估:

#### 破坏性变更检测
- `drop_table` / `drop_column` — 数据丢失风险
- `alter_column` 类型变更 — 可能导致数据截断
- 移除 nullable=True — 现有 NULL 数据会报错
- 移除默认值 — 依赖默认值的插入会失败

#### 性能影响评估
- 大表加索引 — 是否需要 `CREATE INDEX CONCURRENTLY`
- 大表加 NOT NULL 列 — 需要默认值避免全表锁
- 外键添加 — 需要目标表索引

#### 安全建议
- 如果检测到破坏性变更，输出警告并建议分步迁移策略
- 如果涉及大表，建议在低峰期执行

### 阶段 4: 本地测试

```bash
# 升级测试
cd backend && alembic upgrade head

# 降级测试（回退到上一版本）
cd backend && alembic downgrade -1

# 再次升级确认幂等性
cd backend && alembic upgrade head
```

测试通过后输出报告。如果失败，分析错误原因并修复迁移文件。

## 输出格式

```
## 迁移报告: {描述}

### 迁移文件
- `backend/alembic/versions/{revision}_{slug}.py`

### 变更内容
- {表/列/索引变更列表}

### 安全分析
- 破坏性变更: 无 / {列出具体风险}
- 性能影响: 无 / {评估}
- 建议: {如有}

### 测试结果
- upgrade: pass/fail
- downgrade: pass/fail
- re-upgrade: pass/fail

### 下一步
- 继续开发 → 回到 `/g-develop`
- 部署上线 → `/g-ship` 会自动识别新增 migration 文件
```

## 关键文件

- `backend/alembic/` — 迁移目录
- `backend/alembic/env.py` — 迁移环境配置
- `backend/alembic.ini` — Alembic 配置
- `backend/app/models/` — ORM model 定义
- `backend/app/models/__init__.py` — 必须导入所有 model

## 注意事项

- **model 导入**: `backend/app/models/__init__.py` 必须导入所有 model，否则 autogenerate 检测不到
- **时间戳**: 新增时间字段必须用 `server_default=func.now()`，Python 层用 `utcnow()`
- **UUID 主键**: 使用 `Column(UUID, primary_key=True, default=uuid.uuid4)`
- **JSONB**: JSON 字段统一用 `Column(JSONB)`，不用 `Column(JSON)` 或 `Column(Text)`
- **CASCADE**: 外键务必指定 `ondelete="CASCADE"` 或 `"SET NULL"`
