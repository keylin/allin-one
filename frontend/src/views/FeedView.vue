<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listContent, getContent, analyzeContent, toggleFavorite, listSourceOptions, incrementView, chatWithContent, enrichContent, applyEnrichment, getContentStats, batchMarkRead } from '@/api/content'
import { useToast } from '@/composables/useToast'
import { useIntersectionObserver } from '@/composables/useIntersectionObserver'
import { useDebounce } from '@/composables/useDebounce'
import { useSwipe } from '@/composables/useSwipe'
import FeedCard from '@/components/feed-card.vue'
import IframeVideoPlayer from '@/components/iframe-video-player.vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { formatTimeFull } from '@/utils/time'

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
const contentViewMode = ref('best') // 'best' | 'processed' | 'raw'
let detailRequestId = 0 // 防止快速切换时竞态覆盖

// --- Chat state ---
const chatMessages = ref([])
const chatInput = ref('')
const chatStreaming = ref(false)
const chatAbort = ref(null)
const chatInputRef = ref(null)
const chatMessagesEndRef = ref(null)

// --- Toast ---
const { success: toastSuccess, error: toastError } = useToast()

// --- Enrich state ---
const enriching = ref(false)
const enrichResults = ref(null)
const showEnrichModal = ref(false)
const applyingEnrich = ref(null)

// === 自动标记已读状态 ===
const hasScrolled = ref(false) // 用户是否已开始滚动
const pendingReadIds = ref(new Set()) // 待提交的已读 ID
const cardPositions = ref(new Map()) // Map<itemId, lastY> 记录卡片Y坐标，用于判断移动方向
const mobileDetailRef = ref(null) // 移动端详情容器 ref
const autoActivateTimer = ref(null) // 非可滚动容器的自动激活定时器
const AUTO_ACTIVATE_DELAY = 3000 // 3秒延迟（给用户开始阅读的时间）

// Markdown & DOMPurify setup
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

const md = new MarkdownIt({ html: true, linkify: true, typographer: true })

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

// --- Detail computed ---
const renderedAnalysis = computed(() => {
  if (!detailContent.value?.analysis_result) return ''
  const analysis = detailContent.value.analysis_result
  if (typeof analysis === 'object') {
    let markdown = ''
    if (analysis.summary) markdown += `## 摘要\n\n${analysis.summary}\n\n`
    if (analysis.tags && Array.isArray(analysis.tags)) markdown += `**标签:** ${analysis.tags.join(', ')}\n\n`
    if (analysis.sentiment) markdown += `**情感:** ${analysis.sentiment}\n\n`
    if (analysis.category) markdown += `**分类:** ${analysis.category}\n\n`
    for (const [key, value] of Object.entries(analysis)) {
      if (!['summary', 'tags', 'sentiment', 'category'].includes(key)) {
        markdown += `**${key}:** ${value}\n\n`
      }
    }
    return md.render(markdown)
  }
  return md.render(String(analysis))
})

const renderedContent = computed(() => {
  if (!detailContent.value?.processed_content) return ''
  const text = detailContent.value.processed_content
  // HTML 内容 → DOMPurify 清理后直接渲染
  if (/<[a-z][\s\S]*>/i.test(text)) {
    return DOMPurify.sanitize(text, {
      ALLOWED_TAGS: [
        'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'a', 'img', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
        'em', 'strong', 'b', 'i', 'u', 's', 'del', 'sub', 'sup', 'hr',
        'table', 'thead', 'tbody', 'tr', 'td', 'th', 'caption',
        'figure', 'figcaption', 'div', 'span',
      ],
      ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'width', 'height', 'target', 'rel', 'class'],
      ADD_ATTR: ['target'],
      FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'textarea', 'select'],
    })
  }
  // Markdown fallback（兼容历史纯文本数据）
  if (text.includes('##') || text.includes('**') || text.includes('[](')) {
    return md.render(text)
  }
  return `<pre class="whitespace-pre-wrap">${text}</pre>`
})

// 是否两个版本都有内容，支持切换
const hasBothVersions = computed(() => {
  return !!detailContent.value?.processed_content && hasRawContent.value
})

// 当前展示的正文 HTML（根据 contentViewMode 选择）
const displayedBodyHtml = computed(() => {
  const mode = contentViewMode.value
  if (mode === 'raw' && hasRawContent.value) return renderedRawContent.value
  if (mode === 'processed' && detailContent.value?.processed_content) return renderedContent.value
  // 'best' 模式：优先 processed，否则 raw
  if (detailContent.value?.processed_content) return renderedContent.value
  if (hasRawContent.value) return renderedRawContent.value
  return ''
})

