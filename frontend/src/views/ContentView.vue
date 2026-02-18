<script setup>
import { ref, onMounted, computed, nextTick, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { useContentStore } from '@/stores/content'
import { listSources } from '@/api/sources'
import { analyzeContent, incrementView, getContentStats, batchMarkRead, batchFavorite } from '@/api/content'
import ContentDetailPanel from '@/components/content-detail-panel.vue'
import DetailDrawer from '@/components/detail-drawer.vue'
import ConfirmDialog from '@/components/confirm-dialog.vue'

const route = useRoute()
const router = useRouter()
const store = useContentStore()

// Filters (from URL)
const searchQuery = ref(route.query.q || '')
const filterStatus = ref(route.query.status || '')
const filterHasVideo = ref(route.query.has_video === '1')
const filterSourceId = ref(route.query.source_id || '')
const sources = ref([])

// Stats
const contentStats = ref({
  total: 0,
  today: 0,
  pending: 0,
  processing: 0,
  analyzed: 0,
  failed: 0,
  read: 0,      // 新增
  unread: 0     // 新增
})

// Date range
const dateRange = ref(route.query.date_range || '')
const dateRangeOptions = [
  { value: '', label: '全部时间' },
  { value: '1', label: '今天' },
  { value: '3', label: '近3天' },
  { value: '7', label: '近7天' },
  { value: '30', label: '近30天' },
]

// Favorites toggle
const showFavoritesOnly = ref(route.query.favorites === '1')
// 三态已读/未读筛选：null=全部, 'unread'=仅未读, 'read'=仅已读
const readStatusFilter = ref(
  route.query.read_status === 'unread' ? 'unread' :
  route.query.read_status === 'read' ? 'read' :
  null
)

// Sort (from URL)
const sortBy = ref(route.query.sort_by || 'collected_at')
const sortOrder = ref(route.query.sort_order || 'desc')

// Detail drawer
const selectedId = ref(null)
const drawerVisible = ref(false)

// Batch ops
const selectedIds = ref([])
const showBatchDeleteDialog = ref(false)
const showDeleteAllDialog = ref(false)
const deletingAll = ref(false)

let searchTimer = null

const statusLabels = {
  pending: '待处理',
  processing: '处理中',
  ready: '已就绪',
  analyzed: '已分析',
  failed: '失败',
}
const statusStyles = {
  pending: 'bg-slate-100 text-slate-600',
  processing: 'bg-indigo-50 text-indigo-700',
  ready: 'bg-sky-50 text-sky-700',
  analyzed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
}

const totalPages = computed(() => Math.max(1, Math.ceil(store.total / store.pageSize)))

function syncQueryParams() {
  const query = {}
  if (searchQuery.value) query.q = searchQuery.value
  if (filterStatus.value) query.status = filterStatus.value
  if (filterHasVideo.value) query.has_video = '1'
  if (filterSourceId.value) query.source_id = filterSourceId.value
  if (dateRange.value) query.date_range = dateRange.value
  if (showFavoritesOnly.value) query.favorites = '1'
  if (readStatusFilter.value) query.read_status = readStatusFilter.value  // 三态筛选
  if (sortBy.value !== 'collected_at') query.sort_by = sortBy.value
  if (sortOrder.value !== 'desc') query.sort_order = sortOrder.value
  if (store.currentPage > 1) query.page = String(store.currentPage)
  router.replace({ query }).catch(() => {})
}

function getDateRange() {
  if (!dateRange.value) return {}
  const days = parseInt(dateRange.value)
  if (isNaN(days)) return {}
  const from = new Date()
  from.setDate(from.getDate() - days + 1)
  from.setHours(0, 0, 0, 0)
  return {
    date_from: from.toISOString().split('T')[0],
    date_to: new Date().toISOString().split('T')[0],
  }
}

async function fetchContentStats() {
  try {
    const res = await getContentStats()
    if (res.code === 0) contentStats.value = res.data
  } catch { /* ignore */ }
}

function handleStatCardClick(statusFilter) {
  if (statusFilter === null) return  // "今日新增"等卡片不可点击

  // 处理收藏筛选
  if (statusFilter === 'favorited') {
    showFavoritesOnly.value = !showFavoritesOnly.value
  }
  // 处理已读/未读筛选（特殊值）
  else if (statusFilter === 'unread' || statusFilter === 'read') {
    readStatusFilter.value = readStatusFilter.value === statusFilter ? null : statusFilter
  }
  // 处理 status 筛选（pending/analyzed/failed）
  else {
    filterStatus.value = filterStatus.value === statusFilter ? '' : statusFilter
  }

  handleFilterChange()
}

function fetchWithFilters() {
  const params = {
    sort_by: sortBy.value,
    sort_order: sortOrder.value,
    ...getDateRange(),
  }
  if (searchQuery.value) params.q = searchQuery.value
  if (filterStatus.value) params.status = filterStatus.value
  if (filterHasVideo.value) params.has_video = true
  if (filterSourceId.value) params.source_id = filterSourceId.value
  if (showFavoritesOnly.value) params.is_favorited = true

  // 三态已读/未读筛选
  if (readStatusFilter.value === 'unread') params.is_unread = true
  if (readStatusFilter.value === 'read') params.is_unread = false

  store.fetchContent(params)
  syncQueryParams()
  fetchContentStats()
}

function handleSearch() {
  store.currentPage = 1
  fetchWithFilters()
}

function handleFilterChange() {
  store.currentPage = 1
  fetchWithFilters()
}

function goToPage(page) {
  if (page < 1 || page > totalPages.value) return
  store.currentPage = page
  fetchWithFilters()
}

function selectItem(item) {
  selectedId.value = item.id
  drawerVisible.value = true
  incrementView(item.id).catch(() => {})
}

function closeDrawer() {
  drawerVisible.value = false
}

const analyzingIds = ref(new Set())

async function handleAnalyze(id) {
  analyzingIds.value.add(id)
  try {
    await analyzeContent(id)
    fetchWithFilters()
  } finally {
    analyzingIds.value.delete(id)
  }
}

async function handleFavorite(id) {
  await store.toggleFavorite(id)
}

function toggleSelect(id, event) {
  if (event) event.stopPropagation()
  const idx = selectedIds.value.indexOf(id)
  if (idx > -1) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

function toggleSelectAll() {
  if (selectedIds.value.length === store.items.length) {
    selectedIds.value = []
  } else {
    selectedIds.value = store.items.map(i => i.id)
  }
}

const batchAnalyzing = ref(false)
const batchProgress = ref(0)
const batchTotal = ref(0)

async function handleBatchAnalyze() {
  batchAnalyzing.value = true
  const ids = [...selectedIds.value]
  batchTotal.value = ids.length
  batchProgress.value = 0
  try {
    for (const id of ids) {
      await analyzeContent(id)
      batchProgress.value++
    }
    selectedIds.value = []
    fetchWithFilters()
  } finally {
    batchAnalyzing.value = false
  }
}

async function handleBatchDelete() {
  showBatchDeleteDialog.value = false
  await store.batchDelete(selectedIds.value)
  selectedIds.value = []
  fetchWithFilters()
}

async function handleDeleteAll() {
  showDeleteAllDialog.value = false
  deletingAll.value = true
  try {
    await store.deleteAll()
    store.currentPage = 1
    fetchWithFilters()
  } finally {
    deletingAll.value = false
  }
}

async function handleBatchRead() {
  await batchMarkRead(selectedIds.value)
  selectedIds.value = []
  fetchWithFilters()
}

async function handleBatchFavorite() {
  await batchFavorite(selectedIds.value)
  selectedIds.value = []
  fetchWithFilters()
}

function formatTime(t) {
  return t ? dayjs.utc(t).local().format('YYYY-MM-DD HH:mm:ss') : '-'
}

function handleSort(field) {
  if (sortBy.value === field) {
    sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortBy.value = field
    sortOrder.value = 'desc'
  }
  store.currentPage = 1
  fetchWithFilters()
}

// Search debounce
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => handleSearch(), 300)
}

