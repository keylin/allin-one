# Services 层开发规范

## 目录结构

```
services/
├── pipeline/            # 流水线引擎（编排器、执行器、注册表）
│   ├── registry.py      # 步骤定义 + 内置模板
│   ├── orchestrator.py  # 为 ContentItem 创建 PipelineExecution
│   └── executor.py      # 执行步骤，管理状态转换
├── collectors/          # 数据采集器（每种 SourceType 一个）
│   ├── rss.py           # RSSHubCollector + RSSStdCollector
│   ├── web_scraper.py   # ScraperCollector (L1/L2/L3)
│   ├── bilibili.py      # B站账号 API（不是视频采集器）
│   └── youtube.py       # （保留，未使用 — YouTube 走 RSSHub）
├── analyzers/           # LLM 分析
│   └── llm_analyzer.py  # 使用 OpenAI 兼容 SDK 的 LLMAnalyzer
└── publishers/          # 消息推送
    ├── email.py
    └── dingtalk.py
```

## 两条独立流程：采集 vs 处理

### 流程 1：采集（调度器 → 采集器 → ContentItem）
```
APScheduler (每5分钟) → check_and_collect_sources()
  → 遍历活跃数据源:
    → 按 source_type 获取对应的 Collector
    → collector.collect(source) → list[RawContentItem]
    → 通过 (source_id, external_id) 唯一约束去重
    → 创建 ContentItem 行 (status=pending)
    → 创建 CollectionRecord
```

### 流程 2：处理（编排器 → 执行器 → 步骤）
```
对每条新 ContentItem:
  → orchestrator.trigger_for_content(content) → PipelineExecution
    → 读取 source.pipeline_template_id → PipelineTemplate
    → 从 template.steps_config 创建 PipelineStep 行
  → orchestrator.start_execution(execution_id)
    → 通过 Huey 入队第一个步骤
  → execute_pipeline_step(execution_id, step_index)
    → STEP_HANDLERS[step_type](context) → output_data
    → executor.advance_pipeline() → 下一步或完成
```

**关键**: 这两条流程完全独立。采集器产出 ContentItem，流水线处理 ContentItem。流水线绝不包含 fetch/collect 步骤。

## 采集器开发

所有采集器实现此接口:
```python
class BaseCollector(ABC):
    @abstractmethod
    async def collect(self, source: SourceConfig) -> list[ContentItem]:
        """从数据源抓取新条目。去重在 DB 层处理。"""
```

SourceType → Collector 映射见 `app/tasks/scheduled_tasks.py` 中的 COLLECTOR_MAP。

没有 BilibiliVideoCollector 或 YouTubeVideoCollector。B站/YouTube 视频通过 RSSHub 发现，由流水线的 `download_video` 步骤处理。

## 步骤处理器开发

步骤处理器在 `app/tasks/pipeline_tasks.py` 中。每个处理器接收 context 字典:
```python
context = {
    "execution_id": str,
    "content_id": str,           # 始终存在
    "source_id": str,
    "template_name": str,
    "content_url": str,          # 来自 ContentItem.url
    "content_title": str,
    "step_type": str,
    "step_config": dict,         # 来自模板步骤定义
    "previous_steps": {          # 上游步骤的输出
        "enrich_content": {"full_text": "...", ...},
        ...
    }
}
```

处理器返回的字典成为 `step.output_data`:
```python
def _handle_xxx(context: dict) -> dict:
    # 从 context["step_config"] 读取配置
    # 从 context["previous_steps"] 读取上游输出
    # 执行处理，按需更新 ContentItem 字段
    return {"status": "done", "key": "value"}
```

在 `pipeline_tasks.py` 底部的 `STEP_HANDLERS` 字典中注册处理器。

### download_video 步骤输出

`download_video` 处理器的 `output_data` 包含以下字段：
- `file_path`: 视频文件绝对路径
- `title`: 视频标题
- `duration`: 时长（秒）
- `platform`: 平台标识 (bilibili/youtube)
- `thumbnail_path`: 封面图绝对路径（yt-dlp 下载优先，ffmpeg 截取回退）

## 关键步骤 vs 非关键步骤

- `is_critical: True` → 失败则整条流水线停止 (status=failed)
- `is_critical: False` → 失败则标记为 skipped，流水线继续
- 惯例: 模板中第一个处理步骤设为关键，其余为非关键

## 内置流水线模板

内置模板定义见 `app/services/pipeline/registry.py` 中的 BUILTIN_TEMPLATES。

## 三层内容模型

ContentItem 有三个内容字段，逐步填充:
1. `raw_data` (JSON) — 采集时由 Collector 设置
2. `processed_content` (Text) — 由 enrich/translate/transcribe 步骤设置
3. `analysis_result` (JSON) — 由 analyze_content 步骤设置

## LLM 分析器模式

```python
class LLMAnalyzer:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL
        )

    async def analyze(self, content: str, prompt: PromptTemplate) -> dict:
        # 确定响应格式
        output_format = prompt.output_format or "json"
        response_format = {"type": "json_object"} if output_format == "json" else None

        response = await self.client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": prompt.user_prompt.format(content=content)}
            ],
            response_format=response_format
        )

        result_text = response.choices[0].message.content

        if output_format == "json":
            return json.loads(result_text)
        else:
            return {"content": result_text, "format": output_format}
```
