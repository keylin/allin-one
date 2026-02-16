<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listContent, getContent, analyzeContent, toggleFavorite, listSourceOptions, incrementView, enrichContent, applyEnrichment, getContentStats } from '@/api/content'
import { useToast } from '@/composables/useToast'
import { useSwipe } from '@/composables/useSwipe'
import { useAutoRead } from '@/composables/useAutoRead'
import { useFeedChat } from '@/composables/useFeedChat'
import FeedCard from '@/components/feed-card.vue'
import DetailContent from '@/components/feed/detail-content.vue'
import ChatPanel from '@/components/feed/chat-panel.vue'

const route = useRoute()
const router = useRouter()

// --- List state ---
const items = ref([])
const totalCount = ref(0)
const contentStats = ref({ read: 0, unread: 0, total: 0 })
const loading = ref(true)
const loadingMore = ref(false)
const page = ref(1)
const pageSize = 20
const hasMore = ref(true)
const activeMediaType = ref(route.query.has_video === '1' ? 'video' : '')
const sortBy = ref(route.query.sort_by || 'published_at')

// 搜索 & 筛选
const searchQuery = ref(route.query.q || '')
const filterSources = ref(route.query.source_id ? route.query.source_id.split(',') : [])
const filterStatus = ref(route.query.status || '')
const showFavoritesOnly = ref(route.query.favorites === '1')
const showUnreadOnly = ref(route.query.unread !== '0')
const sourceOptions = ref([])
const showSourceDropdown = ref(false)
let searchTimer = null

// 滚动容器 ref
const leftPanelRef = ref(null)
const rightPanelRef = ref(null)

const mediaTypes = [
  { value: '', label: '全部' },
  { value: 'video', label: '有视频' },
]

const sortOptions = [
  { value: 'published_at', label: '发布时间' },
  { value: 'collected_at', label: '采集时间' },
  { value: 'updated_at', label: '更新时间' },
]

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'analyzed', label: '已分析' },
  { value: 'pending', label: '待处理' },
  { value: 'failed', label: '失败' },
]

// --- Detail state ---
const selectedId = ref(null)
const detailContent = ref(null)
const detailLoading = ref(false)
const analyzing = ref(false)
let detailRequestId = 0

// --- Toast ---
const { success: toastSuccess, error: toastError } = useToast()

// --- Enrich state ---
const enriching = ref(false)
const enrichResults = ref(null)
const showEnrichModal = ref(false)
const applyingEnrich = ref(null)

// --- Detail content ref ---
const detailContentRef = ref(null)
const mobileDetailContentRef = ref(null)

// --- Mobile detail overlay ---
const showMobileDetail = ref(false)
const mobileDetailRef = ref(null)

// --- Chat composable ---
const {
  chatMessages,
  chatInput,
  chatStreaming,
  chatInputRef,
  chatMessagesEndRef,
  cancelChat,
  clearChat,
  sendChat,
  handleChatKeydown,
  renderChatMarkdown,
} = useFeedChat({
  getContentId: () => selectedId.value,
})

// --- Auto-read composable ---
const { handleScrollBottom } = useAutoRead({
  items,
  leftPanelRef,
  loadStats,
})

// 是否有活跃筛选
const hasActiveFilters = computed(() => {
  return searchQuery.value.trim() || filterSources.value.length > 0 || filterStatus.value || showFavoritesOnly.value || showUnreadOnly.value
})

const activeSourceNames = computed(() => {
  if (!filterSources.value.length) return []
  return filterSources.value.map(id => {
    const s = sourceOptions.value.find(o => String(o.id) === id)
    return s ? s.name : id
  })
})

function toggleSourceFilter(id) {
  const strId = String(id)
  const idx = filterSources.value.indexOf(strId)
  if (idx === -1) {
    filterSources.value = [...filterSources.value, strId]
  } else {
    filterSources.value = filterSources.value.filter(s => s !== strId)
  }
}

function clearSources() {
  filterSources.value = []
}

// 选中项在列表中的 index
const selectedIndex = computed(() => {
  if (!selectedId.value) return -1
  return items.value.findIndex(i => i.id === selectedId.value)
})

