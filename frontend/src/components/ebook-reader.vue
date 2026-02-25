<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useScrollLock } from '@/composables/useScrollLock'
import { useSwipe } from '@/composables/useSwipe'
import {
  getEbookDetail,
  fetchEbookBlob,
  getReadingProgress,
  updateReadingProgress,
  listAnnotations,
  createAnnotation,
  updateAnnotation,
  deleteAnnotation,
  listBookmarks,
  createBookmark,
  deleteBookmark,
} from '@/api/ebook'
import { getSourceConfig } from '@/config/external-sources'
import { Overlayer } from 'foliate-js/overlayer.js'

// 注册 foliate-view 自定义元素
import 'foliate-js/view.js'

const props = defineProps({
  contentId: { type: String, required: true },
})
const emit = defineEmits(['close'])

const isVisible = ref(true)
useScrollLock(isVisible)

// --- State ---
const loading = ref(true)
const errorMsg = ref('')
const bookTitle = ref('')
const toolbarVisible = ref(false)
const tocVisible = ref(false)
const settingsVisible = ref(false)
const shortcutHelpVisible = ref(false)

// --- Desktop detection (md breakpoint: 768px) ---
const windowWidth = ref(window.innerWidth)
const isDesktop = computed(() => windowWidth.value >= 768)
function onResize() { windowWidth.value = window.innerWidth }

// Annotations & Bookmarks
const annotations = ref([])
const bookmarks = ref([])
const selection = ref(null) // { cfiRange, sectionIndex, selectedText }
const selectionToolbarVisible = ref(false)
const selectionToolbarPos = ref({ x: 0, y: 0 })
const activeAnnotation = ref(null)
const annotationPopupVisible = ref(false)
const annotationPopupPos = ref({ x: 0, y: 0 })
const noteText = ref('')
const annotationsSidebarVisible = ref(false)
const annotationsTab = ref('highlights') // 'highlights' | 'bookmarks'

// Bookmark feedback indicator
const bookmarkFeedback = ref(null) // { added: boolean } or null
let bookmarkFeedbackTimer = null
function showBookmarkFeedback(added) {
  clearTimeout(bookmarkFeedbackTimer)
  bookmarkFeedback.value = { added }
  bookmarkFeedbackTimer = setTimeout(() => { bookmarkFeedback.value = null }, 1200)
}

// Overscroll hint for scrolled mode chapter navigation
const overscrollHint = ref(null) // { direction: 'next'|'prev', progress: 0-1 }

const HIGHLIGHT_COLORS = {
  yellow: '#facc15', green: '#4ade80', blue: '#60a5fa', pink: '#f472b6', purple: '#a78bfa',
}

// TOC (flattened for rendering)
const tocItems = ref([])
const flatToc = computed(() => {
  const result = []
  function walk(items, depth = 0) {
    for (const it of items) {
      result.push({ title: it.title, href: it.href, depth })
      if (it.children?.length) walk(it.children, depth + 1)
    }
  }
  walk(tocItems.value)
  return result
})

// Reading position
const progress = ref(0)
const chapterTitle = ref('')

// Settings (persisted to localStorage)
const PREFS_KEY = 'ebook_reader_prefs'
function loadPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return {}
}
function savePrefs(extra) {
  const current = loadPrefs()
  localStorage.setItem(PREFS_KEY, JSON.stringify({
    ...current,
    fontSize: fontSize.value,
    theme: theme.value,
    fontFamily: fontFamily.value,
    flowMode: flowMode.value,
    ...extra,
  }))
}
const savedPrefs = loadPrefs()
const fontSize = ref(savedPrefs.fontSize || 100)
const theme = ref(savedPrefs.theme || 'light')
const fontFamily = ref(savedPrefs.fontFamily || 'default')
const isMobile = navigator.maxTouchPoints > 1
const flowMode = ref(savedPrefs.flowMode ?? (isMobile ? 'scrolled' : 'paginated'))

// --- Desktop panel push-content layout ---
const readerLeft = computed(() =>
  isDesktop.value && tocVisible.value ? '288px' : '0'
)
const readerRight = computed(() =>
  isDesktop.value && annotationsSidebarVisible.value ? '288px' : '0'
)
// 桌面端面板顶部：工具栏可见时避开工具栏高度，隐藏时贴顶
const panelTop = computed(() => {
  if (!isDesktop.value) return '0'
  return toolbarVisible.value ? 'calc(max(10px, env(safe-area-inset-top, 0px)) + 46px)' : '0'
})

// Grouped annotations for sidebar
const groupedAnnotations = computed(() => {
  const groups = {}
  for (const a of annotations.value) {
    const chapter = getChapterTitle(a.section_index ?? 0) || '未知章节'
    if (!groups[chapter]) groups[chapter] = []
    groups[chapter].push(a)
  }
  return groups
})

// Current page bookmarked
const currentSectionIndex = ref(0)
const currentPageBookmarked = computed(() => {
  return bookmarks.value.find(b => b.section_title === chapterTitle.value)
})

// Refs
const readerEl = ref(null)
const tocPanelEl = ref(null)
const annotationsPanelEl = ref(null)
let view = null
let book = null
let saveTimer = null
let toolbarTimer = null
let isAnimating = false
let keyThrottle = false
let pendingAnnotationClick = false
let isRecovering = false
let navCtx = {
  source: 'init',       // 'sequential' | 'jump' | 'init'
  direction: null,       // 'next' | 'prev' | null
  lastGoodFraction: 0,   // 上次验证通过的全局 fraction
  stuckCount: 0,         // 连续未收到有效 relocate 的导航次数
  lastRelocateTs: Date.now(),
}
const sectionDocs = new Map() // 暂存 section doc 引用，供 create-overlay 使用
const iframeDocs = [] // 所有 iframe doc 引用，用于 cleanup keydown 监听

const noteEditorExpanded = ref(false)

function refocusReader() {
  const iframe = readerEl.value?.querySelector('iframe')
  iframe?.contentWindow?.focus()
}

// Section index → chapter title map (pre-computed on open)
const chapterMap = []

// --- Theme config ---
const themeCSS = {
  light: 'body { color: #374151; background: #ffffff; }',
  warm: 'body { color: #5b4636; background: #f8f1e3; }',
  dark: 'body { color: #d1d5db; background: #1a1a2e; }',
}

const containerBg = computed(
  () => ({ light: '#ffffff', warm: '#f8f1e3', dark: '#1a1a2e' })[theme.value],
)

const toolbarCls = computed(
  () =>
    ({
      light: 'bg-white/95 text-slate-800 border-slate-200/80',
      warm: 'bg-[#f8f1e3]/95 text-[#5b4636] border-[#e0d4c0]/80',
      dark: 'bg-[#1a1a2e]/95 text-gray-200 border-gray-700/80',
    })[theme.value],
)

const subCls = computed(
  () =>
    ({
      light: 'text-slate-400',
      warm: 'text-[#9b8b78]',
      dark: 'text-gray-500',
    })[theme.value],
)

const shortcutList = [
  { key: '← / h', desc: '上一页' },
  { key: '→ / l', desc: '下一页' },
  { key: 'j / Space', desc: '下一页' },
  { key: 'k / PageUp', desc: '上一页' },
  { key: 't', desc: '目录' },
  { key: 'n', desc: '标注与书签' },
  { key: 's', desc: '设置' },
  { key: 'b', desc: '添加/移除书签' },
  { key: 'd', desc: '切换主题' },
  { key: '+ / -', desc: '调整字号' },
  { key: 'Esc', desc: '关闭/退出' },
  { key: '?', desc: '快捷键帮助' },
]

const kbdCls = computed(() => ({
  light: 'bg-gray-100 border-gray-300 text-gray-600',
  warm:  'bg-[#ede4d3] border-[#d4c8b0] text-[#5b4636]',
  dark:  'bg-gray-800 border-gray-600 text-gray-300',
})[theme.value])

// --- Panel visual hierarchy (side panels slightly darker than content area) ---
const panelBg = computed(() => ({
  light: '#f5f5f7',
  warm:  '#f0e8d8',
  dark:  '#141425',
})[theme.value])

const panelTextCls = computed(() => ({
  light: 'text-slate-600',
  warm:  'text-[#7b6b58]',
  dark:  'text-gray-400',
})[theme.value])

const panelEdgeCls = computed(() => ({
  light: 'bg-[#f5f5f7]/90 text-slate-400 border-slate-200/60',
  warm:  'bg-[#f0e8d8]/90 text-[#9b8b78] border-[#e0d4c0]/60',
  dark:  'bg-[#141425]/90 text-gray-500 border-gray-700/60',
})[theme.value])

const panelShadowLeft = computed(() =>
  theme.value === 'dark'
    ? 'inset -8px 0 16px -10px rgba(0,0,0,0.3)'
    : 'inset -8px 0 16px -10px rgba(0,0,0,0.06)'
)
const panelShadowRight = computed(() =>
  theme.value === 'dark'
    ? 'inset 8px 0 16px -10px rgba(0,0,0,0.3)'
    : 'inset 8px 0 16px -10px rgba(0,0,0,0.06)'
)

// --- Lifecycle ---
onMounted(async () => {
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('visibilitychange', onVisChange)
  window.addEventListener('beforeunload', saveNow)
  window.addEventListener('resize', onResize)
  // Restore desktop panel states (toolbar hidden by default)
  if (isDesktop.value) {
    tocVisible.value = savedPrefs.desktopTocOpen ?? false
    annotationsSidebarVisible.value = savedPrefs.desktopAnnotationsOpen ?? false
  }
  await init()
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('visibilitychange', onVisChange)
  window.removeEventListener('beforeunload', saveNow)
  window.removeEventListener('resize', onResize)
  clearTimeout(saveTimer)
  clearTimeout(toolbarTimer)
  clearTimeout(selectionHideTimer)
  saveNow()
  cleanup()
})

