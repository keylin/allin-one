# 技术方案: EPUB/MOBI 电子书阅读器

> 版本: v1.0 | 日期: 2026-02-21

---

## 1. 背景与目标

在 Allin-One 信息聚合平台中增加电子书阅读功能，支持 EPUB 和 MOBI 格式。用户可上传电子书文件，在浏览器内阅读，并保存阅读进度、高亮批注和书签。

### 核心原则

- **复用现有体系**: 电子书是 ContentItem 的一种，通过 `file.upload` Source 上传，通过 MediaItem 管理文件
- **前端渲染**: 使用 foliate-js 在浏览器端直接渲染 EPUB/MOBI，后端只做文件存储和元数据解析
- **渐进实现**: Phase 1 聚焦核心阅读体验，后续再加批注/LLM 集成

---

## 2. 数据模型

### 2.1 现有模型复用

电子书融入现有 ContentItem + MediaItem 体系，不引入新的顶层实体：

```
ContentItem (电子书)
  ├── title = 书名
  ├── author = 作者
  ├── raw_data = {"format":"epub", "metadata":{...}, "toc":[...]}
  ├── source_id → file.upload 类型的 SourceConfig
  └── media_items[]
       └── MediaItem (media_type="ebook")
            ├── local_path = data/media/{content_id}/book.epub
            ├── status = downloaded
            └── metadata_json = {"format":"epub", "cover_path":"...", "file_size":12345, "language":"zh", "publisher":"..."}
```

### 2.2 MediaType 扩展

```python
# app/models/content.py
class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    EBOOK = "ebook"    # 新增: 覆盖 epub/mobi/azw3 等电子书格式
```

### 2.3 新增表: reading_progress (阅读进度)

```sql
CREATE TABLE reading_progress (
    id              TEXT PRIMARY KEY,           -- UUID
    content_id      TEXT NOT NULL,              -- FK → content_items
    -- 定位
    cfi             TEXT,                       -- EPUB CFI (Canonical Fragment Identifier)
    progress        FLOAT DEFAULT 0,           -- 阅读百分比 0.0~1.0
    section_index   INTEGER DEFAULT 0,          -- 当前章节序号
    section_title   TEXT,                       -- 当前章节标题 (冗余, 方便展示)
    -- 时间
    updated_at      TIMESTAMP DEFAULT NOW(),
    created_at      TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (content_id) REFERENCES content_items(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_reading_progress_content ON reading_progress(content_id);
```

**设计说明**: 个人项目单用户，content_id 即唯一键，无需 user_id。CFI 是 EPUB 标准的精确位置标识符，foliate-js 原生支持。

### 2.4 新增表: book_annotations (批注/高亮) — Phase 2

```sql
CREATE TABLE book_annotations (
    id              TEXT PRIMARY KEY,           -- UUID
    content_id      TEXT NOT NULL,              -- FK → content_items
    -- 定位
    cfi_range       TEXT NOT NULL,              -- CFI 范围 (起止位置)
    section_index   INTEGER,                    -- 所在章节序号
    -- 内容
    type            TEXT DEFAULT 'highlight',   -- highlight / note
    color           TEXT DEFAULT 'yellow',      -- yellow / green / blue / pink / purple
    selected_text   TEXT,                       -- 选中的原文
    note            TEXT,                       -- 用户批注
    -- 时间
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (content_id) REFERENCES content_items(id) ON DELETE CASCADE
);

CREATE INDEX ix_annotation_content ON book_annotations(content_id);
```

### 2.5 新增表: book_bookmarks (书签) — Phase 2

```sql
CREATE TABLE book_bookmarks (
    id              TEXT PRIMARY KEY,           -- UUID
    content_id      TEXT NOT NULL,              -- FK → content_items
    cfi             TEXT NOT NULL,              -- CFI 位置
    title           TEXT,                       -- 书签标题 (用户可编辑)
    section_title   TEXT,                       -- 所在章节标题
    created_at      TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (content_id) REFERENCES content_items(id) ON DELETE CASCADE
);

CREATE INDEX ix_bookmark_content ON book_bookmarks(content_id);
```

### 2.6 ER 关系图 (电子书部分)

```
content_items 1───1 reading_progress
              1───∞ book_annotations     (Phase 2)
              1───∞ book_bookmarks       (Phase 2)
              1───∞ media_items (media_type='ebook')
```

---

## 3. API 设计

### 3.1 电子书管理

