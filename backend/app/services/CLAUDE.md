# Services 层开发规范

## 目录结构

```
services/
├── pipeline/            # 流水线引擎（编排器、执行器、注册表）
│   ├── registry.py      # 步骤定义 + 内置模板
│   ├── orchestrator.py  # 为 ContentItem 创建 PipelineExecution
│   └── executor.py      # 执行步骤，管理状态转换
├── collectors/          # 数据采集器（每种 SourceType 一个）
│   ├── base.py          # BaseCollector 接口
│   ├── rss.py           # RSSHubCollector + RSSStdCollector
│   ├── web_scraper.py   # ScraperCollector (L1/L2/L3)
│   ├── akshare.py       # AkShareCollector (金融数据)
│   ├── podcast.py       # PodcastCollector (Apple Podcasts)
│   ├── bilibili.py      # BilibiliCollector (B站账号 API)
│   ├── generic_account.py # GenericAccountCollector
│   ├── file_upload.py   # FileUploadCollector
│   └── utils.py         # 采集器工具函数
├── scheduling/          # 智能调度服务
│   ├── calculator.py    # SchedulingService (间隔计算)
│   ├── config.py        # SchedulingConfig (调度参数)
│   ├── helpers.py       # 辅助函数
│   ├── periodicity.py   # 周期性分析
│   └── hotspot.py       # 热点检测
├── analyzers/           # LLM 分析
│   └── llm_analyzer.py  # 使用 OpenAI 兼容 SDK 的 LLMAnalyzer
├── publishers/          # 消息推送
│   ├── email.py
│   └── dingtalk.py
├── chat_service.py      # 内容 AI 对话服务
├── enrichment.py        # 内容富化 (enrich_content 步骤实现)
├── media_detection.py   # 媒体检测
├── rsshub_sync.py       # RSSHub 同步服务
├── scheduling_service.py # 向后兼容入口 → scheduling/
└── source_cleanup.py    # 数据源清理
```

## 两条独立流程：采集 vs 处理

### 流程 1：采集（调度器 → 采集器 → ContentItem）
```
Procrastinate periodic (每1分钟) → check_and_collect_sources()
  → 查询 next_collection_at <= now 的活跃数据源
  → 对每个到期的源 defer collect_single_source 到 scheduled 队列
  → collect_single_source(source_id):
    → 按 source_type 获取对应的 Collector
    → collector.collect(source) → list[ContentItem]
    → 通过 (source_id, external_id) 唯一约束去重
    → 创建 ContentItem 行 (status=pending)
    → 创建 CollectionRecord
    → SchedulingService.update_next_collection_time(source) 更新下次采集时间
```

### 流程 2：处理（编排器 → 执行器 → 步骤）
```
对每条新 ContentItem:
  → orchestrator.trigger_for_content(content) → PipelineExecution
    → 读取 source.pipeline_template_id → PipelineTemplate
    → 从 template.steps_config 创建 PipelineStep 行（步骤完全来自模板，不再自动注入）
    → 无模板时直接标记 content.status = READY
  → orchestrator.async_start_execution(execution_id)
    → 通过 Procrastinate defer 入队第一个步骤到 pipeline 队列
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

SourceType → Collector 映射见 `app/tasks/collection_tasks.py` 中的 COLLECTOR_MAP。

没有 BilibiliVideoCollector 或 YouTubeVideoCollector。B站/YouTube 视频通过 RSSHub 发现，由流水线的 `localize_media` 步骤处理。

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

### localize_media 步骤输出

`localize_media` 处理器的 `output_data` 包含以下字段：
- `status`: "done"
- `media_items_created`: 创建的 MediaItem 数量
- `has_video`: 是否包含视频
- `file_path`: 视频文件绝对路径（视频时）
- `subtitle_path`: 字幕文件路径（视频时）
- `thumbnail_path`: 封面图绝对路径（yt-dlp 下载优先，ffmpeg 截取回退）
- `duration`: 时长（秒，视频时）

## 关键步骤 vs 非关键步骤

- `is_critical: True` → 失败则整条流水线停止 (status=failed)
- `is_critical: False` → 失败则标记为 skipped，流水线继续
- 惯例: 模板中第一个处理步骤设为关键，其余为非关键

## 内置流水线模板

内置模板定义见 `app/services/pipeline/registry.py` 中的 BUILTIN_TEMPLATES。
模板包含所有步骤（含 extract_content、localize_media），Orchestrator 不再自动注入预处理步骤。

## 三层内容模型

ContentItem 有三个内容字段，逐步填充:
1. `raw_data` (JSON) — 采集时由 Collector 设置
2. `processed_content` (Text) — 由 extract_content/enrich/translate/transcribe 步骤设置
3. `analysis_result` (JSON) — 由 analyze_content 步骤设置

## LLM 分析器模式

```python
class LLMAnalyzer:
    def __init__(self):
        # LLM 配置从 system_settings 表读取（非环境变量）
        config = get_llm_config()
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url
        )
        self.model = config.model

    async def analyze(self, content: str, prompt: PromptTemplate) -> dict:
        # 确定响应格式
        output_format = prompt.output_format or "json"
        response_format = {"type": "json_object"} if output_format == "json" else None

        response = await self.client.chat.completions.create(
            model=self.model,
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
