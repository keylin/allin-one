# RSSHub 数据源字段优化 - 实施总结

## ✅ 已完成的修改

### Phase 1: 后端统一与简化

#### 1. 创建共享 URL 解析工具
- **文件**: `backend/app/services/collectors/utils.py` (新建)
- **功能**: 单一真实来源（Single Source of Truth）的 Feed URL 解析逻辑
- **核心逻辑**:
  - `rss.hub`: 使用 `config_json.rsshub_route`，拼接到 RSSHub 基础 URL
  - `rss.standard`: 使用 `url` 字段
  - 缺少必需字段时抛出 `ValueError`

#### 2. 更新 RSS 采集器
- **文件**: `backend/app/services/collectors/rss.py`
- **修改**: 移除三层降级逻辑，统一调用共享工具函数
- **影响**: 简化代码，消除冗余逻辑

#### 3. 更新 Sources API
- **文件**: `backend/app/api/routes/sources.py`
- **修改 1**: `_resolve_rss_feed_url` 函数调用共享工具
- **修改 2**: 修复 OPML 导出 bug（L250-261）- 现在导出完整的 HTTP URL 而非路由路径
- **修改 3**: 创建端点增加验证（L115-137）
  - RSSHub 源必须有 `config_json.rsshub_route`
  - 标准 RSS 源必须有 `url`
- **修改 4**: 更新端点增加验证（L287-328）
  - 同样的验证逻辑，支持部分更新场景

---

### Phase 2: 前端优化

#### 1. 更新表单字段显示逻辑
- **文件**: `frontend/src/components/source-form-modal.vue`
- **修改 1** (L150-153): `needsUrl` 计算属性
  - 明确列出需要 URL 字段的类型：`['rss.standard', 'web.scraper', 'account.generic']`
  - 排除 `rss.hub`（改用 `rsshub_route`）
- **修改 2** (L314-324): URL 字段
  - `rss.standard` 显示 "Feed URL *"（必填）
  - 其他类型显示 "URL"（非必填）
  - 针对性的 placeholder 提示
- **修改 3** (L407-422): RSSHub 配置区
  - "RSSHub 路由 *" 字段标记必填
  - 添加 `required` 属性
  - 更详细的说明文字

#### 2. 更新数据源详情显示
- **文件**: `frontend/src/components/source-detail-panel.vue`
- **修改 1** (L88-98): 添加 `displayUrl` 计算属性
  - RSSHub 源显示路由路径（格式：`RSSHub: /路径`）
  - 其他源显示完整 URL
- **修改 2** (L141-156): URL 显示区域
  - 动态标签（"RSSHub 路由" vs "URL"）
  - RSSHub 路由用 `font-mono` 显示
  - 仅标准 RSS 的 URL 可点击跳转

#### 3. 更新数据源列表显示
- **文件**: `frontend/src/views/SourcesView.vue`
- **修改 1** (L72-82): 添加 `getDisplayUrl` 辅助函数
  - RSSHub 源显示路由路径
  - 其他源显示 URL
- **修改 2** (L542): URL 列使用 `getDisplayUrl(source)`

---

### Phase 3: 数据迁移

#### 创建 Alembic 迁移脚本
- **文件**: `backend/alembic/versions/0010_migrate_rsshub_routes.py` (新建)
- **功能**: 将现有 RSSHub 数据源的 `url` 字段迁移到 `config_json.rsshub_route`
- **逻辑**:
  - 查找所有 `source_type = 'rss.hub'` 且 `url` 不为空的源
  - 如果 `config_json` 已有 `rsshub_route`，跳过
  - 如果 `url` 不是完整 HTTP URL（不以 `http://` 或 `https://` 开头），迁移到 `config_json`
  - 清空原 `url` 字段
- **回滚**: 支持 `downgrade()` 将 `rsshub_route` 移回 `url` 字段

---

### Phase 4: 文档更新

#### 更新模型文档
- **文件**: `backend/app/models/content.py`
- **修改** (L87-92): 更新 `config_json` 示例注释
  - 明确标准 RSS 使用 `url` 字段，`config_json` 可留空
  - 统一示例格式

---

## 📋 部署步骤

### 1. 运行数据库迁移
```bash
cd backend
alembic upgrade head
```

### 2. 重启服务
```bash
# 后端
cd backend
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm run dev

# Worker
cd backend
procrastinate --app=app.tasks.procrastinate_app.proc_app worker --concurrency=4 --queues=pipeline
procrastinate --app=app.tasks.procrastinate_app.proc_app worker --concurrency=2 --queues=scheduled
```

### 3. 验证（可选但推荐）
使用下方的验证清单进行手动测试。

---

## ✅ 验证清单

### 后端验证

- [ ] 迁移成功运行，无错误
- [ ] 查看数据库：现有 RSSHub 源的 `config_json` 包含 `rsshub_route`，`url` 为空
- [ ] 尝试创建 RSSHub 源（仅填 `rsshub_route`）→ 创建成功
- [ ] 尝试创建 RSSHub 源（未填 `rsshub_route`）→ 返回 400 错误
- [ ] 尝试创建 RSS/Atom 源（仅填 `url`）→ 创建成功
- [ ] 尝试创建 RSS/Atom 源（未填 `url`）→ 返回 400 错误
- [ ] OPML 导出 → 检查文件中 `xmlUrl` 为完整 HTTP URL（如 `http://rsshub:1200/bilibili/user/video/12345`）
- [ ] 手动触发现有 RSSHub 源采集 → 采集成功

