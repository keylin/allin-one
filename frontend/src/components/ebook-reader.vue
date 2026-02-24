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
function savePrefs() {
  localStorage.setItem(PREFS_KEY, JSON.stringify({
    fontSize: fontSize.value,
    theme: theme.value,
    fontFamily: fontFamily.value,
    flowMode: flowMode.value,
  }))
}
const savedPrefs = loadPrefs()
const fontSize = ref(savedPrefs.fontSize || 100)
const theme = ref(savedPrefs.theme || 'light')
const fontFamily = ref(savedPrefs.fontFamily || 'default')
const isMobile = navigator.maxTouchPoints > 1
const flowMode = ref(savedPrefs.flowMode ?? (isMobile ? 'scrolled' : 'paginated'))

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

// --- Lifecycle ---
onMounted(async () => {
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('visibilitychange', onVisChange)
  window.addEventListener('beforeunload', saveNow)
  window.addEventListener('resize', onResize)
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
  view?.renderer?.setStyles?.(getStyles())
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

function runOverlayAnimation(overlay, direction, onEnd) {
  overlay.style.transform = 'translateX(0)'
  let ended = false
  function finish() {
    if (ended) return
    ended = true
    overlay.remove()
    onEnd()
  }
  overlay.addEventListener('transitionend', finish, { once: true })
  setTimeout(finish, 500)
  requestAnimationFrame(() => {
    overlay.style.transition = 'transform 380ms cubic-bezier(0.25,0.46,0.45,0.94)'
    overlay.style.transform = direction === 'next' ? 'translateX(-100%)' : 'translateX(100%)'
  })
}

async function animatePageTurn(direction) {
  if (isAnimating) return
  dismissOverlays()
  isAnimating = true
  const overlay = createOverlay()
  readerEl.value.appendChild(overlay)
  try {
    if (direction === 'next') await view?.next()
    else await view?.prev()
  } catch { /* ignore */ }
  runOverlayAnimation(overlay, direction, () => { isAnimating = false })
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
    try {
      await deleteBookmark(props.contentId, existing.id)
    } catch {
      // Re-add on failure
      bookmarks.value.push(existing)
    }
  } else {
    const cfi = view?.lastLocation?.start?.cfi || ''
    const tempId = `temp-bm-${++tempIdCounter}`
    const optimistic = {
      id: tempId,
      cfi,
      title: chapterTitle.value || bookTitle.value,
      section_title: chapterTitle.value || null,
    }
    bookmarks.value.push(optimistic)
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

    const w = doc.defaultView?.innerWidth || window.innerWidth
    const x = e.clientX
    if (x < w * 0.25) prev()
    else if (x > w * 0.75) next()
    else toggleToolbar()
  })

  doc.addEventListener('touchstart', (e) => {
    sx = e.changedTouches[0].clientX
    sy = e.changedTouches[0].clientY
    swipeHandled = false
    overlay = null
  }, { passive: true })

  doc.addEventListener('touchmove', (e) => {
    if (flowMode.value !== 'paginated') return
    const dx = e.changedTouches[0].clientX - sx
    const dy = e.changedTouches[0].clientY - sy
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
        try {
          if (direction === 'next') await view?.next()
          else await view?.prev()
        } catch { /* ignore */ }
        runOverlayAnimation(ol, direction, () => { isAnimating = false })
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
        // 滚动模式：横划直接跳章节，无动画
        try {
          if (dx < 0) await view?.next()
          else await view?.prev()
        } catch { /* ignore */ }
      }
    }
  }, { passive: true })
}

// --- Relocate ---
function onRelocate(e) {
  const { fraction, section, tocItem } = e.detail
  progress.value = fraction ?? 0
  currentSectionIndex.value = section?.current ?? 0
  chapterTitle.value = tocItem?.label?.trim() || getChapterTitle(currentSectionIndex.value)
  scheduleSave()
}

// --- Progress persistence ---
function scheduleSave() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(saveNow, 5000)
}