// Keyboard navigation
function handleKeydown(e) {
  const tag = e.target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
  if (e.key === 'Escape' && drawerVisible.value) {
    closeDrawer()
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    const idx = store.items.findIndex(i => i.id === selectedId.value)
    if (idx < store.items.length - 1) {
      const nextItem = store.items[idx + 1]
      selectedId.value = nextItem.id
      if (drawerVisible.value) incrementView(nextItem.id).catch(() => {})
      nextTick(() => scrollRowIntoView(idx + 1))
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    const idx = store.items.findIndex(i => i.id === selectedId.value)
    if (idx > 0) {
      const prevItem = store.items[idx - 1]
      selectedId.value = prevItem.id
      if (drawerVisible.value) incrementView(prevItem.id).catch(() => {})
      nextTick(() => scrollRowIntoView(idx - 1))
    }
  }
}

const tableRef = ref(null)
function scrollRowIntoView(index) {
  if (!tableRef.value) return
  const rows = tableRef.value.querySelectorAll('[data-content-row]')
  if (rows[index]) {
    rows[index].scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }
}

onMounted(async () => {
  if (route.query.page) store.currentPage = parseInt(route.query.page) || 1
  fetchWithFilters()
  fetchContentStats()
  try {
    const res = await listSources({ page_size: 100 })
    if (res.code === 0) sources.value = res.data
  } catch { /* ignore */ }
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  clearTimeout(searchTimer)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Sticky header -->
    <div class="px-4 pt-3 pb-2 space-y-2.5 sticky top-0 bg-white z-10 border-b border-slate-100 shrink-0">
      <!-- Batch actions -->
      <div v-if="selectedIds.length > 0" class="flex items-center gap-2">
        <span class="text-sm text-slate-500">已选 {{ selectedIds.length }}</span>
        <button
          class="px-3 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-all disabled:opacity-50"
          :disabled="batchAnalyzing"
          @click="handleBatchAnalyze"
        >
          {{ batchAnalyzing ? `${batchProgress}/${batchTotal}` : '批量分析' }}
        </button>
        <button
          class="px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-all"
          @click="handleBatchRead"
        >
          标记已读
        </button>
        <button
          class="px-3 py-1.5 text-sm font-medium text-white bg-amber-500 rounded-lg hover:bg-amber-600 transition-all"
          @click="handleBatchFavorite"
        >
          批量收藏
        </button>
        <button
          class="px-3 py-1.5 text-sm font-medium text-white bg-rose-600 rounded-lg hover:bg-rose-700 transition-all"
          @click="showBatchDeleteDialog = true"
        >
          批量删除
        </button>
        <button
          class="px-3 py-1.5 text-sm font-medium text-slate-500 hover:text-slate-700 transition-colors"
          @click="selectedIds = []"
        >
          取消
        </button>
      </div>

      <!-- Stats cards -->
      <div class="flex gap-2 overflow-x-auto p-0.5 scrollbar-hide items-center">
        <button
          v-for="card in [
            { label: '全部', value: contentStats.total, filter: '', icon: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z', color: 'text-slate-600 bg-slate-50', active: 'ring-slate-400' },
            { label: '今日新增', value: contentStats.today, filter: null, icon: 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z', color: 'text-blue-600 bg-blue-50', active: '' },
            { label: '待处理', value: contentStats.pending, filter: 'pending', icon: 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z', color: 'text-amber-600 bg-amber-50', active: 'ring-amber-400' },
            { label: '已就绪', value: contentStats.ready, filter: 'ready', icon: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z', color: 'text-sky-600 bg-sky-50', active: 'ring-sky-400' },
            { label: '已分析', value: contentStats.analyzed, filter: 'analyzed', icon: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z', color: 'text-emerald-600 bg-emerald-50', active: 'ring-emerald-400' },
            { label: '失败', value: contentStats.failed, filter: 'failed', icon: 'M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z', color: 'text-rose-600 bg-rose-50', active: 'ring-rose-400' },
            { label: '未读', value: contentStats.unread, filter: 'unread', icon: 'M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.64 0 8.577 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.64 0-8.577-3.007-9.963-7.178zM15 12a3 3 0 11-6 0 3 3 0 016 0z', color: 'text-blue-600 bg-blue-50', active: 'ring-blue-400' },
            { label: '已读', value: contentStats.read, filter: 'read', icon: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z', color: 'text-slate-600 bg-slate-100', active: 'ring-slate-400' },
            { label: '收藏', value: contentStats.favorited || 0, filter: 'favorited', icon: 'M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z', color: 'text-amber-500 bg-amber-50', active: 'ring-amber-400' },
          ]"
          :key="card.label"
          class="flex items-center gap-2.5 px-3 py-2 rounded-lg border transition-all duration-200 shrink-0 min-w-0"
          :class="[
            // 判断卡片是否激活
            (
              (card.filter !== null && card.filter !== 'unread' && card.filter !== 'read' && card.filter !== 'favorited' && filterStatus === card.filter) ||
              (card.filter === 'unread' && readStatusFilter === 'unread') ||
              (card.filter === 'read' && readStatusFilter === 'read') ||
              (card.filter === 'favorited' && showFavoritesOnly)
            )
              ? `border-transparent ring-2 ${card.active} ${card.color}`
              : 'border-slate-200 hover:border-slate-300 bg-white',
            card.filter === null ? 'cursor-default' : 'cursor-pointer'
          ]"
          @click="handleStatCardClick(card.filter)"
        >
          <div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" :class="card.color">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" :d="card.icon" />
            </svg>
          </div>
          <div class="text-left">
            <p class="text-lg font-bold text-slate-900 leading-none tabular-nums">{{ card.value }}</p>
            <p class="text-[10px] text-slate-400 mt-0.5">{{ card.label }}</p>
          </div>
        </button>
        <button
          v-if="contentStats.total > 0"
          class="ml-auto px-3 py-1.5 text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 border border-red-200 rounded-lg transition-all duration-200 shrink-0 disabled:opacity-50"
          :disabled="deletingAll"
          @click="showDeleteAllDialog = true"
        >
          {{ deletingAll ? '清空中...' : '清空全部' }}
        </button>
      </div>

      <!-- Filter bar -->
      <div class="flex flex-wrap items-center gap-3">
      <div class="relative flex-1 min-w-[200px] max-w-sm">
        <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索标题..."
          class="w-full bg-white rounded-lg pl-9 pr-3 py-2 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all"
          @input="onSearchInput"
        />
      </div>
      <select
        v-model="filterSourceId"
        @change="handleFilterChange"
        class="bg-white text-sm text-slate-600 rounded-lg px-3 py-2 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer max-w-[140px]"
      >
        <option value="">全部来源</option>
        <option v-for="s in sources" :key="s.id" :value="String(s.id)">{{ s.name }}</option>
      </select>
      <select
        v-model="filterStatus"
        @change="handleFilterChange"
        class="bg-white text-sm text-slate-600 rounded-lg px-3 py-2 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer"
      >
        <option value="">全部状态</option>
        <option v-for="(label, value) in statusLabels" :key="value" :value="value">{{ label }}</option>
      </select>
      <button
        class="p-2 rounded-lg border transition-all duration-200"
        :class="filterHasVideo ? 'bg-violet-50 border-violet-300 text-violet-600' : 'bg-white border-slate-200 text-slate-400 hover:text-slate-600 hover:border-slate-300'"
        :title="filterHasVideo ? '显示全部' : '仅看视频'"
        @click="filterHasVideo = !filterHasVideo; handleFilterChange()"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
        </svg>
      </button>
      <select
        v-model="dateRange"
        @change="handleFilterChange"
        class="bg-white text-sm text-slate-600 rounded-lg px-3 py-2 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer"
      >
        <option v-for="opt in dateRangeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <button
        class="p-2 rounded-lg border transition-all duration-200"
        :class="readStatusFilter === 'unread' ? 'bg-blue-50 border-blue-300 text-blue-600' : 'bg-white border-slate-200 text-slate-400 hover:text-slate-600 hover:border-slate-300'"
        :title="readStatusFilter === 'unread' ? '显示全部' : '仅看未读'"
        @click="readStatusFilter = readStatusFilter === 'unread' ? null : 'unread'; handleFilterChange()"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path v-if="readStatusFilter !== 'unread'" stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.64 0 8.577 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.64 0-8.577-3.007-9.963-7.178z" />
          <path v-if="readStatusFilter !== 'unread'" stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          <path v-if="readStatusFilter === 'unread'" stroke-linecap="round" stroke-linejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
        </svg>
      </button>
      <button
        class="p-2 rounded-lg border transition-all duration-200"
        :class="showFavoritesOnly ? 'bg-amber-50 border-amber-300 text-amber-500' : 'bg-white border-slate-200 text-slate-400 hover:text-slate-600 hover:border-slate-300'"
        :title="showFavoritesOnly ? '显示全部' : '仅看收藏'"
        @click="showFavoritesOnly = !showFavoritesOnly; handleFilterChange()"
      >
        <svg class="w-4 h-4" :fill="showFavoritesOnly ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
        </svg>
      </button>
      <select
        :value="`${sortBy}:${sortOrder}`"
        @change="e => { const [f, o] = e.target.value.split(':'); sortBy = f; sortOrder = o; store.currentPage = 1; fetchWithFilters() }"
        class="bg-white text-sm text-slate-600 rounded-lg px-3 py-2 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer ml-auto"
      >
        <option value="collected_at:desc">采集时间 ↓</option>
        <option value="collected_at:asc">采集时间 ↑</option>
        <option value="published_at:desc">发布时间 ↓</option>
        <option value="published_at:asc">发布时间 ↑</option>
        <option value="updated_at:desc">更新时间 ↓</option>
        <option value="view_count:desc">浏览最多</option>
        <option value="title:asc">标题 A-Z</option>
      </select>
      </div>
    </div>

    <!-- Scrollable content -->
    <div class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">

    <!-- Loading -->
    <div v-if="store.loading" class="flex items-center justify-center py-16">
      <svg class="w-8 h-8 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <!-- Empty -->
    <div v-else-if="store.items.length === 0" class="text-center py-16">
      <div class="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
        <svg class="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
      </div>
      <p class="text-sm text-slate-500 font-medium mb-1">暂无内容</p>
      <p class="text-xs text-slate-400">添加数据源后内容会自动出现在这里</p>
    </div>

    <!-- Desktop table -->
    <template v-else>
      <div ref="tableRef" class="hidden md:block bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
        <table class="w-full">
          <thead class="bg-slate-50/80">
            <tr>
              <th class="w-10 px-4 py-3">
                <input
                  type="checkbox"
                  class="h-3.5 w-3.5 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                  :checked="selectedIds.length === store.items.length && store.items.length > 0"
                  @change="toggleSelectAll"
                />
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">标题</th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">来源</th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">状态</th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">媒体</th>
              <th class="px-4 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">浏览</th>
              <th
                class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100 select-none"
                @click="handleSort('collected_at')"
              >
                <div class="flex items-center gap-1">
                  <span>采集时间</span>
                  <svg v-if="sortBy === 'collected_at'" class="w-3 h-3" :class="sortOrder === 'desc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                  </svg>
                </div>
              </th>
              <th
                class="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100 select-none"
                @click="handleSort('published_at')"
              >
                <div class="flex items-center gap-1">
                  <span>发布时间</span>
                  <svg v-if="sortBy === 'published_at'" class="w-3 h-3" :class="sortOrder === 'desc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                  </svg>
                </div>
              </th>
              <th class="px-4 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr
              v-for="item in store.items"
              :key="item.id"
              data-content-row
              class="hover:bg-slate-50/50 cursor-pointer transition-colors duration-150"
              :class="{ 'bg-indigo-50/40': selectedId === item.id && drawerVisible }"
              @click="selectItem(item)"
            >
              <td class="w-10 px-4 py-3">
                <input
                  type="checkbox"
                  class="h-3.5 w-3.5 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                  :checked="selectedIds.includes(item.id)"
                  @change="toggleSelect(item.id, $event)"
                  @click.stop
                />
              </td>
              <td class="px-4 py-2.5 max-w-xs">
                <div class="flex items-center gap-1.5">
                  <svg v-if="item.is_favorited" class="w-3.5 h-3.5 text-amber-400 shrink-0" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                  </svg>
                  <div class="min-w-0">
                    <span class="text-sm font-medium text-slate-800 truncate block">{{ item.title }}</span>
                    <p v-if="item.summary_text" class="text-xs text-slate-400 truncate mt-0.5">{{ item.summary_text }}</p>
                  </div>
                </div>
              </td>
              <td class="px-4 py-3 text-sm text-slate-500 truncate max-w-[120px]">{{ item.source_name || '-' }}</td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md"
                  :class="statusStyles[item.status] || 'bg-slate-100 text-slate-600'"
                >
                  {{ statusLabels[item.status] || item.status }}
                </span>
              </td>
              <td class="px-4 py-3 text-sm text-slate-400">
                <span v-if="item.media_items?.some(m => m.media_type === 'video')" class="text-violet-500">视频</span>
                <span v-else-if="item.media_items?.some(m => m.media_type === 'image')" class="text-emerald-500">图片</span>
                <span v-else-if="item.media_items?.some(m => m.media_type === 'audio')" class="text-rose-500">音频</span>
                <span v-else class="text-slate-300">-</span>
              </td>
              <td class="px-4 py-3 text-sm text-slate-400 text-right tabular-nums">{{ item.view_count || 0 }}</td>
              <td class="px-4 py-3 text-sm text-slate-400 whitespace-nowrap">{{ formatTime(item.collected_at) }}</td>
              <td class="px-4 py-3 text-sm text-slate-400 whitespace-nowrap">{{ formatTime(item.published_at) }}</td>
              <td class="px-4 py-3 text-right" @click.stop>
                <button
                  v-if="item.status === 'pending'"
                  class="px-2.5 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all duration-200 disabled:opacity-50"
                  :disabled="analyzingIds.has(item.id)"
                  @click="handleAnalyze(item.id)"
                >
                  {{ analyzingIds.has(item.id) ? '分析中...' : '分析' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Mobile cards -->
      <div class="md:hidden space-y-2">
        <div
          v-for="item in store.items"
          :key="item.id"
          data-content-row
          class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4 cursor-pointer transition-all duration-200 hover:border-indigo-300"
          :class="{ 'border-indigo-400 ring-1 ring-indigo-400/20': selectedId === item.id && drawerVisible }"
          @click="selectItem(item)"
        >
          <div class="flex items-start justify-between gap-2 mb-2">
            <div class="flex items-center gap-1.5 min-w-0">
              <input
                type="checkbox"
                class="h-3.5 w-3.5 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500 shrink-0"
                :checked="selectedIds.includes(item.id)"
                @change="toggleSelect(item.id, $event)"
                @click.stop
              />
              <svg v-if="item.is_favorited" class="w-3.5 h-3.5 text-amber-400 shrink-0" fill="currentColor" viewBox="0 0 24 24">
                <path d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
              </svg>
              <span class="text-sm font-medium text-slate-800 line-clamp-1">{{ item.title }}</span>
            </div>
            <span
              class="inline-flex px-1.5 py-0.5 text-[10px] font-medium rounded shrink-0"
              :class="statusStyles[item.status] || 'bg-slate-100 text-slate-600'"
            >
              {{ statusLabels[item.status] || item.status }}
            </span>
          </div>
          <p v-if="item.summary_text" class="text-xs text-slate-400 line-clamp-1 mb-2">{{ item.summary_text }}</p>
          <div class="flex flex-col gap-1 text-xs text-slate-400">
            <div class="flex items-center gap-2">
              <span class="truncate max-w-[120px]">{{ item.source_name || '-' }}</span>
              <span v-if="item.media_items?.length" class="text-slate-300">
                {{ item.media_items.some(m => m.media_type === 'video') ? '视频' : item.media_items.some(m => m.media_type === 'image') ? '图片' : '音频' }}
              </span>
            </div>
            <div class="flex items-center gap-2 text-[10px]">
              <span class="text-slate-500">采集: {{ formatTime(item.collected_at) }}</span>
              <span class="text-slate-500">发布: {{ formatTime(item.published_at) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Pagination -->
      <div v-if="store.total > store.pageSize" class="flex items-center justify-between mt-4">
        <span class="text-sm text-slate-400">{{ store.currentPage }} / {{ totalPages }} 页</span>
        <div class="flex items-center gap-2">
          <button
            class="px-3 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            :disabled="store.currentPage <= 1 || store.loading"
            @click="goToPage(store.currentPage - 1)"
          >
            上一页
          </button>
          <button
            class="px-3 py-1.5 text-sm font-medium border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            :disabled="store.currentPage >= totalPages || store.loading"
            @click="goToPage(store.currentPage + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </template>

      </div>
    </div>

    <!-- Detail Drawer -->
    <DetailDrawer :visible="drawerVisible" @close="closeDrawer">
      <ContentDetailPanel
        v-if="selectedId"
        :content-id="selectedId"
        @favorite="handleFavorite"
        @analyzed="fetchWithFilters"
      />
    </DetailDrawer>

    <!-- Confirm dialogs -->
    <ConfirmDialog
      :visible="showBatchDeleteDialog"
      title="批量删除"
      :message="`确定要删除选中的 ${selectedIds.length} 条内容吗？`"
      confirm-text="删除"
      :danger="true"
      @confirm="handleBatchDelete"
      @cancel="showBatchDeleteDialog = false"
    />

    <ConfirmDialog
      :visible="showDeleteAllDialog"
      title="清空全部内容"
      :message="`确定要删除全部 ${contentStats.total} 条内容吗？此操作将同时清除所有关联的流水线记录和媒体文件，不可恢复。`"
      confirm-text="清空全部"
      :danger="true"
      @confirm="handleDeleteAll"
      @cancel="showDeleteAllDialog = false"
    />
  </div>
</template>