```
POST   /api/ebook/upload                  → 上传电子书文件
GET    /api/ebook/list                    → 书架列表（分页、搜索、排序）
GET    /api/ebook/{content_id}            → 电子书详情（元数据 + 阅读进度）
DELETE /api/ebook/{content_id}            → 删除电子书（文件 + 记录）
GET    /api/ebook/{content_id}/file       → 下载/流式传输原始文件（供 foliate-js 加载）
GET    /api/ebook/{content_id}/cover      → 封面图
```

### 3.2 阅读进度

```
GET    /api/ebook/{content_id}/progress   → 获取阅读进度
PUT    /api/ebook/{content_id}/progress   → 更新阅读进度
```

### 3.3 批注与书签 (Phase 2)

```
GET    /api/ebook/{content_id}/annotations        → 获取全部批注
POST   /api/ebook/{content_id}/annotations        → 新增批注
PUT    /api/ebook/{content_id}/annotations/{id}   → 修改批注
DELETE /api/ebook/{content_id}/annotations/{id}   → 删除批注
GET    /api/ebook/{content_id}/bookmarks          → 获取全部书签
POST   /api/ebook/{content_id}/bookmarks          → 新增书签
DELETE /api/ebook/{content_id}/bookmarks/{id}     → 删除书签
```

### 3.4 请求/响应 Schema

```python
# app/schemas/ebook.py

class EbookUploadResponse(BaseModel):
    content_id: str
    title: str
    author: str | None
    format: str          # epub / mobi
    cover_url: str | None

class EbookListItem(BaseModel):
    content_id: str
    title: str
    author: str | None
    format: str
    cover_url: str | None
    file_size: int | None
    progress: float      # 0.0~1.0
    section_title: str | None   # 当前阅读章节
    last_read_at: str | None    # ISO datetime
    created_at: str

class ReadingProgressUpdate(BaseModel):
    cfi: str | None = None
    progress: float          # 0.0~1.0
    section_index: int | None = None
    section_title: str | None = None

class ReadingProgressResponse(BaseModel):
    cfi: str | None
    progress: float
    section_index: int
    section_title: str | None
    updated_at: str | None

# Phase 2
class AnnotationCreate(BaseModel):
    cfi_range: str
    section_index: int | None = None
    type: str = "highlight"      # highlight / note
    color: str = "yellow"
    selected_text: str | None = None
    note: str | None = None

class BookmarkCreate(BaseModel):
    cfi: str
    title: str | None = None
    section_title: str | None = None
```

---

## 4. 关键流程

### 4.1 上传流程

```
用户选择 .epub/.mobi 文件 → POST /api/ebook/upload (multipart/form-data)
    │
    ▼
后端接收文件
    ├── 校验扩展名 (.epub / .mobi)
    ├── 生成 content_id (UUID)
    ├── 保存文件到 data/media/{content_id}/book.{ext}
    ├── 解析元数据 (ebooklib for epub, mobi lib for mobi):
    │     title, author, language, publisher, cover image
    ├── 提取封面图 → data/media/{content_id}/cover.jpg
    ├── 提取目录 (TOC) → JSON
    ├── 创建 ContentItem (title=书名, author=作者, raw_data=metadata+toc JSON)
    ├── 创建 MediaItem (media_type="ebook", local_path=..., status="downloaded", metadata_json=...)
    └── 返回 EbookUploadResponse
```

### 4.2 阅读流程

```
用户打开书架 → GET /api/ebook/list
    │
    ▼
用户点击书籍 → 前端路由跳转到 /ebook/{content_id}
    │
    ├── GET /api/ebook/{content_id}          → 获取元数据
    ├── GET /api/ebook/{content_id}/progress → 获取上次阅读位置
    ├── GET /api/ebook/{content_id}/file     → 加载原始文件 (Blob)
    │
    ▼
foliate-js 初始化阅读器
    ├── 解析 EPUB/MOBI 文件 (浏览器端)
    ├── 渲染到 iframe (CSS multi-column 分页)
    ├── 恢复到上次 CFI 位置
    │
    ▼
阅读中
    ├── 翻页/滚动 → 前端节流 debounce 5s → PUT /api/ebook/{content_id}/progress
    ├── 点击目录项 → foliate-js 跳转
    ├── 调整字体/主题 → 前端 localStorage + rendition.themes
    └── 关闭/离开 → 立即保存进度
```

### 4.3 文件传输

