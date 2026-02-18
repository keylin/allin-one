<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listContent, toggleFavorite, batchMarkRead, incrementView } from '@/api/content'
import { listSources } from '@/api/sources'
import { formatTimeShort } from '@/utils/time'
import { useToast } from '@/composables/useToast'
import ContentDetailModal from '@/components/content-detail-modal.vue'

const route = useRoute()
const router = useRouter()
const toast = useToast()

// --- 数据 & 状态 ---
const items = ref([])
const totalCount = ref(0)
const loading = ref(true)
const loadingMore = ref(false)
const page = ref(1)
const pageSize = 24
const hasMore = ref(true)
const sentinelRef = ref(null)
const mobileSearchInput = ref(null)
let observer = null

// --- 筛选 ---
const searchQuery = ref(route.query.q || '')
const activeMediaType = ref(route.query.media_type || '')
const filterSourceId = ref(route.query.source_id || '')
const dateRange = ref(route.query.date_range || '')
const sortBy = ref(route.query.sort_by || 'favorited_at')
const sortOrder = ref(route.query.sort_order || 'desc')
const sources = ref([])
let searchTimer = null

const mediaTypes = [
  { value: '', label: '全部' },
  { value: 'video', label: '视频' },
  { value: 'article', label: '文章' },
]

const dateRangeOptions = [
  { value: '', label: '全部时间' },
  { value: '1', label: '今天' },
  { value: '3', label: '近3天' },
  { value: '7', label: '近7天' },
  { value: '30', label: '近30天' },
]

const sortOptions = [
  { value: 'favorited_at:desc', label: '最近收藏' },
  { value: 'published_at:desc', label: '最新发布' },
  { value: 'collected_at:desc', label: '最新采集' },
  { value: 'view_count:desc', label: '最多浏览' },
]

const currentSort = computed({
  get: () => `${sortBy.value}:${sortOrder.value}`,
  set: (val) => {
    const [field, order] = val.split(':')
    sortBy.value = field
    sortOrder.value = order
  },
})

// --- 移动端筛选状态 ---
const mobileSearchOpen = ref(false)
const mobileFilterOpen = ref(false)

function toggleMobileSearch() {
  mobileSearchOpen.value = !mobileSearchOpen.value
  if (mobileSearchOpen.value) {
    mobileFilterOpen.value = false
    nextTick(() => mobileSearchInput.value?.focus())
  }
}

function closeMobileSearch() {
  mobileSearchOpen.value = false
  if (!searchQuery.value) searchQuery.value = ''
}

function toggleMobileFilter() {
  mobileFilterOpen.value = !mobileFilterOpen.value
  if (mobileFilterOpen.value) mobileSearchOpen.value = false
}

// 活跃筛选器数量（移动端角标）
const activeFilterCount = computed(() => {
  let count = 0
  if (filterSourceId.value) count++
  if (dateRange.value) count++
  if (sortBy.value !== 'favorited_at') count++
  return count
})

// --- 批量操作 ---
const selectedIds = ref([])

// --- 详情弹层 ---
const modalVisible = ref(false)
const selectedId = ref(null)

const currentItemIndex = computed(() => {
  if (!selectedId.value) return -1
  return items.value.findIndex(i => i.id === selectedId.value)
})
const hasPrev = computed(() => currentItemIndex.value > 0)
const hasNext = computed(() => currentItemIndex.value < items.value.length - 1)

// --- 辅助计算 ---
function hasVideo(item) {
  return item.media_items?.some(m => m.media_type === 'video')
}

function hasThumbnail(item) {
  // content API 的 has_thumbnail 在顶层
  return item.has_thumbnail === true
}

function getContentId(item) {
  return item.id
}

function getVideoInfo(item) {
  // content API 没有嵌套 video_info，信息在顶层和 media_items 中
  const videoMedia = item.media_items?.find(m => m.media_type === 'video') || {}
  return {
    platform: item.url?.includes('youtube') ? 'youtube' : item.url?.includes('bilibili') ? 'bilibili' : '',
    has_thumbnail: item.has_thumbnail,
    thumbnail_path: videoMedia.thumbnail_path,
  }
}