// 当前展示模式的标签
const currentViewLabel = computed(() => {
  if (contentViewMode.value === 'raw') return '原文'
  if (contentViewMode.value === 'processed') return '处理版'
  // best 模式下显示实际选中的版本
  return detailContent.value?.processed_content ? '处理版' : '原文'
})

function toggleContentView() {
  if (contentViewMode.value === 'raw' || (contentViewMode.value === 'best' && !detailContent.value?.processed_content)) {
    contentViewMode.value = 'processed'
  } else {
    contentViewMode.value = 'raw'
  }
}

const renderedRawContent = computed(() => {
  if (!detailContent.value?.raw_data) return ''
  try {
    const raw = typeof detailContent.value.raw_data === 'string'
      ? JSON.parse(detailContent.value.raw_data)
      : detailContent.value.raw_data
    if (!raw || typeof raw !== 'object') return ''
    let html = ''
    if (Array.isArray(raw.content) && raw.content.length > 0) {
      const first = raw.content[0]
      html = typeof first === 'object' ? (first.value || '') : String(first)
    }
    if (!html) html = raw.summary || raw.description || ''
    if (!html.trim()) return ''
    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS: [
        'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'a', 'img', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
        'em', 'strong', 'b', 'i', 'u', 's', 'del', 'sub', 'sup', 'hr',
        'table', 'thead', 'tbody', 'tr', 'td', 'th', 'caption',
        'figure', 'figcaption', 'video', 'source', 'audio',
        'div', 'span',
      ],
      ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'width', 'height', 'target', 'rel', 'class'],
      ADD_ATTR: ['target'],
      FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'textarea', 'select'],
    })
  } catch {
    return ''
  }
})

const hasRawContent = computed(() => renderedRawContent.value.length > 0)

const urlHostname = computed(() => {
  if (!detailContent.value?.url) return ''
  try {
    return new URL(detailContent.value.url).hostname.replace(/^www\./, '')
  } catch {
    return detailContent.value.url
  }
})

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