// --- Init ---
async function init() {
  loading.value = true
  errorMsg.value = ''

  try {
    // Book detail (title + server-parsed TOC)
    const detail = await getEbookDetail(props.contentId)
    if (detail.code === 0 && detail.data) {
      bookTitle.value = detail.data.title || '未知书名'
      if (detail.data.toc?.length) tocItems.value = detail.data.toc
    }

    // Guard: external media (Apple Books / 微信读书 etc.) — cannot load file
    if (detail?.data?.media_status === 'external') {
      const extId = detail.data.external_id
      const srcCfg = getSourceConfig(detail.data.source)
      const platformName = srcCfg?.label || '外部应用'
      errorMsg.value = `此书来自 ${platformName}，请${srcCfg?.openLabel || '在原应用中打开阅读'}`
      if (extId && srcCfg) {
        window.location.href = srcCfg.deepLink(extId)
      }
      loading.value = false
      return
    }

    // Fetch ebook binary (auth handled by axios interceptor)
    const blob = await fetchEbookBlob(props.contentId)
    // foliate-js 的 isCBZ/isFBZ 会调用 name.endsWith()，Blob 没有 name 属性会抛错
    // 必须包成 File 并带上正确的文件名
    const fmt = detail?.data?.format || 'epub'
    const ebookFile = new File([blob], `book.${fmt}`, { type: blob.type || 'application/epub+zip' })

    // Create foliate-view and render
    // foliate-view 自定义元素默认 display:inline，必须显式设置尺寸，否则 paginator 渲染区域为 0x0
    await nextTick()
    view = document.createElement('foliate-view')
    view.style.cssText = 'display:block;width:100%;height:100%;'
    view.setAttribute('flow', flowMode.value)
    readerEl.value.appendChild(view)

    await view.open(ebookFile)
    book = view.book  // view.open() 无返回值，从元素属性取
    applyStyles()

    // Extract TOC from book if server didn't provide it
    if (!tocItems.value.length && book?.toc?.length) {
      tocItems.value = book.toc.map(mapToc)
    }

    // Build section → chapter map for quick lookups
    buildChapterMap()

    // Listen for events
    view.addEventListener('relocate', onRelocate)
    view.addEventListener('load', onSectionLoad)
    view.addEventListener('draw-annotation', onDrawAnnotation)
    view.addEventListener('create-overlay', onCreateOverlay)
    view.addEventListener('show-annotation', onShowAnnotation)

    // Restore position OR navigate to start
    // view.open() 只加载书籍但不渲染任何页面，必须调用 goTo 才会显示内容
    let navigated = false
    try {
      const prog = await getReadingProgress(props.contentId)
      if (prog?.data?.progress > 0) {
        navCtx.source = 'init'
        navCtx.lastGoodFraction = prog.data.progress
        await view.goToFraction(prog.data.progress)
        navigated = true
      }
    } catch {
      /* ignore progress errors */
    }
    if (!navigated) {
      // 没有保存进度，或进度恢复失败，跳到书籍开头
      await view.init({ showTextStart: false })
    }

    // Load annotations & bookmarks
    try {
      const [annRes, bmRes] = await Promise.all([
        listAnnotations(props.contentId),
        listBookmarks(props.contentId),
      ])
      if (annRes?.code === 0) annotations.value = annRes.data || []
      if (bmRes?.code === 0) bookmarks.value = bmRes.data || []
      // Render existing annotations for currently visible sections
      for (const a of annotations.value) {
        view.addAnnotation({ value: a.cfi_range, color: a.color })
      }
    } catch (err) {
      console.warn('Failed to load annotations/bookmarks:', err)
    }

    loading.value = false
    updateThemeColor(containerBg.value)
    // 移动端首次加载时短暂显示工具栏，提示用户控件存在
    if (!isDesktop.value) {
      toolbarVisible.value = true
      startAutoHide()
    } else if (toolbarVisible.value) {
      // 桌面端初始显示工具栏后启动自动隐藏
      startAutoHide()
    }
  } catch (e) {
    console.error('Reader init error:', e)
    const status = e.response?.status
    if (status === 404) errorMsg.value = '电子书文件不存在'
    else if (status === 403) errorMsg.value = '无权访问该电子书'
    else if (status === 413) errorMsg.value = '文件过大，无法加载'
    else if (e.code === 'ECONNABORTED' || e.message?.includes('timeout')) errorMsg.value = '加载超时，请重试'
    else errorMsg.value = `无法加载电子书：${e?.message || e}`
    loading.value = false
  }
}

function mapToc(item) {
  return {
    title: item.label?.trim() || '',
    href: item.href,
    children: item.subitems?.map(mapToc) || [],
  }
}

function buildChapterMap() {
  if (!book?.toc) return
  function walk(items) {
    for (const item of items) {
      try {
        const resolved = book.resolveHref(item.href)
        const idx = typeof resolved === 'number' ? resolved : resolved?.index
        if (idx != null) {
          chapterMap[idx] = item.label?.trim() || ''
        }
      } catch {
        /* skip unresolvable hrefs */
      }
      if (item.subitems?.length) walk(item.subitems)
    }
  }
  walk(book.toc)
}

function getChapterTitle(index) {
  for (let i = index; i >= 0; i--) {
    if (chapterMap[i]) return chapterMap[i]
  }
  return ''
}

// --- Annotation event handlers ---
function onDrawAnnotation(e) {
  const { draw, annotation } = e.detail
  const color = HIGHLIGHT_COLORS[annotation.color] || annotation.color || HIGHLIGHT_COLORS.yellow
  draw(Overlayer.highlight, { color })
}

function onCreateOverlay(e) {
  const { index } = e.detail
  for (const a of annotations.value) {
    if (a.section_index === index || a.section_index == null) {
      view.addAnnotation({ value: a.cfi_range, color: a.color })
    }
  }
  // 在 foliate 的 annotation click handler 之后注册我们的 handler
  // create-overlay 在 #createOverlayer 内部、foliate 注册 click handler 之后触发
  const doc = sectionDocs.get(index)
  if (doc) {
    addTouchHandler(doc)
    sectionDocs.delete(index)
  }
}

function onShowAnnotation(e) {
  pendingAnnotationClick = true
  // 安全兜底：若 show-annotation 无对应 click（如 programmatic 触发），100ms 后自动清除
  setTimeout(() => { pendingAnnotationClick = false }, 100)

  const { value, range } = e.detail
  const ann = annotations.value.find(a => a.cfi_range === value)
  if (!ann) {
    console.warn('[ebook-reader] show-annotation: no matching annotation for value', value,
      'known cfi_ranges:', annotations.value.map(a => a.cfi_range))
    return
  }
  activeAnnotation.value = ann
  noteText.value = ann.note || ''
  noteEditorExpanded.value = false
  // Position popup near the annotation
  if (range) {
    const rect = range.getBoundingClientRect()
    const iframe = range.startContainer?.ownerDocument?.defaultView?.frameElement
    const iframeRect = iframe?.getBoundingClientRect() || { left: 0, top: 0 }
    annotationPopupPos.value = {
      x: Math.min(rect.left + iframeRect.left + rect.width / 2, window.innerWidth - 160),
      y: rect.bottom + iframeRect.top + 8,
    }
  }
  annotationPopupVisible.value = true
  selectionToolbarVisible.value = false
}

// --- Dismiss all overlays ---
function dismissOverlays() {
  selectionToolbarVisible.value = false
  annotationPopupVisible.value = false
  activeAnnotation.value = null
  selection.value = null
  refocusReader()
}

// --- Styles helpers ---
const fontFamilyCSS = {
  default: '',
  kaiti: '"STKaiti","华文楷体","楷体","KaiTi",Georgia,serif',
  songti: '"STSong","华文宋体","宋体","SimSun",Georgia,serif',
  heiti: '"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif',
}

function getStyles() {
  const ff = fontFamilyCSS[fontFamily.value]
  const fontRule = ff ? `body, p, div, span { font-family: ${ff} !important; }` : ''
  return `${themeCSS[theme.value]} body { font-size: ${fontSize.value}% !important; } ${fontRule}`
}

function applyStyles() {
  // 延迟到下一帧，让 Vue 的 UI 更新（按钮高亮、背景色）先完成渲染
  requestAnimationFrame(() => {
    view?.renderer?.setStyles?.(getStyles())
  })
}

// --- Section load: attach interaction handlers ---
function onSectionLoad(e) {
  // 暂存 doc，等 create-overlay 时再注册 touch/click handler
  // 这样保证我们的 click handler 注册在 foliate 的 annotation click handler 之后
  sectionDocs.set(e.detail.index, e.detail.doc)
  addSelectionHandler(e.detail.doc, e.detail.index)
}

// --- Page turn animation ---
// ctx.drawImage() does NOT accept HTMLIFrameElement (not a valid CanvasImageSource),
// so we use a solid background-color overlay that slides away to reveal the new page.
function createOverlay() {
  const overlay = document.createElement('div')
  overlay.style.cssText = `position:absolute;inset:0;z-index:10;pointer-events:none;background:${containerBg.value};`
  // Subtle shadow at the leading edge for depth
  const shadow = document.createElement('div')
  shadow.style.cssText = 'position:absolute;inset:0;background:linear-gradient(to right,rgba(0,0,0,0.06) 0%,transparent 8%);pointer-events:none;'
  overlay.appendChild(shadow)
  return overlay
}

function runOverlayAnimation(overlay, direction, onEnd, startOffsetPx = 0) {
  const containerWidth = readerEl.value?.offsetWidth || window.innerWidth
  const remaining = Math.max(0, containerWidth - Math.abs(startOffsetPx)) / containerWidth
  const duration = Math.max(120, Math.round(380 * remaining))

  overlay.style.transition = 'none'
  overlay.style.transform = `translateX(${startOffsetPx}px)`

  let ended = false
  function finish() {
    if (ended) return
    ended = true
    overlay.remove()
    onEnd()
  }
  overlay.addEventListener('transitionend', finish, { once: true })
  setTimeout(finish, duration + 150)

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      overlay.style.transition = `transform ${duration}ms cubic-bezier(0.25,0.46,0.45,0.94)`
      overlay.style.transform = direction === 'next' ? 'translateX(-100%)' : 'translateX(100%)'
    })
  })
}