function formatDuration(seconds) {
  if (!seconds) return ''
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

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

// 文章卡片主题色 — 根据来源名散列
const accentColors = [
  { bg: 'bg-indigo-500', light: 'bg-indigo-50', text: 'text-indigo-600' },
  { bg: 'bg-violet-500', light: 'bg-violet-50', text: 'text-violet-600' },
  { bg: 'bg-sky-500', light: 'bg-sky-50', text: 'text-sky-600' },
  { bg: 'bg-emerald-500', light: 'bg-emerald-50', text: 'text-emerald-600' },
  { bg: 'bg-amber-500', light: 'bg-amber-50', text: 'text-amber-600' },
  { bg: 'bg-rose-500', light: 'bg-rose-50', text: 'text-rose-600' },
  { bg: 'bg-teal-500', light: 'bg-teal-50', text: 'text-teal-600' },
  { bg: 'bg-fuchsia-500', light: 'bg-fuchsia-50', text: 'text-fuchsia-600' },
]
function getAccentColor(item) {
  const name = item.source_name || item.title || ''
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = ((hash << 5) - hash) + name.charCodeAt(i)
  return accentColors[Math.abs(hash) % accentColors.length]
}

// --- URL 同步 ---
function syncQueryParams() {
  const query = {}
  if (searchQuery.value) query.q = searchQuery.value
  if (activeMediaType.value) query.media_type = activeMediaType.value
  if (filterSourceId.value) query.source_id = filterSourceId.value
  if (dateRange.value) query.date_range = dateRange.value
  if (sortBy.value !== 'favorited_at') query.sort_by = sortBy.value
  if (sortOrder.value !== 'desc') query.sort_order = sortOrder.value
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

// --- 数据获取 ---
async function fetchItems(reset = false) {
  if (reset) {
    page.value = 1
    items.value = []
    hasMore.value = true
    loading.value = true
    selectedIds.value = []
  } else {
    loadingMore.value = true
  }

  try {
    const params = {
      page: page.value,
      page_size: pageSize,
      is_favorited: true,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
      ...getDateRange(),
    }
    if (searchQuery.value.trim()) params.q = searchQuery.value.trim()
    if (activeMediaType.value === 'video') params.has_video = true
    if (activeMediaType.value === 'article') params.has_video = false
    if (filterSourceId.value) params.source_id = filterSourceId.value

    const res = await listContent(params)
    if (res.code === 0) {
      if (reset) {
        items.value = res.data
        totalCount.value = res.total
      } else {
        items.value = [...items.value, ...res.data]
      }
      hasMore.value = items.value.length < res.total
    }
  } finally {
    loading.value = false
    loadingMore.value = false
  }
  if (reset) syncQueryParams()
}

function loadMore() {
  if (!hasMore.value || loadingMore.value) return
  page.value++
  fetchItems()
}

// --- 筛选联动 ---
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => fetchItems(true), 300)
})

watch([() => activeMediaType.value, () => filterSourceId.value, () => dateRange.value, currentSort], () => {
  fetchItems(true)
})

// --- 收藏操作（乐观更新） ---
async function handleFavorite(id) {
  const item = items.value.find(i => i.id === id)
  if (!item) return

  const wasFavorited = item.is_favorited
  item.is_favorited = !wasFavorited

  try {
    const res = await toggleFavorite(id)
    if (res.code === 0) {
      item.is_favorited = res.data.is_favorited
      if (!res.data.is_favorited) {
        // 如果弹层正在显示该条目，先导航到下一条或关闭
        if (modalVisible.value && selectedId.value === id) {
          const idx = items.value.findIndex(i => i.id === id)
          if (idx < items.value.length - 1) {
            selectedId.value = items.value[idx + 1].id
          } else if (idx > 0) {
            selectedId.value = items.value[idx - 1].id
          } else {
            closeModal()
          }
        }
        items.value = items.value.filter(i => i.id !== id)
        totalCount.value = Math.max(0, totalCount.value - 1)
        toast.success('已取消收藏')
      }
    } else {
      item.is_favorited = wasFavorited
      toast.error('操作失败')
    }
  } catch {
    item.is_favorited = wasFavorited
    toast.error('网络错误')
  }
}

