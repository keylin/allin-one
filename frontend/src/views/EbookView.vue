<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listEbooks, uploadEbook, deleteEbook, getEbookFilters } from '@/api/ebook'
import { formatTimeShort } from '@/utils/time'
import EbookReader from '@/components/ebook-reader.vue'
import EbookMetadataModal from '@/components/ebook-metadata-modal.vue'

const router = useRouter()

// State
const loading = ref(false)
const books = ref([])
const totalCount = ref(0)
const searchQuery = ref('')
const sortBy = ref('created_at')
const showUploadArea = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadError = ref('')
const selectedBookId = ref(null)
const readerVisible = ref(false)
const contextMenuBook = ref(null)
const deleteConfirmId = ref(null)

// Filter state
const filterAuthor = ref('')
const filterCategory = ref('')
const filterAuthors = ref([])
const filterCategories = ref([])

// Metadata modal state
const metadataBookId = ref(null)
const metadataVisible = ref(false)

let searchTimer = null
let longPressTimer = null
let deleteConfirmTimer = null

// Fetch books
async function fetchBooks() {
  loading.value = true
  try {
    const params = { page: 1, page_size: 100, sort_by: sortBy.value, sort_order: 'desc' }
    if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
    if (filterAuthor.value) params.author = filterAuthor.value
    if (filterCategory.value) params.category = filterCategory.value
    const res = await listEbooks(params)
    if (res.code === 0) {
      books.value = res.data
      totalCount.value = res.total
    }
  } finally {
    loading.value = false
  }
}

async function fetchFilters() {
  try {
    const res = await getEbookFilters()
    if (res.code === 0) {
      filterAuthors.value = res.data.authors || []
      filterCategories.value = res.data.categories || []
    }
  } catch (e) {
    // ignore
  }
}

// Metadata modal
function openMetadata(book, event) {
  event?.stopPropagation?.()
  metadataBookId.value = book.content_id
  metadataVisible.value = true
}

function closeMetadata() {
  metadataVisible.value = false
  metadataBookId.value = null
}

function onMetadataUpdated() {
  fetchBooks()
  fetchFilters()
}

// Upload
async function handleFileSelect(event) {
  const file = event.target.files?.[0]
  if (!file) return
  // macOS 上解压的 epub 目录被 file input 当成 0 字节文件
  if (file.size === 0) {
    uploadError.value = '该文件无法通过文件选择器上传（可能是未打包的 epub 目录），请直接拖拽到此区域'
    event.target.value = ''
    return
  }
  await doUpload(file)
  event.target.value = ''
}

async function handleDrop(event) {
  event.preventDefault()

  // 优先用 DataTransferItem API，支持目录拖入（macOS 解压的 epub 目录）
  const items = event.dataTransfer?.items
  if (items?.length > 0) {
    const entry = items[0].webkitGetAsEntry?.()
    if (entry?.isDirectory && entry.name.toLowerCase().endsWith('.epub')) {
      await packEpubDirectoryAndUpload(entry)
      return
    }
  }

  const file = event.dataTransfer?.files?.[0]
  if (!file) return

  // 0 字节 = macOS 未打包的 epub 目录被当作文件拖入
  if (file.size === 0 && file.name.toLowerCase().endsWith('.epub')) {
    uploadError.value = '检测到未打包的 epub 目录，拖拽时请直接将文件夹拖到此虚线框内'
    return
  }

  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!['epub', 'mobi', 'azw', 'azw3'].includes(ext)) {
    uploadError.value = '不支持的格式，请上传 EPUB 或 MOBI 文件'
    return
  }
  await doUpload(file)
}