async function animatePageTurn(direction) {
  if (isAnimating) return
  dismissOverlays()
  isAnimating = true
  const overlay = createOverlay()
  readerEl.value.appendChild(overlay)
  await safeNav(direction)
  runOverlayAnimation(overlay, direction, () => { isAnimating = false })
}

// --- Scrolled mode: fade transition for chapter navigation ---
async function fadeChapterNav(direction) {
  if (isAnimating) return
  dismissOverlays()
  isAnimating = true
  const mask = document.createElement('div')
  mask.style.cssText = `position:absolute;inset:0;z-index:10;pointer-events:none;background:${containerBg.value};opacity:0;transition:opacity 150ms ease-in;`
  readerEl.value.appendChild(mask)
  // Fade in
  await new Promise(r => requestAnimationFrame(() => { mask.style.opacity = '1'; mask.addEventListener('transitionend', r, { once: true }); setTimeout(r, 200) }))
  // Navigate — 等待 load 事件确认新 section 就绪
  const loadPromise = new Promise(r => {
    const onLoad = () => { view.removeEventListener('load', onLoad); r() }
    view.addEventListener('load', onLoad)
    setTimeout(r, 1000) // 超时兜底
  })
  await safeNav(direction)
  await loadPromise
  // 等待浏览器完成 paint
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))
  // Fade out
  mask.style.transition = 'opacity 200ms ease-out'
  await new Promise(r => requestAnimationFrame(() => { mask.style.opacity = '0'; mask.addEventListener('transitionend', r, { once: true }); setTimeout(r, 250) }))
  mask.remove()
  isAnimating = false
}

// --- Selection handler for annotations ---
let selectionHideTimer = null

function addSelectionHandler(doc, sectionIndex) {
  doc.addEventListener('selectionchange', () => {
    clearTimeout(selectionHideTimer)
    const sel = doc.getSelection()
    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
      selectionHideTimer = setTimeout(() => {
        selectionToolbarVisible.value = false
        selection.value = null
      }, 200)
      return
    }
    try {
      const range = sel.getRangeAt(0)
      const cfi = view.getCFI(sectionIndex, range)
      if (!cfi) return
      selection.value = {
        cfiRange: cfi,
        sectionIndex,
        selectedText: sel.toString().trim().slice(0, 500),
      }
      // Position toolbar above selection
      const rect = range.getBoundingClientRect()
      const iframe = doc.defaultView?.frameElement
      const iframeRect = iframe?.getBoundingClientRect() || { left: 0, top: 0 }
      selectionToolbarPos.value = {
        x: Math.min(
          Math.max(rect.left + iframeRect.left + rect.width / 2, 100),
          window.innerWidth - 100,
        ),
        y: rect.top + iframeRect.top - 12,
      }
      selectionToolbarVisible.value = true
    } catch { /* ignore CFI errors */ }
  })
}

// --- Highlight CRUD ---
let tempIdCounter = 0

async function addHighlight(color) {
  if (!selection.value) return
  const { cfiRange, sectionIndex, selectedText } = selection.value
  selectionToolbarVisible.value = false

  const savedProgress = progress.value
  view.deselect?.()

  const tempId = `temp-${++tempIdCounter}`
  const optimistic = {
    id: tempId,
    cfi_range: cfiRange,
    section_index: sectionIndex,
    type: 'highlight',
    color,
    selected_text: selectedText,
    note: null,
  }
  annotations.value.push(optimistic)
  await view.addAnnotation({ value: cfiRange, color })

  // Restore position if addAnnotation caused drift
  if (Math.abs(progress.value - savedProgress) > 0.001) {
    navCtx.source = 'jump'
    navCtx.direction = null
    await view.goToFraction(savedProgress)
  }

  try {
    const res = await createAnnotation(props.contentId, {
      cfi_range: cfiRange,
      section_index: sectionIndex,
      type: 'highlight',
      color,
      selected_text: selectedText,
    })
    if (res?.code === 0 && res.data?.id) {
      optimistic.id = res.data.id
    }
  } catch (err) {
    console.error('Failed to create annotation:', err)
    annotations.value = annotations.value.filter(a => a.id !== tempId)
    view.deleteAnnotation?.({ value: cfiRange })
  }
  selection.value = null
  refocusReader()
}

async function addHighlightWithNote() {
  if (!selection.value) return
  await addHighlight('yellow')
  // Open edit popup for the just-created annotation with note editor expanded
  const ann = annotations.value[annotations.value.length - 1]
  if (ann) {
    activeAnnotation.value = ann
    noteText.value = ''
    noteEditorExpanded.value = true
    annotationPopupPos.value = { ...selectionToolbarPos.value }
    annotationPopupVisible.value = true
  }
}

async function changeAnnotationColor(ann, newColor) {
  if (!ann || ann.color === newColor) return
  const oldColor = ann.color
  ann.color = newColor
  // Re-render: remove and re-add
  view.deleteAnnotation?.({ value: ann.cfi_range })
  view.addAnnotation({ value: ann.cfi_range, color: newColor })
  try {
    await updateAnnotation(props.contentId, ann.id, { color: newColor })
  } catch {
    ann.color = oldColor
    view.deleteAnnotation?.({ value: ann.cfi_range })
    view.addAnnotation({ value: ann.cfi_range, color: oldColor })
  }
}

async function saveAnnotationNote() {
  if (!activeAnnotation.value) return
  const ann = activeAnnotation.value
  ann.note = noteText.value || null
  try {
    await updateAnnotation(props.contentId, ann.id, { note: ann.note })
  } catch (err) {
    console.error('Failed to save note:', err)
  }
  annotationPopupVisible.value = false
  activeAnnotation.value = null
  refocusReader()
}

function copyAnnotationText(ann) {
  if (!ann?.selected_text) return
  navigator.clipboard.writeText(ann.selected_text)
  annotationPopupVisible.value = false
  activeAnnotation.value = null
  refocusReader()
}

async function removeAnnotation(ann) {
  if (!ann) return
  view.deleteAnnotation?.({ value: ann.cfi_range })
  annotations.value = annotations.value.filter(a => a.id !== ann.id)
  annotationPopupVisible.value = false
  activeAnnotation.value = null
  try {
    await deleteAnnotation(props.contentId, ann.id)
  } catch (err) {
    console.error('Failed to delete annotation:', err)
  }
  refocusReader()
}

// --- Bookmark CRUD ---
async function removeBookmarkById(bm) {
  if (!bm) return
  bookmarks.value = bookmarks.value.filter(b => b.id !== bm.id)
  try {
    await deleteBookmark(props.contentId, bm.id)
  } catch {
    bookmarks.value.push(bm)
  }
}

async function toggleBookmark() {
  const existing = currentPageBookmarked.value
  if (existing) {
    bookmarks.value = bookmarks.value.filter(b => b.id !== existing.id)
    showBookmarkFeedback(false)
    try {
      await deleteBookmark(props.contentId, existing.id)
    } catch {
      // Re-add on failure
      bookmarks.value.push(existing)
    }
  } else {
    const cfi = view?.lastLocation?.cfi || ''
    const tempId = `temp-bm-${++tempIdCounter}`
    const optimistic = {
      id: tempId,
      cfi,
      title: chapterTitle.value || bookTitle.value,
      section_title: chapterTitle.value || null,
    }
    bookmarks.value.push(optimistic)
    showBookmarkFeedback(true)
    try {
      const res = await createBookmark(props.contentId, {
        cfi,
        title: optimistic.title,
        section_title: optimistic.section_title,
      })
      if (res?.code === 0 && res.data?.id) {
        optimistic.id = res.data.id
      }
    } catch {
      bookmarks.value = bookmarks.value.filter(b => b.id !== tempId)
    }
  }
}