// --- List methods ---
function syncQueryParams() {
  const query = {}
  if (searchQuery.value) query.q = searchQuery.value
  if (filterSources.value.length) query.source_id = filterSources.value.join(',')
  if (filterStatus.value) query.status = filterStatus.value
  if (activeMediaType.value === 'video') query.has_video = '1'
  if (sortBy.value !== 'published_at') query.sort_by = sortBy.value
  if (showFavoritesOnly.value) query.favorites = '1'
  if (!showUnreadOnly.value) query.unread = '0'
  router.replace({ query }).catch(() => {})
}

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
    if (activeMediaType.value === 'video') params.has_video = true
    if (searchQuery.value.trim()) params.q = searchQuery.value.trim()
    if (filterSources.value.length) params.source_id = filterSources.value.join(',')
    if (filterStatus.value) params.status = filterStatus.value
    if (showFavoritesOnly.value) params.is_favorited = true
    if (showUnreadOnly.value) params.is_unread = true

    const res = await listContent(params)
    if (res.code === 0) {
      if (reset) {
        items.value = res.data
        totalCount.value = res.total
      } else {
        items.value.push(...res.data)
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

// 筛选联动
watch([filterSources, filterStatus, showFavoritesOnly, showUnreadOnly], () => {
  fetchItems(true)
})

// 清除筛选
function clearSearch() { searchQuery.value = ''; fetchItems(true) }
function clearStatus() { filterStatus.value = '' }
function clearFavorites() { showFavoritesOnly.value = false }
function clearUnread() { showUnreadOnly.value = false }
function toggleFavorites() {
  showFavoritesOnly.value = !showFavoritesOnly.value
  if (showFavoritesOnly.value) showUnreadOnly.value = false
}
function toggleUnread() {
  showUnreadOnly.value = !showUnreadOnly.value
  if (showUnreadOnly.value) showFavoritesOnly.value = false
}
function clearAllFilters() {
  searchQuery.value = ''
  filterSources.value = []
  filterStatus.value = ''
  showFavoritesOnly.value = false
  showUnreadOnly.value = false
  fetchItems(true)
}

// --- Detail methods ---
async function loadDetail(id) {
  if (!id) return
  const requestId = ++detailRequestId
  detailLoading.value = true
  try {
    const res = await getContent(id)
    if (requestId !== detailRequestId) return
    if (res.code === 0) detailContent.value = res.data
  } finally {
    if (requestId === detailRequestId) {
      detailLoading.value = false
    }
  }
}

function selectItem(item) {
  selectedId.value = item.id
  showMobileDetail.value = true
  // Reset view mode on sub-components
  if (detailContentRef.value) detailContentRef.value.resetViewMode()
  if (mobileDetailContentRef.value) mobileDetailContentRef.value.resetViewMode()
  clearChat()
  // 右栏滚回顶部
  if (rightPanelRef.value) rightPanelRef.value.scrollTop = 0
  incrementView(item.id).then(() => {
    if (!item.view_count || item.view_count === 0) {
      loadStats()
    }
  }).catch(() => {})
  loadDetail(item.id)
}

function closeMobileDetail() {
  showMobileDetail.value = false
}

async function handleFavorite(id) {
  const res = await toggleFavorite(id)
  if (res.code === 0) {
    const item = items.value.find(i => i.id === id)
    if (item) item.is_favorited = res.data.is_favorited
    if (detailContent.value && detailContent.value.id === id) {
      detailContent.value.is_favorited = res.data.is_favorited
    }
  }
}

async function handleDetailFavorite() {
  if (!selectedId.value) return
  await handleFavorite(selectedId.value)
}

async function handleAnalyze() {
  if (!selectedId.value || analyzing.value) return
  analyzing.value = true
  try {
    await analyzeContent(selectedId.value)
    await loadDetail(selectedId.value)
  } finally {
    analyzing.value = false
  }
}

// --- Enrich methods ---
async function handleEnrich() {
  if (!selectedId.value || enriching.value || !detailContent.value?.url) return
  showEnrichModal.value = true
  enriching.value = true
  enrichResults.value = null
  try {
    const res = await enrichContent(selectedId.value)
    if (res.code === 0) {
      enrichResults.value = res.data.results
    } else {
      toastError(res.message || '富化对比失败')
      showEnrichModal.value = false
    }
  } catch (e) {
    toastError('富化对比请求失败')
    showEnrichModal.value = false
  } finally {
    enriching.value = false
  }
}

async function handleApplyEnrich(result) {
  if (!selectedId.value || !result.content) return
  applyingEnrich.value = result.level
  try {
    const res = await applyEnrichment(selectedId.value, result.content, result.label)
    if (res.code === 0) {
      toastSuccess('已应用富化结果')
      showEnrichModal.value = false
      enrichResults.value = null
      await loadDetail(selectedId.value)
    } else {
      toastError(res.message || '应用失败')
    }
  } catch {
    toastError('应用富化结果失败')
  } finally {
    applyingEnrich.value = null
  }
}

function closeEnrichModal() {
  showEnrichModal.value = false
  enrichResults.value = null
  enriching.value = false
}

// --- Left panel scroll → infinite load ---
function handleLeftScroll(e) {
  const el = e.target
  const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight

  if (distanceToBottom < 200) {
    loadMore()
  }

  handleScrollBottom(distanceToBottom)
}

// --- Keyboard navigation (arrow up/down) ---
function handleKeydown(e) {
  const tag = e.target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    const idx = selectedIndex.value
    if (idx < items.value.length - 1) {
      const nextItem = items.value[idx + 1]
      selectItem(nextItem)
      if (idx + 1 >= items.value.length - 3 && hasMore.value) loadMore()
      nextTick(() => scrollCardIntoView(idx + 1))
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    const idx = selectedIndex.value
    if (idx > 0) {
      const prevItem = items.value[idx - 1]
      selectItem(prevItem)
      nextTick(() => scrollCardIntoView(idx - 1))
    }
  }
}

function scrollCardIntoView(index) {
  if (!leftPanelRef.value) return
  const cards = leftPanelRef.value.querySelectorAll('[data-feed-card]')
  if (cards[index]) {
    cards[index].scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }
}

function handleClickOutside() {
  showSourceDropdown.value = false
}

// 加载统计数据
async function loadStats() {
  try {
    const res = await getContentStats()
    if (res.code === 0) {
      contentStats.value = {
        read: res.data.read || 0,
        unread: res.data.unread || 0,
        total: res.data.total || 0,
      }
    }
  } catch (_) { /* ignore */ }
}

// 初始化手势
const { isSwiping, swipeOffset } = useSwipe(mobileDetailRef, {
  threshold: 80,
  onSwipeRight: () => {
    closeMobileDetail()
  }
})

onMounted(async () => {
  fetchItems(true)
  loadStats()
  try {
    const res = await listSourceOptions()
    if (res.code === 0) sourceOptions.value = res.data
  } catch (_) { /* ignore */ }
  document.addEventListener('keydown', handleKeydown)
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  clearTimeout(searchTimer)
  cancelChat()
  document.removeEventListener('keydown', handleKeydown)
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 双栏主体 -->
    <div class="flex flex-1 min-h-0">
      <!-- 左栏：列表 -->
      <div
        ref="leftPanelRef"
        class="w-full md:w-[480px] md:shrink-0 md:border-r border-slate-200 overflow-y-auto"
        :class="{ 'hidden md:block': showMobileDetail }"
        @scroll="handleLeftScroll"
      >
        <div class="px-4 pt-3 pb-2 space-y-2.5 sticky top-0 bg-white z-10 border-b border-slate-100">
          <!-- 计数 + 排序 -->
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3">
              <p class="text-xs text-slate-400">{{ totalCount }} 条内容</p>
            </div>
            <select
              :value="sortBy"
              @change="switchSort($event.target.value)"
              class="bg-slate-50 text-xs text-slate-600 rounded-lg px-2.5 py-1.5 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer"
            >
              <option v-for="sort in sortOptions" :key="sort.value" :value="sort.value">{{ sort.label }}</option>
            </select>
          </div>

          <!-- 搜索 + 筛选 -->
          <div class="flex items-center gap-2">
            <!-- 搜索框 -->
            <div class="relative flex-1 min-w-0">
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

            <!-- 来源多选按钮 -->
            <div class="relative shrink-0">
              <button
                class="flex items-center gap-1 px-3 py-2 text-xs font-medium rounded-lg border transition-all duration-200"
                :class="filterSources.length
                  ? 'text-indigo-700 bg-indigo-50 border-indigo-200'
                  : 'text-slate-600 bg-slate-50 border-slate-200 hover:border-slate-300'"
                @click.stop="showSourceDropdown = !showSourceDropdown"
              >
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
                </svg>
                来源{{ filterSources.length ? `(${filterSources.length})` : '' }}
                <svg class="w-3 h-3 transition-transform" :class="{ 'rotate-180': showSourceDropdown }" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              <!-- 来源多选下拉 -->
              <Transition
                enter-active-class="transition-all duration-150 ease-out"
                enter-from-class="opacity-0 scale-95"
                enter-to-class="opacity-100 scale-100"
                leave-active-class="transition-all duration-100 ease-in"
                leave-from-class="opacity-100 scale-100"
                leave-to-class="opacity-0 scale-95"
              >
                <div
                  v-if="showSourceDropdown"
                  class="absolute right-0 top-full mt-1 w-56 bg-white rounded-xl shadow-lg border border-slate-200 py-1 z-30 max-h-64 overflow-y-auto"
                  @click.stop
                >
                  <div v-if="filterSources.length" class="px-3 py-1.5 border-b border-slate-100">
                    <button @click="clearSources" class="text-xs text-indigo-600 hover:text-indigo-800">清除所有来源</button>
                  </div>
                  <label
                    v-for="s in sourceOptions"
                    :key="s.id"
                    class="flex items-center gap-2 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 cursor-pointer transition-colors"
                  >
                    <input
                      type="checkbox"
                      :checked="filterSources.includes(String(s.id))"
                      class="w-3.5 h-3.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500/20"
                      @change="toggleSourceFilter(s.id)"
                    />
                    <span class="truncate">{{ s.name }}</span>
                  </label>
                  <div v-if="!sourceOptions.length" class="px-3 py-3 text-xs text-slate-400 text-center">暂无来源</div>
                </div>
              </Transition>
            </div>

            <!-- 状态下拉 -->
            <select
              v-model="filterStatus"
              class="bg-slate-50 text-xs text-slate-600 rounded-lg px-2.5 py-2 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer shrink-0"
            >
              <option v-for="st in statusOptions" :key="st.value" :value="st.value">{{ st.label }}</option>
            </select>

            <!-- 未读 toggle -->
            <button
              class="p-2 rounded-lg transition-all duration-200 border shrink-0"
              :class="showUnreadOnly
                ? 'text-blue-600 bg-blue-50 border-blue-200'
                : 'text-slate-400 hover:text-slate-600 bg-slate-50 border-slate-200 hover:border-slate-300'"
              :title="showUnreadOnly ? '显示全部' : '只看未读'"
              @click="toggleUnread"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.64 0 8.577 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.64 0-8.577-3.007-9.963-7.178z" />
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>

            <!-- 收藏 toggle -->
            <button
              class="p-2 rounded-lg transition-all duration-200 border shrink-0"
              :class="showFavoritesOnly
                ? 'text-amber-500 bg-amber-50 border-amber-200'
                : 'text-slate-400 hover:text-slate-600 bg-slate-50 border-slate-200 hover:border-slate-300'"
              :title="showFavoritesOnly ? '显示全部' : '只看收藏'"
              @click="toggleFavorites"
            >
              <svg class="w-4 h-4" :fill="showFavoritesOnly ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
              </svg>
            </button>
          </div>

          <!-- 活跃筛选 tags -->
          <div v-if="hasActiveFilters" class="flex items-center gap-1.5 flex-wrap">
            <span
              v-if="searchQuery.trim()"
              class="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 text-indigo-700 text-xs font-medium rounded-full"
            >
              搜索:{{ searchQuery.trim() }}
              <button @click="clearSearch" class="ml-0.5 hover:text-indigo-900">&times;</button>
            </span>
            <span
              v-for="(name, i) in activeSourceNames"
              :key="'src-' + i"
              class="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 text-indigo-700 text-xs font-medium rounded-full"
            >
              {{ name }}
              <button @click="toggleSourceFilter(filterSources[i])" class="ml-0.5 hover:text-indigo-900">&times;</button>
            </span>
            <span
              v-if="filterStatus"
              class="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 text-indigo-700 text-xs font-medium rounded-full"
            >
              状态:{{ statusOptions.find(s => s.value === filterStatus)?.label }}
              <button @click="clearStatus" class="ml-0.5 hover:text-indigo-900">&times;</button>
            </span>
            <span
              v-if="showUnreadOnly"
              class="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 text-xs font-medium rounded-full"
            >
              未读
              <button @click="clearUnread" class="ml-0.5 hover:text-blue-900">&times;</button>
            </span>
            <span
              v-if="showFavoritesOnly"
              class="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-50 text-amber-700 text-xs font-medium rounded-full"
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
          <div class="flex items-center gap-0.5 bg-slate-100 rounded-xl p-0.5 overflow-x-auto">
            <button
              v-for="mt in mediaTypes"
              :key="mt.value"
              class="px-3 py-1 text-xs font-medium rounded-lg transition-all duration-200 whitespace-nowrap shrink-0"
              :class="activeMediaType === mt.value
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'"
              @click="switchMediaType(mt.value)"
            >
              {{ mt.label }}
            </button>
          </div>
        </div>

        <!-- 卡片列表 -->
        <div class="px-4 py-3">
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

          <!-- Feed 卡片列表 -->
          <div v-else class="space-y-3">
            <FeedCard
              v-for="item in items"
              :key="item.id"
              :item="item"
              :selected="selectedId === item.id"
              :data-item-id="item.id"
              data-feed-card
              @click="selectItem"
              @favorite="handleFavorite"
            />

            <!-- 加载更多 -->
            <div v-if="loadingMore" class="flex items-center justify-center py-6">
              <div class="flex items-center gap-2 text-sm text-slate-400">
                <svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                <span>加载中...</span>
              </div>
            </div>

            <!-- 虚拟底部空白区（让最后几条卡片可以向上移出视野） -->
            <div v-else-if="!hasMore && items.length > 0" class="flex items-center justify-center text-center min-h-[80vh] pt-12 text-sm text-slate-400">
              <div>
                <p class="mb-1">已浏览完所有内容</p>
                <p class="text-xs text-slate-300">
                  {{ contentStats.read }}/{{ contentStats.total }} 已读
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右栏：详情 (桌面端始终显示, 移动端滑入覆盖) -->
      <div class="hidden md:flex flex-1 min-w-0 overflow-y-auto">
        <!-- 空状态 -->
        <div v-if="!selectedId" class="flex-1 flex items-center justify-center">
          <div class="text-center">
            <div class="w-20 h-20 bg-slate-50 rounded-2xl flex items-center justify-center mx-auto mb-4">
              <svg class="w-10 h-10 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
            </div>
            <p class="text-sm text-slate-400 font-medium">选择一篇文章查看</p>
            <p class="text-xs text-slate-300 mt-1">使用 ↑↓ 键快速切换</p>
          </div>
        </div>

        <!-- 加载中 -->
        <div v-else-if="detailLoading && !detailContent" class="flex-1 flex items-center justify-center">
          <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        </div>

        <!-- 详情内容 -->
        <div v-else-if="detailContent" class="flex-1 min-w-0 flex flex-col">
          <div ref="rightPanelRef" class="flex-1 overflow-y-auto overflow-x-hidden p-6 space-y-6">
            <DetailContent
              ref="detailContentRef"
              :item="detailContent"
              :analyzing="analyzing"
              :enriching="enriching"
              :enrich-results="enrichResults"
              :show-enrich-modal="showEnrichModal"
              :applying-enrich="applyingEnrich"
              @analyze="handleAnalyze"
              @favorite="handleDetailFavorite"
              @enrich="handleEnrich"
              @apply-enrich="handleApplyEnrich"
              @close-enrich="closeEnrichModal"
            >
              <!-- Chat messages (slotted into detail content) -->
              <ChatPanel
                :messages="chatMessages.map(m => ({ ...m, renderedContent: m.role === 'assistant' ? renderChatMarkdown(m.content || '') : '' }))"
                :loading="chatStreaming"
                :input="chatInput"
              >
                <template #messages-end>
                  <div ref="chatMessagesEndRef"></div>
                </template>
              </ChatPanel>
            </DetailContent>
          </div>

          <!-- AI 对话输入栏 -->
          <div class="px-4 py-3 border-t border-slate-100 shrink-0 bg-white">
            <div class="flex items-end gap-2">
              <textarea
                ref="chatInputRef"
                v-model="chatInput"
                :disabled="chatStreaming"
                rows="1"
                class="flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all disabled:opacity-50"
                :class="{ 'max-h-[6rem] overflow-y-auto': true }"
                placeholder="讨论这篇内容..."
                @keydown="handleChatKeydown"
                @input="e => { e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 96) + 'px' }"
              ></textarea>
              <button
                class="shrink-0 p-2.5 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                :disabled="!chatInput.trim() || chatStreaming"
                @click="sendChat"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 移动端详情覆盖层 -->
      <Transition
        enter-active-class="transition-transform duration-200 ease-out"
        enter-from-class="translate-x-full"
        enter-to-class="translate-x-0"
        leave-active-class="transition-transform duration-150 ease-in"
        leave-from-class="translate-x-0"
        leave-to-class="translate-x-full"
      >
        <div
          v-if="showMobileDetail && selectedId"
          ref="mobileDetailRef"
          class="fixed inset-0 z-40 bg-white flex flex-col md:hidden"
          :style="isSwiping ? { transform: `translateX(${Math.max(0, swipeOffset)}px)` } : {}"
        >
          <!-- 移动端返回栏 -->
          <div class="flex items-center gap-3 px-4 py-3 border-b border-slate-100 shrink-0">
            <button
              class="p-2 -ml-2 rounded-lg text-slate-500 hover:bg-slate-50 transition-colors"
              @click="closeMobileDetail"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
            </button>
            <span class="text-sm font-medium text-slate-600 truncate">返回列表</span>
          </div>

          <!-- 移动端详情内容 -->
          <div v-if="detailLoading && !detailContent" class="flex-1 flex items-center justify-center">
            <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
          </div>

          <div v-else-if="detailContent" class="flex-1 min-h-0 flex flex-col">
            <div class="flex-1 overflow-y-auto p-4 space-y-5">
              <DetailContent
                ref="mobileDetailContentRef"
                :item="detailContent"
                :analyzing="analyzing"
                :enriching="enriching"
                :enrich-results="enrichResults"
                :show-enrich-modal="showEnrichModal"
                :applying-enrich="applyingEnrich"
                @analyze="handleAnalyze"
                @favorite="handleDetailFavorite"
                @enrich="handleEnrich"
                @apply-enrich="handleApplyEnrich"
                @close-enrich="closeEnrichModal"
              >
                <!-- Chat messages (slotted into detail content) -->
                <ChatPanel
                  :messages="chatMessages.map(m => ({ ...m, renderedContent: m.role === 'assistant' ? renderChatMarkdown(m.content || '') : '' }))"
                  :loading="chatStreaming"
                  :input="chatInput"
                />
              </DetailContent>
            </div>

            <!-- AI 对话输入栏（移动端） -->
            <div class="px-4 py-3 border-t border-slate-100 shrink-0 bg-white">
              <div class="flex items-end gap-2">
                <textarea
                  v-model="chatInput"
                  :disabled="chatStreaming"
                  rows="1"
                  class="flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all disabled:opacity-50 max-h-[6rem] overflow-y-auto"
                  placeholder="讨论这篇内容..."
                  @keydown="handleChatKeydown"
                  @input="e => { e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 96) + 'px' }"
                ></textarea>
                <button
                  class="shrink-0 p-2.5 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  :disabled="!chatInput.trim() || chatStreaming"
                  @click="sendChat"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>