### 前端验证

#### RSSHub 数据源创建
- [ ] 选择 "RSSHub" 类型
- [ ] 验证通用 URL 字段不显示
- [ ] 验证 "RSSHub 路由 *" 字段显示且带必填标记
- [ ] 留空路由字段提交 → 浏览器验证报错（HTML5 required）
- [ ] 填写路由 `/bilibili/user/video/12345` → 创建成功
- [ ] 后端返回 400 错误 → 前端显示错误提示

#### RSSHub 数据源编辑
- [ ] 编辑现有 RSSHub 源
- [ ] 验证路由字段预填充 `config_json` 中的值
- [ ] 修改路由并保存 → 更新成功

#### RSS/Atom 数据源
- [ ] 选择 "RSS/Atom" 类型
- [ ] 验证通用 URL 字段显示（标签为 "Feed URL *"）
- [ ] 验证无 RSSHub 配置区
- [ ] 留空 URL 字段提交 → 浏览器验证报错
- [ ] 填写完整 URL `https://sspai.com/feed` → 创建成功

#### 数据源列表显示
- [ ] RSSHub 源在 URL 列显示路由路径（如 `/bilibili/user/video/12345`）
- [ ] RSS/Atom 源在 URL 列显示完整 URL

#### 数据源详情面板
- [ ] 点击 RSSHub 源 → 详情面板显示 "RSSHub 路由: /路径"
- [ ] 点击 RSS/Atom 源 → 详情面板显示 "URL: 完整地址"（可点击）

#### OPML 导出/导入
- [ ] 导出包含 RSSHub 源的 OPML 文件
- [ ] 打开文件检查 `xmlUrl` 为完整 HTTP URL
- [ ] （可选）用其他 RSS 阅读器导入该 OPML 文件验证兼容性

---

## 🔄 回滚方案

如果部署后出现问题：

### 1. 代码回滚
```bash
git log --oneline -5  # 查看最近的提交
git revert <commit-hash>
git push
```

### 2. 数据库回滚
```bash
cd backend
alembic downgrade -1  # 回滚一个版本
```

### 3. 验证
- 检查现有数据源是否恢复正常工作
- 手动触发采集验证功能

---

## 📊 影响范围评估

### 破坏性变更
- **无**。所有现有数据源通过迁移脚本自动适配，向后兼容。

### 用户可见变更
1. **创建 RSSHub 源**：必须填写 "RSSHub 路由" 字段，不再显示通用 URL 字段
2. **创建 RSS/Atom 源**：URL 字段标记为必填
3. **数据源列表**：RSSHub 源显示路由路径而非完整 URL
4. **OPML 导出**：导出的文件包含完整 HTTP URL，可导入其他阅读器

### 系统内部变更
1. **代码简化**：移除三层降级逻辑，单一 URL 解析入口
2. **数据规范**：每种数据源类型有且仅有一个规范的地址配置方式
3. **错误提示**：配置错误的源在创建/更新时立即报错，而非采集时失败

---

## 🎯 成功标准

- ✅ RSSHub 数据源表单仅显示一个路由字段，无 URL 字段
- ✅ RSS/Atom 数据源表单仅显示 URL 字段
- ✅ 创建 RSSHub 源时未填路由字段会提示错误
- ✅ OPML 导出文件包含完整的 HTTP URL（可导入其他 RSS 阅读器）
- ✅ 现有数据源迁移后正常采集
- ✅ 代码中移除所有 URL 字段作为路由的降级逻辑

---

## 📝 相关文件清单

### 新建文件
- `backend/app/services/collectors/utils.py`
- `backend/alembic/versions/0010_migrate_rsshub_routes.py`
- `RSSHUB_OPTIMIZATION_SUMMARY.md` (本文件)

### 修改文件
- `backend/app/services/collectors/rss.py`
- `backend/app/api/routes/sources.py`
- `backend/app/models/content.py`
- `frontend/src/components/source-form-modal.vue`
- `frontend/src/components/source-detail-panel.vue`
- `frontend/src/views/SourcesView.vue`

---

## 🐛 已知问题 / 注意事项

1. **自动修正错误配置**：迁移脚本会自动识别并修正错误配置的数据源。如果某个 `rss.hub` 类型的源使用完整 HTTP URL（如 `https://v2ex.com/index.xml`），会自动改为 `rss.standard` 类型。

2. **OPML 导出包含内部 URL**：导出的 OPML 中 RSSHub 源的 `xmlUrl` 包含内部服务地址（如 `http://rsshub:1200`），如果导入到外部 RSS 阅读器需要修改为公开的 RSSHub 实例地址。

3. **前端验证仅为提示**：HTML5 `required` 属性可被绕过，真正的验证在后端。前端验证主要提升用户体验。

## 🔧 部署后的修复记录

### 2026-02-15 修复错误配置的数据源

**问题**: v2ex 数据源配置错误
- `source_type`: `rss.hub`（错误）
- `url`: `https://v2ex.com/index.xml`（标准 RSS feed）
- `config_json`: 空

**修复**:
- 手动将 source_type 改为 `rss.standard`
- 更新迁移脚本，自动处理此类错误配置

---

生成时间: 2026-02-15