function addTouchHandler(doc) {
  // 在 iframe document 上注册 keydown，使焦点在 iframe 内时键盘快捷键仍然生效
  doc.addEventListener('keydown', onKeydown)
  iframeDocs.push(doc)

  let sx = 0, sy = 0
  let overlay = null
  let swipeHandled = false
  let mouseDownX = 0, mouseDownY = 0
  let hitBoundaryAt = null // touchY when scroll hit top/bottom boundary

  doc.addEventListener('mousedown', (e) => {
    mouseDownX = e.clientX
    mouseDownY = e.clientY
  })
  // 移动端没有 mousedown，用 touchstart 记录坐标以修正 drag detection
  doc.addEventListener('touchstart', (e) => {
    const t = e.changedTouches[0]
    if (t) { mouseDownX = t.clientX; mouseDownY = t.clientY }
  }, { passive: true })

  // Click handler — 注册在 foliate 的 annotation click handler 之后（通过 create-overlay 时机保证）
  // 同一 click 事件中 foliate 的 handler 先执行，命中标注时同步设置 pendingAnnotationClick flag
  doc.addEventListener('click', (e) => {
    if (swipeHandled) { swipeHandled = false; return }
    if (Math.abs(e.clientX - mouseDownX) > 5 || Math.abs(e.clientY - mouseDownY) > 5) return

    // foliate 的 handler 已先执行；若命中标注，flag 已同步设好
    if (pendingAnnotationClick) {
      pendingAnnotationClick = false
      return
    }

    if (annotationPopupVisible.value) {
      annotationPopupVisible.value = false
      activeAnnotation.value = null
      return
    }
    if (settingsVisible.value) { settingsVisible.value = false; return }

    if (flowMode.value === 'scrolled') {
      // 滚动模式：纵向点击区域 — 上 25% 向上滚，下 75% 向下滚，中间切换工具栏
      const h = doc.defaultView?.innerHeight || window.innerHeight
      const y = e.clientY
      if (y < h * 0.25) {
        const el = doc.scrollingElement || doc.documentElement
        el.scrollBy({ top: -Math.round(h * 0.85), behavior: 'smooth' })
      } else if (y > h * 0.75) {
        const el = doc.scrollingElement || doc.documentElement
        el.scrollBy({ top: Math.round(h * 0.85), behavior: 'smooth' })
      } else {
        toggleToolbar()
      }
    } else {
      // 翻页模式：左右点击区域
      const w = doc.defaultView?.innerWidth || window.innerWidth
      const x = e.clientX
      if (x < w * 0.25) prev()
      else if (x > w * 0.75) next()
      else toggleToolbar()
    }
  })

  doc.addEventListener('touchstart', (e) => {
    sx = e.changedTouches[0].clientX
    sy = e.changedTouches[0].clientY
    swipeHandled = false
    overlay = null
    hitBoundaryAt = null
    overscrollHint.value = null
  }, { passive: true })

  doc.addEventListener('touchmove', (e) => {
    const touchY = e.changedTouches[0].clientY
    if (flowMode.value === 'scrolled') {
      // 滚动模式：检测是否到达上下边界并过度滚动
      const el = doc.scrollingElement || doc.documentElement
      const atTop = el.scrollTop <= 0
      const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 1
      const dy = touchY - sy
      // 到达底部且继续上拉（dy < 0），或到达顶部且继续下拉（dy > 0）
      const pullingNext = atBottom && dy < 0
      const pullingPrev = atTop && dy > 0
      if (pullingNext || pullingPrev) {
        if (hitBoundaryAt === null) hitBoundaryAt = touchY
        const overDelta = Math.abs(touchY - hitBoundaryAt)
        if (overDelta > 20) {
          overscrollHint.value = {
            direction: pullingNext ? 'next' : 'prev',
            progress: Math.min(1, (overDelta - 20) / 60),
          }
        }
      } else {
        hitBoundaryAt = null
        overscrollHint.value = null
      }
      return
    }
    // 翻页模式：水平滑动覆盖层动画
    const dx = e.changedTouches[0].clientX - sx
    const dy = touchY - sy
    if (Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy) && !isAnimating) {
      if (!overlay) {
        overlay = createOverlay()
        overlay.style.transform = 'translateX(0)'
        readerEl.value.appendChild(overlay)
      }
      overlay.style.transform = `translateX(${dx}px)`
    }
  }, { passive: true })

  doc.addEventListener('touchend', async (e) => {
    // 滚动模式：过度滚动触发章节导航
    if (overscrollHint.value && overscrollHint.value.progress >= 0.8) {
      const dir = overscrollHint.value.direction
      overscrollHint.value = null
      hitBoundaryAt = null
      swipeHandled = true
      fadeChapterNav(dir)
      return
    }
    overscrollHint.value = null
    hitBoundaryAt = null

    const dx = e.changedTouches[0].clientX - sx
    const dy = e.changedTouches[0].clientY - sy
    const threshold = Math.max(40, window.innerWidth * 0.15)
    const isHorizontalSwipe = Math.abs(dx) > threshold && Math.abs(dx) > Math.abs(dy) * 1.5

    if (overlay) {
      const ol = overlay
      overlay = null
      if (isHorizontalSwipe) {
        swipeHandled = true
        isAnimating = true
        const direction = dx < 0 ? 'next' : 'prev'
        await safeNav(direction)
        runOverlayAnimation(ol, direction, () => { isAnimating = false }, dx)
      } else {
        // Snap back to original position
        let removed = false
        ol.addEventListener('transitionend', () => { if (!removed) { removed = true; ol.remove() } }, { once: true })
        setTimeout(() => { if (!removed) { removed = true; ol.remove() } }, 300)
        ol.style.transition = 'transform 200ms ease-out'
        ol.style.transform = 'translateX(0)'
      }
    } else if (isHorizontalSwipe && !isAnimating) {
      swipeHandled = true
      if (flowMode.value === 'paginated') {
        dx < 0 ? animatePageTurn('next') : animatePageTurn('prev')
      } else {
        // 滚动模式：横划跳章节，使用淡入淡出动画
        fadeChapterNav(dx < 0 ? 'next' : 'prev')
      }
    }
  }, { passive: true })
}

// --- Relocate ---
function onRelocate(e) {
  const { fraction, section, tocItem } = e.detail

  // TIER 1: 拒绝非法值
  if (typeof fraction !== 'number' || !isFinite(fraction) || fraction < 0 || fraction > 1) return

  // TIER 2: 顺序导航的方向性验证
  if (navCtx.source === 'sequential' && navCtx.lastGoodFraction > 0.01) {
    const delta = fraction - navCtx.lastGoodFraction
    const sectionChanged = (section?.current ?? 0) !== currentSectionIndex.value
    // 同章节内阈值 8%，跨章节阈值 20%（章节切换时进度变化可能稍大）
    const threshold = sectionChanged ? 0.20 : 0.08

    if (navCtx.direction === 'next' && delta < -threshold) {
      console.warn('[ebook] Rejected regression on next():',
        navCtx.lastGoodFraction.toFixed(4), '→', fraction.toFixed(4))
      return
    }
    if (navCtx.direction === 'prev' && delta > threshold) {
      console.warn('[ebook] Rejected forward jump on prev():',
        navCtx.lastGoodFraction.toFixed(4), '→', fraction.toFixed(4))
      return
    }
  }

  // TIER 3: 接受并更新状态
  progress.value = fraction
  navCtx.lastGoodFraction = fraction
  navCtx.stuckCount = 0
  navCtx.lastRelocateTs = Date.now()
  currentSectionIndex.value = section?.current ?? 0
  chapterTitle.value = tocItem?.label?.trim() || getChapterTitle(currentSectionIndex.value)
  scheduleSave()
}

// --- Safe navigation with stuck detection ---
async function safeNav(direction) {
  if (isRecovering) return

  // 书首/书末边界：进度不变是正常的，不计入卡死检测
  if ((direction === 'prev' && progress.value <= 0.001) ||
      (direction === 'next' && progress.value >= 0.999)) {
    try {
      if (direction === 'next') await view?.next()
      else await view?.prev()
    } catch { /* ignore */ }
    return
  }

  navCtx.source = 'sequential'
  navCtx.direction = direction

  try {
    if (direction === 'next') await view?.next()
    else await view?.prev()
  } catch { /* ignore */ }

  // 卡死检测：如果 relocate 被拒或未触发，stuckCount 递增
  // 等 300ms 让 relocate 有时间触发
  setTimeout(() => {
    if (Date.now() - navCtx.lastRelocateTs > 300) {
      navCtx.stuckCount++
    }
    if (navCtx.stuckCount >= 5 && Date.now() - navCtx.lastRelocateTs > 3000) {
      console.warn('[ebook] Navigation stuck, recovering...')
      navCtx.stuckCount = 0
      recoverView()
    }
  }, 300)
}

async function recoverView() {
  if (isRecovering) return
  isRecovering = true
  try {
    if (!navCtx.lastGoodFraction || navCtx.lastGoodFraction <= 0) return

    saveNow()
    cleanup()
    // 等待旧视图的异步操作自然结束，避免 SES_UNCAUGHT_EXCEPTION
    await new Promise(r => setTimeout(r, 200))
    await init()
  } finally {
    navCtx.stuckCount = 0
    navCtx.lastRelocateTs = Date.now()
    isRecovering = false
  }
}

// --- Progress persistence ---
function scheduleSave() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(saveNow, 5000)
}

function saveNow() {
  if (!isFinite(progress.value) || progress.value <= 0) return
  updateReadingProgress(props.contentId, {
    cfi: null,
    progress: progress.value,
    section_index: currentSectionIndex.value,
    section_title: chapterTitle.value || null,
  }).catch(() => {})
}

function onVisChange() {
  if (document.visibilityState === 'hidden') saveNow()
}

// --- Navigation ---
function prev() {
  animatePageTurn('prev')
}
function next() {
  animatePageTurn('next')
}

function onKeydown(e) {
  const tag = e.target?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

  // Escape: 层级退出 — 先关闭最上层覆盖，无覆盖时退出阅读器
  if (e.key === 'Escape') {
    if (shortcutHelpVisible.value) { shortcutHelpVisible.value = false }
    else if (annotationPopupVisible.value) { annotationPopupVisible.value = false; activeAnnotation.value = null }
    else if (selectionToolbarVisible.value) { selectionToolbarVisible.value = false }
    else if (settingsVisible.value) { settingsVisible.value = false }
    else if (tocVisible.value) { tocVisible.value = false }
    else if (annotationsSidebarVisible.value) { annotationsSidebarVisible.value = false }
    else if (toolbarVisible.value) { toolbarVisible.value = false }
    else { handleClose() }
    return
  }

  // 快捷键帮助打开时，除 ? 外不响应（Escape 已在上方层级退出中处理）
  if (shortcutHelpVisible.value) {
    if (e.key === '?') shortcutHelpVisible.value = false
    return
  }

  // 阻止浏览器默认滚动
  if (['ArrowLeft', 'ArrowRight', ' ', 'PageUp', 'PageDown'].includes(e.key)) {
    e.preventDefault()
  }

  // 翻页（带节流）
  if (keyThrottle) return
  if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
    keyThrottle = true
    doKeyNav('prev')
  } else if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') {
    keyThrottle = true
    doKeyNav('next')
  } else if (!e.metaKey && !e.ctrlKey && !e.altKey) {
    // Vim 导航
    if (e.key === 'h' || e.key === 'k') {
      keyThrottle = true
      doKeyNav('prev')
    } else if (e.key === 'j' || e.key === 'l') {
      keyThrottle = true
      doKeyNav('next')
    }
    // 面板切换
    else if (e.key === 't') {
      dismissOverlays()
      tocVisible.value = !tocVisible.value
    } else if (e.key === 'n') {
      dismissOverlays()
      annotationsSidebarVisible.value = !annotationsSidebarVisible.value
    } else if (e.key === 's') {
      dismissOverlays()
      settingsVisible.value = !settingsVisible.value
    }
    // 阅读操作
    else if (e.key === 'b') {
      toggleBookmark()
    } else if (e.key === 'd') {
      cycleTheme()
    }
    // 字号调整
    else if (e.key === '=' || e.key === '+') {
      e.preventDefault()
      adjustFont(10)
    } else if (e.key === '-') {
      e.preventDefault()
      adjustFont(-10)
    }
    // 帮助
    else if (e.key === '?') {
      shortcutHelpVisible.value = !shortcutHelpVisible.value
    }
  }
}

