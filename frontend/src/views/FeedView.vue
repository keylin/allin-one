<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { listContent, toggleFavorite, listSourceOptions, incrementView } from '@/api/content'
import FeedCard from '@/components/feed-card.vue'
import ContentDetailModal from '@/components/content-detail-modal.vue'

const items = ref([])
const loading = ref(true)
const loadingMore = ref(false)
const page = ref(1)
const pageSize = 20
const hasMore = ref(true)
const activeMediaType = ref('')
const sortBy = ref('collected_at')

// 搜索 & 筛选
const searchQuery = ref('')
const filterSource = ref('')
const filterStatus = ref('')
const showFavoritesOnly = ref(false)
const sourceOptions = ref([])
let searchTimer = null

const mediaTypes = [
  { value: '', label: '全部' },
  { value: 'text', label: '文本' },
  { value: 'video', label: '视频' },
  { value: 'audio', label: '音频' },
  { value: 'image', label: '图片' },
]

const sortOptions = [
  { value: 'collected_at', label: '按抓取时间', icon: 'M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5' },
  { value: 'published_at', label: '按发布时间', icon: 'M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5' },
  { value: 'updated_at', label: '按更新时间', icon: 'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99' },
]

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'analyzed', label: '已分析' },
  { value: 'pending', label: '待处理' },
  { value: 'failed', label: '失败' },
]

// 详情弹窗 + 导航
const showDetail = ref(false)
const detailIndex = ref(-1)
const detailContentId = computed(() => items.value[detailIndex.value]?.id ?? null)

// 是否有活跃筛选
const hasActiveFilters = computed(() => {
  return searchQuery.value.trim() || filterSource.value || filterStatus.value || showFavoritesOnly.value
})

// 当前来源名称（用于 tag 显示）
const activeSourceName = computed(() => {
  if (!filterSource.value) return ''
  const s = sourceOptions.value.find(o => o.id === filterSource.value)
  return s ? s.name : filterSource.value
})

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
      sort_order: 'desc',
    }
    if (activeMediaType.value) params.media_type = activeMediaType.value
    if (searchQuery.value.trim()) params.q = searchQuery.value.trim()
    if (filterSource.value) params.source_id = filterSource.value
    if (filterStatus.value) params.status = filterStatus.value
    if (showFavoritesOnly.value) params.is_favorited = true

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

// 搜索防抖
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => fetchItems(true), 300)
})

// 筛选联动（非搜索）
watch([filterSource, filterStatus, showFavoritesOnly], () => {
  fetchItems(true)
})

// 清除单个筛选
function clearSearch() {
  searchQuery.value = ''
  fetchItems(true)
}
function clearSource() {
  filterSource.value = ''
}
function clearStatus() {
  filterStatus.value = ''
}
function clearFavorites() {
  showFavoritesOnly.value = false
}
function clearAllFilters() {
  searchQuery.value = ''
  filterSource.value = ''
  filterStatus.value = ''
  showFavoritesOnly.value = false
  fetchItems(true)
}

// 弹窗导航
function openDetail(item) {
  detailIndex.value = items.value.findIndex(i => i.id === item.id)
  showDetail.value = true
  incrementView(item.id).catch(() => {})
}

function closeDetail() {
  showDetail.value = false
  detailIndex.value = -1
}

function goPrev() {
  if (detailIndex.value > 0) detailIndex.value--
}

function goNext() {
  if (detailIndex.value < items.value.length - 1) detailIndex.value++
  if (detailIndex.value >= items.value.length - 3 && hasMore.value) loadMore()
}

async function handleFavorite(id) {
  const res = await toggleFavorite(id)
  if (res.code === 0) {
    const item = items.value.find(i => i.id === id)
    if (item) item.is_favorited = res.data.is_favorited
  }
}

// 无限滚动
function handleScroll(e) {
  const el = e.target
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 200) {
    loadMore()
  }
}

function getScrollContainer() {
  const main = document.querySelector('main')
  return main || window
}

onMounted(async () => {
  fetchItems(true)
  // 加载来源选项
  try {
    const res = await listSourceOptions()
    if (res.code === 0) sourceOptions.value = res.data
  } catch (_) { /* ignore */ }
  const container = getScrollContainer()
  container.addEventListener('scroll', handleScroll)
})

