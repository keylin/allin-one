<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, toRef } from 'vue'
import { useScrollLock } from '@/composables/useScrollLock'
import {
  getEbookDetail,
  getEbookFileUrl,
  getReadingProgress,
  updateReadingProgress,
} from '@/api/ebook'
import ePub from 'epubjs'

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
const currentCfi = ref('')
const progress = ref(0)
const locationsReady = ref(false)
const chapterTitle = ref('')
const pageInfo = ref('')

// Settings
const fontSize = ref(100)
const theme = ref('light')

// Refs
const readerEl = ref(null)
let book = null
let rendition = null
let saveTimer = null

// --- Theme config ---
const themeStyles = {
  light: { body: { color: '#374151', background: '#ffffff' } },
  warm: { body: { color: '#5b4636', background: '#f8f1e3' } },
  dark: { body: { color: '#d1d5db', background: '#1a1a2e' } },
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
  await init()
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('visibilitychange', onVisChange)
  window.removeEventListener('beforeunload', saveNow)
  clearTimeout(saveTimer)
  saveNow()
  cleanup()
})

// --- Init ---
async function init() {
  loading.value = true
  errorMsg.value = ''

  try {
    // Book detail (title + TOC)
    const detail = await getEbookDetail(props.contentId)
    if (detail.code === 0 && detail.data) {
      bookTitle.value = detail.data.title || '未知书名'
      if (detail.data.toc?.length) tocItems.value = detail.data.toc
    }

    // Fetch EPUB binary with auth
    const url = getEbookFileUrl(props.contentId)
    const apiKey = localStorage.getItem('api_key')
    const resp = await fetch(url, {
      headers: apiKey ? { 'X-API-Key': apiKey } : {},
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const buf = await resp.arrayBuffer()

    // epub.js
    book = ePub(buf)
    await book.ready

    // Fallback TOC
    if (!tocItems.value.length && book.navigation?.toc?.length) {
      tocItems.value = book.navigation.toc.map(mapToc)
    }

    // Render
    await nextTick()
    rendition = book.renderTo(readerEl.value, {
      width: '100%',
      height: '100%',
      flow: 'paginated',
      spread: 'none',
      snap: true,
    })

    // Themes
    Object.entries(themeStyles).forEach(([n, s]) => rendition.themes.register(n, s))
    applySettings()

    // Restore position
    let savedCfi = null
    try {
      const prog = await getReadingProgress(props.contentId)
      if (prog?.data?.cfi) savedCfi = prog.data.cfi
    } catch {
      /* first read */
    }
    await rendition.display(savedCfi || undefined)

    // Generate locations (async, for progress %)
    book.locations.generate(1024).then(() => {
      locationsReady.value = true
      if (rendition?.location) updateDisplay(rendition.location)
    })

    // Events
    rendition.on('relocated', onRelocated)
    rendition.on('click', onContentClick)
    rendition.hooks.content.register(addTouchHandlers)

    loading.value = false
  } catch (e) {
    console.error('Reader init error:', e)
    errorMsg.value = '无法加载电子书'
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

function addTouchHandlers(contents) {
  const doc = contents.document
  let sx = 0
  let sy = 0
  doc.addEventListener(
    'touchstart',
    (e) => {
      sx = e.changedTouches[0].clientX
      sy = e.changedTouches[0].clientY
    },
    { passive: true },
  )
  doc.addEventListener(
    'touchend',
    (e) => {
      const dx = e.changedTouches[0].clientX - sx
      const dy = e.changedTouches[0].clientY - sy
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy) * 1.5) {
        dx > 0 ? rendition.prev() : rendition.next()
      }
    },
    { passive: true },
  )
}

// --- Relocated ---
function onRelocated(loc) {
  if (!loc?.start) return
  currentCfi.value = loc.start.cfi
  updateDisplay(loc)
  scheduleSave()
}

function updateDisplay(loc) {
  if (!loc?.start) return
  if (locationsReady.value && book.locations?.length()) {
    progress.value = book.locations.percentageFromCfi(loc.start.cfi) || 0
  }
  chapterTitle.value = findChapter(loc.start.href) || ''
  if (loc.start.displayed) {
    pageInfo.value = `${loc.start.displayed.page} / ${loc.start.displayed.total}`
  }
}

function findChapter(href) {
  const clean = href?.split('#')[0]
  function walk(items) {
    for (const it of items) {
      if (it.href?.split('#')[0] === clean) return it.title
      if (it.children?.length) {
        const r = walk(it.children)
        if (r) return r
      }
    }
    return null
  }
  return walk(tocItems.value)
}

// --- Progress persistence ---
function scheduleSave() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(saveNow, 5000)
}

function saveNow() {
  if (!currentCfi.value) return
  updateReadingProgress(props.contentId, {
    cfi: currentCfi.value,
    progress: progress.value,
    section_title: chapterTitle.value || null,
  }).catch(() => {})
}

function onVisChange() {
  if (document.visibilityState === 'hidden') saveNow()
}

// --- Navigation ---
function prev() {
  rendition?.prev()
}
function next() {
  rendition?.next()
}

function onKeydown(e) {
  if (e.key === 'Escape') {
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
  if (e.key === 'ArrowLeft') prev()
  if (e.key === 'ArrowRight') next()
}

function onContentClick(e) {
  const w = window.innerWidth
  const x = e.clientX ?? e.pageX ?? w / 2
  if (x < w * 0.25) prev()
  else if (x > w * 0.75) next()
  else toggleToolbar()
}

function toggleToolbar() {
  toolbarVisible.value = !toolbarVisible.value
  if (!toolbarVisible.value) {
    tocVisible.value = false
    settingsVisible.value = false
  }
}

// --- TOC navigation ---
function goToHref(href) {
  if (!href) return
  rendition?.display(href)
  tocVisible.value = false
  toolbarVisible.value = false
}

// --- Settings ---
function applySettings() {
  if (!rendition) return
  rendition.themes.select(theme.value)
  rendition.themes.fontSize(`${fontSize.value}%`)
}

function changeTheme(t) {
  theme.value = t
  applySettings()
}

function adjustFont(delta) {
  fontSize.value = Math.max(70, Math.min(160, fontSize.value + delta))
  applySettings()
}

// --- Progress slider ---
function onSlider(e) {
  const pct = parseFloat(e.target.value)
  if (locationsReady.value && book.locations?.length()) {
    const cfi = book.locations.cfiFromPercentage(pct)
    rendition?.display(cfi)
  }
}

// --- Close ---
function handleClose() {
  saveNow()
  isVisible.value = false
  emit('close')
}

function cleanup() {
  if (rendition) {
    rendition.destroy()
    rendition = null
  }
  if (book) {
    book.destroy()
    book = null
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[60]" :style="{ background: containerBg }">
      <!-- Reader target (always present) -->
      <div ref="readerEl" class="absolute inset-0" />

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
              @click="tocVisible = !tocVisible; settingsVisible = false"
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

            <!-- Settings -->
            <button
              @click="settingsVisible = !settingsVisible; tocVisible = false"
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
            class="absolute bottom-0 left-0 right-0 z-20 backdrop-blur-md border-t px-4 pt-2.5"
            :class="toolbarCls"
            :style="{ paddingBottom: 'max(10px, env(safe-area-inset-bottom, 0px))' }"
          >
            <!-- Chapter & progress text -->
            <div class="flex items-center justify-between text-xs mb-2" :class="subCls">
              <span class="truncate max-w-[65%]">{{ chapterTitle || '—' }}</span>
              <span class="tabular-nums shrink-0">
                {{ locationsReady ? Math.round(progress * 100) + '%' : pageInfo || '—' }}
              </span>
            </div>
            <!-- Progress slider -->
            <input
              v-if="locationsReady"
              type="range"
              min="0"
              max="1"
              step="0.001"
              :value="progress"
              @input="onSlider"
              class="w-full h-1 mb-1 appearance-none rounded-full cursor-pointer opacity-60 hover:opacity-100 transition-opacity [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-indigo-500 [&::-webkit-slider-thumb]:shadow [&::-moz-range-thumb]:w-3 [&::-moz-range-thumb]:h-3 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-indigo-500 [&::-moz-range-thumb]:border-0"
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
            class="absolute top-[52px] right-3 w-56 z-30 rounded-xl border shadow-xl p-4 space-y-4"
            :class="toolbarCls"
            :style="{ background: containerBg }"
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
          </div>
        </Transition>

        <!-- ======== Page turn areas (desktop) ======== -->
        <button
          v-if="!toolbarVisible"
          @click="prev"
          class="absolute left-0 top-0 bottom-0 w-[15%] z-[5] cursor-w-resize opacity-0 focus:outline-none hidden md:block"
          aria-label="上一页"
        />
        <button
          v-if="!toolbarVisible"
          @click="next"
          class="absolute right-0 top-0 bottom-0 w-[15%] z-[5] cursor-e-resize opacity-0 focus:outline-none hidden md:block"
          aria-label="下一页"
        />
      </template>
    </div>
  </Teleport>
</template>
