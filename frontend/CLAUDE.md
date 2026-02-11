# 前端开发规范

## 组件约定

必须使用 `<script setup>` Composition API:
```vue
<script setup>
import { ref, onMounted } from 'vue'
import api from '@/api'

const items = ref([])
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const res = await api.get('/sources', { params: { page: 1, page_size: 20 } })
    items.value = res.data
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="p-6">
    <!-- 内容 -->
  </div>
</template>
```

## API 调用

`src/api/index.js` 中的 Axios 实例会自动解包 `response.data`。
后端返回 `{code, data, message}`，经过拦截器后直接拿到这个结构。

```javascript
const res = await api.get('/sources')                    // res = {code, data, message}
const res = await api.post('/sources', sourceData)       // POST
const res = await api.put(`/sources/${id}`, updateData)  // PUT
const res = await api.delete(`/sources/${id}`)           // DELETE

// 分页模式:
const res = await api.get('/content', {
  params: { page: 1, page_size: 20, source_id: 'xxx', status: 'pending' }
})
// res = {code, data: [...], total, page, page_size, message}
```

## 页面路由

| 路径              | 视图                  | 说明             |
|-------------------|----------------------|------------------|
| /dashboard        | DashboardView.vue    | 统计概览、告警    |
| /feed             | FeedView.vue         | 卡片式信息流      |
| /sources          | SourcesView.vue      | 数据源 CRUD      |
| /content          | ContentView.vue      | 内容表格管理      |
| /pipelines        | PipelinesView.vue    | 流水线监控        |
| /video-download   | VideoView.vue        | 视频下载/播放     |
| /prompt-templates | TemplatesView.vue    | 提示词模板配置    |
| /settings         | SettingsView.vue     | 系统设置          |

## 命名规范

- 文件: kebab-case (`source-card.vue`, `feed-filter.vue`)
- 组件: 模板中用 PascalCase (`<SourceCard />`)
- 变量/函数: camelCase (`sourceList`, `handleDelete`)
- 样式: TailwindCSS 工具类为主，尽量不写自定义 CSS
- Store: camelCase 文件名，`useXxxStore` 导出

## Pinia Store 模式

```javascript
// stores/sources.js
import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/api'

export const useSourcesStore = defineStore('sources', () => {
  const sources = ref([])
  const loading = ref(false)

  async function fetchSources(params = {}) {
    loading.value = true
    try {
      const res = await api.get('/sources', { params })
      sources.value = res.data
    } finally {
      loading.value = false
    }
  }

  return { sources, loading, fetchSources }
})
```

## 时间戳处理

- 后端存 UTC 时间戳
- 前端通过 dayjs 转为本地时间:
```javascript
import dayjs from 'dayjs'
dayjs(item.collected_at).format('YYYY-MM-DD HH:mm')
```
