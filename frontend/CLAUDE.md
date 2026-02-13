# 前端开发规范

## UI 设计规范（强制）

所有前端代码必须遵守以下设计原则，等同于 `design-expert` skill 的要求：

### 核心理念
- **拒绝平庸**: 不使用默认浏览器样式或过时的 Bootstrap 风格
- **极简主义**: 注重留白，让内容呼吸
- **移动优先**: 始终从小屏幕写起，用响应式扩展到大屏（`class="p-4 md:p-8"`）
- **排版层级**: 用不同大小、字重、颜色建立视觉层级（`text-gray-500` vs `text-gray-900`）
- **细腻质感**: 柔和阴影 (`shadow-sm`, `shadow-lg`)、圆角 (`rounded-xl`, `rounded-2xl`)、微妙边框 (`border-gray-100`)

### Tailwind 默认写法
- **背景**: `bg-gray-50/50` 或 `bg-white` 搭配大面积留白
- **标题**: `font-bold tracking-tight text-gray-900`
- **正文**: `text-gray-600 leading-relaxed`
- **交互**: 按钮必须有 hover/active 态，使用 `transition-all duration-200`
- **容器**: `max-w-7xl mx-auto px-4 sm:px-6 lg:px-8`
- **图标**: 使用 `lucide-vue-next`（现代线条风格）

### 设计流程
编写任何页面/组件前，先完成设计思考：
1. **分析**: 理解页面目的和用户行为
2. **视觉定义**: 确定色调（推荐 Indigo/Violet/Emerald/Rose）、布局方式（Grid/Flex）、整体氛围
3. **编码**: 产出高质量 Vue 组件

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
| /pipelines        | PipelinesView.vue    | 流水线（执行记录+模板+提示词） |
| /video-download   | VideoView.vue        | 视频下载/播放     |
| /settings         | SettingsView.vue     | 系统设置          |

## URL 状态持久化

列表页的搜索、筛选、排序状态通过 URL query 参数持久化，支持刷新保持和浏览器导航。

```javascript
// 1. 从 route.query 初始化
const searchQuery = ref(route.query.q || '')

// 2. 变更时同步到 URL（仅非默认值，保持 URL 简洁）
function syncQueryParams() {
  const query = {}
  if (searchQuery.value) query.q = searchQuery.value
  router.replace({ query }).catch(() => {})
}
```

已实现: ContentView, FeedView, SourcesView

## 命名规范

- 文件: kebab-case (`source-card.vue`, `feed-filter.vue`)
- 组件: 模板中用 PascalCase (`<SourceCard />`)
- 变量/函数: camelCase (`sourceList`, `handleDelete`)
- 样式: TailwindCSS 工具类为主，尽量不写自定义 CSS
- Store: camelCase 文件名，`useXxxStore` 导出

## Modal 组件模式

全屏 Modal 组件遵循此结构（参考 `source-form-modal.vue`、`pipeline-template-form-modal.vue`）：
- Props: `visible: Boolean`, 资源对象（null=创建，object=编辑）
- Emits: `submit(data)`, `cancel`
- 滚动锁定: `useScrollLock(toRef(props, 'visible'))` — 所有 Modal 必须调用
- 布局: 固定遮罩 (`fixed inset-0`) + backdrop-blur + sticky header + 可滚动内容 + sticky footer
- 宽度: `max-w-2xl`（常规）或 `max-w-3xl`（复杂表单）

## Composables

`src/composables/` 中的可复用组合函数:

### useScrollLock

所有 Modal/Dialog 组件**必须**使用，防止背景页面滚动。支持嵌套弹窗引用计数。

```javascript
import { toRef } from 'vue'
import { useScrollLock } from '@/composables/useScrollLock'

const props = defineProps({ visible: Boolean })
useScrollLock(toRef(props, 'visible'))
```

### useToast

全局 Toast 通知:

```javascript
const { success, error, warning, info } = useToast()
success('保存成功')
error('操作失败', { duration: 5000 })
```

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
