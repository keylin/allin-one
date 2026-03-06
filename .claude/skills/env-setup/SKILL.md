---
name: env-setup
description: 环境配置管理 — 扫描代码依赖 → 生成 .env 模板 → 校验完整性 → 安全检查
argument-hint: [可选: scan|validate|template] (默认 validate 校验当前配置)
model: sonnet
---

# 环境配置管理

扫描、校验和管理环境变量配置。当前操作: **$ARGUMENTS**（默认 validate）

## 操作模式

| 模式 | 关键词 | 功能 |
|------|-------|------|
| scan | `scan` | 扫描代码中所有环境变量依赖，生成完整清单 |
| validate | `validate` | 校验当前 `.env` 是否完整，标记缺失项 |
| template | `template` | 生成/更新 `.env.example` 模板文件 |

## 工作流

### 阶段 1: 环境变量扫描

扫描代码中所有环境变量引用:

```bash
# Python: os.getenv / os.environ / Settings 字段
cd /Users/lin/workspace/allin-one/backend
grep -rn "os\.getenv\|os\.environ\|env=" app/ --include="*.py" | grep -v __pycache__ | grep -v ".pyc"

# Settings 类定义（Pydantic BaseSettings）
grep -rn "class Settings" app/ --include="*.py" -A 50

# Docker Compose 环境变量
grep -n "environment:" ../docker-compose*.yml -A 20
grep -n '\${' ../docker-compose*.yml

# 前端环境变量
cd /Users/lin/workspace/allin-one/frontend
grep -rn "import\.meta\.env\|VITE_" src/ --include="*.ts" --include="*.js" --include="*.vue"
```

整理为结构化清单:

| 变量名 | 来源文件 | 必填 | 默认值 | 类型 | 说明 |
|--------|---------|------|-------|------|------|
| DATABASE_URL | database.py | 是 | — | string | PG 连接字符串 |
| ... | ... | ... | ... | ... | ... |

### 阶段 2: 配置校验

读取当前 `.env` 文件并比对扫描结果:

```bash
# 读取现有 .env
cat /Users/lin/workspace/allin-one/.env 2>/dev/null || echo "No .env found"
cat /Users/lin/workspace/allin-one/backend/.env 2>/dev/null || echo "No backend/.env found"
```

校验规则:
- **必填项缺失** → 标记为错误
- **有默认值但未配置** → 标记为警告（使用默认值）
- **配置了但代码中未引用** → 标记为可能废弃
- **Secret 类型变量** → 检查是否为空或占位符

### 阶段 3: 安全检查

对 Secret 类型变量进行安全审查:

```
Secret 关键词: api_key, token, password, secret, credential, encryption_key
```

检查项:
- **明文存储**: `.env` 中的 secret 是否为真实值（非占位符）— 提醒不要提交到 git
- **加密存储**: `CREDENTIAL_ENCRYPTION_KEY` 是否已配置（影响凭证加密功能）
- **LLM API Key**: 是否走 `system_settings` 加密存储而非环境变量
- **`.gitignore`**: `.env` 是否在 `.gitignore` 中

### 阶段 4: 输出 / 更新

根据操作模式输出:

#### scan 模式 → 输出完整变量清单

#### validate 模式 → 输出校验报告

```
## 环境配置校验报告

### 校验结果: 完整 / 有缺失 / 有风险

### 必填项
| 变量 | 状态 | 当前值 |
|------|------|-------|
| DATABASE_URL | 已配置 | postgresql://... |
| CREDENTIAL_ENCRYPTION_KEY | 缺失 | — |

### 可选项（使用默认值）
| 变量 | 默认值 |
|------|-------|
| DB_POOL_SIZE | 10 |

### 安全检查
- .gitignore 包含 .env: 是/否
- Secret 变量加密状态: {状态}

### 建议
- {缺失变量}: 请在 .env 中添加
- {安全风险}: 请检查...
```

#### template 模式 → 生成 `.env.example`

生成包含所有变量的模板文件（Secret 值用占位符）:

```env
# Database
DATABASE_URL=postgresql://allinone:password@localhost:5432/allinone
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=5

# Security
CREDENTIAL_ENCRYPTION_KEY=  # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# LLM (configured via system_settings UI, not env vars)
# OPENAI_API_KEY is stored encrypted in database

# ...
```

## 与其他 Skill 联动

- `/g-develop` 新增环境变量时 → 建议运行 `/env-setup validate` 确认配置
- `/g-ship` 部署前 → 建议运行 `/env-setup validate` 确认远程配置完整
- 新部署环境 → `/env-setup template` 生成配置模板

## 关键文件

- `backend/app/core/config.py` — Settings 类定义
- `backend/app/core/crypto.py` — 加密配置
- `backend/app/database.py` — 数据库连接配置
- `docker-compose.local.yml` — 本地环境配置
- `docker-compose.remote.yml` — 远程环境配置
- `.env` / `backend/.env` — 环境变量文件
- `.gitignore` — 确认 .env 被忽略