onUnmounted(() => {
  clearTimeout(searchTimer)
  const container = getScrollContainer()
  container.removeEventListener('scroll', handleScroll)
})
</script>

<template>
  <div class="min-h-screen bg-slate-50/30">
    <!-- 顶部固定栏 -->
    <div class="sticky top-0 z-10 bg-white/80 backdrop-blur-md border-b border-slate-200/60">
      <div class="max-w-4xl px-4 md:px-8 py-4">
        <!-- 标题 + 排序 -->
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

        <!-- 搜索 + 来源 + 状态 + 收藏 -->
        <div class="flex items-center gap-2 mb-3 flex-wrap">
          <!-- 搜索框 -->
          <div class="relative flex-1 min-w-[180px]">
            <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              v-model="searchQuery"
              type="text"
              placeholder="搜索标题..."
              class="w-full bg-slate-50 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all"
            />
          </div>

          <!-- 来源下拉 -->
          <select
            v-model="filterSource"
            class="bg-slate-50 text-xs text-slate-600 rounded-lg px-3 py-2 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer min-w-[100px]"
          >
            <option value="">全部来源</option>
            <option v-for="s in sourceOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>

          <!-- 状态 pills -->
          <div class="flex items-center gap-1 bg-slate-100 rounded-lg p-0.5">
            <button
              v-for="st in statusOptions"
              :key="st.value"
              class="px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 whitespace-nowrap"
              :class="filterStatus === st.value
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'"
              @click="filterStatus = st.value"
            >
              {{ st.label }}
            </button>
          </div>

          <!-- 收藏 toggle -->
          <button
            class="p-2 rounded-lg transition-all duration-200 border"
            :class="showFavoritesOnly
              ? 'text-amber-500 bg-amber-50 border-amber-200'
              : 'text-slate-400 hover:text-slate-600 bg-slate-50 border-slate-200 hover:border-slate-300'"
            :title="showFavoritesOnly ? '显示全部' : '只看收藏'"
            @click="showFavoritesOnly = !showFavoritesOnly"
          >
            <svg class="w-4 h-4" :fill="showFavoritesOnly ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
            </svg>
          </button>
        </div>

        <!-- 活跃筛选 tags -->
        <div v-if="hasActiveFilters" class="flex items-center gap-2 mb-3 flex-wrap">
          <span
            v-if="searchQuery.trim()"
            class="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-50 text-indigo-700 text-xs font-medium rounded-full"
          >
            搜索:{{ searchQuery.trim() }}
            <button @click="clearSearch" class="ml-0.5 hover:text-indigo-900">&times;</button>
          </span>
          <span
            v-if="filterSource"
            class="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-50 text-indigo-700 text-xs font-medium rounded-full"
          >
            来源:{{ activeSourceName }}
            <button @click="clearSource" class="ml-0.5 hover:text-indigo-900">&times;</button>
          </span>
          <span
            v-if="filterStatus"
            class="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-50 text-indigo-700 text-xs font-medium rounded-full"
          >
            状态:{{ statusOptions.find(s => s.value === filterStatus)?.label }}
            <button @click="clearStatus" class="ml-0.5 hover:text-indigo-900">&times;</button>
          </span>
          <span
            v-if="showFavoritesOnly"
            class="inline-flex items-center gap-1 px-2.5 py-1 bg-amber-50 text-amber-700 text-xs font-medium rounded-full"
          >
            收藏
            <button @click="clearFavorites" class="ml-0.5 hover:text-amber-900">&times;</button>
          </span>
          <button
            @click="clearAllFilters"
            class="text-xs text-slate-400 hover:text-slate-600 transition-colors"
          >
            清除全部
          </button>
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

    <!-- 信息流内容区 -->
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
        <p class="text-sm text-slate-500 font-medium mb-1">
          {{ hasActiveFilters ? '没有找到匹配的内容' : '暂无内容' }}
        </p>
        <p class="text-xs text-slate-400">
          {{ hasActiveFilters ? '试试调整筛选条件' : '添加数据源后内容会自动出现在这里' }}
        </p>
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
      :has-prev="detailIndex > 0"
      :has-next="detailIndex < items.length - 1"
      :current-index="detailIndex"
      :total-count="items.length"
      @close="closeDetail"
      @favorite="handleFavorite"
      @prev="goPrev"
      @next="goNext"
    />
  </div>
</template>
