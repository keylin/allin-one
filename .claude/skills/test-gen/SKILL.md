---
name: test-gen
description: 自动测试生成 — 分析目标代码 → 生成 pytest/Vitest 测试 → 运行验证
argument-hint: <目标模块> (如 "source CRUD API", "pipeline executor", "Feed 页面组件")
model: sonnet
---

# 自动测试生成

为指定模块生成测试代码。当前目标: **$ARGUMENTS**

## 工作前准备

1. 确认目标模块的代码位置和类型（后端 API / Service / 前端组件）
2. 阅读相关规范:
   - 后端: `backend/CLAUDE.md`
   - 前端: `frontend/CLAUDE.md`
3. 检查现有测试目录结构:
   - 后端: `backend/tests/`
   - 前端: `frontend/src/**/__tests__/` 或 `frontend/tests/`

## 三阶段工作流

### 阶段 1: 代码分析

深入理解目标模块:

1. 读取目标代码文件，理解公开接口、参数、返回值
2. 梳理依赖关系（数据库、外部 API、其他 service）
3. 识别测试边界:
   - 需要 mock 的外部依赖（LLM API、Browserless、RSSHub）
   - 需要 fixture 的数据库实体
   - 需要特殊环境的配置项
4. 确定测试策略:

| 代码类型 | 测试工具 | 测试类型 |
|---------|---------|---------|
| FastAPI endpoint | pytest + httpx AsyncClient | API 集成测试 |
| Service/Handler | pytest | 单元测试 |
| SQLAlchemy model | pytest + test DB session | 模型测试 |
| Procrastinate task | pytest + mock | 任务测试 |
| Vue 组件 | Vitest + Vue Test Utils | 组件测试 |
| Pinia store | Vitest | Store 测试 |
| API 调用层 | Vitest + MSW | API mock 测试 |

### 阶段 2: 生成测试

#### 后端测试 (pytest)

测试文件结构:
```
backend/tests/
  conftest.py          — 共享 fixtures（db session, test client, factory）
  test_api/            — API endpoint 测试
    test_{module}.py
  test_services/       — Service 层测试
    test_{module}.py
  test_models/         — Model 测试
    test_{module}.py
  test_tasks/          — Task 测试
    test_{module}.py
```

**测试编写规范**:
- 每个测试函数: `test_{行为}_{场景}_{预期结果}`
- 使用 `@pytest.fixture` 管理测试数据
- mock 外部依赖: `@pytest.mock.patch` 或 `monkeypatch`
- 数据库测试使用事务回滚隔离
- 断言使用明确的比较，避免 `assert result`（改用 `assert result is not None`）

**conftest.py 核心 fixture**（如不存在则创建）:
```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import get_db, Base

@pytest.fixture(scope="session")
def engine():
    """使用测试数据库或 SQLite 内存库"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return engine

@pytest.fixture
def db_session(engine):
    """每个测试用事务隔离"""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()

@pytest.fixture
def client(db_session):
    """FastAPI 测试客户端"""
    def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

#### 前端测试 (Vitest)

测试文件结构:
```
frontend/src/
  components/
    __tests__/
      {Component}.test.js
  views/
    __tests__/
      {View}.test.js
  stores/
    __tests__/
      {store}.test.js
```

**测试编写规范**:
- `describe('{组件名}', () => { ... })` 分组
- `it('should {行为}', () => { ... })` 单测
- 使用 `mount` / `shallowMount` 按需选择
- API mock 使用 `vi.mock('@/api/...')`
- 测试用户交互: `await wrapper.find('button').trigger('click')`

### 阶段 3: 运行验证

```bash
# 后端测试
cd backend && python -m pytest tests/ -v --tb=short

# 前端测试
cd frontend && npx vitest run --reporter=verbose

# 单个测试文件
cd backend && python -m pytest tests/test_api/test_sources.py -v
cd frontend && npx vitest run src/components/__tests__/SourceList.test.js
```

- 所有测试必须通过
- 如果测试失败，分析原因并修复（测试代码问题 or 被测代码 bug）
- 被测代码 bug 记录在报告中，不在此 skill 中修复

## 输出格式

```
## 测试生成报告: {目标模块}

### 生成的测试文件
- `{path}` — {测试数量} 个测试用例
  - {测试名}: {测试什么}
  - ...

### 覆盖范围
- 正常路径: {N} 个用例
- 边界条件: {N} 个用例
- 异常路径: {N} 个用例
- Mock 依赖: {列出被 mock 的外部依赖}

### 运行结果
- 通过: {N}/{Total}
- 失败: {列出失败用例和原因}

### 发现的问题（如有）
- {被测代码中发现的 bug，建议 `/g-develop` 修复}

### 下一步
- 测试全部通过 → 继续 `/g-develop` 或 `/g-accept`
- 发现 bug → `/g-develop "修复 {问题描述}"`
```

## 注意事项

- **不修改被测代码**: 测试生成只产出测试文件，不修改业务代码
- **mock 粒度**: 只 mock 外部依赖（DB/API/文件系统），不 mock 被测模块的内部方法
- **测试独立性**: 每个测试用例独立运行，不依赖执行顺序
- **时间戳**: 测试中的时间用 `freezegun`（后端）或 `vi.useFakeTimers()`（前端）