电子书文件通过 `/api/ebook/{content_id}/file` 以完整 `FileResponse` 返回（非 Range streaming）。
原因: foliate-js 需要完整的 Blob/ArrayBuffer 来解析 zip (EPUB) 或 binary (MOBI) 结构，
不支持流式加载。文件通常 1-50MB，一次性传输可接受。

---

## 5. 前端设计

### 5.1 新增文件

```
frontend/src/
├── api/ebook.js                      # API 封装
├── views/EbookView.vue               # 书架页面 (书籍网格 + 上传)
├── components/ebook-reader.vue       # 阅读器全屏组件 (foliate-js)
├── components/ebook-upload-modal.vue # 上传弹窗
└── composables/useEbookReader.js     # 阅读器逻辑封装 (可选)
```

### 5.2 书架页面 (EbookView.vue)

- 封面网格展示（响应式: mobile 2列, tablet 3列, desktop 4-5列）
- 每本书显示: 封面、书名、作者、阅读进度条、最近阅读时间
- 搜索框（按标题/作者过滤）
- 排序: 最近阅读 / 上传时间 / 书名
- 右上角"上传"按钮 → 弹出上传 Modal
- 长按/右键菜单: 删除

### 5.3 阅读器组件 (ebook-reader.vue)

- **全屏模式**: 覆盖整个视口，隐藏导航栏
- **核心交互**:
  - 点击左/右 1/3 区域翻页（或键盘左右方向键）
  - 移动端滑动翻页 (touch swipe)
  - 点击中央区域显示/隐藏工具栏
- **工具栏** (顶部):
  - 返回按钮、书名
  - 目录侧边栏 toggle
  - 设置齿轮 (字体、主题)
- **底部信息栏**:
  - 章节名、页码/百分比
  - 进度滑块 (拖拽快速跳转)
- **设置面板** (底部 sheet):
  - 字号 (14-24px 滑块)
  - 行高 (1.4-2.0)
  - 字体族 (系统默认 / 衬线 / 无衬线)
  - 主题 (亮色 / 暖色 / 暗色)
  - 分页/滚动模式切换
- **进度保存**: visibilitychange + beforeunload + 5s 节流

### 5.4 foliate-js 集成方式

```javascript
// 核心集成代码结构 (简化)
import { makeBook } from 'foliate-js/book.js'
import { View } from 'foliate-js/view.js'

// 1. 从后端获取文件 Blob
const res = await fetch(`/api/ebook/${contentId}/file`)
const blob = await res.blob()

// 2. 创建 book 对象
const book = await makeBook(blob, blob.type)

// 3. 创建 view 并挂载到 DOM
const view = new View({ book })
document.getElementById('reader-container').append(view)

// 4. 恢复阅读位置
const progress = await fetchProgress(contentId)
if (progress?.cfi) {
  view.goTo(progress.cfi)
}

// 5. 监听位置变化
view.addEventListener('relocate', (e) => {
  debouncedSaveProgress({
    cfi: e.detail.cfi,
    progress: e.detail.fraction,
    section_index: e.detail.sectionIndex,
    section_title: e.detail.sectionTitle,
  })
})
```

foliate-js 作为 git submodule 或将所需模块复制到 `frontend/src/lib/foliate-js/`，锁定版本避免 API 变更。

### 5.5 路由

```javascript
// router/index.js 新增
{ path: '/ebooks', component: () => import('@/views/EbookView.vue') },
```

侧边导航栏新增"书架"入口。

---

## 6. 后端实现

### 6.1 依赖新增

```
# requirements.txt 新增
ebooklib>=0.18           # EPUB 解析 (元数据、目录、封面提取)
mobi>=0.3.3              # MOBI → EPUB 解包 (KindleUnpack pip 封装)
```

### 6.2 新增文件

```
backend/app/
├── api/routes/ebook.py          # 电子书 API 路由
├── schemas/ebook.py             # Pydantic schema
├── models/ebook.py              # ORM: ReadingProgress, BookAnnotation, BookBookmark
└── services/ebook_parser.py     # 元数据解析服务 (ebooklib + mobi)
```

### 6.3 元数据解析服务

