---
name: new-vue-page
description: 引导实现 Vue 页面组件，包含 API 对接和 TailwindCSS 样式
argument-hint: <页面名> (如 FeedView, SourcesView, DashboardView)
model: sonnet
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# 实现 Vue 页面

你正在实现页面: **$ARGUMENTS**

## 开始之前

阅读现有模式和需求文档:
1. `frontend/src/App.vue` — 侧边栏导航和路由结构
2. `frontend/src/router/index.js` — 路由定义
3. `frontend/src/api/index.js` — Axios 实例
4. `frontend/src/views/$ARGUMENTS.vue` — 当前的占位桩代码
5. `docs/product_spec.md` — 该页面的 UI 需求
6. `docs/system_design.md` 第 6 节 — 该页面消费的 API 端点

## 开发规则

- 必须使用 `<script setup>` Composition API
- 使用 TailwindCSS 做样式（除非万不得已不要写 `<style>` 块）
- 使用 `ref()` 和 `reactive()` 管理状态
- 使用 `onMounted()` 做初始数据加载
- 使用 `@/api` Axios 实例发起所有 API 请求
- 时间戳: 通过 `dayjs(ts).format('YYYY-MM-DD HH:mm')` 将 UTC 转为本地时间
- 始终处理加载态和错误态

## 页面组件模板

```vue
<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '@/api'
import dayjs from 'dayjs'

// 状态
const items = ref([])
const loading = ref(false)
const error = ref(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

// 计算属性
const totalPages = computed(() => Math.ceil(total.value / pageSize.value))

// 方法
async function fetchData() {
  loading.value = true
  error.value = null
  try {
    const res = await api.get('/resource', {
      params: { page: page.value, page_size: pageSize.value }
    })
    if (res.code === 0) {
      items.value = res.data
      total.value = res.total
    }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function formatTime(ts) {
  return ts ? dayjs(ts).format('YYYY-MM-DD HH:mm') : '-'
}

// 生命周期
onMounted(fetchData)
</script>

<template>
  <div class="p-6">
    <!-- 头部 -->
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-2xl font-bold text-gray-800">页面标题</h2>
      <button class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
        操作按钮
      </button>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="flex justify-center py-12">
      <div class="text-gray-400">加载中...</div>
    </div>

    <!-- 错误 -->
    <div v-else-if="error" class="bg-red-50 text-red-600 p-4 rounded-lg">
      {{ error }}
    </div>

    <!-- 内容区 -->
    <div v-else>
      <!-- 在这里渲染列表 -->
    </div>

    <!-- 分页 -->
    <div v-if="totalPages > 1" class="flex items-center justify-between mt-6">
      <span class="text-sm text-gray-500">
        {{ (page - 1) * pageSize + 1 }}-{{ Math.min(page * pageSize, total) }} / {{ total }}
      </span>
      <div class="flex gap-2">
        <button @click="page--; fetchData()" :disabled="page <= 1"
          class="px-3 py-1 border rounded disabled:opacity-50">上一页</button>
        <button @click="page++; fetchData()" :disabled="page >= totalPages"
          class="px-3 py-1 border rounded disabled:opacity-50">下一页</button>
      </div>
    </div>
  </div>
</template>
```

## 各页面特有需求

阅读 `docs/product_spec.md` 获取详细需求。各页面要点:

### FeedView（信息流）
- 卡片式布局，用于内容消费
- 每张卡片显示数据源图标+名称
- AI 分析展开/收起
- 收藏/删除操作
- 按媒体类型筛选（全部/文章/视频/图片）
- 按时间排序（最新/最早）

### SourcesView（数据源管理）
- 表格/列表 + CRUD 操作
- 新建对话框: 数据源类型选择、URL 输入、流水线模板绑定
- 编辑/删除每个数据源
- 批量导入导出（OPML 格式）
- 显示最后采集时间、状态、失败次数

### ContentView（内容管理）
- 表格 + 筛选: 数据源、状态（pending/analyzed/failed）、媒体类型、时间范围
- 按 published_at、collected_at、title 排序
- 复选框批量删除
- 点击行查看详情 + 分析结果

### DashboardView（仪表盘）
- 统计卡片: 数据源总数、今日新增内容、流水线运行中/失败数
- 最近流水线执行列表
- 最近采集记录
- 错误/告警高亮

### PipelinesView（流水线监控）
- 执行列表 + 状态徽章（pending/running/completed/failed）
- 步骤进度指示器
- 点击查看步骤级详情和日志
- 重试失败的执行

### SettingsView（系统设置）
- 分区表单: LLM 配置（provider、API Key、model）、代理、通知
- 每个分区有保存/重置按钮

### VideoView（视频管理）
- 下载表单: URL 输入 + 清晰度选择
- 下载任务列表 + 进度
- 内嵌视频播放器（Artplayer）

### TemplatesView（模板管理）
- 流水线模板列表 + 步骤可视化
- 提示词模板列表 + 编辑功能
- 创建自定义模板

## 组件提取

如果页面中有可复用的 UI 元素，提取到 `frontend/src/components/`:
- `source-card.vue` — 数据源展示卡片
- `content-card.vue` — 信息流内容卡片
- `pipeline-status.vue` — 流水线状态徽章
- `pagination.vue` — 通用分页组件
- `confirm-dialog.vue` — 确认对话框

文件用 kebab-case 命名，模板中用 PascalCase 引用（`<SourceCard />`）。

## Pinia Store（按需创建）

创建 `frontend/src/stores/<resource>.js`:
```javascript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/api'

export const use${Resource}Store = defineStore('${resource}', () => {
  const items = ref([])
  const loading = ref(false)

  async function fetch(params = {}) {
    loading.value = true
    try {
      const res = await api.get('/${resource}', { params })
      items.value = res.data
    } finally {
      loading.value = false
    }
  }

  return { items, loading, fetch }
})
```
