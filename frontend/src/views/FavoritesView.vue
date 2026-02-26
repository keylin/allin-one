<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listContent, toggleFavorite, batchMarkRead, incrementView } from '@/api/content'
import { listSources } from '@/api/sources'
import { useToast } from '@/composables/useToast'
import { formatTimeShort } from '@/utils/time'
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
let observer = null

// --- 移动端工具栏自动收起 ---
const scrollContainerRef = ref(null)
const toolbarCollapsed = ref(false)
let lastScrollTop = 0
const SCROLL_THRESHOLD = 8

function handleScroll() {
  const el = scrollContainerRef.value
  if (!el || window.innerWidth >= 768) return
  const st = el.scrollTop
  if (Math.abs(st - lastScrollTop) < SCROLL_THRESHOLD) return
  toolbarCollapsed.value = st > lastScrollTop && st > 40
  lastScrollTop = st
}

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
  { value: 'audio', label: '播客' },
  { value: 'image', label: '图片' },
  { value: 'ebook', label: '电子书' },
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

// --- 辅助判断 ---
function hasVideo(item) {
  return item.media_items?.some(m => m.media_type === 'video')
}
function hasAudio(item) {
  return item.media_items?.some(m => m.media_type === 'audio')
}
function hasImage(item) {
  return item.media_items?.some(m => m.media_type === 'image')
}
function hasThumbnail(item) {
  return item.has_thumbnail === true
}
function getContentId(item) {
  return item.id
}
function getVideoInfo(item) {
  const videoMedia = item.media_items?.find(m => m.media_type === 'video') || {}
  let duration = null
  if (videoMedia.metadata_json) {
    try { duration = JSON.parse(videoMedia.metadata_json).duration || null } catch { /* ignore */ }
  }
  return {
    platform: item.url?.includes('youtube') ? 'youtube' : item.url?.includes('bilibili') ? 'bilibili' : '',
    has_thumbnail: item.has_thumbnail,
    thumbnail_path: videoMedia.thumbnail_path,
    duration,
  }
}
function formatDuration(seconds) {
  if (!seconds) return ''
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

// --- Tab 计数（并行轻量请求） ---
const tabCounts = ref({ video: null, audio: null, image: null, ebook: null, article: null })

async function fetchTabCounts() {
  const base = { page: 1, page_size: 1, is_favorited: true }
  if (searchQuery.value.trim()) base.q = searchQuery.value.trim()
  if (filterSourceId.value) base.source_id = filterSourceId.value
  Object.assign(base, getDateRange())

  try {
    const [v, a, img, eb, art] = await Promise.all([
      listContent({ ...base, has_video: true }),
      listContent({ ...base, has_audio: true }),
      listContent({ ...base, has_image: true }),
      listContent({ ...base, has_ebook: true }),
      listContent({ ...base, has_video: false, has_audio: false, has_image: false, has_ebook: false }),
    ])
    tabCounts.value = {
      video: v.code === 0 ? v.total : null,
      audio: a.code === 0 ? a.total : null,
      image: img.code === 0 ? img.total : null,
      ebook: eb.code === 0 ? eb.total : null,
      article: art.code === 0 ? art.total : null,
    }
  } catch { /* non-fatal */ }
}

// --- 筛选状态 ---
const selectArrowStyle = "appearance:none; background-image:url(\"data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e\"); background-repeat:no-repeat; background-position:right 0.3rem center; background-size:1.2em 1.2em;"

const hasActiveFilters = computed(() =>
  !!(searchQuery.value || activeMediaType.value || filterSourceId.value || dateRange.value)
)

function clearFilters() {
  searchQuery.value = ''
  activeMediaType.value = ''
  filterSourceId.value = ''
  dateRange.value = ''
  currentSort.value = 'favorited_at:desc'
}

// --- 批量操作 ---
const selectedIds = ref([])
const showBatchBar = computed(() => selectedIds.value.length > 0)

// --- 详情弹层 ---
const modalVisible = ref(false)
const selectedId = ref(null)

const currentItemIndex = computed(() => {
  if (!selectedId.value) return -1
  return items.value.findIndex(i => i.id === selectedId.value)
})
const hasPrev = computed(() => currentItemIndex.value > 0)
const hasNext = computed(() => currentItemIndex.value < items.value.length - 1)

// --- 封面横竖屏检测 ---
const detectedOrientations = ref({})
function isPortrait(item) {
  return detectedOrientations.value[item.id] === 'portrait'
}
function onThumbnailLoad(event, itemId) {
  const img = event.target
  if (img.naturalHeight > img.naturalWidth) {
    detectedOrientations.value[itemId] = 'portrait'
  }
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
    if (activeMediaType.value === 'audio') params.has_audio = true
    if (activeMediaType.value === 'image') params.has_image = true
    if (activeMediaType.value === 'ebook') params.has_ebook = true
    if (activeMediaType.value === 'article') { params.has_video = false; params.has_audio = false; params.has_image = false; params.has_ebook = false }
    if (filterSourceId.value) params.source_id = filterSourceId.value
    if (!reset && items.value.length > 0) {
      params.cursor_id = items.value[items.value.length - 1].id
    }

    const res = await listContent(params)
    if (res.code === 0) {
      if (reset) {
        items.value = res.data
        totalCount.value = res.total
      } else {
        items.value = [...items.value, ...res.data]
      }
      hasMore.value = res.data.length >= pageSize
    }
  } finally {
    loading.value = false
    loadingMore.value = false
  }
  if (reset) syncQueryParams()
}