// 将解压的 epub 目录重新打包为标准 epub zip，再上传
async function packEpubDirectoryAndUpload(dirEntry) {
  uploading.value = true
  uploadProgress.value = 0
  uploadError.value = ''
  try {
    const { default: JSZip } = await import('jszip')
    const zip = new JSZip()

    // 递归读取目录所有文件
    async function readDir(entry, basePath) {
      if (entry.isFile) {
        const file = await new Promise((res, rej) => entry.file(res, rej))
        const buf = await file.arrayBuffer()
        const opts = entry.name === 'mimetype' ? { compression: 'STORE' } : {}
        zip.file(basePath, buf, opts)
      } else {
        const reader = entry.createReader()
        const entries = await new Promise((res, rej) => {
          const all = []
          const read = () => reader.readEntries(batch => {
            if (!batch.length) return res(all)
            all.push(...batch)
            read()
          }, rej)
          read()
        })
        for (const e of entries) {
          await readDir(e, basePath ? `${basePath}/${e.name}` : e.name)
        }
      }
    }

    // mimetype 必须最先写入且不压缩（epub 规范要求）
    const reader = dirEntry.createReader()
    const topEntries = await new Promise((res, rej) => {
      const all = []
      const read = () => reader.readEntries(batch => {
        if (!batch.length) return res(all)
        all.push(...batch)
        read()
      }, rej)
      read()
    })
    const mimetypeEntry = topEntries.find(e => e.name === 'mimetype')
    if (mimetypeEntry) await readDir(mimetypeEntry, 'mimetype')
    for (const e of topEntries) {
      if (e.name !== 'mimetype') await readDir(e, e.name)
    }

    const blob = await zip.generateAsync({ type: 'blob', mimeType: 'application/epub+zip' })
    const file = new File([blob], dirEntry.name, { type: 'application/epub+zip' })
    await doUpload(file)
  } catch (e) {
    uploadError.value = '目录打包失败：' + (e.message || '未知错误')
    uploading.value = false
  }
}

async function doUpload(file) {
  uploading.value = true
  uploadProgress.value = 0
  uploadError.value = ''
  try {
    const res = await uploadEbook(file, (e) => {
      if (e.total) uploadProgress.value = Math.round((e.loaded / e.total) * 100)
    })
    if (res.code === 0) {
      showUploadArea.value = false
      fetchBooks()
    } else {
      uploadError.value = res.message || '上传失败'
    }
  } catch (e) {
    uploadError.value = e.response?.data?.message || '上传失败'
  } finally {
    uploading.value = false
    uploadProgress.value = 0
  }
}

// Delete — 两次点击确认（第一次进入确认态，3 秒后自动取消）
function handleDeleteClick(contentId, event) {
  event?.stopPropagation?.()
  if (deleteConfirmId.value === contentId) {
    doDelete(contentId)
  } else {
    deleteConfirmId.value = contentId
    clearTimeout(deleteConfirmTimer)
    deleteConfirmTimer = setTimeout(() => { deleteConfirmId.value = null }, 3000)
  }
}

async function doDelete(contentId) {
  deleteConfirmId.value = null
  clearTimeout(deleteConfirmTimer)
  try {
    await deleteEbook(contentId)
    fetchBooks()
  } catch (e) {
    console.error('Delete failed:', e)
  }
}

// Long press for mobile context menu
function onPointerDown(book, event) {
  // Only for touch (primary pointer on mobile)
  if (event.pointerType !== 'touch') return
  longPressTimer = setTimeout(() => {
    contextMenuBook.value = book
    longPressTimer = null
  }, 500)
}

function onPointerUp() {
  if (longPressTimer) {
    clearTimeout(longPressTimer)
    longPressTimer = null
  }
}

function onPointerCancel() {
  if (longPressTimer) {
    clearTimeout(longPressTimer)
    longPressTimer = null
  }
}

function closeContextMenu() {
  contextMenuBook.value = null
  deleteConfirmId.value = null
}

// Open reader
function openBook(book, fromMenu = false) {
  if (!fromMenu && contextMenuBook.value) return // Don't open if context menu is showing
  selectedBookId.value = book.content_id
  readerVisible.value = true
}

function closeReader() {
  readerVisible.value = false
  selectedBookId.value = null
  fetchBooks() // Refresh progress
}

// Search debounce
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(fetchBooks, 300)
})

watch(sortBy, fetchBooks)
watch(filterAuthor, fetchBooks)
watch(filterCategory, fetchBooks)