// --- 批量操作 ---
function toggleSelect(id, event) {
  if (event) event.stopPropagation()
  const idx = selectedIds.value.indexOf(id)
  if (idx > -1) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

function toggleSelectAll() {
  if (selectedIds.value.length === items.value.length) {
    selectedIds.value = []
  } else {
    selectedIds.value = items.value.map(i => i.id)
  }
}

async function handleBatchUnfavorite() {
  const ids = [...selectedIds.value]
  for (const id of ids) {
    try { await toggleFavorite(id) } catch { /* continue */ }
  }
  items.value = items.value.filter(i => !ids.includes(i.id))
  totalCount.value = Math.max(0, totalCount.value - ids.length)
  selectedIds.value = []
  toast.success(`已取消 ${ids.length} 条收藏`)
}

async function handleBatchRead() {
  await batchMarkRead(selectedIds.value)
  selectedIds.value = []
  fetchItems(true)
  toast.success('已标记为已读')
}

// --- 详情弹层 ---
function selectItem(item) {
  selectedId.value = item.id
  modalVisible.value = true
  incrementView(item.id).catch(() => {})
}

function closeModal() {
  modalVisible.value = false
}

function goToPrev() {
  const idx = currentItemIndex.value
  if (idx > 0) {
    selectedId.value = items.value[idx - 1].id
    incrementView(items.value[idx - 1].id).catch(() => {})
  }
}

function goToNext() {
  const idx = currentItemIndex.value
  if (idx < items.value.length - 1) {
    selectedId.value = items.value[idx + 1].id
    incrementView(items.value[idx + 1].id).catch(() => {})
    if (idx + 1 >= items.value.length - 3 && hasMore.value) loadMore()
  }
}

// --- 键盘导航 ---
function handleKeydown(e) {
  const tag = e.target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
  if (e.key === 'Escape' && modalVisible.value) {
    closeModal()
    return
  }
}

// --- 封面加载检测（横竖屏） ---
const detectedOrientations = ref({})
function isPortrait(item) {
  const info = getVideoInfo(item)
  const w = info.width
  const h = info.height
  if (w && h) return h > w
  return detectedOrientations.value[item.id] === 'portrait'
}

function onThumbnailLoad(event, itemId) {
  const img = event.target
  if (img.naturalHeight > img.naturalWidth) {
    detectedOrientations.value[itemId] = 'portrait'
  }
}

function formatTime(t) {
  return formatTimeShort(t)
}

// --- IntersectionObserver 无限滚动 ---
function setupObserver() {
  if (observer) observer.disconnect()
  observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) loadMore()
  }, { threshold: 0 })
  if (sentinelRef.value) observer.observe(sentinelRef.value)
}