function loadMore() {
  if (!hasMore.value || loadingMore.value) return
  fetchItems()
}

// --- 筛选联动 ---
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { fetchItems(true); fetchTabCounts() }, 300)
})
watch([() => filterSourceId.value, () => dateRange.value], () => {
  fetchTabCounts()
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
        if (modalVisible.value && selectedId.value === id) {
          const idx = items.value.findIndex(i => i.id === id)
          if (idx < items.value.length - 1) selectedId.value = items.value[idx + 1].id
          else if (idx > 0) selectedId.value = items.value[idx - 1].id
          else closeModal()
        }
        // 乐观递减 Tab 计数
        const removedItem = items.value.find(i => i.id === id)
        if (removedItem) {
          if (hasVideo(removedItem) && tabCounts.value.video != null) tabCounts.value.video = Math.max(0, tabCounts.value.video - 1)
          else if (hasAudio(removedItem) && tabCounts.value.audio != null) tabCounts.value.audio = Math.max(0, tabCounts.value.audio - 1)
          else if (hasImage(removedItem) && tabCounts.value.image != null) tabCounts.value.image = Math.max(0, tabCounts.value.image - 1)
          else if (removedItem.content_type === 'ebook' && tabCounts.value.ebook != null) tabCounts.value.ebook = Math.max(0, tabCounts.value.ebook - 1)
          else if (tabCounts.value.article != null) tabCounts.value.article = Math.max(0, tabCounts.value.article - 1)
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
  fetchTabCounts()
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
  if (e.key === 'Escape' && modalVisible.value) closeModal()
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
  fetchTabCounts()
  try {
    const res = await listSources({ page_size: 100 })
    if (res.code === 0) sources.value = res.data
  } catch { /* ignore */ }
  nextTick(() => setupObserver())
  document.addEventListener('keydown', handleKeydown)
  scrollContainerRef.value?.addEventListener('scroll', handleScroll, { passive: true })
})

onUnmounted(() => {
  clearTimeout(searchTimer)
  document.removeEventListener('keydown', handleKeydown)
  scrollContainerRef.value?.removeEventListener('scroll', handleScroll)
  if (observer) observer.disconnect()
})
</script>

<template>
  <div class="flex flex-col h-full bg-slate-50">

    <!-- ══════════════════════════════════════════════
         Sticky 头部
         ══════════════════════════════════════════════ -->
    <div class="sticky top-0 z-10 bg-white/95 backdrop-blur-sm border-b border-slate-100 shrink-0">

      <!-- ── 移动端搜索框（仅移动端独占一行） ── -->
      <div
        class="px-4 pt-2.5 md:hidden transition-all duration-300 ease-in-out overflow-hidden"
        :class="toolbarCollapsed ? 'max-h-0 !pt-0 opacity-0' : 'max-h-20 opacity-100'"
      >
        <div class="relative">
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"/>
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索收藏内容..."
            class="w-full pl-9 pr-4 py-2 bg-slate-50 rounded-xl border border-slate-200 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 focus:bg-white transition-all duration-200"
          />
          <button
            v-if="searchQuery"
            class="absolute right-2.5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400 hover:text-slate-600 rounded-full hover:bg-slate-200 flex items-center justify-center transition-colors"
            @click="searchQuery = ''"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- ── 筛选工具栏（移动端单行，桌面端与搜索框合并） ── -->
      <div
        class="flex items-center gap-1.5 px-4 pt-2 pb-2.5 md:px-5 overflow-x-auto scrollbar-hide transition-all duration-300 ease-in-out md:!max-h-none md:!opacity-100 md:!pt-2.5 md:!pb-2.5"
        :class="toolbarCollapsed ? 'max-h-0 !pt-0 !pb-0 opacity-0 !overflow-hidden' : 'max-h-16 opacity-100'"
      >
        <!-- 桌面端搜索框（工具栏最前面） -->
        <div class="hidden md:block relative flex-shrink-0 w-48 lg:w-56">
          <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"/>
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索..."
            class="w-full pl-8 pr-7 py-1 bg-slate-50 rounded-lg border border-slate-200 text-xs text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 focus:bg-white transition-all duration-200"
          />
          <button
            v-if="searchQuery"
            class="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 hover:text-slate-600 rounded-full hover:bg-slate-200 flex items-center justify-center transition-colors"
            @click="searchQuery = ''"
          >
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <!-- 媒体类型 tabs -->
        <div class="flex items-center gap-1 flex-shrink-0">
          <button
            v-for="mt in mediaTypes"
            :key="mt.value"
            class="px-2.5 py-1 text-xs font-medium rounded-lg border transition-all duration-200 whitespace-nowrap inline-flex items-center gap-1"
            :class="activeMediaType === mt.value
              ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
              : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-700'"
            @click="activeMediaType = mt.value"
          >
            {{ mt.label }}
            <span
              v-if="mt.value ? tabCounts[mt.value] != null : (!loading && totalCount > 0)"
              class="text-[10px] tabular-nums"
              :class="activeMediaType === mt.value ? 'text-indigo-500' : 'text-slate-400'"
            >{{ mt.value ? tabCounts[mt.value] : totalCount }}</span>
          </button>
        </div>

        <!-- 来源 -->
        <select
          v-if="sources.length > 0"
          v-model="filterSourceId"
          class="flex-shrink-0 md:ml-auto pl-2.5 pr-6 py-1 text-xs font-medium border rounded-lg outline-none transition-all duration-200 cursor-pointer"
          :class="filterSourceId ? 'border-indigo-300 text-indigo-700 bg-indigo-50' : 'border-slate-200 text-slate-500 bg-white'"
          :style="selectArrowStyle"
        >
          <option value="">来源</option>
          <option v-for="s in sources" :key="s.id" :value="String(s.id)">{{ s.name }}</option>
        </select>

        <!-- 时间 -->
        <select
          v-model="dateRange"
          class="flex-shrink-0 pl-2.5 pr-6 py-1 text-xs font-medium border rounded-lg outline-none transition-all duration-200 cursor-pointer"
          :class="dateRange ? 'border-indigo-300 text-indigo-700 bg-indigo-50' : 'border-slate-200 text-slate-500 bg-white'"
          :style="selectArrowStyle"
        >
          <option v-for="opt in dateRangeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>

        <!-- 排序 -->
        <select
          v-model="currentSort"
          class="flex-shrink-0 pl-2.5 pr-6 py-1 text-xs font-medium border rounded-lg outline-none transition-all duration-200 cursor-pointer"
          :class="sortBy !== 'favorited_at' ? 'border-indigo-300 text-indigo-700 bg-indigo-50' : 'border-slate-200 text-slate-500 bg-white'"
          :style="selectArrowStyle"
        >
          <option v-for="opt in sortOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>

        <!-- 清除筛选 -->
        <button
          v-if="hasActiveFilters"
          class="flex-shrink-0 px-2.5 py-1 text-xs text-rose-500 hover:text-rose-700 hover:bg-rose-50 rounded-lg transition-colors font-medium whitespace-nowrap"
          @click="clearFilters"
        >清除</button>
      </div>
    </div>

    <!-- ══════════════════════════════════════════════
         内容区（可滚动）
         ══════════════════════════════════════════════ -->
    <div ref="scrollContainerRef" class="flex-1 overflow-y-auto overscroll-contain">
      <div class="px-3 py-4 md:px-5 md:py-5">

        <!-- ── 骨架屏 ── -->
        <div v-if="loading" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-3 md:gap-4">
          <!-- 视频骨架（前3个） -->
          <div v-for="i in 3" :key="'vsk-' + i" class="bg-white rounded-xl border border-slate-200/60 overflow-hidden animate-pulse">
            <div class="aspect-video bg-slate-100"/>
            <div class="p-3 space-y-2.5">
              <div class="h-3.5 bg-slate-100 rounded-md w-full"/>
              <div class="h-3.5 bg-slate-100 rounded-md w-4/5"/>
              <div class="flex items-center gap-2 pt-0.5">
                <div class="h-2.5 bg-slate-100 rounded w-14"/>
                <div class="h-2.5 bg-slate-100 rounded w-10"/>
              </div>
            </div>
          </div>
          <!-- 文章骨架（后9个） -->
          <div v-for="i in 9" :key="'ask-' + i" class="bg-white rounded-xl border border-slate-200/60 overflow-hidden animate-pulse h-[200px] flex flex-col">
            <div class="p-3.5 flex flex-col h-full">
              <div class="flex items-center gap-2 mb-2.5">
                <div class="h-2.5 bg-slate-100 rounded w-16"/>
                <div class="h-2 bg-slate-100 rounded w-10"/>
              </div>
              <div class="h-3.5 bg-slate-100 rounded-md w-full mb-1.5"/>
              <div class="h-3.5 bg-slate-100 rounded-md w-4/5 mb-2.5"/>
              <div class="h-2.5 bg-slate-100 rounded w-full mb-1.5"/>
              <div class="h-2.5 bg-slate-100 rounded w-3/4 mb-1.5"/>
              <div class="h-2.5 bg-slate-100 rounded w-1/2"/>
              <div class="mt-auto pt-2.5 flex gap-1.5">
                <div class="h-4 bg-slate-100 rounded-md w-12"/>
                <div class="h-4 bg-slate-100 rounded-md w-10"/>
              </div>
            </div>
          </div>
        </div>

        <!-- ── 空状态 ── -->
        <div v-else-if="items.length === 0" class="flex flex-col items-center justify-center py-20 px-6">

          <!-- 搜索/筛选无结果 -->
          <template v-if="hasActiveFilters">
            <div class="w-20 h-20 bg-slate-100 rounded-2xl flex items-center justify-center mb-5">
              <svg class="w-9 h-9 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"/>
              </svg>
            </div>
            <h3 class="text-base font-semibold text-slate-700 mb-1.5">没有找到匹配的收藏</h3>
            <p class="text-sm text-slate-400 text-center max-w-xs leading-relaxed mb-5">试试调整搜索词或筛选条件</p>
            <button
              class="inline-flex items-center gap-1.5 px-4 py-2 bg-slate-100 text-slate-600 text-sm font-medium rounded-xl hover:bg-slate-200 transition-colors"
              @click="clearFilters"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
              </svg>
              清除筛选条件
            </button>
          </template>

          <!-- 真正空状态 -->
          <template v-else>
            <div class="relative mb-5">
              <div class="w-24 h-24 bg-indigo-50 rounded-3xl flex items-center justify-center">
                <svg class="w-11 h-11 text-indigo-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/>
                </svg>
              </div>
              <!-- 装饰小星星 -->
              <div class="absolute -top-1.5 -right-2 w-8 h-8 bg-amber-50 rounded-xl flex items-center justify-center shadow-sm border border-amber-100">
                <svg class="w-4 h-4 text-amber-400" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/>
                </svg>
              </div>
            </div>
            <h3 class="text-base font-semibold text-slate-700 mb-2">还没有收藏内容</h3>
            <p class="text-sm text-slate-400 text-center max-w-xs leading-relaxed mb-6">
              在信息流中点击 ★ 即可收藏，<br>收藏的内容永久保留，不受自动清理影响。
            </p>
            <router-link
              to="/feed"
              class="inline-flex items-center gap-2 px-5 py-2.5 bg-indigo-600 text-white text-sm font-medium rounded-xl hover:bg-indigo-700 active:bg-indigo-800 transition-colors shadow-sm shadow-indigo-200"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"/>
              </svg>
              去信息流看看
            </router-link>
          </template>
        </div>

        <!-- ── 卡片网格 ── -->
        <template v-else>
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-3 md:gap-4">
            <div
              v-for="item in items"
              :key="item.id"
              class="group relative bg-white rounded-xl border overflow-hidden cursor-pointer transition-all duration-200 border-slate-200/60 hover:border-slate-300 hover:shadow-md hover:-translate-y-0.5 active:scale-[0.99]"
              :class="selectedIds.includes(item.id) ? 'ring-2 ring-indigo-400 border-indigo-300 shadow-sm' : ''"
              @click="selectItem(item)"
            >
              <!-- 选中复选框 -->
              <div
                class="hidden md:flex absolute top-2 right-2 z-10 transition-all duration-150"
                :class="showBatchBar || selectedIds.includes(item.id) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'"
                @click.stop="toggleSelect(item.id)"
              >
                <div
                  class="w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all duration-150 shadow-sm"
                  :class="selectedIds.includes(item.id)
                    ? 'bg-indigo-500 border-indigo-500'
                    : 'bg-white/90 border-slate-300 backdrop-blur-sm'"
                >
                  <svg v-if="selectedIds.includes(item.id)" class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="3">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/>
                  </svg>
                </div>
              </div>

              <!-- ════ 视频卡片 ════ -->
              <template v-if="hasVideo(item)">
                <!-- 封面 -->
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
                      <path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                    </svg>
                  </div>
                  <div class="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black/60 to-transparent pointer-events-none"/>
                  <div class="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-all duration-300 flex items-center justify-center">
                    <div class="w-11 h-11 bg-white/95 rounded-full flex items-center justify-center opacity-75 md:opacity-0 group-hover:opacity-100 scale-90 group-hover:scale-100 transition-all duration-300 shadow-lg">
                      <svg class="w-5 h-5 text-indigo-600 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M8 5v14l11-7z"/>
                      </svg>
                    </div>
                  </div>
                  <span v-if="getVideoInfo(item).duration" class="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 text-[10px] font-medium tabular-nums bg-black/70 text-white rounded backdrop-blur-sm">
                    {{ formatDuration(getVideoInfo(item).duration) }}
                  </span>
                  <span v-if="getVideoInfo(item).platform" class="absolute top-2 right-2 px-1.5 py-0.5 text-[10px] font-medium bg-white/80 text-slate-600 rounded capitalize backdrop-blur-sm group-hover:opacity-0 transition-opacity duration-200">
                    {{ getVideoInfo(item).platform }}
                  </span>
                </div>

                <!-- 视频信息 -->
                <div class="p-3">
                  <h4 class="text-[13px] font-semibold text-slate-800 line-clamp-2 leading-snug mb-2">
                    {{ item.title || '未知标题' }}
                  </h4>
                  <!-- Tags -->
                  <div v-if="item.tags && item.tags.length > 0" class="flex items-center gap-1 flex-wrap mb-2">
                    <span
                      v-for="tag in item.tags.slice(0, 2)"
                      :key="tag"
                      class="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-indigo-50 text-indigo-600"
                    >#{{ tag }}</span>
                  </div>
                  <!-- 元信息 -->
                  <div class="flex items-center justify-between text-[11px] text-slate-400">
                    <span class="truncate max-w-[100px] text-slate-500 font-medium">{{ item.source_name }}</span>
                    <div class="flex items-center gap-2 shrink-0">
                      <span v-if="item.view_count > 0" class="flex items-center gap-0.5">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                        </svg>
                        {{ item.view_count }}
                      </span>
                    </div>
                  </div>
                </div>
              </template>

              <!-- ════ 文章卡片（自适应高度） ════ -->
              <template v-else>
                <div class="flex flex-col">
                  <!-- 头部：来源 + 时间 -->
                  <div class="flex items-center justify-between px-3.5 pt-3 pb-0">
                    <div class="flex items-center gap-1.5 min-w-0 text-[11px] text-slate-400">
                      <span v-if="item.source_name" class="text-slate-500 font-medium truncate max-w-[90px]">{{ item.source_name }}</span>
                      <span v-if="item.source_name && (item.published_at || item.collected_at)" class="text-slate-200 shrink-0">&middot;</span>
                      <span class="shrink-0 whitespace-nowrap">{{ formatTimeShort(item.published_at || item.collected_at) }}</span>
                    </div>
                  </div>

                  <!-- 中部：标题 + 摘要 -->
                  <div class="px-3.5 pt-2">
                    <h4 class="text-[13px] font-semibold text-slate-800 line-clamp-2 leading-snug">
                      {{ item.title || '未知标题' }}
                    </h4>
                    <p class="text-[11px] text-slate-400 leading-relaxed line-clamp-3 mt-1.5">
                      {{ item.summary_text || item.processed_content?.substring(0, 200) || '暂无摘要' }}
                    </p>
                  </div>

                  <!-- 底部：tags + 浏览数 -->
                  <div class="flex items-center gap-1.5 px-3.5 pb-3 pt-1.5">
                    <div class="flex items-center gap-1 flex-1 min-w-0 overflow-hidden">
                      <template v-if="item.tags && item.tags.length > 0">
                        <span
                          v-for="tag in item.tags.slice(0, 3)"
                          :key="tag"
                          class="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-indigo-50 text-indigo-600 whitespace-nowrap"
                        >#{{ tag }}</span>
                      </template>
                      <span v-else class="text-[10px] text-slate-300">暂无标签</span>
                    </div>
                    <span v-if="item.view_count > 0" class="flex items-center gap-0.5 text-[11px] text-slate-400 shrink-0">
                      <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                      </svg>
                      {{ item.view_count }}
                    </span>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- 加载更多 -->
          <div v-if="loadingMore" class="flex items-center justify-center py-10">
            <div class="flex items-center gap-2.5 text-slate-400">
              <svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              <span class="text-xs">加载更多...</span>
            </div>
          </div>

          <!-- 已显示全部：分割线设计 -->
          <div v-else-if="!hasMore && items.length > 0" class="flex items-center gap-3 py-10 px-2">
            <div class="h-px flex-1 bg-slate-100"/>
            <span class="flex items-center gap-1.5 text-xs text-slate-400 whitespace-nowrap">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
              已显示全部 {{ totalCount }} 条收藏
            </span>
            <div class="h-px flex-1 bg-slate-100"/>
          </div>

          <!-- 无限滚动 sentinel -->
          <div ref="sentinelRef" class="h-1"/>
        </template>
      </div>
    </div>

    <!-- ══════════════════════════════════════════════
         批量操作浮层（底部，选中后滑入）
         ══════════════════════════════════════════════ -->
    <Transition
      enter-active-class="transition-transform duration-300 ease-out"
      leave-active-class="transition-transform duration-200 ease-in"
      enter-from-class="translate-y-full"
      enter-to-class="translate-y-0"
      leave-from-class="translate-y-0"
      leave-to-class="translate-y-full"
    >
      <div v-if="showBatchBar" class="hidden md:block shrink-0 bg-white border-t border-slate-200 shadow-lg px-4 py-3">
        <div class="flex items-center gap-2 max-w-4xl mx-auto">
          <div class="flex items-center gap-1.5 text-sm font-medium text-slate-700">
            <div class="w-5 h-5 bg-indigo-500 rounded-full flex items-center justify-center shrink-0">
              <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="3">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/>
              </svg>
            </div>
            已选 {{ selectedIds.length }} 条
          </div>
          <button
            class="text-xs text-slate-500 hover:text-slate-700 px-2.5 py-1.5 rounded-lg hover:bg-slate-50 transition-colors"
            @click="toggleSelectAll"
          >{{ selectedIds.length === items.length ? '取消全选' : '全选' }}</button>
          <div class="flex-1"/>
          <button
            class="text-xs font-medium text-slate-600 hover:text-slate-800 px-3 py-1.5 rounded-lg border border-slate-200 hover:border-slate-300 hover:bg-slate-50 transition-all"
            @click="handleBatchRead"
          >标记已读</button>
          <button
            class="text-xs font-medium text-rose-600 hover:text-rose-700 px-3 py-1.5 rounded-lg border border-rose-200 hover:border-rose-300 hover:bg-rose-50 transition-all"
            @click="handleBatchUnfavorite"
          >取消收藏</button>
          <button
            class="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-50 transition-colors"
            @click="selectedIds = []"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>
    </Transition>

    <!-- 详情弹层 -->
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