// Keyboard navigation: bypasses overlay animation, locks only for the duration
// of view.next/prev (typically < 50ms within a section), so rapid key presses
// are processed as fast as the reader can handle without dropping any.
async function doKeyNav(direction) {
  if (!view || loading.value) { keyThrottle = false; return }
  dismissOverlays()
  // Safety reset in case view.next/prev hangs (e.g. broken epub)
  const safety = setTimeout(() => { keyThrottle = false }, 5000)
  await safeNav(direction)
  clearTimeout(safety)
  keyThrottle = false
  // 章节切换后新 iframe 可能未获得焦点，主动聚焦以恢复键盘快捷键
  refocusReader()
}

function startAutoHide() {
  clearTimeout(toolbarTimer)
  if (!settingsVisible.value) {
    toolbarTimer = setTimeout(() => { toolbarVisible.value = false }, 4000)
  }
}

function stopAutoHide() {
  clearTimeout(toolbarTimer)
}

function toggleToolbar() {
  toolbarVisible.value = !toolbarVisible.value
  if (toolbarVisible.value) {
    startAutoHide()
  } else {
    stopAutoHide()
    settingsVisible.value = false
    // 移动端隐藏工具栏时关闭侧栏，桌面端保留（侧栏固定展示）
    if (!isDesktop.value) {
      tocVisible.value = false
      annotationsSidebarVisible.value = false
    }
  }
}

// --- Annotation/Bookmark navigation ---
function goToAnnotation(ann) {
  if (!ann?.cfi_range) return
  navCtx.source = 'jump'
  navCtx.direction = null
  view?.showAnnotation?.({ value: ann.cfi_range })
  if (!isDesktop.value) annotationsSidebarVisible.value = false
}

function goToBookmark(bm) {
  if (!bm?.cfi) return
  navCtx.source = 'jump'
  navCtx.direction = null
  view?.goTo(bm.cfi)
  if (!isDesktop.value) annotationsSidebarVisible.value = false
}

// --- TOC navigation ---
function goToHref(href) {
  if (!href || !book) return
  navCtx.source = 'jump'
  navCtx.direction = null
  view?.goTo(href)
  if (!isDesktop.value) {
    tocVisible.value = false
    toolbarVisible.value = false
  }
}

// --- Settings ---
function updateThemeColor(color) {
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', color)
}

function changeTheme(t) {
  theme.value = t
  updateThemeColor(containerBg.value)
  applyStyles()
  savePrefs()
}

const THEME_ORDER = ['light', 'warm', 'dark']
function cycleTheme() {
  const idx = THEME_ORDER.indexOf(theme.value)
  changeTheme(THEME_ORDER[(idx + 1) % THEME_ORDER.length])
}

function adjustFont(delta) {
  fontSize.value = Math.max(70, Math.min(160, fontSize.value + delta))
  applyStyles()
  savePrefs()
}

function changeFont(f) {
  fontFamily.value = f
  applyStyles()
  savePrefs()
}

function changeFlowMode(mode) {
  flowMode.value = mode
  savePrefs()
  requestAnimationFrame(() => {
    view?.renderer?.setAttribute('flow', mode)
  })
}

// --- Progress slider ---
function onSlider(e) {
  navCtx.source = 'jump'
  navCtx.direction = null
  const frac = parseFloat(e.target.value)
  view?.goToFraction(frac)
}

// --- Close ---
function handleClose() {
  saveNow()
  updateThemeColor('#ffffff')
  isVisible.value = false
  emit('close')
}

function cleanup() {
  // 移除 iframe document 上的 keydown 监听
  for (const doc of iframeDocs) {
    try { doc.removeEventListener('keydown', onKeydown) } catch { /* iframe 已销毁 */ }
  }
  iframeDocs.length = 0

  if (view) {
    view.removeEventListener('draw-annotation', onDrawAnnotation)
    view.removeEventListener('create-overlay', onCreateOverlay)
    view.removeEventListener('show-annotation', onShowAnnotation)
    view.close?.()
    view.remove()
    view = null
  }
  book = null
  chapterMap.length = 0
}

// --- Auto-hide watchers ---
// 移动端：侧栏打开时暂停自动隐藏；桌面端：侧栏独立于工具栏，不影响自动隐藏
watch(tocVisible, (val) => {
  if (isDesktop.value) return
  if (val) stopAutoHide()
  else if (toolbarVisible.value) startAutoHide()
})
watch(settingsVisible, (val) => {
  if (val) stopAutoHide()
  else if (toolbarVisible.value) startAutoHide()
})
watch(annotationsSidebarVisible, (val) => {
  if (isDesktop.value) return
  if (val) stopAutoHide()
  else if (toolbarVisible.value) startAutoHide()
})

// --- Persist desktop panel states ---
watch([tocVisible, annotationsSidebarVisible], () => {
  if (!isDesktop.value) return
  savePrefs({
    desktopTocOpen: tocVisible.value,
    desktopAnnotationsOpen: annotationsSidebarVisible.value,
  })
})

// --- TOC swipe to close ---
useSwipe(tocPanelEl, {
  threshold: 60,
  onSwipeLeft: () => { tocVisible.value = false },
})