```python
# app/services/ebook_parser.py

class EbookMetadata:
    title: str
    author: str | None
    language: str | None
    publisher: str | None
    description: str | None
    cover_data: bytes | None     # 封面图二进制
    cover_ext: str | None        # jpg / png
    toc: list[dict]              # [{"title": "Chapter 1", "href": "..."}, ...]

def parse_epub(file_path: str) -> EbookMetadata:
    """使用 ebooklib 解析 EPUB 元数据"""

def parse_mobi(file_path: str) -> EbookMetadata:
    """使用 mobi 库解包 MOBI，提取元数据"""
    # mobi.extract() → tempdir 包含解包后的 EPUB/HTML
    # 如果解包出 EPUB → 用 parse_epub 处理
    # 否则从 HTML 中提取基本信息

def parse_ebook(file_path: str) -> EbookMetadata:
    """根据扩展名分发到对应解析器"""
    ext = Path(file_path).suffix.lower()
    if ext == '.epub':
        return parse_epub(file_path)
    elif ext in ('.mobi', '.azw', '.azw3'):
        return parse_mobi(file_path)
    else:
        raise ValueError(f"Unsupported format: {ext}")
```

### 6.4 文件存储结构

```
data/media/{content_id}/
├── book.epub          # 或 book.mobi — 原始文件
└── cover.jpg          # 提取的封面图
```

与视频存储模式一致: `MEDIA_DIR/{content_id}/`。

---

## 7. 对现有模块的影响

| 文件 | 改动 | 说明 |
|------|------|------|
| `backend/app/models/content.py` | 修改 | MediaType 新增 `EBOOK = "ebook"` |
| `backend/app/models/__init__.py` | 修改 | 导入新模型 |
| `backend/app/main.py` | 修改 | 注册 ebook router |
| `backend/requirements.txt` | 修改 | 新增 ebooklib, mobi |
| `frontend/src/router/index.js` | 修改 | 新增 /ebooks 路由 |
| `frontend/src/App.vue` | 修改 | 侧边栏新增"书架"入口 |
| `frontend/package.json` | 修改 | 如使用 npm 包方式引入 foliate-js |
| `docs/system_design.md` | 修改 | 新增 ebook 相关表和 API 文档 |
| `docs/business_glossary.md` | 修改 | MediaType 新增 ebook |

**影响范围**: 新增功能为主，对现有代码的修改仅限于枚举扩展和路由注册，不影响现有功能。

---

## 8. 数据迁移

新增一个 Alembic 迁移文件:

```python
# alembic/versions/xxxx_add_ebook_tables.py

def upgrade():
    # 1. reading_progress 表
    op.create_table('reading_progress', ...)

    # 2. book_annotations 表 (Phase 2, 可先建表)
    op.create_table('book_annotations', ...)

    # 3. book_bookmarks 表 (Phase 2, 可先建表)
    op.create_table('book_bookmarks', ...)

def downgrade():
    op.drop_table('book_bookmarks')
    op.drop_table('book_annotations')
    op.drop_table('reading_progress')
```

注意: MediaType 枚举值存储为字符串，无需 DDL 迁移。

---

## 9. 实现分期

### Phase 1: MVP 核心阅读 (本期)

- [x] MediaType 新增 EBOOK
- [ ] 后端: ebook_parser.py (ebooklib + mobi 元数据解析)
- [ ] 后端: ebook.py API (上传、列表、详情、删除、文件流、封面、进度)
- [ ] 后端: ORM 模型 (ReadingProgress)
- [ ] 后端: Alembic 迁移
- [ ] 前端: foliate-js 集成
- [ ] 前端: EbookView.vue 书架页面
- [ ] 前端: ebook-reader.vue 阅读器组件 (分页、翻页、目录、设置)
- [ ] 前端: 阅读进度保存/恢复
- [ ] 路由、导航栏集成

### Phase 2: 批注与检索

- [ ] 后端: 批注/书签 CRUD API
- [ ] 前端: 文本选中 → 高亮/批注
- [ ] 前端: 书签管理面板
- [ ] 批注导出 (Markdown)

### Phase 3: LLM 集成

- [ ] 章节摘要 (复用 analyze_content 步骤)
- [ ] 选中文本 → AI 解释/翻译
- [ ] 书籍 AI 对话 (复用 chat_service)

---

## 10. 替代方案

| 方案 | 未采用原因 |
|------|-----------|
| epub.js 替代 foliate-js | epub.js 不支持 MOBI，已停更 4 年 |
| 服务端 MOBI→EPUB 转换 | foliate-js 原生支持 MOBI 渲染，无需后端转换 |
| 独立 Book 表替代 ContentItem | 违反项目"内容统一管理"原则，增加复杂度 |
| 服务端渲染 HTML 替代客户端 foliate-js | 丢失分页/字体/主题等客户端控制能力 |
| ebooklib 解析 MOBI | ebooklib 的 MOBI 支持尚未成熟，mobi 库更可靠 |
