<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { listContent, toggleFavorite } from '@/api/content'
import FeedCard from '@/components/feed-card.vue'
import ContentDetailModal from '@/components/content-detail-modal.vue'

const items = ref([])
const loading = ref(true)
const loadingMore = ref(false)
const page = ref(1)
const pageSize = 20
const hasMore = ref(true)
const activeMediaType = ref('')
const sortBy = ref('collected_at')  // collected_at | updated_at

const mediaTypes = [
  { value: '', label: '全部' },
  { value: 'text', label: '文本' },
  { value: 'video', label: '视频' },
  { value: 'audio', label: '音频' },
  { value: 'image', label: '图片' },
]

const sortOptions = [
  { value: 'collected_at', label: '按抓取时间', icon: 'M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5' },
  { value: 'updated_at', label: '按更新时间', icon: 'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99' },
]

// 详情弹窗
const showDetail = ref(false)
const detailContentId = ref(null)

async function fetchItems(reset = false) {
  if (reset) {
    page.value = 1
    items.value = []
    hasMore.value = true
    loading.value = true
  } else {
    loadingMore.value = true
  }

  try {
    const params = {
      page: page.value,
      page_size: pageSize,
      sort_by: sortBy.value,
      order: 'desc'
    }
    if (activeMediaType.value) params.media_type = activeMediaType.value
    const res = await listContent(params)
    if (res.code === 0) {
      if (reset) {
        items.value = res.data
      } else {
        items.value.push(...res.data)
      }
      hasMore.value = items.value.length < res.total
    }
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function loadMore() {
  if (!hasMore.value || loadingMore.value) return
  page.value++
  fetchItems()
}

function switchMediaType(type) {
  activeMediaType.value = type
  fetchItems(true)
}

function switchSort(sort) {
  sortBy.value = sort
  fetchItems(true)
}

function openDetail(item) {
  detailContentId.value = item.id
  showDetail.value = true
}

async function handleFavorite(id) {
  const res = await toggleFavorite(id)
  if (res.code === 0) {
    const item = items.value.find(i => i.id === id)
    if (item) item.is_favorited = res.data.is_favorited
  }
}

// 无限滚动
function handleScroll() {
  const scrollHeight = document.documentElement.scrollHeight
  const scrollTop = document.documentElement.scrollTop
  const clientHeight = document.documentElement.clientHeight

  // 距离底部 200px 时触发加载
  if (scrollHeight - scrollTop - clientHeight < 200) {
    loadMore()
  }
}

onMounted(() => {
  fetchItems(true)
  window.addEventListener('scroll', handleScroll)
})

onUnmounted(() => {
  window.removeEventListener('scroll', handleScroll)
})
</script>

<template>
  <div class="min-h-screen bg-slate-50/30">
    <!-- 顶部固定栏 -->
    <div class="sticky top-0 z-10 bg-white/80 backdrop-blur-md border-b border-slate-200/60">
      <div class="max-w-4xl px-4 md:px-8 py-4">
        <div class="flex items-center justify-between mb-3">
          <div>
            <h2 class="text-xl font-bold text-slate-900 tracking-tight">信息流</h2>
            <p class="text-xs text-slate-500 mt-0.5">{{ items.length }} 条内容</p>
          </div>

          <!-- 排序选项 -->
          <div class="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
            <button
              v-for="sort in sortOptions"
              :key="sort.value"
              :title="sort.label"
              class="p-2 rounded-md transition-all duration-200"
              :class="sortBy === sort.value
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'"
              @click="switchSort(sort.value)"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" :d="sort.icon" />
              </svg>
            </button>
          </div>
        </div>

        <!-- 媒体类型 Tab -->
        <div class="flex items-center gap-1 bg-slate-100 rounded-xl p-1 overflow-x-auto">
          <button
            v-for="mt in mediaTypes"
            :key="mt.value"
            class="px-4 py-1.5 text-sm font-medium rounded-lg transition-all duration-200 whitespace-nowrap shrink-0"
            :class="activeMediaType === mt.value
              ? 'bg-white text-slate-900 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'"
            @click="switchMediaType(mt.value)"
          >
            {{ mt.label }}
          </button>
        </div>
      </div>
    </div>

    <!-- 信息流内容区 - 左对齐 -->
    <div class="max-w-4xl px-4 md:px-8 py-6">
      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center py-16">
        <svg class="w-8 h-8 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>

      <!-- Empty -->
      <div v-else-if="items.length === 0" class="text-center py-16">
        <div class="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <svg class="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 01-2.25 2.25M16.5 7.5V18a2.25 2.25 0 002.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 002.25 2.25h13.5M6 7.5h3v3H6v-3z" />
          </svg>
        </div>
        <p class="text-sm text-slate-500 font-medium mb-1">暂无内容</p>
        <p class="text-xs text-slate-400">添加数据源后内容会自动出现在这里</p>
      </div>

      <!-- Feed 单列卡片流 -->
      <div v-else class="space-y-4">
        <FeedCard
          v-for="item in items"
          :key="item.id"
          :item="item"
          @click="openDetail"
          @favorite="handleFavorite"
        />

        <!-- 加载更多指示器 -->
        <div v-if="loadingMore" class="flex items-center justify-center py-8">
          <div class="flex items-center gap-2 text-sm text-slate-400">
            <svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <span>加载中...</span>
          </div>
        </div>

        <!-- 到底了提示 -->
        <div v-else-if="!hasMore && items.length > 0" class="text-center py-8">
          <div class="inline-flex items-center gap-2 px-4 py-2 bg-slate-100 rounded-full text-xs text-slate-500">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            已经到底了
          </div>
        </div>
      </div>
    </div>

    <ContentDetailModal
      :visible="showDetail"
      :content-id="detailContentId"
      @close="showDetail = false"
      @favorite="handleFavorite"
    />
  </div>
</template>