function saveNow() {
  if (progress.value <= 0) return
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
  if (e.key === 'Escape') {
    if (annotationPopupVisible.value) {
      annotationPopupVisible.value = false
      activeAnnotation.value = null
      return
    }
    if (selectionToolbarVisible.value) {
      selectionToolbarVisible.value = false
      return
    }
    if (annotationsSidebarVisible.value) {
      annotationsSidebarVisible.value = false
      return
    }
    if (tocVisible.value) {
      tocVisible.value = false
      return
    }
    if (settingsVisible.value) {
      settingsVisible.value = false
      return
    }
    handleClose()
    return
  }
  // Prevent browser scroll for navigation keys
  if (['ArrowLeft', 'ArrowRight', ' ', 'PageUp', 'PageDown'].includes(e.key)) {
    e.preventDefault()
  }
  if (keyThrottle) return
  if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
    keyThrottle = true
    doKeyNav('prev')
  } else if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') {
    keyThrottle = true
    doKeyNav('next')
  } else if (!e.metaKey && !e.ctrlKey && !e.altKey) {
    if (e.key === 'h' || e.key === 'k') {
      keyThrottle = true
      doKeyNav('prev')
    } else if (e.key === 'j' || e.key === 'l') {
      keyThrottle = true
      doKeyNav('next')
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
  try {
    if (direction === 'next') await view.next()
    else await view.prev()
  } catch { /* ignore */ }
  clearTimeout(safety)
  keyThrottle = false
}

function startAutoHide() {
  if (isDesktop.value) return // 桌面端常驻，不自动隐藏
  clearTimeout(toolbarTimer)
  if (!tocVisible.value && !settingsVisible.value && !annotationsSidebarVisible.value) {
    toolbarTimer = setTimeout(() => { toolbarVisible.value = false }, 4000)
  }
}

function stopAutoHide() {
  clearTimeout(toolbarTimer)
}

function toggleToolbar() {
  if (isDesktop.value) return // 桌面端工具栏常驻，不切换
  toolbarVisible.value = !toolbarVisible.value
  if (toolbarVisible.value) {
    startAutoHide()
  } else {
    stopAutoHide()
    tocVisible.value = false
    settingsVisible.value = false
    annotationsSidebarVisible.value = false
  }
}

// --- Annotation/Bookmark navigation ---
function goToAnnotation(ann) {
  if (!ann?.cfi_range) return
  view?.showAnnotation?.({ value: ann.cfi_range })
  annotationsSidebarVisible.value = false
}

function goToBookmark(bm) {
  if (!bm?.cfi) return
  view?.goTo(bm.cfi)
  annotationsSidebarVisible.value = false
}

// --- TOC navigation ---
function goToHref(href) {
  if (!href || !book) return
  const target = book.resolveHref(href)
  if (target != null) view?.goTo(target)
  tocVisible.value = false
  toolbarVisible.value = false
}

// --- Settings ---
function changeTheme(t) {
  theme.value = t
  applyStyles()
  savePrefs()
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
  view?.renderer?.setAttribute('flow', mode)
  savePrefs()
}

// --- Progress slider ---
function onSlider(e) {
  const frac = parseFloat(e.target.value)
  view?.goToFraction(frac)
}

// --- Close ---
function handleClose() {
  saveNow()
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
watch(tocVisible, (val) => {
  if (val) stopAutoHide()
  else if (toolbarVisible.value) startAutoHide()
})
watch(settingsVisible, (val) => {
  if (val) stopAutoHide()
  else if (toolbarVisible.value) startAutoHide()
})

watch(annotationsSidebarVisible, (val) => {
  if (val) stopAutoHide()
  else if (toolbarVisible.value) startAutoHide()
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
      <div ref="readerEl" class="absolute inset-0" style="touch-action: manipulation;" />

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
          :css="!isDesktop"
        >
          <div
            v-if="toolbarVisible || isDesktop"
            class="absolute top-0 left-0 right-0 z-20 backdrop-blur-md border-b flex items-center gap-2 px-3 py-2.5"
            :class="toolbarCls"
            :style="{ paddingTop: 'max(10px, env(safe-area-inset-top, 0px))' }"
          >
            <!-- Close -->
            <button
              @click="handleClose"
              class="w-9 h-9 flex items-center justify-center rounded-lg hover:bg-black/10 active:bg-black/15 transition-colors shrink-0"
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
            </button>

            <!-- Title -->
            <span class="flex-1 text-sm font-medium truncate text-center px-1">
              {{ bookTitle }}
            </span>

            <!-- TOC -->
            <button
              @click="tocVisible = !tocVisible; settingsVisible = false; annotationsSidebarVisible = false"
              class="w-9 h-9 flex items-center justify-center rounded-lg hover:bg-black/10 active:bg-black/15 transition-colors shrink-0"
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

            <!-- Annotations sidebar -->
            <button
              @click="annotationsSidebarVisible = !annotationsSidebarVisible; tocVisible = false; settingsVisible = false"
              class="w-9 h-9 flex items-center justify-center rounded-lg hover:bg-black/10 active:bg-black/15 transition-colors shrink-0"
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
          :css="!isDesktop"
        >
          <div
            v-if="toolbarVisible || isDesktop"
            class="absolute bottom-0 left-0 right-0 z-20 backdrop-blur-md border-t px-4 pt-2.5"
            :class="toolbarCls"
            :style="{ paddingBottom: 'max(10px, env(safe-area-inset-bottom, 0px))' }"
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

        <!-- ======== TOC sidebar ======== -->
        <!-- Backdrop -->
        <Transition
          enter-active-class="transition-opacity duration-200"
          enter-from-class="opacity-0"
          enter-to-class="opacity-100"
          leave-active-class="transition-opacity duration-150"
          leave-from-class="opacity-100"
          leave-to-class="opacity-0"
        >
          <div
            v-if="tocVisible"
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
            class="absolute inset-y-0 left-0 w-72 max-w-[80vw] z-30 flex flex-col border-r backdrop-blur-xl"
            :class="toolbarCls"
            :style="{ background: containerBg }"
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
                class="block w-full text-left text-sm py-2.5 px-4 hover:bg-black/5 active:bg-black/10 transition-colors truncate"
                :style="{ paddingLeft: item.depth * 16 + 16 + 'px' }"
              >
                <span :class="item.depth > 0 ? subCls : ''">{{ item.title }}</span>
              </button>
              <div v-if="flatToc.length === 0" class="px-4 py-8 text-center text-sm" :class="subCls">
                暂无目录
              </div>
            </div>
          </div>
        </Transition>

        <!-- ======== Settings panel ======== -->
        <Transition
          enter-active-class="transition-all duration-200 ease-out"
          enter-from-class="opacity-0 scale-95 origin-top-right"
          enter-to-class="opacity-100 scale-100"
          leave-active-class="transition-all duration-150 ease-in"
          leave-from-class="opacity-100 scale-100"
          leave-to-class="opacity-0 scale-95 origin-top-right"
        >
          <div
            v-if="settingsVisible"
            class="absolute w-56 z-30 rounded-xl border shadow-xl p-4 space-y-4"
            :class="toolbarCls"
            :style="{
              top: 'calc(max(10px, env(safe-area-inset-top, 0px)) + 46px)',
              right: '12px',
              background: containerBg,
            }"
          >
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
        <!-- Backdrop -->
        <Transition
          enter-active-class="transition-opacity duration-200"
          enter-from-class="opacity-0"
          enter-to-class="opacity-100"
          leave-active-class="transition-opacity duration-150"
          leave-from-class="opacity-100"
          leave-to-class="opacity-0"
        >
          <div
            v-if="annotationsSidebarVisible"
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
            class="absolute inset-y-0 right-0 w-72 max-w-[80vw] z-30 flex flex-col border-l backdrop-blur-xl"
            :class="toolbarCls"
            :style="{ background: containerBg }"
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
                      class="group relative flex items-start gap-2.5 px-4 py-2.5 hover:bg-black/5 active:bg-black/10 transition-colors cursor-pointer"
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

        <!-- ======== Page turn areas (desktop) ======== -->
        <button
          v-if="!toolbarVisible || isDesktop"
          @click="prev"
          class="absolute left-0 top-0 bottom-0 w-[15%] z-[5] cursor-w-resize opacity-0 focus:outline-none hidden md:block"
          aria-label="上一页"
        />
        <button
          v-if="!toolbarVisible || isDesktop"
          @click="next"
          class="absolute right-0 top-0 bottom-0 w-[15%] z-[5] cursor-e-resize opacity-0 focus:outline-none hidden md:block"
          aria-label="下一页"
        />
      </template>
    </div>
  </Teleport>
</template>