// --- Annotations sidebar swipe to close ---
useSwipe(annotationsPanelEl, {
  threshold: 60,
  onSwipeRight: () => { annotationsSidebarVisible.value = false },
})
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[60]" :style="{ background: containerBg }">
      <!-- Reader target (always present) -->
      <div
        ref="readerEl"
        class="absolute inset-0 transition-[left,right] duration-300 ease-out"
        :style="{ left: readerLeft, right: readerRight, 'touch-action': 'manipulation' }"
      />

      <!-- Loading -->
      <div v-if="loading" class="absolute inset-0 flex items-center justify-center z-10">
        <div class="text-center">
          <svg
            class="w-8 h-8 animate-spin mx-auto mb-3"
            :class="subCls"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
          <p class="text-sm" :class="subCls">加载中...</p>
        </div>
      </div>

      <!-- Error -->
      <div v-else-if="errorMsg" class="absolute inset-0 flex items-center justify-center z-10">
        <div class="text-center px-6">
          <div
            class="w-14 h-14 mx-auto mb-3 bg-rose-100 rounded-2xl flex items-center justify-center"
          >
            <svg
              class="w-7 h-7 text-rose-500"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <circle cx="12" cy="12" r="10" />
              <path d="m15 9-6 6M9 9l6 6" />
            </svg>
          </div>
          <p class="text-sm text-rose-600 font-medium mb-1">{{ errorMsg }}</p>
          <button @click="handleClose" class="mt-3 text-sm text-indigo-600 hover:underline">
            返回书架
          </button>
        </div>
      </div>

      <!-- UI overlays (after loaded) -->
      <template v-if="!loading && !errorMsg">
        <!-- ======== Top toolbar ======== -->
        <Transition
          enter-active-class="transition-all duration-200 ease-out"
          enter-from-class="opacity-0 -translate-y-full"
          enter-to-class="opacity-100 translate-y-0"
          leave-active-class="transition-all duration-150 ease-in"
          leave-from-class="opacity-100 translate-y-0"
          leave-to-class="opacity-0 -translate-y-full"
        >
          <div
            v-if="toolbarVisible"
            class="absolute top-0 left-0 right-0 z-[35] backdrop-blur-md border-b flex items-center gap-2 md:gap-3 px-3 md:px-5 py-2.5"
            :class="toolbarCls"
            :style="{ paddingTop: 'max(10px, env(safe-area-inset-top, 0px))' }"
          >
            <!-- Close -->
            <button
              @click="handleClose"
              class="h-9 flex items-center justify-center rounded-lg hover:bg-black/10 active:bg-black/15 transition-colors shrink-0 px-1.5 md:px-2"
            >
              <svg
                class="w-5 h-5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="m15 18-6-6 6-6" />
              </svg>
              <span v-if="isDesktop" class="text-sm ml-0.5">返回</span>
            </button>

            <!-- Title -->
            <span class="flex-1 text-sm font-medium truncate text-center px-1">
              {{ bookTitle }}
            </span>

            <!-- TOC (mobile only — desktop uses edge tab) -->
            <button
              @click="tocVisible = !tocVisible; settingsVisible = false; annotationsSidebarVisible = false"
              class="w-9 h-9 flex items-center justify-center rounded-lg hover:bg-black/10 active:bg-black/15 transition-colors shrink-0 md:hidden"
            >
              <svg
                class="w-5 h-5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="M4 6h16M4 12h10M4 18h16" />
              </svg>
            </button>

            <!-- Bookmark -->
            <button
              @click="toggleBookmark"
              class="w-9 h-9 flex items-center justify-center rounded-lg hover:bg-black/10 active:bg-black/15 transition-colors shrink-0"
            >
              <svg
                class="w-5 h-5 transition-colors"
                viewBox="0 0 24 24"
                :fill="currentPageBookmarked ? '#6366f1' : 'none'"
                :stroke="currentPageBookmarked ? '#6366f1' : 'currentColor'"
                stroke-width="2"
              >
                <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
              </svg>
            </button>

            <!-- Annotations sidebar (mobile only — desktop uses edge tab) -->
            <button
              @click="annotationsSidebarVisible = !annotationsSidebarVisible; tocVisible = false; settingsVisible = false"
              class="w-9 h-9 flex md:hidden items-center justify-center rounded-lg hover:bg-black/10 active:bg-black/15 transition-colors shrink-0"
            >
              <svg
                class="w-5 h-5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
            </button>

            <!-- Settings -->
            <button
              @click="settingsVisible = !settingsVisible; tocVisible = false; annotationsSidebarVisible = false"
              class="w-9 h-9 flex items-center justify-center rounded-lg hover:bg-black/10 active:bg-black/15 transition-colors shrink-0"
            >
              <svg
                class="w-[18px] h-[18px]"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="M4 21V14M4 10V3M12 21V12M12 8V3M20 21V16M20 12V3" />
                <line x1="1" y1="14" x2="7" y2="14" />
                <line x1="9" y1="8" x2="15" y2="8" />
                <line x1="17" y1="16" x2="23" y2="16" />
              </svg>
            </button>
          </div>
        </Transition>

        <!-- ======== Bottom bar ======== -->
        <Transition
          enter-active-class="transition-all duration-200 ease-out"
          enter-from-class="opacity-0 translate-y-full"
          enter-to-class="opacity-100 translate-y-0"
          leave-active-class="transition-all duration-150 ease-in"
          leave-from-class="opacity-100 translate-y-0"
          leave-to-class="opacity-0 translate-y-full"
        >
          <div
            v-if="toolbarVisible"
            class="absolute bottom-0 z-20 backdrop-blur-md border-t px-4 pt-2.5 transition-[left,right] duration-300 ease-out"
            :class="toolbarCls"
            :style="{ left: readerLeft, right: readerRight, paddingBottom: 'max(10px, env(safe-area-inset-bottom, 0px))' }"
          >
            <!-- Chapter & progress text -->
            <div class="flex items-center justify-between text-xs mb-2" :class="subCls">
              <span class="truncate max-w-[65%]">{{ chapterTitle || '—' }}</span>
              <span class="tabular-nums shrink-0">
                {{ Math.round(progress * 100) }}%
              </span>
            </div>
            <!-- Progress slider -->
            <input
              type="range"
              min="0"
              max="1"
              step="0.001"
              :value="progress"
              @input="onSlider"
              class="w-full h-1.5 mb-1 appearance-none rounded-full cursor-pointer opacity-70 hover:opacity-100 transition-opacity [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-indigo-500 [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white [&::-moz-range-thumb]:w-5 [&::-moz-range-thumb]:h-5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-indigo-500 [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-white"
              :style="{
                background: `linear-gradient(to right, rgb(99 102 241) ${progress * 100}%, ${theme === 'dark' ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.1)'} ${progress * 100}%)`,
              }"
            />
          </div>
        </Transition>

        <!-- ======== Mini progress bar (toolbar hidden) ======== -->
        <div
          v-if="!toolbarVisible && !loading && !errorMsg"
          @click="toggleToolbar"
          class="absolute bottom-0 z-10 px-4 py-2
                 flex items-center justify-between text-[11px] opacity-60 cursor-pointer
                 transition-[left,right] duration-300 ease-out"
          :class="subCls"
          :style="{ left: readerLeft, right: readerRight, paddingBottom: 'max(8px, env(safe-area-inset-bottom, 0px))' }"
        >
          <span class="truncate max-w-[70%]">{{ chapterTitle || '—' }}</span>
          <span class="tabular-nums shrink-0">{{ Math.round(progress * 100) }}%</span>
        </div>

        <!-- ======== Shortcut hint button (desktop, toolbar hidden) ======== -->
        <button
          v-if="isDesktop && !toolbarVisible && !loading && !errorMsg"
          @click="shortcutHelpVisible = true"
          class="absolute bottom-3 right-3 z-10 w-7 h-7 flex items-center justify-center
                 rounded-lg border opacity-40 hover:opacity-80 transition-opacity text-xs font-mono"
          :class="panelEdgeCls"
          title="键盘快捷键 (?)"
        >?</button>

        <!-- ======== Bookmark feedback indicator ======== -->
        <Transition
          enter-active-class="transition-all duration-200 ease-out"
          enter-from-class="opacity-0 scale-75"
          enter-to-class="opacity-100 scale-100"
          leave-active-class="transition-all duration-300 ease-in"
          leave-from-class="opacity-100 scale-100"
          leave-to-class="opacity-0 scale-75"
        >
          <div
            v-if="bookmarkFeedback"
            class="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50
                   flex flex-col items-center gap-1.5 px-5 py-3.5 rounded-2xl
                   backdrop-blur-md shadow-lg pointer-events-none"
            :class="theme === 'dark' ? 'bg-gray-800/80 text-gray-100' : 'bg-black/60 text-white'"
          >
            <svg class="w-7 h-7" viewBox="0 0 24 24" :fill="bookmarkFeedback.added ? '#6366f1' : 'none'" stroke="currentColor" stroke-width="2">
              <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
            </svg>
            <span class="text-xs font-medium">{{ bookmarkFeedback.added ? '已添加书签' : '已移除书签' }}</span>
          </div>
        </Transition>

        <!-- ======== Overscroll hint (scrolled mode chapter nav) ======== -->
        <div
          v-if="overscrollHint"
          class="absolute left-0 right-0 z-20 flex justify-center pointer-events-none"
          :class="overscrollHint.direction === 'next' ? 'bottom-8' : 'top-8'"
          :style="{ opacity: overscrollHint.progress }"
        >
          <div
            class="flex items-center gap-1.5 px-4 py-2 rounded-full backdrop-blur-md shadow-lg text-xs font-medium"
            :class="theme === 'dark' ? 'bg-gray-800/80 text-gray-100' : 'bg-black/60 text-white'"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path v-if="overscrollHint.direction === 'next'" d="M12 5v14M19 12l-7 7-7-7" />
              <path v-else d="M12 19V5M5 12l7-7 7 7" />
            </svg>
            {{ overscrollHint.direction === 'next' ? '释放进入下一章' : '释放进入上一章' }}
          </div>
        </div>

        <!-- ======== Desktop edge tabs (panel collapsed) ======== -->
        <!-- Left edge tab: open TOC -->
        <button
          v-if="isDesktop && !tocVisible && !loading && !errorMsg"
          @click="tocVisible = true"
          class="absolute left-0 top-1/2 -translate-y-1/2 z-20 w-5 h-14 flex items-center justify-center
                 rounded-r-lg border border-l-0 backdrop-blur-md hover:bg-black/5 active:bg-black/10 transition-colors"
          :class="panelEdgeCls"
          title="打开目录"
        >
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="m9 18 6-6-6-6" />
          </svg>
        </button>
        <!-- Right edge tab: open annotations -->
        <button
          v-if="isDesktop && !annotationsSidebarVisible && !loading && !errorMsg"
          @click="annotationsSidebarVisible = true"
          class="absolute right-0 top-1/2 -translate-y-1/2 z-20 w-5 h-14 flex items-center justify-center
                 rounded-l-lg border border-r-0 backdrop-blur-md hover:bg-black/5 active:bg-black/10 transition-colors"
          :class="panelEdgeCls"
          title="打开标注"
        >
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </button>

        <!-- ======== TOC sidebar ======== -->
        <!-- Backdrop (mobile only — desktop pushes content) -->
        <Transition
          enter-active-class="transition-opacity duration-200"
          enter-from-class="opacity-0"
          enter-to-class="opacity-100"
          leave-active-class="transition-opacity duration-150"
          leave-from-class="opacity-100"
          leave-to-class="opacity-0"
        >
          <div
            v-if="tocVisible && !isDesktop"
            class="absolute inset-0 z-[25] bg-black/20"
            @click="tocVisible = false"
          />
        </Transition>
        <!-- Panel -->
        <Transition
          enter-active-class="transition-transform duration-300 ease-out"
          enter-from-class="-translate-x-full"
          enter-to-class="translate-x-0"
          leave-active-class="transition-transform duration-200 ease-in"
          leave-from-class="translate-x-0"
          leave-to-class="-translate-x-full"
        >
          <div
            v-if="tocVisible"
            ref="tocPanelEl"
            class="absolute left-0 bottom-0 w-72 z-30 flex flex-col border-r backdrop-blur-xl transition-[top] duration-200 ease-out"
            :class="[toolbarCls, isDesktop ? '' : 'max-w-[80vw]']"
            :style="{ top: panelTop, background: panelBg, boxShadow: isDesktop ? panelShadowLeft : 'none' }"
          >
            <!-- TOC header -->
            <div class="flex items-center justify-between px-4 py-3 border-b" :class="toolbarCls">
              <h3 class="text-sm font-semibold">目录</h3>
              <button
                @click="tocVisible = false"
                class="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-black/10 transition-colors"
              >
                <svg
                  class="w-4 h-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <path d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            </div>
            <!-- TOC list -->
            <div class="flex-1 overflow-y-auto py-2">
              <button
                v-for="(item, idx) in flatToc"
                :key="idx"
                @click="goToHref(item.href)"
                class="block w-full text-left text-sm py-3 px-4 hover:bg-black/5 active:bg-black/10 transition-colors truncate"
                :class="panelTextCls"
                :style="{ paddingLeft: item.depth * 16 + 16 + 'px' }"
              >
                <span :class="item.depth > 0 ? subCls : ''">{{ item.title }}</span>
              </button>
              <div v-if="flatToc.length === 0" class="px-4 py-8 text-center text-sm" :class="subCls">
                暂无目录
              </div>
            </div>
            <!-- Mobile entry to annotations sidebar -->
            <button
              v-if="!isDesktop"
              @click="tocVisible = false; annotationsSidebarVisible = true"
              class="flex items-center gap-2 w-full px-4 py-3 border-t text-sm hover:bg-black/5 active:bg-black/10 transition-colors"
              :class="[toolbarCls, subCls]"
            >
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
              划线与笔记
            </button>
          </div>
        </Transition>

        <!-- ======== Settings panel ======== -->
        <!-- Mobile backdrop -->
        <Transition
          enter-active-class="transition-opacity duration-200"
          enter-from-class="opacity-0"
          enter-to-class="opacity-100"
          leave-active-class="transition-opacity duration-150"
          leave-from-class="opacity-100"
          leave-to-class="opacity-0"
        >
          <div
            v-if="settingsVisible && !isDesktop"
            class="absolute inset-0 z-[34] bg-black/20"
            @click="settingsVisible = false"
          />
        </Transition>
        <Transition
          :enter-active-class="isDesktop ? 'transition-all duration-200 ease-out' : 'transition-transform duration-300 ease-out'"
          :enter-from-class="isDesktop ? 'opacity-0 scale-95 origin-top-right' : 'translate-y-full'"
          :enter-to-class="isDesktop ? 'opacity-100 scale-100' : 'translate-y-0'"
          :leave-active-class="isDesktop ? 'transition-all duration-150 ease-in' : 'transition-transform duration-200 ease-in'"
          :leave-from-class="isDesktop ? 'opacity-100 scale-100' : 'translate-y-0'"
          :leave-to-class="isDesktop ? 'opacity-0 scale-95 origin-top-right' : 'translate-y-full'"
        >
          <div
            v-if="settingsVisible"
            class="absolute z-[35] border shadow-xl"
            :class="[
              toolbarCls,
              isDesktop
                ? 'w-56 rounded-xl p-4 space-y-4'
                : 'left-0 right-0 bottom-0 rounded-t-2xl px-5 pt-8 space-y-5'
            ]"
            :style="isDesktop
              ? { top: 'calc(max(10px, env(safe-area-inset-top, 0px)) + 46px)', right: '12px', background: containerBg }
              : { paddingBottom: 'max(20px, env(safe-area-inset-bottom, 0px))', background: containerBg }"
          >
            <!-- Mobile drag handle indicator -->
            <div
              v-if="!isDesktop"
              class="absolute top-2.5 left-1/2 -translate-x-1/2 w-10 h-1 rounded-full"
              :class="theme === 'dark' ? 'bg-gray-600' : 'bg-gray-300'"
            />
            <!-- Font size -->
            <div>
              <label class="text-[11px] font-medium mb-2 block tracking-wide uppercase" :class="subCls">
                字号
              </label>
              <div class="flex items-center gap-2">
                <button
                  @click="adjustFont(-10)"
                  class="w-9 h-9 flex items-center justify-center rounded-lg border text-sm font-bold hover:bg-black/5 active:bg-black/10 transition-colors"
                  :class="toolbarCls"
                >
                  A<span class="text-[10px]">-</span>
                </button>
                <span class="flex-1 text-center text-sm tabular-nums">{{ fontSize }}%</span>
                <button
                  @click="adjustFont(10)"
                  class="w-9 h-9 flex items-center justify-center rounded-lg border text-sm font-bold hover:bg-black/5 active:bg-black/10 transition-colors"
                  :class="toolbarCls"
                >
                  A<span class="text-xs">+</span>
                </button>
              </div>
            </div>

            <!-- Font family -->
            <div>
              <label class="text-[11px] font-medium mb-2 block tracking-wide uppercase" :class="subCls">
                字体
              </label>
              <div class="flex gap-1.5">
                <button
                  @click="changeFont('default')"
                  class="flex-1 h-9 rounded-lg border-2 text-xs transition-colors"
                  :class="[toolbarCls, fontFamily === 'default' ? 'border-indigo-500' : 'border-slate-200']"
                >
                  默认
                </button>
                <button
                  @click="changeFont('kaiti')"
                  class="flex-1 h-9 rounded-lg border-2 text-xs transition-colors"
                  :class="[toolbarCls, fontFamily === 'kaiti' ? 'border-indigo-500' : 'border-slate-200']"
                  style="font-family: STKaiti,'华文楷体','楷体',KaiTi,Georgia,serif"
                >
                  楷
                </button>
                <button
                  @click="changeFont('songti')"
                  class="flex-1 h-9 rounded-lg border-2 text-xs transition-colors"
                  :class="[toolbarCls, fontFamily === 'songti' ? 'border-indigo-500' : 'border-slate-200']"
                  style="font-family: STSong,'华文宋体','宋体',SimSun,Georgia,serif"
                >
                  宋
                </button>
                <button
                  @click="changeFont('heiti')"
                  class="flex-1 h-9 rounded-lg border-2 text-xs transition-colors"
                  :class="[toolbarCls, fontFamily === 'heiti' ? 'border-indigo-500' : 'border-slate-200']"
                  style="font-family: 'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif"
                >
                  黑
                </button>
              </div>
            </div>

            <!-- Theme -->
            <div>
              <label class="text-[11px] font-medium mb-2 block tracking-wide uppercase" :class="subCls">
                主题
              </label>
              <div class="flex gap-2">
                <button
                  @click="changeTheme('light')"
                  class="flex-1 h-9 rounded-lg border-2 transition-colors bg-white"
                  :class="theme === 'light' ? 'border-indigo-500' : 'border-slate-200'"
                />
                <button
                  @click="changeTheme('warm')"
                  class="flex-1 h-9 rounded-lg border-2 transition-colors bg-[#f8f1e3]"
                  :class="theme === 'warm' ? 'border-indigo-500' : 'border-slate-200'"
                />
                <button
                  @click="changeTheme('dark')"
                  class="flex-1 h-9 rounded-lg border-2 transition-colors bg-[#1a1a2e]"
                  :class="theme === 'dark' ? 'border-indigo-500' : 'border-gray-600'"
                />
              </div>
            </div>

            <!-- Flow mode -->
            <div>
              <label class="text-[11px] font-medium mb-2 block tracking-wide uppercase" :class="subCls">
                阅读模式
              </label>
              <div class="flex gap-1.5">
                <button
                  @click="changeFlowMode('scrolled')"
                  class="flex-1 h-9 rounded-lg border-2 text-xs transition-colors"
                  :class="[toolbarCls, flowMode === 'scrolled' ? 'border-indigo-500' : 'border-slate-200']"
                >
                  滚动
                </button>
                <button
                  @click="changeFlowMode('paginated')"
                  class="flex-1 h-9 rounded-lg border-2 text-xs transition-colors"
                  :class="[toolbarCls, flowMode === 'paginated' ? 'border-indigo-500' : 'border-slate-200']"
                >
                  翻页
                </button>
              </div>
            </div>
          </div>
        </Transition>

        <!-- ======== Selection toolbar (floating color picker) ======== -->
        <Teleport to="body">
          <Transition
            enter-active-class="transition-all duration-200 ease-out"
            enter-from-class="opacity-0 translate-y-1"
            enter-to-class="opacity-100 translate-y-0"
            leave-active-class="transition-opacity duration-100 ease-in"
            leave-from-class="opacity-100"
            leave-to-class="opacity-0"
          >
            <div
              v-if="selectionToolbarVisible"
              class="fixed z-[70] flex items-center gap-1.5 px-2.5 py-2 rounded-xl border shadow-xl backdrop-blur-md"
              :class="toolbarCls"
              :style="{
                left: selectionToolbarPos.x + 'px',
                top: selectionToolbarPos.y + 'px',
                transform: 'translate(-50%, -100%)',
                background: containerBg,
              }"
              @pointerdown.stop
            >
              <button
                v-for="(hex, name) in HIGHLIGHT_COLORS"
                :key="name"
                @click="addHighlight(name)"
                class="w-7 h-7 rounded-full border-2 border-white/60 hover:scale-110 active:scale-95 transition-transform shadow-sm"
                :style="{ background: hex }"
                :title="name"
              />
              <div class="w-px h-5 mx-0.5" :class="theme === 'dark' ? 'bg-gray-600' : 'bg-gray-200'" />
              <button
                @click="addHighlightWithNote"
                class="w-7 h-7 flex items-center justify-center rounded-full hover:bg-black/10 active:bg-black/15 transition-colors"
                title="添加笔记"
              >
                <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                </svg>
              </button>
            </div>
          </Transition>
        </Teleport>

        <!-- ======== Annotation action bar (WeChat Read / Apple Books style) ======== -->
        <Teleport to="body">
          <Transition
            enter-active-class="transition-all duration-200 ease-out"
            enter-from-class="opacity-0 translate-y-2"
            enter-to-class="opacity-100 translate-y-0"
            leave-active-class="transition-opacity duration-100 ease-in"
            leave-from-class="opacity-100"
            leave-to-class="opacity-0"
          >
            <div
              v-if="annotationPopupVisible && activeAnnotation"
              class="fixed z-[70]"
              :class="noteEditorExpanded || activeAnnotation.note ? 'w-72' : ''"
              :style="{
                left: Math.min(Math.max(annotationPopupPos.x, (noteEditorExpanded || activeAnnotation.note) ? 152 : 120), window.innerWidth - ((noteEditorExpanded || activeAnnotation.note) ? 152 : 120)) + 'px',
                top: Math.min(annotationPopupPos.y, window.innerHeight - (noteEditorExpanded ? 200 : 80)) + 'px',
                transform: 'translateX(-50%)',
              }"
              @pointerdown.stop
            >
              <!-- Layer 1: Compact action bar -->
              <div
                class="flex items-center gap-1.5 px-2.5 py-2 rounded-xl border shadow-xl backdrop-blur-md"
                :class="[toolbarCls, (noteEditorExpanded || activeAnnotation.note) ? 'rounded-b-none border-b-0' : '']"
                :style="{ background: containerBg }"
              >
                <!-- Color dots -->
                <button
                  v-for="(hex, name) in HIGHLIGHT_COLORS"
                  :key="name"
                  @click="changeAnnotationColor(activeAnnotation, name)"
                  class="w-7 h-7 rounded-full border-2 hover:scale-110 active:scale-95 transition-all shadow-sm"
                  :class="activeAnnotation.color === name ? 'ring-2 ring-offset-1 ring-indigo-400' : ''"
                  :style="{ background: hex, borderColor: activeAnnotation.color === name ? hex : 'rgba(255,255,255,0.6)' }"
                />
                <!-- Separator -->
                <div class="w-px h-5 mx-0.5" :class="theme === 'dark' ? 'bg-gray-600' : 'bg-gray-200'" />
                <!-- Note toggle -->
                <button
                  @click="noteEditorExpanded = !noteEditorExpanded"
                  class="w-7 h-7 flex items-center justify-center rounded-full hover:bg-black/10 active:bg-black/15 transition-colors"
                  :class="noteEditorExpanded ? 'text-indigo-500' : ''"
                  title="笔记"
                >
                  <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                  </svg>
                </button>
                <!-- Copy -->
                <button
                  @click="copyAnnotationText(activeAnnotation)"
                  class="w-7 h-7 flex items-center justify-center rounded-full hover:bg-black/10 active:bg-black/15 transition-colors"
                  title="复制"
                >
                  <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                </button>
                <!-- Delete -->
                <button
                  @click="removeAnnotation(activeAnnotation)"
                  class="w-7 h-7 flex items-center justify-center rounded-full hover:bg-rose-50 active:bg-rose-100 text-rose-500 transition-colors"
                  :class="theme === 'dark' ? 'hover:bg-rose-500/10 active:bg-rose-500/20' : ''"
                  title="删除"
                >
                  <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>

              <!-- Layer 2: Note area (expandable) -->
              <div
                class="overflow-hidden transition-all duration-200 ease-out"
                :style="{ maxHeight: (noteEditorExpanded || activeAnnotation.note) ? '200px' : '0px' }"
              >
                <div
                  class="border border-t-0 rounded-b-xl shadow-xl backdrop-blur-md px-3 pb-3 pt-2"
                  :class="toolbarCls"
                  :style="{ background: containerBg }"
                >
                  <!-- Note preview (collapsed, has note) -->
                  <div
                    v-if="activeAnnotation.note && !noteEditorExpanded"
                    @click="noteEditorExpanded = true"
                    class="text-xs leading-relaxed line-clamp-2 cursor-pointer hover:opacity-80 transition-opacity"
                    :class="subCls"
                  >
                    {{ activeAnnotation.note }}
                  </div>
                  <!-- Note editor (expanded) -->
                  <template v-if="noteEditorExpanded">
                    <textarea
                      v-model="noteText"
                      placeholder="添加笔记..."
                      rows="3"
                      class="w-full text-sm rounded-lg border px-2.5 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-indigo-400"
                      :class="theme === 'dark' ? 'bg-gray-800 border-gray-600 text-gray-200 placeholder-gray-500' : 'bg-white border-gray-200 text-gray-700 placeholder-gray-400'"
                    />
                    <button
                      @click="saveAnnotationNote"
                      class="mt-1.5 w-full text-xs py-1.5 rounded-lg bg-indigo-500 text-white hover:bg-indigo-600 active:bg-indigo-700 transition-colors"
                    >
                      保存笔记
                    </button>
                  </template>
                </div>
              </div>
            </div>
          </Transition>
        </Teleport>

        <!-- ======== Annotations/Bookmarks sidebar ======== -->
        <!-- Backdrop (mobile only — desktop pushes content) -->
        <Transition
          enter-active-class="transition-opacity duration-200"
          enter-from-class="opacity-0"
          enter-to-class="opacity-100"
          leave-active-class="transition-opacity duration-150"
          leave-from-class="opacity-100"
          leave-to-class="opacity-0"
        >
          <div
            v-if="annotationsSidebarVisible && !isDesktop"
            class="absolute inset-0 z-[25] bg-black/20"
            @click="annotationsSidebarVisible = false"
          />
        </Transition>
        <!-- Panel -->
        <Transition
          enter-active-class="transition-transform duration-300 ease-out"
          enter-from-class="translate-x-full"
          enter-to-class="translate-x-0"
          leave-active-class="transition-transform duration-200 ease-in"
          leave-from-class="translate-x-0"
          leave-to-class="translate-x-full"
        >
          <div
            v-if="annotationsSidebarVisible"
            ref="annotationsPanelEl"
            class="absolute right-0 bottom-0 w-72 z-30 flex flex-col border-l backdrop-blur-xl transition-[top] duration-200 ease-out"
            :class="[toolbarCls, isDesktop ? '' : 'max-w-[80vw]']"
            :style="{ top: panelTop, background: panelBg, boxShadow: isDesktop ? panelShadowRight : 'none' }"
          >
            <!-- Header -->
            <div class="flex items-center justify-between px-4 py-3 border-b" :class="toolbarCls">
              <div class="flex items-center gap-1">
                <button
                  @click="annotationsTab = 'highlights'"
                  class="text-sm px-2.5 py-1 rounded-md transition-colors"
                  :class="annotationsTab === 'highlights' ? 'bg-indigo-500/10 text-indigo-500 font-semibold' : subCls"
                >
                  划线
                </button>
                <button
                  @click="annotationsTab = 'bookmarks'"
                  class="text-sm px-2.5 py-1 rounded-md transition-colors"
                  :class="annotationsTab === 'bookmarks' ? 'bg-indigo-500/10 text-indigo-500 font-semibold' : subCls"
                >
                  书签
                </button>
              </div>
              <button
                @click="annotationsSidebarVisible = false"
                class="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-black/10 transition-colors"
              >
                <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            </div>
            <!-- Content -->
            <div class="flex-1 overflow-y-auto py-2">
              <!-- Highlights tab -->
              <template v-if="annotationsTab === 'highlights'">
                <template v-if="annotations.length">
                  <div v-for="(items, chapter) in groupedAnnotations" :key="chapter">
                    <div class="px-4 py-2 text-[11px] font-medium tracking-wide uppercase" :class="subCls">
                      {{ chapter }}
                    </div>
                    <div
                      v-for="ann in items"
                      :key="ann.id"
                      class="group relative flex items-start gap-2.5 px-4 py-3 hover:bg-black/5 active:bg-black/10 transition-colors cursor-pointer"
                      :class="panelTextCls"
                      @click="goToAnnotation(ann)"
                    >
                      <div
                        class="w-1 self-stretch rounded-full shrink-0 mt-0.5"
                        :style="{ background: HIGHLIGHT_COLORS[ann.color] || '#facc15' }"
                      />
                      <div class="min-w-0 flex-1">
                        <p class="text-sm leading-relaxed line-clamp-3">
                          {{ ann.selected_text || '(无文本)' }}
                        </p>
                        <p v-if="ann.note" class="text-xs mt-1 line-clamp-2" :class="subCls">
                          {{ ann.note }}
                        </p>
                      </div>
                      <button
                        @click.stop="removeAnnotation(ann)"
                        class="shrink-0 w-6 h-6 flex items-center justify-center rounded-full text-gray-400 hover:text-rose-500 hover:bg-rose-50 active:bg-rose-100 transition-all md:opacity-0 md:group-hover:opacity-100"
                        :class="theme === 'dark' ? 'hover:bg-rose-500/10 active:bg-rose-500/20' : ''"
                        title="删除"
                      >
                        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </template>
                <div v-else class="px-4 py-8 text-center text-sm" :class="subCls">
                  暂无划线
                </div>
              </template>
              <!-- Bookmarks tab -->
              <template v-else>
                <template v-if="bookmarks.length">
                  <div
                    v-for="bm in bookmarks"
                    :key="bm.id"
                    class="group relative flex items-center gap-2.5 px-4 py-3 hover:bg-black/5 active:bg-black/10 transition-colors cursor-pointer"
                    :class="panelTextCls"
                    @click="goToBookmark(bm)"
                  >
                    <svg class="w-4 h-4 text-indigo-500 shrink-0" viewBox="0 0 24 24" fill="#6366f1" stroke="#6366f1" stroke-width="2">
                      <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
                    </svg>
                    <div class="min-w-0 flex-1">
                      <p class="text-sm truncate">{{ bm.title || bm.section_title || '未命名书签' }}</p>
                      <p v-if="bm.section_title && bm.title !== bm.section_title" class="text-xs mt-0.5 truncate" :class="subCls">
                        {{ bm.section_title }}
                      </p>
                    </div>
                    <button
                      @click.stop="removeBookmarkById(bm)"
                      class="shrink-0 w-6 h-6 flex items-center justify-center rounded-full text-gray-400 hover:text-rose-500 hover:bg-rose-50 active:bg-rose-100 transition-all md:opacity-0 md:group-hover:opacity-100"
                      :class="theme === 'dark' ? 'hover:bg-rose-500/10 active:bg-rose-500/20' : ''"
                      title="删除"
                    >
                      <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      </svg>
                    </button>
                  </div>
                </template>
                <div v-else class="px-4 py-8 text-center text-sm" :class="subCls">
                  暂无书签
                </div>
              </template>
            </div>
          </div>
        </Transition>

        <!-- ======== Shortcut help panel (desktop only) ======== -->
        <Teleport to="body">
          <Transition
            enter-active-class="transition-opacity duration-200 ease-out"
            enter-from-class="opacity-0"
            enter-to-class="opacity-100"
            leave-active-class="transition-opacity duration-150 ease-in"
            leave-from-class="opacity-100"
            leave-to-class="opacity-0"
          >
            <div
              v-if="shortcutHelpVisible && isDesktop"
              class="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 backdrop-blur-sm"
              @click.self="shortcutHelpVisible = false"
            >
              <div
                class="w-80 max-h-[80vh] rounded-2xl border shadow-2xl overflow-hidden"
                :class="toolbarCls"
                :style="{ background: containerBg }"
              >
                <!-- Header -->
                <div class="flex items-center justify-between px-5 py-3.5 border-b" :class="toolbarCls">
                  <h3 class="text-sm font-semibold">键盘快捷键</h3>
                  <button
                    @click="shortcutHelpVisible = false"
                    class="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-black/10 transition-colors"
                  >
                    <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M18 6 6 18M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <!-- Key list -->
                <div class="px-5 py-3 space-y-2 overflow-y-auto max-h-[60vh]">
                  <div
                    v-for="(item, idx) in shortcutList"
                    :key="idx"
                    class="flex items-center justify-between py-1"
                  >
                    <span class="text-sm" :class="panelTextCls">{{ item.desc }}</span>
                    <span class="flex items-center gap-1">
                      <kbd
                        v-for="(k, ki) in item.key.split(' / ')"
                        :key="ki"
                        class="inline-block px-1.5 py-0.5 text-xs font-mono rounded border leading-none"
                        :class="kbdCls"
                      >{{ k }}</kbd>
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </Transition>
        </Teleport>

        <!-- ======== Page turn areas (desktop) ======== -->
        <button
          @click="prev"
          class="absolute top-0 bottom-0 w-[15%] z-[5] cursor-w-resize opacity-0 focus:outline-none hidden md:block transition-[left] duration-300 ease-out"
          :style="{ left: readerLeft }"
          aria-label="上一页"
        />
        <button
          @click="next"
          class="absolute top-0 bottom-0 w-[15%] z-[5] cursor-e-resize opacity-0 focus:outline-none hidden md:block transition-[right] duration-300 ease-out"
          :style="{ right: readerRight }"
          aria-label="下一页"
        />
      </template>
    </div>
  </Teleport>
</template>
