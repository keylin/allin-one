<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listContent, getContent, analyzeContent, toggleFavorite, listSourceOptions, enrichContent, applyEnrichment, getContentStats, markAllRead } from '@/api/content'
import { useToast } from '@/composables/useToast'
import { useSwipe } from '@/composables/useSwipe'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { useAutoRead } from '@/composables/useAutoRead'
import { useContentChat } from '@/composables/useContentChat'
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
const activeMediaType = ref(route.query.has_video === '1' ? 'video' : route.query.has_audio === '1' ? 'audio' : '')
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

// 标签筛选
const filterTag = ref(route.query.tag || '')

// 日期范围筛选
const dateRange = ref(route.query.date_range || '')

const dateRangeOptions = [
  { value: '', label: '全部时间' },
  { value: 'today', label: '今天' },
  { value: '3d', label: '近 3 天' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
]

function getDateParams() {
  if (!dateRange.value) return {}
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  let dateFrom
  switch (dateRange.value) {
    case 'today':
      dateFrom = today
      break
    case '3d':
      dateFrom = new Date(today.getTime() - 2 * 86400000)
      break
    case '7d':
      dateFrom = new Date(today.getTime() - 6 * 86400000)
      break
    case '30d':
      dateFrom = new Date(today.getTime() - 29 * 86400000)
      break
    default:
      return {}
  }
  const fmt = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return { date_from: fmt(dateFrom) }
}

// 密度模式
const densityMode = ref(localStorage.getItem('feed_density') || 'comfortable')

function toggleDensity() {
  densityMode.value = densityMode.value === 'comfortable' ? 'compact' : 'comfortable'
  localStorage.setItem('feed_density', densityMode.value)
}

// 快捷键帮助浮层
const showShortcutHelp = ref(false)

// 新内容到达提醒
const newContentCount = ref(0)
let lastKnownTotal = null

// 阅读进度：基于未读消化比例
const sessionInitialUnread = ref(0)
const readingProgress = computed(() => {
  if (sessionInitialUnread.value <= 0) return 0
  const consumed = sessionInitialUnread.value - contentStats.value.unread
  return Math.min(100, Math.max(0, (consumed / sessionInitialUnread.value) * 100))
})

// 滚动容器 ref
const leftPanelRef = ref(null)
const rightPanelRef = ref(null)

const mediaTypes = [
  { value: '', label: '全部' },
  { value: 'video', label: '有视频' },
  { value: 'audio', label: '有音频' },
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
const mobileDetailHeight = ref(null) // null = use CSS 100dvh
const mobileDetailTop = ref(0)

function onVisualViewportChange() {
  const vv = window.visualViewport
  if (!vv) return
  mobileDetailHeight.value = vv.height
  mobileDetailTop.value = vv.offsetTop
}


// --- Chat composable ---
const {
  chatMessages,
  chatInput,
  chatStreaming,
  chatLoading: chatHistoryLoading,
  chatInputRef,
  chatMessagesEndRef,
  cancelChat,
  loadHistory,
  clearHistory,
  sendChat,
  handleChatKeydown,
  renderChatMarkdown,
} = useContentChat({
  getContentId: () => selectedId.value,
})

// --- Auto-read composable (pass contentStats for optimistic update) ---
const { markAsRead, handleScrollBottom } = useAutoRead({
  items,
  leftPanelRef,
  loadStats,
  contentStats,
})

// 是否有活跃筛选
const hasActiveFilters = computed(() => {
  return searchQuery.value.trim() || filterSources.value.length > 0 || filterStatus.value || showFavoritesOnly.value || showUnreadOnly.value || dateRange.value || filterTag.value
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
  if (activeMediaType.value === 'audio') query.has_audio = '1'
  if (sortBy.value !== 'published_at') query.sort_by = sortBy.value
  if (showFavoritesOnly.value) query.favorites = '1'
  if (!showUnreadOnly.value) query.unread = '0'
  if (dateRange.value) query.date_range = dateRange.value
  if (filterTag.value) query.tag = filterTag.value
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
      page_size: pageSize,
      sort_by: sortBy.value,
      sort_order: 'desc',
    }
    if (activeMediaType.value === 'video') params.has_video = true
    if (activeMediaType.value === 'audio') params.has_audio = true
    if (searchQuery.value.trim()) params.q = searchQuery.value.trim()
    if (filterSources.value.length) params.source_id = filterSources.value.join(',')
    if (filterStatus.value) params.status = filterStatus.value
    if (showFavoritesOnly.value) params.is_favorited = true
    if (showUnreadOnly.value) params.is_unread = true

    // 日期范围
    const dp = getDateParams()
    if (dp.date_from) params.date_from = dp.date_from
    // 标签筛选
    if (filterTag.value) params.tag = filterTag.value

    // 游标分页: 非 reset 且有已加载项时，用最后一条的 id 作为游标
    if (!reset && items.value.length > 0) {
      params.cursor_id = items.value[items.value.length - 1].id
    } else {
      params.page = page.value
    }

    const res = await listContent(params)
    if (res.code === 0) {
      if (reset) {
        items.value = res.data
        totalCount.value = res.total
      } else {
        items.value = [...items.value, ...res.data]
      }
      // 用返回数量判断是否还有更多（解决自动已读导致 total 变化的偏移漂移问题）
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
watch([filterSources, filterStatus, showFavoritesOnly, showUnreadOnly, dateRange, filterTag], () => {
  fetchItems(true)
})

// 清除筛选
function clearSearch() { searchQuery.value = ''; fetchItems(true) }
function clearStatus() { filterStatus.value = '' }
function clearFavorites() { showFavoritesOnly.value = false }
function clearUnread() { showUnreadOnly.value = false }
function clearDateRange() { dateRange.value = '' }
function clearTag() { filterTag.value = '' }
function handleTagClick(tag) { filterTag.value = tag }
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
  dateRange.value = ''
  filterTag.value = ''
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
  loadHistory(item.id)
  // 右栏滚回顶部
  if (rightPanelRef.value) rightPanelRef.value.scrollTop = 0
  // [B] 点击选中走 markAsRead 统一路径（乐观更新）
  markAsRead(item.id)
  loadDetail(item.id)
}

function closeMobileDetail() {
  showMobileDetail.value = false
}

// 键盘弹起时动态调整移动端详情面板位置和高度，防止 sticky header 被顶出屏幕
// iOS Safari 键盘弹起不改变 layout viewport，而是推移 visual viewport：
//   - resize: vv.height 缩小（键盘占位）
//   - scroll: vv.offsetTop 增大（视口下移）
// 需同时监听两个事件，将 fixed 容器对齐到 visual viewport
watch(showMobileDetail, (visible) => {
  const vv = window.visualViewport
  if (visible && vv) {
    mobileDetailHeight.value = vv.height
    mobileDetailTop.value = vv.offsetTop
    vv.addEventListener('resize', onVisualViewportChange)
    vv.addEventListener('scroll', onVisualViewportChange)
  } else {
    mobileDetailHeight.value = null
    mobileDetailTop.value = 0
    vv?.removeEventListener('resize', onVisualViewportChange)
    vv?.removeEventListener('scroll', onVisualViewportChange)
  }
})

// [6] 收藏乐观更新
async function handleFavorite(id) {
  const item = items.value.find(i => i.id === id)
  if (!item) return

  // 乐观更新
  const wasFavorited = item.is_favorited
  item.is_favorited = !wasFavorited
  if (detailContent.value && detailContent.value.id === id) {
    detailContent.value.is_favorited = !wasFavorited
  }

  try {
    const res = await toggleFavorite(id)
    if (res.code === 0) {
      // 用服务器返回值校准
      item.is_favorited = res.data.is_favorited
      if (detailContent.value && detailContent.value.id === id) {
        detailContent.value.is_favorited = res.data.is_favorited
      }
    } else {
      // 失败回滚
      item.is_favorited = wasFavorited
      if (detailContent.value && detailContent.value.id === id) {
        detailContent.value.is_favorited = wasFavorited
      }
      toastError('收藏操作失败')
    }
  } catch {
    // 网络错误回滚
    item.is_favorited = wasFavorited
    if (detailContent.value && detailContent.value.id === id) {
      detailContent.value.is_favorited = wasFavorited
    }
    toastError('网络错误，收藏操作已回滚')
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

// --- Mark all read ---
const markingAllRead = ref(false)

async function handleMarkAllRead() {
  if (markingAllRead.value || contentStats.value.unread === 0) return
  markingAllRead.value = true
  try {
    const params = {}
    if (filterSources.value.length) params.source_id = filterSources.value.join(',')
    if (filterStatus.value) params.status = filterStatus.value
    if (activeMediaType.value === 'video') params.has_video = true
    if (activeMediaType.value === 'audio') params.has_audio = true
    if (searchQuery.value.trim()) params.q = searchQuery.value.trim()
    const dp = getDateParams()
    if (dp.date_from) params.date_from = dp.date_from

    const res = await markAllRead(params)
    if (res.code === 0) {
      // 更新本地列表状态
      items.value.forEach(item => {
        if ((item.view_count || 0) === 0) {
          item.view_count = 1
          item.last_viewed_at = new Date().toISOString()
        }
      })
      await loadStats()
      toastSuccess(`已标记 ${res.data.updated} 条为已读`)
    }
  } catch {
    toastError('标记全部已读失败')
  } finally {
    markingAllRead.value = false
  }
}

// --- Left panel scroll → infinite load + auto-read ---
function handleLeftScroll(e) {
  const el = e.target
  const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight

  if (distanceToBottom < 200) {
    loadMore()
  }

  handleScrollBottom(distanceToBottom)
}

// --- [5] Detail panel navigation ---
function navigateDetail(direction) {
  const idx = selectedIndex.value
  if (idx === -1) return

  const newIdx = idx + direction
  if (newIdx < 0 || newIdx >= items.value.length) return

  const targetItem = items.value[newIdx]
  selectItem(targetItem)
  if (newIdx >= items.value.length - 3 && hasMore.value) loadMore()
  nextTick(() => scrollCardIntoView(newIdx))
}

// --- [2] Keyboard shortcuts ---
function handleKeydown(e) {
  const tag = e.target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

  // ? — show shortcut help
  if (e.key === '?') {
    e.preventDefault()
    showShortcutHelp.value = !showShortcutHelp.value
    return
  }

  // Escape — close help / enrich modal
  if (e.key === 'Escape') {
    if (showShortcutHelp.value) { showShortcutHelp.value = false; return }
    if (showEnrichModal.value) { closeEnrichModal(); return }
    return
  }

  // j / ArrowDown — next item
  if (e.key === 'j' || e.key === 'ArrowDown') {
    e.preventDefault()
    const idx = selectedIndex.value
    if (idx < items.value.length - 1) {
      const nextItem = items.value[idx + 1]
      selectItem(nextItem)
      if (idx + 1 >= items.value.length - 3 && hasMore.value) loadMore()
      nextTick(() => scrollCardIntoView(idx + 1))
    }
    return
  }

  // k / ArrowUp — prev item
  if (e.key === 'k' || e.key === 'ArrowUp') {
    e.preventDefault()
    const idx = selectedIndex.value
    if (idx > 0) {
      const prevItem = items.value[idx - 1]
      selectItem(prevItem)
      nextTick(() => scrollCardIntoView(idx - 1))
    }
    return
  }

  // s — toggle favorite
  if (e.key === 's') {
    if (selectedId.value) handleFavorite(selectedId.value)
    return
  }

  // o — open original URL
  if (e.key === 'o') {
    if (detailContent.value?.url) {
      window.open(detailContent.value.url, '_blank', 'noopener')
    }
    return
  }

  // m — toggle read/unread
  if (e.key === 'm') {
    if (selectedId.value) {
      const item = items.value.find(i => i.id === selectedId.value)
      if (item) {
        if ((item.view_count || 0) === 0) {
          markAsRead(item.id)
        }
        // Note: toggling back to unread would need an API call; for now just mark read
      }
    }
    return
  }

  // a — trigger analyze
  if (e.key === 'a') {
    handleAnalyze()
    return
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
let statsLoading = false
async function loadStats() {
  if (statsLoading) return
  statsLoading = true
  try {
    const res = await getContentStats()
    if (res.code === 0) {
      const newTotal = res.data.total || 0

      // 检测新内容到达（仅 polling 触发时，非初始加载）
      if (lastKnownTotal !== null && newTotal > lastKnownTotal) {
        newContentCount.value += newTotal - lastKnownTotal
      }
      lastKnownTotal = newTotal

      contentStats.value = {
        read: res.data.read || 0,
        unread: res.data.unread || 0,
        total: newTotal,
      }

      // 首次（或重置后）捕获初始未读数作为阅读进度基准
      if (sessionInitialUnread.value === 0 && contentStats.value.unread > 0) {
        sessionInitialUnread.value = contentStats.value.unread
      }
    }
  } catch (_) { /* ignore */ }
  finally { statsLoading = false }
}

function loadNewContent() {
  newContentCount.value = 0
  fetchItems(true)
}

// --- Stats polling ---
let statsPollingTimer = null

function startStatsPolling() {
  if (statsPollingTimer) return
  statsPollingTimer = setInterval(() => {
    loadStats()
  }, 60000)
}

function stopStatsPolling() {
  if (statsPollingTimer) {
    clearInterval(statsPollingTimer)
    statsPollingTimer = null
  }
}

// 侧滑关闭时跳过 Vue Transition leave 动画（防止「动画两次」）
const swipeDismissing = ref(false)

// 初始化手势
useSwipe(mobileDetailRef, {
  threshold: 80,
  onSwipeRight: () => {
    swipeDismissing.value = true
    closeMobileDetail()
  }
})

// 下拉刷新
const { isPulling, pullDistance, isRefreshing } = usePullToRefresh(leftPanelRef, {
  onRefresh: async () => {
    sessionInitialUnread.value = 0
    await fetchItems(true)
    await loadStats()
  }
})

const pullOffset = computed(() => {
  if (isRefreshing.value) return 48
  return isPulling.value ? pullDistance.value : 0
})

onMounted(async () => {
  fetchItems(true)
  loadStats()
  startStatsPolling()
  try {
    const res = await listSourceOptions()
    if (res.code === 0) sourceOptions.value = res.data
  } catch (_) { /* ignore */ }
  document.addEventListener('keydown', handleKeydown)
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  clearTimeout(searchTimer)
  stopStatsPolling()
  cancelChat()
  document.removeEventListener('keydown', handleKeydown)
  document.removeEventListener('click', handleClickOutside)
  window.visualViewport?.removeEventListener('resize', onVisualViewportChange)
  window.visualViewport?.removeEventListener('scroll', onVisualViewportChange)
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 双栏主体 -->
    <div class="flex flex-1 min-h-0">
      <!-- 左栏：列表 -->
      <div
        ref="leftPanelRef"
        class="w-full md:w-[480px] md:shrink-0 md:border-r border-slate-200 overflow-y-auto overscroll-contain relative"
        :class="{ 'hidden md:block': showMobileDetail }"
        @scroll="handleLeftScroll"
      >
        <!-- 下拉刷新指示器 -->
        <div
          v-if="isPulling || isRefreshing"
          class="absolute top-0 inset-x-0 flex items-center justify-center z-30 pointer-events-none"
          :style="{ height: pullOffset + 'px' }"
        >
          <!-- 刷新中：spinner -->
          <svg v-if="isRefreshing" class="w-5 h-5 animate-spin text-indigo-500" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          <!-- 拉动中：箭头（超过阈值旋转 180°） -->
          <svg
            v-else
            class="w-5 h-5 text-slate-400 transition-transform duration-200"
            :style="{ transform: pullDistance >= 64 ? 'rotate(180deg)' : 'rotate(0deg)' }"
            fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
          </svg>
        </div>

        <!-- 内容 wrapper，拉动时 translateY 下移 -->
        <div
          :style="{
            transform: `translateY(${pullOffset}px)`,
            transition: (isPulling ? 'none' : 'transform 0.3s ease-out')
          }"
        >
        <div class="relative px-3 md:px-4 pt-2 md:pt-3 pb-1.5 md:pb-2 space-y-1.5 md:space-y-2.5 sticky top-0 bg-white z-10 border-b border-slate-100">
          <!-- 计数 + 排序 + 密度切换 -->
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <p class="text-sm md:text-xs text-slate-400">
                <span v-if="contentStats.unread > 0" class="inline-flex items-center gap-1">
                  <span class="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 text-xs font-medium rounded-full bg-indigo-100 text-indigo-700">
                    {{ contentStats.unread }}
                  </span>
                  <span>未读</span>
                </span>
                <span v-else class="text-slate-300">已全部阅读</span>
              </p>
              <!-- 全部已读按钮 -->
              <button
                v-if="contentStats.unread > 0"
                class="text-sm md:text-xs text-slate-400 hover:text-indigo-600 transition-colors disabled:opacity-40 py-2 md:py-1.5"
                :disabled="markingAllRead"
                title="标记全部已读"
                @click="handleMarkAllRead"
              >
                <span v-if="markingAllRead">标记中...</span>
                <span v-else class="flex items-center gap-0.5">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  全部已读
                </span>
              </button>
            </div>
            <div class="flex items-center gap-1 md:gap-1.5">
              <!-- 来源多选按钮 -->
              <div class="relative shrink-0">
                <button
                  class="flex items-center gap-1 px-2 py-1.5 md:px-3 md:py-2 text-xs font-medium rounded-lg border transition-all duration-200"
                  :class="filterSources.length
                    ? 'text-indigo-700 bg-indigo-50 border-indigo-200'
                    : 'text-slate-600 bg-slate-50 border-slate-200 hover:border-slate-300'"
                  @click.stop="showSourceDropdown = !showSourceDropdown"
                >
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
                  </svg>
                  <span class="hidden md:inline">来源</span><span v-if="filterSources.length">({{ filterSources.length }})</span>
                  <svg class="w-3 h-3 transition-transform hidden md:block" :class="{ 'rotate-180': showSourceDropdown }" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
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

              <!-- 未读 toggle -->
              <button
                class="p-1.5 md:p-2 rounded-lg transition-all duration-200 border shrink-0"
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

              <!-- 密度切换（移动端隐藏） -->
              <button
                class="hidden md:inline-flex md:p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-all"
                :title="densityMode === 'compact' ? '切换舒适模式' : '切换紧凑模式'"
                @click="toggleDensity"
              >
                <svg v-if="densityMode === 'compact'" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5M3.75 17.25h16.5" />
                </svg>
                <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 5.25h16.5m-16.5 4.5h16.5m-16.5 4.5h16.5m-16.5 4.5h16.5" />
                </svg>
              </button>
              <!-- 快捷键帮助（移动端隐藏） -->
              <button
                class="hidden md:inline-flex md:p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-all"
                title="快捷键 (?)"
                @click="showShortcutHelp = !showShortcutHelp"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
                </svg>
              </button>
              <select
                :value="sortBy"
                @change="switchSort($event.target.value)"
                class="bg-slate-50 text-xs text-slate-600 rounded-lg px-3 py-1.5 md:px-2.5 md:py-2 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer"
              >
                <option v-for="sort in sortOptions" :key="sort.value" :value="sort.value">{{ sort.label }}</option>
              </select>
            </div>
          </div>

          <!-- 搜索 + 高级筛选（桌面端） -->
          <div class="hidden md:flex items-center gap-2 flex-wrap">
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

            <!-- 日期范围 -->
            <select
              v-model="dateRange"
              class="bg-slate-50 text-xs text-slate-600 rounded-lg px-2.5 py-2 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer shrink-0"
            >
              <option v-for="dr in dateRangeOptions" :key="dr.value" :value="dr.value">{{ dr.label }}</option>
            </select>

            <!-- 状态下拉 -->
            <select
              v-model="filterStatus"
              class="bg-slate-50 text-xs text-slate-600 rounded-lg px-2.5 py-2 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all appearance-none cursor-pointer shrink-0"
            >
              <option v-for="st in statusOptions" :key="st.value" :value="st.value">{{ st.label }}</option>
            </select>
          </div>

          <!-- 活跃筛选 tags -->
          <div v-if="hasActiveFilters" class="hidden md:flex items-center gap-1.5 flex-wrap">
            <span
              v-if="searchQuery.trim()"
              class="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-100 text-indigo-700 text-xs font-medium rounded-full shadow-sm border border-indigo-200/50"
            >
              搜索:{{ searchQuery.trim() }}
              <button @click="clearSearch" class="ml-0.5 hover:text-indigo-900 transition-colors">&times;</button>
            </span>
            <span
              v-for="(name, i) in activeSourceNames"
              :key="'src-' + i"
              class="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-100 text-indigo-700 text-xs font-medium rounded-full shadow-sm border border-indigo-200/50"
            >
              {{ name }}
              <button @click="toggleSourceFilter(filterSources[i])" class="ml-0.5 hover:text-indigo-900 transition-colors">&times;</button>
            </span>
            <span
              v-if="dateRange"
              class="inline-flex items-center gap-1 px-2.5 py-1 bg-cyan-100 text-cyan-700 text-xs font-medium rounded-full shadow-sm border border-cyan-200/50"
            >
              {{ dateRangeOptions.find(d => d.value === dateRange)?.label }}
              <button @click="clearDateRange" class="ml-0.5 hover:text-cyan-900 transition-colors">&times;</button>
            </span>
            <span
              v-if="filterStatus"
              class="inline-flex items-center gap-1 px-2.5 py-1 bg-indigo-100 text-indigo-700 text-xs font-medium rounded-full shadow-sm border border-indigo-200/50"
            >
              状态:{{ statusOptions.find(s => s.value === filterStatus)?.label }}
              <button @click="clearStatus" class="ml-0.5 hover:text-indigo-900 transition-colors">&times;</button>
            </span>
            <span
              v-if="showUnreadOnly"
              class="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-100 text-blue-700 text-xs font-medium rounded-full shadow-sm border border-blue-200/50"
            >
              未读
              <button @click="clearUnread" class="ml-0.5 hover:text-blue-900 transition-colors">&times;</button>
            </span>
            <span
              v-if="filterTag"
              class="inline-flex items-center gap-1 px-2.5 py-1 bg-violet-100 text-violet-700 text-xs font-medium rounded-full shadow-sm border border-violet-200/50"
            >
              #{{ filterTag }}
              <button @click="clearTag" class="ml-0.5 hover:text-violet-900 transition-colors">&times;</button>
            </span>

            <button
              @click="clearAllFilters"
              class="text-xs text-slate-400 hover:text-slate-600 transition-colors px-2 py-1"
            >
              清除全部
            </button>
          </div>

          <!-- 媒体类型 Tab（桌面端） -->
          <div class="hidden md:flex items-center gap-0.5 bg-slate-100 rounded-xl p-0.5">
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

          <!-- 阅读进度条（内嵌在 sticky header 底部） -->
          <div
            v-if="sessionInitialUnread > 0 && readingProgress > 0"
            class="absolute bottom-0 left-0 right-0 h-0.5 bg-slate-100"
          >
            <div
              class="h-full bg-indigo-400 transition-[width] duration-150 ease-out"
              :style="{ width: readingProgress + '%' }"
            ></div>
          </div>
        </div>

        <!-- 新内容横幅 -->
        <div
          v-if="newContentCount > 0"
          class="mx-4 mt-2"
        >
          <button
            class="w-full flex items-center justify-center gap-2 px-4 py-2 bg-indigo-50 text-indigo-700 text-sm font-medium rounded-xl border border-indigo-200 hover:bg-indigo-100 transition-all"
            @click="loadNewContent"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
            </svg>
            {{ newContentCount }} 条新内容 — 点击加载
          </button>
        </div>

        <!-- 卡片列表 -->
        <div class="px-3 md:px-4" :class="densityMode === 'compact' ? 'py-1.5' : 'py-2 md:py-3'">
          <!-- Loading skeleton -->
          <div v-if="loading" class="space-y-3">
            <div v-for="i in 4" :key="i" class="animate-pulse bg-white rounded-xl border border-slate-200 p-4">
              <div class="flex items-start gap-2">
                <div class="w-4 h-4 bg-slate-200 rounded shrink-0"></div>
                <div class="flex-1 space-y-2">
                  <div class="h-4 bg-slate-200 rounded w-3/4"></div>
                  <div class="h-3 bg-slate-100 rounded w-1/2"></div>
                  <div class="h-3 bg-slate-100 rounded w-2/3"></div>
                </div>
              </div>
            </div>
          </div>

          <!-- Empty -->
          <div v-else-if="items.length === 0" class="text-center py-16">
            <div class="w-20 h-20 bg-gradient-to-br from-indigo-50 to-purple-50 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-inner">
              <svg class="w-10 h-10 text-indigo-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 01-2.25 2.25M16.5 7.5V18a2.25 2.25 0 002.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 002.25 2.25h13.5M6 7.5h3v3H6v-3z" />
              </svg>
            </div>
            <p class="text-base text-slate-600 font-medium mb-1">
              {{ hasActiveFilters ? '没有找到匹配的内容' : '暂无内容' }}
            </p>
            <p class="text-sm text-slate-400">
              {{ hasActiveFilters ? '试试调整筛选条件' : '添加数据源后内容会自动出现在这里' }}
            </p>
          </div>

          <!-- Feed 卡片列表 -->
          <div v-else :class="densityMode === 'compact' ? 'space-y-1' : 'space-y-2 md:space-y-3'">
            <FeedCard
              v-for="item in items"
              :key="item.id"
              :item="item"
              :selected="selectedId === item.id"
              :compact="densityMode === 'compact'"
              :data-item-id="item.id"
              data-feed-card
              @click="selectItem"
              @favorite="handleFavorite"
              @tag-click="handleTagClick"
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
            <div v-else-if="!hasMore && items.length > 0" class="flex flex-col items-center justify-center text-center min-h-[100dvh] pt-12">
              <p class="text-sm text-slate-400 font-medium antialiased">已浏览完所有内容</p>
              <p class="mt-1 text-xs text-slate-300 antialiased">
                {{ contentStats.read }}/{{ contentStats.total }} 已读
              </p>
            </div>
          </div>
        </div>
        </div><!-- /content wrapper (translateY) -->
      </div>

      <!-- 右栏：详情 (桌面端始终显示, 移动端滑入覆盖) -->
      <div class="hidden md:flex flex-1 min-w-0 overflow-y-auto">
        <!-- 空状态 -->
        <div v-if="!selectedId" class="flex-1 flex items-center justify-center">
          <div class="text-center">
            <div class="w-24 h-24 bg-gradient-to-br from-indigo-50 to-purple-50 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-inner">
              <svg class="w-12 h-12 text-indigo-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
            </div>
            <p class="text-base text-slate-500 font-medium">选择一篇文章查看</p>
            <p class="text-sm text-slate-400 mt-1">使用 j/k 或 ↑↓ 键快速切换，按 ? 查看快捷键</p>
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
          <div ref="rightPanelRef" class="flex-1 overflow-y-auto overflow-x-hidden p-6 space-y-4">
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
              <button
                v-if="chatMessages.length > 0"
                class="shrink-0 p-2.5 rounded-xl text-slate-400 hover:text-red-500 hover:bg-red-50 transition-all"
                title="清除对话"
                @click="clearHistory"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                </svg>
              </button>
              <textarea
                ref="chatInputRef"
                v-model="chatInput"
                :disabled="chatStreaming"
                rows="1"
                class="flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-[16px] md:text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all disabled:opacity-50"
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
        :leave-active-class="swipeDismissing ? '' : 'transition-transform duration-150 ease-in'"
        :leave-from-class="swipeDismissing ? '' : 'translate-x-0'"
        :leave-to-class="swipeDismissing ? '' : 'translate-x-full'"
        @after-leave="swipeDismissing = false"
      >
        <div
          v-if="showMobileDetail && selectedId"
          ref="mobileDetailRef"
          class="fixed inset-x-0 z-40 bg-white flex flex-col md:hidden"
          :style="{ top: mobileDetailTop + 'px', height: mobileDetailHeight != null ? mobileDetailHeight + 'px' : '100dvh' }"
        >
          <!-- 移动端详情内容 -->
          <div v-if="detailLoading && !detailContent" class="flex-1 flex items-center justify-center">
            <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
          </div>

          <div v-else-if="detailContent" class="flex-1 min-h-0 flex flex-col">
            <div class="flex-1 overflow-y-auto">
              <DetailContent
                ref="mobileDetailContentRef"
                :item="detailContent"
                :is-mobile-overlay="true"
                :analyzing="analyzing"
                :enriching="enriching"
                :enrich-results="enrichResults"
                :show-enrich-modal="showEnrichModal"
                :applying-enrich="applyingEnrich"
                @back="closeMobileDetail"
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
                <button
                  v-if="chatMessages.length > 0"
                  class="shrink-0 p-2.5 rounded-xl text-slate-400 hover:text-red-500 hover:bg-red-50 transition-all"
                  title="清除对话"
                  @click="clearHistory"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                  </svg>
                </button>
                <textarea
                  v-model="chatInput"
                  :disabled="chatStreaming"
                  rows="1"
                  class="flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-[16px] md:text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all disabled:opacity-50 max-h-[6rem] overflow-y-auto"
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

    <!-- 快捷键帮助浮层 -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition-opacity duration-150 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-opacity duration-100 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div
          v-if="showShortcutHelp"
          class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
          @click.self="showShortcutHelp = false"
        >
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-base font-bold text-slate-900">快捷键</h3>
              <button
                class="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all"
                @click="showShortcutHelp = false"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div class="space-y-2.5 text-sm">
              <div class="flex items-center justify-between">
                <span class="text-slate-600">下一篇</span>
                <div class="flex gap-1">
                  <kbd class="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono text-slate-600 border border-slate-200">j</kbd>
                  <kbd class="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono text-slate-600 border border-slate-200">↓</kbd>
                </div>
              </div>
              <div class="flex items-center justify-between">
                <span class="text-slate-600">上一篇</span>
                <div class="flex gap-1">
                  <kbd class="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono text-slate-600 border border-slate-200">k</kbd>
                  <kbd class="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono text-slate-600 border border-slate-200">↑</kbd>
                </div>
              </div>
              <div class="flex items-center justify-between">
                <span class="text-slate-600">收藏/取消</span>
                <kbd class="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono text-slate-600 border border-slate-200">s</kbd>
              </div>
              <div class="flex items-center justify-between">
                <span class="text-slate-600">打开原文</span>
                <kbd class="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono text-slate-600 border border-slate-200">o</kbd>
              </div>
              <div class="flex items-center justify-between">
                <span class="text-slate-600">标记已读</span>
                <kbd class="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono text-slate-600 border border-slate-200">m</kbd>
              </div>
              <div class="flex items-center justify-between">
                <span class="text-slate-600">重新分析</span>
                <kbd class="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono text-slate-600 border border-slate-200">a</kbd>
              </div>
              <div class="flex items-center justify-between">
                <span class="text-slate-600">快捷键帮助</span>
                <kbd class="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono text-slate-600 border border-slate-200">?</kbd>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