// --- Mobile detail overlay ---
const showMobileDetail = ref(false)

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
    // 仅当仍是最新请求时才更新，防止快速切换时旧请求覆盖新数据
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
  contentViewMode.value = 'best'
  clearChat()
  // 右栏滚回顶部
  if (rightPanelRef.value) rightPanelRef.value.scrollTop = 0
  incrementView(item.id).then(() => {
    // 如果是首次查看（从未读变已读），更新统计数据
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
    // Also update detail panel
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

function renderEnrichMarkdown(text) {
  return DOMPurify.sanitize(md.render(text))
}

function formatBytes(len) {
  if (len < 1024) return `${len} B`
  return `${(len / 1024).toFixed(1)} KB`
}

// --- Chat methods ---
function cancelChat() {
  if (chatAbort.value) {
    chatAbort.value.abort()
    chatAbort.value = null
  }
  chatStreaming.value = false
}

function clearChat() {
  cancelChat()
  chatMessages.value = []
  chatInput.value = ''
}

function scrollToLastMessage() {
  nextTick(() => {
    if (chatMessagesEndRef.value) {
      chatMessagesEndRef.value.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  })
}

function sendChat() {
  const text = chatInput.value.trim()
  if (!text || chatStreaming.value || !selectedId.value) return

  chatMessages.value.push({ role: 'user', content: text })
  chatInput.value = ''
  chatStreaming.value = true

  // Add placeholder for assistant response
  chatMessages.value.push({ role: 'assistant', content: '' })
  const assistantIdx = chatMessages.value.length - 1
  scrollToLastMessage()

  // Build messages for API (exclude the empty assistant placeholder)
  const apiMessages = chatMessages.value
    .filter((m, i) => i < assistantIdx)
    .map(({ role, content }) => ({ role, content }))

  chatAbort.value = chatWithContent(
    selectedId.value,
    apiMessages,
    (chunk) => {
      chatMessages.value[assistantIdx].content += chunk
      scrollToLastMessage()
    },
    () => {
      chatStreaming.value = false
      chatAbort.value = null
      scrollToLastMessage()
    },
    (errMsg) => {
      chatMessages.value[assistantIdx].content = `**错误:** ${errMsg}`
      chatStreaming.value = false
      chatAbort.value = null
      scrollToLastMessage()
    },
  )
}

function handleChatKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendChat()
  }
}

function renderChatMarkdown(text) {
  return DOMPurify.sanitize(md.render(text))
}

function formatTime(t) {
  return formatTimeFull(t)
}

// --- Left panel scroll → infinite load ---
function handleLeftScroll(e) {
  const el = e.target
  const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight

  // 原有逻辑：距离底部 200px 时触发无限加载
  if (distanceToBottom < 200) {
    loadMore()
  }

  // 新增逻辑：滚动到底部时标记最后一条未读卡片
  if (hasScrolled.value && distanceToBottom < 50) {
    const unreadItems = items.value.filter(i => (i.view_count || 0) === 0)
    if (unreadItems.length > 0) {
      const lastUnread = unreadItems[unreadItems.length - 1]
      markAsRead(lastUnread.id)
    }
  }
}

// --- Keyboard navigation (↑ ↓) ---
function handleKeydown(e) {
  // Don't intercept when typing in inputs
  const tag = e.target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

  // Navigation: ↑ ↓
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    const idx = selectedIndex.value
    if (idx < items.value.length - 1) {
      const nextItem = items.value[idx + 1]
      selectItem(nextItem)
      // Pre-load more when near end
      if (idx + 1 >= items.value.length - 3 && hasMore.value) loadMore()
      // Scroll selected card into view
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

/**
 * 检测容器是否可滚动
 */
function isContainerScrollable() {
  const container = leftPanelRef.value
  if (!container) return false
  return container.scrollHeight > container.clientHeight
}

/**
 * 检查并激活自动标记已读功能
 * - 可滚动容器: 等待用户首次滚动（保持原有行为）
 * - 不可滚动容器: 延迟 3 秒后自动激活
 */
function checkAndActivateAutoRead() {
  // 已激活或无内容，跳过
  if (hasScrolled.value) return

  // 清理之前的定时器
  if (autoActivateTimer.value) {
    clearTimeout(autoActivateTimer.value)
    autoActivateTimer.value = null
  }

  const container = leftPanelRef.value
  if (!container || items.value.length === 0) return

  if (isContainerScrollable()) {
    // 策略 A: 可滚动 → 等待滚动事件（已在 onMounted 中设置）
    console.log('[Auto-read] 容器可滚动，等待用户滚动')
  } else {
    // 策略 B: 不可滚动 → 延迟后自动激活
    console.log('[Auto-read] 容器不可滚动，将在 3 秒后自动激活')
    autoActivateTimer.value = setTimeout(() => {
      // 再次检查是否仍不可滚动（防止期间加载了更多内容）
      if (!hasScrolled.value && !isContainerScrollable()) {
        console.log('[Auto-read] 自动激活（内容少于一页）')
        hasScrolled.value = true
      }
    }, AUTO_ACTIVATE_DELAY)
  }
}

// --- 自动标记已读逻辑 ---
// IntersectionObserver 回调
function handleCardVisible(entry) {
  // 1. 未激活时不处理
  if (!hasScrolled.value) return

  // 2. 获取卡片数据
  const itemId = entry.target.dataset.itemId
  const item = items.value.find(i => i.id === itemId)

  // 3. 过滤已读卡片
  if (!item || (item.view_count || 0) > 0) {
    cardPositions.value.delete(itemId)
    return
  }

  // 4. 获取位置信息
  const currentY = entry.boundingClientRect.top
  const lastY = cardPositions.value.get(itemId)

  if (entry.isIntersecting) {
    // === 卡片进入视野 → 记录位置 ===
    cardPositions.value.set(itemId, currentY)
  } else {
    // === 卡片离开视野 → 判断方向并标记 ===
    if (lastY !== undefined) {
      const isMovingUp = currentY < lastY // 向上移动

      if (isMovingUp) {
        // 向上离开视野 → 立即标记为已读
        markAsRead(itemId)
      }
    }

    // 清理位置记录
    cardPositions.value.delete(itemId)
  }
}

// 标记单个 item 为已读（加入批量队列）
function markAsRead(itemId) {
  if (!pendingReadIds.value.has(itemId)) {
    pendingReadIds.value.add(itemId)
    debouncedBatchSubmit()
  }
}

// 防抖批量提交已读
const debouncedBatchSubmit = useDebounce(async () => {
  if (pendingReadIds.value.size === 0) return

  const ids = Array.from(pendingReadIds.value)
  pendingReadIds.value.clear()

  try {
    await batchMarkRead(ids)

    // 更新本地状态（立即反映视觉变化）
    ids.forEach(id => {
      const item = items.value.find(i => i.id === id)
      if (item) {
        item.view_count = 1
        item.last_viewed_at = new Date().toISOString()
      }
    })

    // 刷新统计数据
    await loadStats()
  } catch (err) {
    console.error('批量标记已读失败:', err)
    // 失败时重新加入队列（下次重试）
    ids.forEach(id => pendingReadIds.value.add(id))
  }
}, 500) // 500ms 防抖

// 初始化 IntersectionObserver
const { observe, unobserve, disconnect } = useIntersectionObserver(
  handleCardVisible,
  {
    threshold: 0,  // 卡片完全离开视野时触发
    rootMargin: '-100px 0px 0px 0px'  // 顶部向内收缩100px，让卡片更早被视为"离开"
  }
)

// 监听 items 变化，自动观察新卡片
watch(items, () => {
  nextTick(() => {
    const container = leftPanelRef.value
    if (!container) return

    // 获取所有卡片元素
    const cards = container.querySelectorAll('[data-item-id]')
    cards.forEach(card => {
      const itemId = card.dataset.itemId
      const item = items.value.find(i => i.id === itemId)

      // 只观察未读卡片
      if (item && (item.view_count || 0) === 0) {
        observe(card)
      }
    })

    // 检查是否需要自动激活
    checkAndActivateAutoRead()
  })
}, { flush: 'post' })

// 初始化手势
const { isSwiping, swipeOffset } = useSwipe(mobileDetailRef, {
  threshold: 80,
  onSwipeRight: () => {
    closeMobileDetail()
  }
})

// 窗口 resize 处理（防抖）
const handleResize = useDebounce(() => {
  checkAndActivateAutoRead()
}, 300)

onMounted(async () => {
  fetchItems(true)
  loadStats()
  try {
    const res = await listSourceOptions()
    if (res.code === 0) sourceOptions.value = res.data
  } catch (_) { /* ignore */ }
  document.addEventListener('keydown', handleKeydown)
  document.addEventListener('click', handleClickOutside)

  // 监听首次滚动，激活自动标记已读
  const container = leftPanelRef.value
  if (container) {
    container.addEventListener('scroll', () => {
      hasScrolled.value = true
    }, { once: true })
  }

  // 监听窗口大小变化（视口改变可能影响可滚动性）
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  clearTimeout(searchTimer)
  cancelChat()
  document.removeEventListener('keydown', handleKeydown)
  document.removeEventListener('click', handleClickOutside)
  // 清理自动标记已读
  disconnect()
  pendingReadIds.value.clear()
  cardPositions.value.clear()
  hasScrolled.value = false
  // 清理自动激活定时器和 resize 监听器
  if (autoActivateTimer.value) {
    clearTimeout(autoActivateTimer.value)
  }
  window.removeEventListener('resize', handleResize)
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
            <!-- 标题 + 操作按钮 + 元信息 -->
            <div>
              <div class="flex items-start justify-between gap-3">
                <h2 class="text-xl font-bold text-slate-900 mb-2 min-w-0">{{ detailContent.title }}</h2>
                <div class="flex items-center gap-1 shrink-0">
                  <a
                    v-if="detailContent.url"
                    :href="detailContent.url"
                    target="_blank"
                    rel="noopener"
                    class="p-1.5 rounded-lg text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 transition-all"
                    title="查看原文"
                  >
                    <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                    </svg>
                  </a>
                  <button
                    class="p-1.5 rounded-lg transition-all disabled:opacity-40"
                    :class="analyzing ? 'text-indigo-600 animate-spin' : 'text-slate-400 hover:text-indigo-600 hover:bg-indigo-50'"
                    :disabled="analyzing"
                    title="重新分析"
                    @click="handleAnalyze"
                  >
                    <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
                    </svg>
                  </button>
                  <button
                    class="p-1.5 rounded-lg transition-all"
                    :class="detailContent.is_favorited
                      ? 'text-amber-500 hover:bg-amber-50'
                      : 'text-slate-400 hover:text-amber-500 hover:bg-amber-50'"
                    :title="detailContent.is_favorited ? '取消收藏' : '收藏'"
                    @click="handleDetailFavorite"
                  >
                    <svg class="w-4.5 h-4.5" :fill="detailContent.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                    </svg>
                  </button>
                </div>
              </div>
              <div class="flex items-center gap-2 text-sm text-slate-400 flex-wrap">
                <a v-if="detailContent.url" :href="detailContent.url" target="_blank" rel="noopener"
                   class="inline-flex items-center gap-1 text-slate-400 hover:text-indigo-600 transition-colors"
                   :title="detailContent.url">
                  <span class="text-xs">跳转来源</span>
                </a>
                <span class="inline-flex items-center gap-1.5 font-medium text-slate-500">
                  <span class="w-2 h-2 rounded-full bg-indigo-400 shrink-0"></span>
                  {{ detailContent.source_name || '未知来源' }}
                </span>
                <span v-if="detailContent.author" class="text-slate-400">{{ detailContent.author }}</span>
                <span class="text-slate-300">&middot;</span>
                <span>{{ formatTime(detailContent.published_at || detailContent.created_at) }}</span>
                <span
                  v-if="detailContent.status && detailContent.status !== 'ready'"
                  class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md"
                  :class="statusStyles[detailContent.status] || 'bg-slate-100 text-slate-600'"
                >
                  {{ statusLabels[detailContent.status] || detailContent.status }}
                </span>
              </div>
              <!-- 操作按钮组（富化对比 + 收藏） -->
              <div class="mt-3 flex items-center gap-2">
                <!-- 富化对比按钮 -->
                <button
                  v-if="detailContent.url"
                  class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  :class="enriching
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200 animate-pulse'
                    : 'bg-white text-emerald-700 border-emerald-200 hover:bg-emerald-50 hover:border-emerald-300'"
                  :disabled="enriching"
                  @click="handleEnrich"
                >
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
                  </svg>
                  {{ enriching ? '富化中...' : '富化对比' }}
                </button>

                <!-- 收藏按钮 -->
                <button
                  class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-all"
                  :class="detailContent.is_favorited
                    ? 'bg-amber-50 text-amber-600 border-amber-200 hover:bg-amber-100'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50 hover:border-slate-300'"
                  @click="handleDetailFavorite"
                >
                  <svg class="w-3.5 h-3.5" :fill="detailContent.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                  </svg>
                  {{ detailContent.is_favorited ? '已收藏' : '收藏' }}
                </button>
              </div>
            </div>

            <!-- 视频播放器 -->
            <IframeVideoPlayer
              v-if="detailContent.media_items?.some(m => m.media_type === 'video')"
              :key="'vp-' + detailContent.id"
              :video-url="detailContent.url"
              :title="detailContent.title || '视频播放'"
            />

            <!-- AI 分析结果 -->
            <div v-if="detailContent.analysis_result" class="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-6 border border-indigo-100">
              <h3 class="text-base font-semibold text-slate-900 mb-4 flex items-center gap-2">
                <svg class="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
                AI 分析
              </h3>
              <div class="prose prose-sm max-w-none markdown-content" v-html="renderedAnalysis"></div>
            </div>

            <!-- 正文内容（智能选择最佳版本） -->
            <div v-if="displayedBodyHtml" class="bg-slate-50 rounded-xl p-6">
              <div class="flex items-center justify-between mb-4">
                <h3 class="text-base font-semibold text-slate-900 flex items-center gap-2">
                  <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                  </svg>
                  正文内容
                </h3>
                <button
                  v-if="hasBothVersions"
                  class="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border border-slate-200 text-slate-500 hover:text-slate-700 hover:border-slate-300 bg-white transition-all"
                  @click="toggleContentView"
                >
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                  </svg>
                  {{ currentViewLabel === '处理版' ? '查看原文' : '查看处理版' }}
                </button>
              </div>
              <div class="prose prose-sm max-w-none markdown-content text-slate-700" v-html="displayedBodyHtml"></div>
            </div>

            <!-- AI 对话消息 -->
            <div v-if="chatMessages.length" class="space-y-3 pt-2">
              <div class="flex items-center gap-2 text-xs text-slate-400">
                <div class="flex-1 border-t border-slate-200"></div>
                <span>AI 对话</span>
                <div class="flex-1 border-t border-slate-200"></div>
              </div>
              <div
                v-for="(msg, idx) in chatMessages"
                :key="idx"
                class="flex"
                :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
              >
                <div
                  class="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed"
                  :class="msg.role === 'user'
                    ? 'bg-indigo-600 text-white rounded-br-md'
                    : 'bg-slate-100 text-slate-700 rounded-bl-md'"
                >
                  <div
                    v-if="msg.role === 'assistant'"
                    class="prose prose-sm max-w-none chat-markdown"
                    v-html="renderChatMarkdown(msg.content || '')"
                  ></div>
                  <template v-else>{{ msg.content }}</template>
                  <span
                    v-if="msg.role === 'assistant' && chatStreaming && idx === chatMessages.length - 1"
                    class="inline-block w-1.5 h-4 bg-slate-400 ml-0.5 animate-pulse rounded-sm align-middle"
                  ></span>
                </div>
              </div>
              <div ref="chatMessagesEndRef"></div>
            </div>
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

          <!-- 移动端详情内容 (复用相同结构) -->
          <div v-if="detailLoading && !detailContent" class="flex-1 flex items-center justify-center">
            <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
          </div>

          <div v-else-if="detailContent" class="flex-1 min-h-0 flex flex-col">
            <div class="flex-1 overflow-y-auto p-4 space-y-5">
              <!-- 标题 + 操作按钮 + 元信息 -->
              <div>
                <div class="flex items-start justify-between gap-3">
                  <h2 class="text-lg font-bold text-slate-900 mb-2 min-w-0">{{ detailContent.title }}</h2>
                  <div class="flex items-center gap-1 shrink-0">
                    <a
                      v-if="detailContent.url"
                      :href="detailContent.url"
                      target="_blank"
                      rel="noopener"
                      class="p-1.5 rounded-lg text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 transition-all"
                      title="查看原文"
                    >
                      <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                      </svg>
                    </a>
                    <button
                      class="p-1.5 rounded-lg transition-all disabled:opacity-40"
                      :class="analyzing ? 'text-indigo-600 animate-spin' : 'text-slate-400 hover:text-indigo-600 hover:bg-indigo-50'"
                      :disabled="analyzing"
                      title="重新分析"
                      @click="handleAnalyze"
                    >
                      <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
                      </svg>
                    </button>
                    <button
                      class="p-1.5 rounded-lg transition-all"
                      :class="detailContent.is_favorited
                        ? 'text-amber-500 hover:bg-amber-50'
                        : 'text-slate-400 hover:text-amber-500 hover:bg-amber-50'"
                      :title="detailContent.is_favorited ? '取消收藏' : '收藏'"
                      @click="handleDetailFavorite"
                    >
                      <svg class="w-4.5 h-4.5" :fill="detailContent.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                      </svg>
                    </button>
                  </div>
                </div>
                <div class="flex items-center gap-2 text-sm text-slate-400 flex-wrap">
                  <a v-if="detailContent.url" :href="detailContent.url" target="_blank" rel="noopener"
                     class="inline-flex items-center gap-1 text-slate-400 hover:text-indigo-600 transition-colors"
                     :title="detailContent.url">
                    <span class="text-xs">跳转来源</span>
                  </a>
                  <span class="inline-flex items-center gap-1.5 font-medium text-slate-500">
                    <span class="w-2 h-2 rounded-full bg-indigo-400 shrink-0"></span>
                    {{ detailContent.source_name || '未知来源' }}
                  </span>
                  <span v-if="detailContent.author" class="text-slate-400">{{ detailContent.author }}</span>
                  <span class="text-slate-300">&middot;</span>
                  <span>{{ formatTime(detailContent.published_at || detailContent.created_at) }}</span>
                  <span
                    v-if="detailContent.status && detailContent.status !== 'ready'"
                    class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md"
                    :class="statusStyles[detailContent.status] || 'bg-slate-100 text-slate-600'"
                  >
                    {{ statusLabels[detailContent.status] || detailContent.status }}
                  </span>
                </div>
                <!-- 操作按钮组（富化对比 + 收藏）（移动端） -->
                <div class="mt-3 flex items-center gap-2">
                  <!-- 富化对比按钮 -->
                  <button
                    v-if="detailContent.url"
                    class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                    :class="enriching
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200 animate-pulse'
                      : 'bg-white text-emerald-700 border-emerald-200 hover:bg-emerald-50 hover:border-emerald-300'"
                    :disabled="enriching"
                    @click="handleEnrich"
                  >
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
                    </svg>
                    {{ enriching ? '富化中...' : '富化对比' }}
                  </button>

                  <!-- 收藏按钮 -->
                  <button
                    class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-all"
                    :class="detailContent.is_favorited
                      ? 'bg-amber-50 text-amber-600 border-amber-200 hover:bg-amber-100'
                      : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50 hover:border-slate-300'"
                    @click="handleDetailFavorite"
                  >
                    <svg class="w-3.5 h-3.5" :fill="detailContent.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                    </svg>
                    {{ detailContent.is_favorited ? '已收藏' : '收藏' }}
                  </button>
                </div>
              </div>

              <!-- 视频播放器 -->
              <IframeVideoPlayer
                v-if="detailContent.media_items?.some(m => m.media_type === 'video')"
                :key="'m-vp-' + detailContent.id"
                :video-url="detailContent.url"
                :title="detailContent.title || '视频播放'"
              />

              <!-- AI 分析 -->
              <div v-if="detailContent.analysis_result" class="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-4 border border-indigo-100">
                <h3 class="text-sm font-semibold text-slate-900 mb-3 flex items-center gap-2">
                  <svg class="w-4 h-4 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                  AI 分析
                </h3>
                <div class="prose prose-sm max-w-none markdown-content" v-html="renderedAnalysis"></div>
              </div>

              <!-- 正文内容（智能选择最佳版本） -->
              <div v-if="displayedBodyHtml" class="bg-slate-50 rounded-xl p-4">
                <div class="flex items-center justify-between mb-3">
                  <h3 class="text-sm font-semibold text-slate-900 flex items-center gap-2">
                    <svg class="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                    </svg>
                    正文内容
                  </h3>
                  <button
                    v-if="hasBothVersions"
                    class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg border border-slate-200 text-slate-500 hover:text-slate-700 hover:border-slate-300 bg-white transition-all"
                    @click="toggleContentView"
                  >
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                    </svg>
                    {{ currentViewLabel === '处理版' ? '查看原文' : '查看处理版' }}
                  </button>
                </div>
                <div class="prose prose-sm max-w-none markdown-content text-slate-700" v-html="displayedBodyHtml"></div>
              </div>

              <!-- AI 对话消息 -->
              <div v-if="chatMessages.length" class="space-y-3 pt-2">
                <div class="flex items-center gap-2 text-xs text-slate-400">
                  <div class="flex-1 border-t border-slate-200"></div>
                  <span>AI 对话</span>
                  <div class="flex-1 border-t border-slate-200"></div>
                </div>
                <div
                  v-for="(msg, idx) in chatMessages"
                  :key="idx"
                  class="flex"
                  :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
                >
                  <div
                    class="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed"
                    :class="msg.role === 'user'
                      ? 'bg-indigo-600 text-white rounded-br-md'
                      : 'bg-slate-100 text-slate-700 rounded-bl-md'"
                  >
                    <div
                      v-if="msg.role === 'assistant'"
                      class="prose prose-sm max-w-none chat-markdown"
                      v-html="renderChatMarkdown(msg.content || '')"
                    ></div>
                    <template v-else>{{ msg.content }}</template>
                    <span
                      v-if="msg.role === 'assistant' && chatStreaming && idx === chatMessages.length - 1"
                      class="inline-block w-1.5 h-4 bg-slate-400 ml-0.5 animate-pulse rounded-sm align-middle"
                    ></span>
                  </div>
                </div>
              </div>
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

    <!-- 富化对比弹窗 -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition-opacity duration-200 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-opacity duration-150 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div v-if="showEnrichModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm" @click.self="closeEnrichModal">
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden">
            <!-- 弹窗头部 -->
            <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100 shrink-0">
              <div>
                <h3 class="text-lg font-bold text-slate-900">富化对比</h3>
                <p class="text-xs text-slate-400 mt-0.5 truncate max-w-md">{{ detailContent?.url }}</p>
              </div>
              <button
                class="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all"
                @click="closeEnrichModal"
              >
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <!-- 加载态 -->
            <div v-if="enriching" class="flex-1 flex flex-col items-center justify-center py-20">
              <svg class="w-12 h-12 animate-spin text-emerald-400 mb-4" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
              <p class="text-sm font-medium text-slate-600">正在并行抓取三种来源...</p>
              <p class="text-xs text-slate-400 mt-1">L1 HTTP / Crawl4AI / L3 Browserless</p>
            </div>

            <!-- 结果态 -->
            <div v-else-if="enrichResults" class="flex-1 overflow-y-auto p-6">
              <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div
                  v-for="result in enrichResults"
                  :key="result.level"
                  class="flex flex-col rounded-xl border transition-all"
                  :class="result.success ? 'border-slate-200 bg-white' : 'border-red-100 bg-red-50/30'"
                >
                  <!-- 卡片头部 -->
                  <div class="px-4 py-3 border-b" :class="result.success ? 'border-slate-100' : 'border-red-100'">
                    <div class="flex items-center justify-between mb-1.5">
                      <h4 class="text-sm font-semibold text-slate-800">{{ result.label }}</h4>
                      <span
                        class="inline-flex px-2 py-0.5 text-xs font-medium rounded-full"
                        :class="result.success ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'"
                      >
                        {{ result.success ? '成功' : '失败' }}
                      </span>
                    </div>
                    <div class="flex items-center gap-3 text-xs text-slate-400">
                      <span>{{ result.elapsed_seconds }}s</span>
                      <span v-if="result.success">{{ formatBytes(result.content_length) }}</span>
                      <span v-if="result.error" class="text-red-400 truncate" :title="result.error">{{ result.error }}</span>
                    </div>
                  </div>

                  <!-- 内容预览 -->
                  <div class="flex-1 px-4 py-3 max-h-80 overflow-y-auto">
                    <div
                      v-if="result.success && result.content"
                      class="prose prose-sm max-w-none markdown-content text-slate-600 text-xs leading-relaxed"
                      v-html="renderEnrichMarkdown(result.content)"
                    ></div>
                    <div v-else class="flex items-center justify-center h-24">
                      <p class="text-xs text-slate-400">{{ result.error || '无内容' }}</p>
                    </div>
                  </div>

                  <!-- 操作按钮 -->
                  <div class="px-4 py-3 border-t" :class="result.success ? 'border-slate-100' : 'border-red-100'">
                    <button
                      v-if="result.success"
                      class="w-full px-4 py-2 text-sm font-medium rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                      :class="applyingEnrich === result.level
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-emerald-600 text-white hover:bg-emerald-700'"
                      :disabled="applyingEnrich !== null"
                      @click="handleApplyEnrich(result)"
                    >
                      {{ applyingEnrich === result.level ? '应用中...' : '应用此结果' }}
                    </button>
                    <div v-else class="text-center text-xs text-slate-400 py-1.5">
                      抓取失败，不可应用
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
/* 内容区域溢出控制 */
.markdown-content,
.raw-content {
  overflow-wrap: break-word;
  word-break: break-word;
}
.markdown-content :deep(img),
.raw-content :deep(img) {
  max-width: 100%;
  height: auto;
}
.markdown-content :deep(pre),
.raw-content :deep(pre) {
  overflow-x: auto;
  max-width: 100%;
}
.markdown-content :deep(table),
.raw-content :deep(table) {
  display: block;
  overflow-x: auto;
  max-width: 100%;
}

/* Markdown 内容样式 */
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3) {
  margin-top: 1.5em;
  margin-bottom: 0.5em;
  font-weight: 600;
  color: #1e293b;
}

.markdown-content :deep(h2) {
  font-size: 1.25em;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 0.3em;
}

.markdown-content :deep(p) {
  margin-bottom: 1em;
  line-height: 1.7;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin-bottom: 1em;
  padding-left: 1.5em;
}

.markdown-content :deep(li) {
  margin-bottom: 0.5em;
}

.markdown-content :deep(code) {
  background: #f1f5f9;
  padding: 0.2em 0.4em;
  border-radius: 0.25em;
  font-size: 0.9em;
  color: #e11d48;
  font-family: 'Monaco', 'Menlo', monospace;
}

.markdown-content :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  padding: 1em;
  border-radius: 0.5em;
  overflow-x: auto;
  margin-bottom: 1em;
}

.markdown-content :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
}

.markdown-content :deep(a) {
  color: #6366f1;
  text-decoration: underline;
}

.markdown-content :deep(a:hover) {
  color: #4f46e5;
}

.markdown-content :deep(blockquote) {
  border-left: 4px solid #e2e8f0;
  padding-left: 1em;
  margin-left: 0;
  color: #64748b;
  font-style: italic;
}

.markdown-content :deep(strong) {
  font-weight: 600;
  color: #1e293b;
}

/* RSS 原文内容样式 */
.raw-content :deep(p) {
  margin-bottom: 1em;
  line-height: 1.7;
}

.raw-content :deep(h1),
.raw-content :deep(h2),
.raw-content :deep(h3),
.raw-content :deep(h4) {
  margin-top: 1.5em;
  margin-bottom: 0.5em;
  font-weight: 600;
  color: #1e293b;
}

.raw-content :deep(a) {
  color: #6366f1;
  text-decoration: underline;
}

.raw-content :deep(a:hover) {
  color: #4f46e5;
}

.raw-content :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 0.5em;
  margin: 1em 0;
}

.raw-content :deep(ul),
.raw-content :deep(ol) {
  margin-bottom: 1em;
  padding-left: 1.5em;
}

.raw-content :deep(li) {
  margin-bottom: 0.5em;
}

.raw-content :deep(blockquote) {
  border-left: 4px solid #e2e8f0;
  padding-left: 1em;
  margin-left: 0;
  color: #64748b;
  font-style: italic;
}

.raw-content :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  padding: 1em;
  border-radius: 0.5em;
  overflow-x: auto;
  margin-bottom: 1em;
}

.raw-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 1em;
}

.raw-content :deep(th),
.raw-content :deep(td) {
  border: 1px solid #e2e8f0;
  padding: 0.5em 0.75em;
  text-align: left;
}

.raw-content :deep(th) {
  background: #f8fafc;
  font-weight: 600;
}

/* AI 对话气泡内 markdown */
.chat-markdown :deep(p) {
  margin-bottom: 0.5em;
  line-height: 1.6;
}
.chat-markdown :deep(p:last-child) {
  margin-bottom: 0;
}
.chat-markdown :deep(code) {
  background: rgba(0,0,0,0.06);
  padding: 0.15em 0.3em;
  border-radius: 0.25em;
  font-size: 0.9em;
}
.chat-markdown :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  padding: 0.75em;
  border-radius: 0.5em;
  overflow-x: auto;
  margin: 0.5em 0;
}
.chat-markdown :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
}
.chat-markdown :deep(ul),
.chat-markdown :deep(ol) {
  padding-left: 1.25em;
  margin-bottom: 0.5em;
}
.chat-markdown :deep(li) {
  margin-bottom: 0.25em;
}
.chat-markdown :deep(a) {
  color: #6366f1;
  text-decoration: underline;
}
</style>