onMounted(async () => {
  fetchItems(true)
  try {
    const res = await listSources({ page_size: 100 })
    if (res.code === 0) sources.value = res.data
  } catch { /* ignore */ }
  nextTick(() => setupObserver())
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  clearTimeout(searchTimer)
  document.removeEventListener('keydown', handleKeydown)
  if (observer) observer.disconnect()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- ═══════════ Sticky header ═══════════ -->
    <div class="sticky top-0 bg-white z-10 border-b border-slate-100 shrink-0">

      <!-- ── 移动端工具栏 (<md) ── -->
      <div class="md:hidden">
        <!-- 主行: 搜索展开态 -->
        <div v-if="mobileSearchOpen" class="flex items-center gap-2 px-3 py-2.5">
          <div class="relative flex-1">
            <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              v-model="searchQuery"
              ref="mobileSearchInput"
              type="text"
              placeholder="搜索收藏内容..."
              class="w-full bg-slate-50 rounded-lg pl-8 pr-3 py-2 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all"
              @keydown.escape="closeMobileSearch"
            />
          </div>
          <button
            class="shrink-0 p-2 text-slate-400 hover:text-slate-600 transition-colors"
            @click="closeMobileSearch"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- 主行: 默认紧凑态 -->
        <div v-else class="flex items-center gap-1.5 px-3 py-2.5">
          <!-- 类型 pills -->
          <div class="flex items-center gap-1">
            <button
              v-for="mt in mediaTypes"
              :key="mt.value"
              class="px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200"
              :class="activeMediaType === mt.value
                ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
                : 'bg-white border-slate-200 text-slate-500'"
              @click="activeMediaType = mt.value"
            >
              {{ mt.label }}
            </button>
          </div>

          <div class="flex-1" />

          <!-- 搜索按钮 -->
          <button
            class="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-all"
            :class="searchQuery ? 'text-indigo-600 bg-indigo-50' : ''"
            @click="toggleMobileSearch"
          >
            <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
          </button>

          <!-- 筛选按钮 -->
          <button
            class="relative p-2 rounded-lg transition-all"
            :class="mobileFilterOpen || activeFilterCount > 0
              ? 'text-indigo-600 bg-indigo-50'
              : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'"
            @click="toggleMobileFilter"
          >
            <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
            </svg>
            <!-- 活跃筛选角标 -->
            <span
              v-if="activeFilterCount > 0"
              class="absolute -top-0.5 -right-0.5 w-4 h-4 bg-indigo-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center"
            >{{ activeFilterCount }}</span>
          </button>

          <!-- 总数 -->
          <span class="text-xs text-slate-400 whitespace-nowrap ml-1">{{ totalCount }}条</span>
        </div>

        <!-- 筛选面板 (slide-down) -->
        <Transition
          enter-active-class="transition-all duration-200 ease-out"
          leave-active-class="transition-all duration-150 ease-in"
          enter-from-class="opacity-0 -translate-y-2 max-h-0"
          enter-to-class="opacity-100 translate-y-0 max-h-60"
          leave-from-class="opacity-100 translate-y-0 max-h-60"
          leave-to-class="opacity-0 -translate-y-2 max-h-0"
        >
          <div v-if="mobileFilterOpen" class="overflow-hidden border-t border-slate-100 bg-slate-50/50 px-3 py-3 space-y-3">
            <!-- 来源 -->
            <div v-if="sources.length > 0" class="flex items-center gap-2">
              <span class="text-xs text-slate-500 w-10 shrink-0">来源</span>
              <select
                v-model="filterSourceId"
                class="flex-1 px-3 py-2 text-xs font-medium bg-white border border-slate-200 rounded-lg text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all"
              >
                <option value="">全部来源</option>
                <option v-for="s in sources" :key="s.id" :value="String(s.id)">{{ s.name }}</option>
              </select>
            </div>

            <!-- 时间 -->
            <div class="flex items-center gap-2">
              <span class="text-xs text-slate-500 w-10 shrink-0">时间</span>
              <select
                v-model="dateRange"
                class="flex-1 px-3 py-2 text-xs font-medium bg-white border border-slate-200 rounded-lg text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all"
              >
                <option v-for="opt in dateRangeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </div>

            <!-- 排序 2×2 网格 -->
            <div class="flex items-start gap-2">
              <span class="text-xs text-slate-500 w-10 shrink-0 pt-2">排序</span>
              <div class="flex-1 grid grid-cols-2 gap-1.5">
                <button
                  v-for="opt in sortOptions"
                  :key="opt.value"
                  class="px-2.5 py-2 text-xs font-medium rounded-lg border transition-all duration-200 text-center"
                  :class="currentSort === opt.value
                    ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
                    : 'bg-white border-slate-200 text-slate-500'"
                  @click="currentSort = opt.value"
                >
                  {{ opt.label }}
                </button>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- ── 桌面端工具栏 (>=md) ── -->
      <div class="hidden md:block px-4 pt-3 pb-2">
        <div class="flex flex-wrap items-center gap-3">
          <!-- 搜索 -->
          <div class="relative flex-1 min-w-[200px] max-w-sm">
            <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              v-model="searchQuery"
              type="text"
              placeholder="搜索收藏内容..."
              class="w-full bg-white rounded-lg pl-9 pr-3 py-2 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all"
            />
          </div>

          <!-- 类型 pills -->
          <div class="flex items-center gap-1">
            <button
              v-for="mt in mediaTypes"
              :key="mt.value"
              class="px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200"
              :class="activeMediaType === mt.value
                ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
                : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'"
              @click="activeMediaType = mt.value"
            >
              {{ mt.label }}
            </button>
          </div>

          <!-- 来源 -->
          <select
            v-if="sources.length > 0"
            v-model="filterSourceId"
            class="px-3 py-1.5 text-xs font-medium bg-white border border-slate-200 rounded-lg text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all"
          >
            <option value="">全部来源</option>
            <option v-for="s in sources" :key="s.id" :value="String(s.id)">{{ s.name }}</option>
          </select>

          <!-- 时间范围 -->
          <select
            v-model="dateRange"
            class="px-3 py-1.5 text-xs font-medium bg-white border border-slate-200 rounded-lg text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all"
          >
            <option v-for="opt in dateRangeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>

          <!-- 排序 pills + 总数 -->
          <div class="flex items-center gap-1 ml-auto">
            <button
              v-for="opt in sortOptions"
              :key="opt.value"
              class="px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200"
              :class="currentSort === opt.value
                ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
                : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'"
              @click="currentSort = opt.value"
            >
              {{ opt.label }}
            </button>
            <span class="text-xs text-slate-400 ml-2 whitespace-nowrap">{{ totalCount }} 条收藏</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Scrollable content -->
    <div class="flex-1 overflow-y-auto">
      <div class="px-3 py-3 md:px-4 md:py-4">
        <!-- Loading -->
        <div v-if="loading" class="flex items-center justify-center py-24">
          <svg class="w-8 h-8 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <!-- Empty -->
        <div v-else-if="items.length === 0" class="text-center py-24">
          <div class="w-16 h-16 mx-auto mb-4 bg-slate-100 rounded-2xl flex items-center justify-center">
            <svg class="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
              <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
            </svg>
          </div>
          <p class="text-sm text-slate-500 font-medium mb-1">
            {{ searchQuery || activeMediaType || filterSourceId ? '没有找到匹配的收藏' : '还没有收藏内容' }}
          </p>
          <p class="text-xs text-slate-400">
            {{ searchQuery || activeMediaType || filterSourceId ? '试试调整筛选条件' : '在信息流中点击星标即可收藏' }}
          </p>
        </div>

        <!-- 卡片网格 -->
        <template v-else>
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-3 md:gap-4">
            <div
              v-for="item in items"
              :key="item.id"
              class="group relative bg-white rounded-xl border overflow-hidden cursor-pointer transition-all duration-300 border-slate-200/60 hover:border-slate-300 hover:shadow-lg hover:-translate-y-0.5 active:scale-[0.98] active:shadow-sm"
              @click="selectItem(item)"
            >
              <!-- ═══════════ 视频卡片 ═══════════ -->
              <template v-if="hasVideo(item)">
                <!-- 封面区域 -->
                <div class="aspect-video bg-gradient-to-br from-slate-800 to-slate-900 relative overflow-hidden">
                  <img
                    v-if="hasThumbnail(item)"
                    :src="`/api/video/${getContentId(item)}/thumbnail`"
                    class="absolute inset-0 w-full h-full transition-transform duration-500 group-hover:scale-105"
                    :class="isPortrait(item) ? 'object-contain' : 'object-cover'"
                    loading="lazy"
                    @load="onThumbnailLoad($event, item.id)"
                    @error="$event.target.style.display='none'"
                  />
                  <div v-else class="absolute inset-0 flex items-center justify-center">
                    <svg class="w-10 h-10 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  </div>

                  <!-- 底部渐变遮罩 -->
                  <div class="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black/60 to-transparent pointer-events-none" />

                  <!-- 悬浮播放按钮 -->
                  <div class="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-all duration-300 flex items-center justify-center">
                    <div class="w-12 h-12 bg-white/95 rounded-full flex items-center justify-center opacity-70 md:opacity-0 group-hover:opacity-100 transform scale-90 md:scale-75 group-hover:scale-100 transition-all duration-300 shadow-xl backdrop-blur-sm">
                      <svg class="w-5 h-5 text-indigo-600 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M8 5v14l11-7z" />
                      </svg>
                    </div>
                  </div>

                  <!-- 时长角标 -->
                  <span
                    v-if="getVideoInfo(item).duration"
                    class="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 text-[10px] font-medium bg-black/70 text-white rounded backdrop-blur-sm"
                  >
                    {{ formatDuration(getVideoInfo(item).duration) }}
                  </span>



                  <!-- 平台标签 -->
                  <span
                    v-if="getVideoInfo(item).platform"
                    class="absolute top-2 right-2 px-1.5 py-0.5 text-[10px] font-medium bg-white/80 text-slate-600 rounded capitalize backdrop-blur-sm group-hover:opacity-0 transition-opacity duration-200"
                  >
                    {{ getVideoInfo(item).platform }}
                  </span>


                </div>

                <!-- 视频信息 -->
                <div class="p-3">
                  <h4 class="text-sm font-medium text-slate-800 line-clamp-2 leading-snug min-h-[2.5rem]">
                    {{ item.title || '未知标题' }}
                  </h4>
                  <div class="mt-2 flex items-center justify-between text-[11px] text-slate-400">
                    <div class="flex items-center gap-1.5 min-w-0">
                      <span v-if="item.source_name" class="truncate max-w-[90px]">{{ item.source_name }}</span>
                      <span v-if="item.source_name && (item.published_at || item.collected_at)" class="text-slate-200">·</span>
                      <span v-if="item.published_at">{{ formatTime(item.published_at) }}</span>
                      <span v-else-if="item.collected_at" class="text-slate-300">{{ formatTime(item.collected_at) }}</span>
                    </div>
                    <div class="flex items-center gap-2 shrink-0">
                      <span v-if="item.view_count" class="inline-flex items-center gap-0.5">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                        {{ item.view_count }}
                      </span>
                      <span v-if="item.favorited_at" class="inline-flex items-center gap-0.5">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" /></svg>
                        {{ formatTime(item.favorited_at) }}
                      </span>
                      <span
                        v-if="item.status && item.status !== 'pending'"
                        class="inline-flex px-1.5 py-0.5 text-[10px] font-medium rounded"
                        :class="statusStyles[item.status] || 'bg-slate-100 text-slate-600'"
                      >
                        {{ statusLabels[item.status] || item.status }}
                      </span>
                    </div>
                  </div>
                </div>
              </template>

              <!-- ═══════════ 文章（信息）卡片 ═══════════ -->
              <template v-else>
                <div class="flex flex-col h-full">
                  <!-- 顶部色带 -->
                  <div class="h-1 w-full" :class="getAccentColor(item).bg" />

                  <div class="p-3.5 flex flex-col flex-1">
                    <!-- 来源标签 -->
                    <div class="flex items-center justify-between gap-2 mb-2">
                      <span
                        v-if="item.source_name"
                        class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full"
                        :class="[getAccentColor(item).light, getAccentColor(item).text]"
                      >
                        <svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                        </svg>
                        {{ item.source_name }}
                      </span>
                      <div class="flex items-center gap-1">
                        <span
                          v-if="item.status && item.status !== 'pending'"
                          class="inline-flex px-1.5 py-0.5 text-[10px] font-medium rounded"
                          :class="statusStyles[item.status] || 'bg-slate-100 text-slate-600'"
                        >
                          {{ statusLabels[item.status] || item.status }}
                        </span>

                      </div>
                    </div>

                    <!-- 标题 -->
                    <h4 class="text-[13px] font-semibold text-slate-800 line-clamp-2 leading-snug mb-1.5">
                      {{ item.title || '未知标题' }}
                    </h4>

                    <!-- 摘要 -->
                    <p class="text-xs text-slate-400 line-clamp-3 leading-relaxed flex-1 mb-2">
                      {{ item.summary_text || item.processed_content?.substring(0, 150) || '暂无摘要' }}
                    </p>

                    <!-- 底部元信息 -->
                    <div class="flex items-center justify-between pt-2 border-t border-slate-100">
                      <div class="flex items-center gap-2 text-[10px] text-slate-400">
                        <span v-if="item.published_at">发布 {{ formatTime(item.published_at) }}</span>
                        <span v-if="item.view_count" class="inline-flex items-center gap-0.5">
                          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                          {{ item.view_count }}
                        </span>
                        <span v-if="item.favorited_at" class="inline-flex items-center gap-0.5">
                          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" /></svg>
                          收藏 {{ formatTime(item.favorited_at) }}
                        </span>
                      </div>

                    </div>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- 加载更多 -->
          <div v-if="loadingMore" class="flex items-center justify-center py-8">
            <svg class="w-6 h-6 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
          </div>
          <div v-else-if="!hasMore && items.length > 0" class="text-center py-8">
            <div class="inline-flex items-center gap-2 px-4 py-2 bg-slate-100 rounded-full text-xs text-slate-500">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              已显示全部收藏
            </div>
          </div>

          <!-- sentinel for infinite scroll -->
          <div ref="sentinelRef" class="h-1" />
        </template>
      </div>
    </div>

    <!-- Detail Modal -->
    <ContentDetailModal
      :visible="modalVisible"
      :content-id="String(selectedId || '')"
      :has-prev="hasPrev"
      :has-next="hasNext"
      :current-index="currentItemIndex"
      :total-count="items.length"
      @close="closeModal"
      @prev="goToPrev"
      @next="goToNext"
      @favorite="handleFavorite"
    />
  </div>
</template>