onMounted(() => {
  fetchBooks()
  fetchFilters()
})

// 整页拖拽：自动展开上传区并处理文件
async function onPageDrop(event) {
  showUploadArea.value = true
  await handleDrop(event)
}

function formatFileSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function formatTime(iso) {
  if (!iso) return ''
  return formatTimeShort(iso)
}
</script>

<template>
  <div
    class="flex flex-col h-full"
    @drop="onPageDrop"
    @dragover.prevent
    @dragenter.prevent
  >
    <!-- Header -->
    <div class="px-4 pt-3 pb-2.5 space-y-2 sticky top-0 bg-white/95 backdrop-blur-sm z-10 border-b border-slate-100 shrink-0">
      <!-- Row 1: Title + count + sort + upload button -->
      <div class="flex items-center gap-2.5">
        <span class="text-xs text-slate-400 tabular-nums shrink-0">{{ totalCount }} 本</span>
        <div class="flex-1" />

        <select
          v-model="sortBy"
          class="hidden md:block text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none cursor-pointer transition-all"
        >
          <option value="created_at">上传时间</option>
          <option value="title">书名</option>
        </select>

        <button
          @click="showUploadArea = !showUploadArea"
          class="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 active:scale-95 transition-all duration-150 shadow-sm shrink-0"
        >
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
          </svg>
          <span class="hidden sm:inline">上传书籍</span>
          <span class="sm:hidden">上传</span>
        </button>
      </div>

      <!-- Row 2: Search -->
      <div class="flex items-center gap-2">
        <div class="relative w-full md:w-56 shrink-0">
          <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
          </svg>
          <input
            v-model="searchQuery"
            placeholder="搜索书名或作者..."
            class="w-full bg-slate-50 rounded-lg pl-8 pr-3 py-1.5 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 focus:bg-white transition-all"
          />
        </div>

        <!-- Mobile sort -->
        <select
          v-model="sortBy"
          class="md:hidden text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 outline-none cursor-pointer ml-auto"
        >
          <option value="created_at">上传时间</option>
          <option value="title">书名</option>
        </select>
      </div>

      <!-- Row 3: Filters -->
      <div v-if="filterAuthors.length || filterCategories.length" class="flex items-center gap-2 pb-0.5">
        <select
          v-if="filterAuthors.length"
          v-model="filterAuthor"
          class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 outline-none cursor-pointer transition-all focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 max-w-[140px]"
        >
          <option value="">全部作者</option>
          <option v-for="a in filterAuthors" :key="a" :value="a">{{ a }}</option>
        </select>
        <select
          v-if="filterCategories.length"
          v-model="filterCategory"
          class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 outline-none cursor-pointer transition-all focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 max-w-[140px]"
        >
          <option value="">全部分类</option>
          <option v-for="c in filterCategories" :key="c" :value="c">{{ c }}</option>
        </select>
        <button
          v-if="filterAuthor || filterCategory"
          @click="filterAuthor = ''; filterCategory = ''"
          class="text-[11px] text-slate-400 hover:text-slate-600 transition-colors"
        >
          清除筛选
        </button>
      </div>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">
        <!-- Upload area (collapsible) -->
        <Transition
          enter-active-class="transition-all duration-300 ease-out"
          enter-from-class="opacity-0 -translate-y-2"
          enter-to-class="opacity-100 translate-y-0"
          leave-active-class="transition-all duration-200 ease-in"
          leave-from-class="opacity-100 translate-y-0"
          leave-to-class="opacity-0 -translate-y-2"
        >
          <div
            v-if="showUploadArea"
            class="mb-5 bg-white border-2 border-dashed border-slate-300 rounded-xl p-8 text-center transition-colors"
            :class="{ 'border-indigo-400 bg-indigo-50/30': uploading }"
            @drop="handleDrop"
            @dragover.prevent
            @dragenter.prevent
          >
            <div class="w-12 h-12 mx-auto mb-3 bg-slate-100 rounded-xl flex items-center justify-center">
              <svg v-if="!uploading" class="w-6 h-6 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
              </svg>
              <svg v-else class="w-6 h-6 text-indigo-500 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
            </div>
            <p class="text-sm text-slate-600 font-medium mb-1">
              {{ uploading ? `上传中... ${uploadProgress}%` : '拖拽文件到这里，或点击选择' }}
            </p>
            <!-- Upload progress bar -->
            <div v-if="uploading" class="w-48 mx-auto h-1.5 bg-slate-200 rounded-full overflow-hidden mb-2">
              <div class="h-full bg-indigo-500 rounded-full transition-all duration-300" :style="{ width: uploadProgress + '%' }" />
            </div>
            <p class="text-xs text-slate-400 mb-3">支持 EPUB、MOBI 格式</p>
            <label v-if="!uploading" class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 cursor-pointer transition-colors">
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><polyline points="13 2 13 9 20 9" />
              </svg>
              选择文件
              <input type="file" accept=".epub,.mobi,.azw,.azw3" class="hidden" @change="handleFileSelect" />
            </label>
            <p v-if="uploadError" class="mt-2 text-xs text-rose-500">{{ uploadError }}</p>
          </div>
        </Transition>

        <!-- Loading -->
        <div v-if="loading" class="flex items-center justify-center py-24">
          <svg class="w-8 h-8 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
        </div>

        <!-- Empty state -->
        <div v-else-if="books.length === 0" class="text-center py-24">
          <div class="w-16 h-16 mx-auto mb-4 bg-slate-100 rounded-2xl flex items-center justify-center">
            <svg class="w-8 h-8 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </div>
          <p class="text-sm text-slate-500 font-medium mb-1">书架空空如也</p>
          <p class="text-xs text-slate-400 mb-5">上传 EPUB 或 MOBI 文件开始阅读</p>
          <button
            @click="showUploadArea = true"
            class="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
            上传书籍
          </button>
        </div>

        <!-- Book grid -->
        <div v-else class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
          <div
            v-for="book in books"
            :key="book.content_id"
            class="group relative bg-white rounded-xl border border-slate-200/60 overflow-hidden cursor-pointer transition-all duration-200 hover:border-indigo-300 hover:shadow-md select-none"
            @click="openBook(book)"
            @pointerdown="onPointerDown(book, $event)"
            @pointerup="onPointerUp"
            @pointercancel="onPointerCancel"
            @contextmenu.prevent="contextMenuBook = book"
          >
            <!-- Cover -->
            <div class="aspect-[2/3] bg-gradient-to-br from-slate-100 to-slate-200 relative overflow-hidden">
              <img
                v-if="book.cover_url"
                :src="book.cover_url"
                :alt="book.title"
                class="absolute inset-0 w-full h-full object-cover"
                loading="lazy"
              />
              <div v-else class="absolute inset-0 flex flex-col items-center justify-center p-4">
                <svg class="w-10 h-10 text-slate-300 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
                </svg>
                <span class="text-xs text-slate-400 text-center line-clamp-3 leading-tight">{{ book.title }}</span>
              </div>

              <!-- Hover overlay -->
              <div class="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-all duration-300 flex items-center justify-center">
                <div class="w-12 h-12 bg-white/95 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transform scale-75 group-hover:scale-100 transition-all duration-300 shadow-xl">
                  <svg class="w-5 h-5 text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
                  </svg>
                </div>
              </div>

              <!-- Action buttons -->
              <div class="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all duration-200">
                <!-- Info button -->
                <button
                  @click="openMetadata(book, $event)"
                  class="w-6 h-6 flex items-center justify-center bg-black/60 hover:bg-indigo-600 text-white rounded-lg transition-colors"
                >
                  <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" />
                  </svg>
                </button>
                <!-- Delete button (二次确认) -->
                <button
                  @click="handleDeleteClick(book.content_id, $event)"
                  class="px-1.5 h-6 flex items-center justify-center text-white rounded-lg transition-all duration-200"
                  :class="deleteConfirmId === book.content_id
                    ? 'bg-rose-600 !opacity-100'
                    : 'bg-black/60 hover:bg-rose-600'"
                >
                  <span v-if="deleteConfirmId === book.content_id" class="text-[10px] font-medium">确认删除</span>
                  <svg v-else class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 6 6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>

              <!-- Format badge -->
              <span class="absolute top-2 left-2 px-1.5 py-0.5 text-[10px] font-medium bg-black/60 text-white rounded uppercase">
                {{ book.format }}
              </span>

            </div>

            <!-- Info -->
            <div class="p-3">
              <h4 class="text-sm font-medium text-slate-800 line-clamp-2 leading-snug min-h-[2.5rem]">
                {{ book.title || '未知书名' }}
              </h4>
              <div class="mt-1 flex items-center gap-1 text-[11px] text-slate-400">
                <span class="truncate">{{ book.author || '未知作者' }}</span>
                <template v-if="book.file_size">
                  <span class="text-slate-200 shrink-0">·</span>
                  <span class="shrink-0">{{ formatFileSize(book.file_size) }}</span>
                </template>
              </div>
              <div v-if="book.subjects?.length" class="mt-1.5 flex flex-wrap gap-1">
                <span
                  v-for="s in book.subjects.slice(0, 2)"
                  :key="s"
                  class="px-1.5 py-0.5 text-[10px] font-medium bg-indigo-50 text-indigo-600 rounded"
                >{{ s }}</span>
              </div>
              <div v-if="book.created_at" class="mt-0.5 text-[10px] text-slate-300">
                {{ formatTime(book.created_at) }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Mobile context menu -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition-opacity duration-150"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-opacity duration-100"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div v-if="contextMenuBook" class="fixed inset-0 z-50 flex items-end sm:items-center justify-center" @click.self="closeContextMenu">
          <div class="absolute inset-0 bg-black/30" @click="closeContextMenu" />
          <div class="relative z-10 bg-white rounded-t-2xl sm:rounded-2xl w-full sm:w-80 shadow-2xl overflow-hidden pb-safe">
            <div class="px-4 py-3 border-b border-slate-100">
              <p class="text-sm font-medium text-slate-800 truncate">{{ contextMenuBook.title }}</p>
              <p class="text-xs text-slate-400 truncate">{{ contextMenuBook.author || '未知作者' }}</p>
            </div>
            <div class="py-1">
              <button
                @click="openBook(contextMenuBook, true); closeContextMenu()"
                class="w-full text-left px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 active:bg-slate-100 flex items-center gap-3"
              >
                <svg class="w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
                </svg>
                打开阅读
              </button>
              <button
                @click="openMetadata(contextMenuBook); closeContextMenu()"
                class="w-full text-left px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 active:bg-slate-100 flex items-center gap-3"
              >
                <svg class="w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" />
                </svg>
                编辑信息
              </button>
              <button
                @click="deleteConfirmId === contextMenuBook.content_id
                  ? (doDelete(contextMenuBook.content_id), closeContextMenu())
                  : handleDeleteClick(contextMenuBook.content_id, $event)"
                class="w-full text-left px-4 py-3 text-sm hover:bg-rose-50 active:bg-rose-100 flex items-center gap-3"
                :class="deleteConfirmId === contextMenuBook.content_id ? 'text-rose-700 bg-rose-50 font-medium' : 'text-rose-600'"
              >
                <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
                {{ deleteConfirmId === contextMenuBook.content_id ? '确认删除？' : '删除书籍' }}
              </button>
            </div>
            <button
              @click="closeContextMenu"
              class="w-full py-3 text-sm text-slate-500 font-medium border-t border-slate-100 hover:bg-slate-50 active:bg-slate-100"
            >
              取消
            </button>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Reader overlay -->
    <EbookReader
      v-if="readerVisible && selectedBookId"
      :content-id="selectedBookId"
      @close="closeReader"
    />

    <!-- Metadata modal -->
    <EbookMetadataModal
      :visible="metadataVisible"
      :content-id="metadataBookId"
      @close="closeMetadata"
      @updated="onMetadataUpdated"
    />
  </div>
</template>
