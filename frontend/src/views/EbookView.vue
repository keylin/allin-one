<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listEbooks, deleteEbook, getEbookFilters, getEbookSyncStatus } from '@/api/ebook'
import { isExternalSource, getSourceConfig } from '@/config/external-sources'
import { formatTimeShort } from '@/utils/time'
import EbookMetadataModal from '@/components/ebook-metadata-modal.vue'
import BookAnnotationSidebar from '@/components/book-annotation-sidebar.vue'

const router = useRouter()

// State
const loading = ref(false)
const books = ref([])
const totalCount = ref(0)
const searchQuery = ref('')
const sortBy = ref('created_at')
const viewMode = ref('grid')
const contextMenuBook = ref(null)
const deleteConfirmId = ref(null)

// Filter state
const filterAuthor = ref('')
const filterCategory = ref('')
const filterAuthors = ref([])
const filterCategories = ref([])

// Sync status
const syncStatus = ref(null)

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

// Open book → open sidebar
const sidebarBook = ref(null)
const sidebarVisible = ref(false)

function openBook(book, fromMenu = false) {
  if (!fromMenu && contextMenuBook.value) return // Don't open if context menu is showing
  sidebarBook.value = book
  sidebarVisible.value = true
}

function closeSidebar() {
  sidebarVisible.value = false
  sidebarBook.value = null
}

function showBookAnnotations(book) {
  openBook(book)
}

function handleSidebarOpenMetadata(book) {
  metadataBookId.value = book.content_id
  metadataVisible.value = true
}

// Search debounce
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(fetchBooks, 300)
})

watch(sortBy, fetchBooks)
watch(filterAuthor, fetchBooks)
watch(filterCategory, fetchBooks)

async function fetchSyncStatus() {
  try {
    const res = await getEbookSyncStatus()
    if (res.code === 0 && res.data?.source_id) {
      syncStatus.value = res.data
    }
  } catch (e) {
    // ignore
  }
}

onMounted(() => {
  fetchBooks()
  fetchFilters()
  fetchSyncStatus()
})

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
  <div class="flex flex-col h-full">
    <!-- Header -->
    <div class="px-4 pt-3 pb-2.5 space-y-2 sticky top-0 bg-white/95 backdrop-blur-sm z-10 border-b border-slate-100 shrink-0">
      <!-- Row 1: Title + count + sort -->
      <div class="flex items-center gap-2.5">
        <span class="text-xs text-slate-400 tabular-nums shrink-0">{{ totalCount }} 本</span>

        <!-- Apple Books sync status -->
        <span
          v-if="syncStatus"
          class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] text-emerald-600 bg-emerald-50 rounded-full"
          :title="syncStatus.last_sync_at ? `上次同步: ${formatTime(syncStatus.last_sync_at)}` : '尚未同步'"
        >
          <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" /><path d="M16 16h5v5" />
          </svg>
          <span class="hidden sm:inline">{{ syncStatus.total_books }} 本同步</span>
        </span>

        <div class="flex-1" />

        <!-- View mode toggle -->
        <div class="flex items-center bg-slate-100 rounded-lg p-0.5">
          <button
            @click="viewMode = 'grid'"
            class="p-1.5 rounded-md transition-all"
            :class="viewMode === 'grid' ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-400 hover:text-slate-600'"
            title="网格视图"
          >
            <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
            </svg>
          </button>
          <button
            @click="viewMode = 'list'"
            class="p-1.5 rounded-md transition-all"
            :class="viewMode === 'list' ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-400 hover:text-slate-600'"
            title="列表视图"
          >
            <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
            </svg>
          </button>
        </div>

        <select
          v-model="sortBy"
          class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none cursor-pointer transition-all"
        >
          <option value="created_at">添加时间</option>
          <option value="title">书名</option>
          <option value="annotation_count">标注数量</option>
        </select>
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
          <p class="text-xs text-slate-400">通过同步功能添加书籍到书架</p>
        </div>

        <!-- Book grid -->
        <div v-else-if="viewMode === 'grid'" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
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
                    <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
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

              <!-- Format / Source badge -->
              <span v-if="isExternalSource(book.source)" class="absolute top-2 left-2 px-1.5 py-0.5 text-[10px] font-medium bg-slate-800/70 text-white rounded flex items-center gap-0.5">
                <svg v-if="book.source === 'apple_books'" class="w-2.5 h-2.5" viewBox="0 0 24 24" fill="currentColor"><path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.8-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/></svg>
                {{ getSourceConfig(book.source)?.label || book.source }}
              </span>
              <span v-else class="absolute top-2 left-2 px-1.5 py-0.5 text-[10px] font-medium bg-black/60 text-white rounded uppercase">
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
              <div class="mt-0.5 flex items-center gap-1 text-[10px] text-slate-300">
                <span v-if="book.created_at">{{ formatTime(book.created_at) }}</span>
                <template v-if="book.annotation_count > 0">
                  <span v-if="book.created_at" class="text-slate-200">·</span>
                  <span class="text-amber-500/70">{{ book.annotation_count }} 条标注</span>
                </template>
              </div>
            </div>
          </div>
        </div>

        <!-- Book table -->
        <table v-else class="w-full text-left">
          <thead>
            <tr class="text-[11px] font-medium text-slate-400 uppercase tracking-wider border-b border-slate-200">
              <th class="pb-2 pl-3 pr-2 font-medium cursor-pointer hover:text-slate-600 transition-colors" @click="sortBy = 'title'">
                <span class="inline-flex items-center gap-0.5">书名<svg v-if="sortBy === 'title'" class="w-3 h-3 text-indigo-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6" /></svg></span>
              </th>
              <th class="pb-2 px-2 font-medium hidden sm:table-cell">作者</th>
              <th class="pb-2 px-2 font-medium hidden md:table-cell">来源</th>
              <th class="pb-2 px-2 font-medium hidden lg:table-cell">分类</th>
              <th class="pb-2 px-2 font-medium text-center w-16 cursor-pointer hover:text-slate-600 transition-colors" @click="sortBy = 'annotation_count'">
                <span class="inline-flex items-center justify-center gap-0.5">标注<svg v-if="sortBy === 'annotation_count'" class="w-3 h-3 text-indigo-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6" /></svg></span>
              </th>
              <th class="pb-2 px-2 font-medium hidden sm:table-cell w-24 cursor-pointer hover:text-slate-600 transition-colors" @click="sortBy = 'created_at'">
                <span class="inline-flex items-center gap-0.5">时间<svg v-if="sortBy === 'created_at'" class="w-3 h-3 text-indigo-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6" /></svg></span>
              </th>
              <th class="pb-2 pl-2 pr-3 font-medium w-20"></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr
              v-for="book in books"
              :key="book.content_id"
              class="group cursor-pointer transition-colors hover:bg-slate-50/80 select-none"
              @click="openBook(book)"
              @pointerdown="onPointerDown(book, $event)"
              @pointerup="onPointerUp"
              @pointercancel="onPointerCancel"
              @contextmenu.prevent="contextMenuBook = book"
            >
              <!-- 书名 -->
              <td class="py-2.5 pl-3 pr-2">
                <span class="text-sm font-medium text-slate-800 line-clamp-1">{{ book.title || '未知书名' }}</span>
              </td>
              <!-- 作者 -->
              <td class="py-2.5 px-2 hidden sm:table-cell">
                <span class="text-xs text-slate-500 truncate block max-w-[120px]">{{ book.author || '—' }}</span>
              </td>
              <!-- 来源 -->
              <td class="py-2.5 px-2 hidden md:table-cell">
                <span v-if="isExternalSource(book.source)" class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium bg-slate-100 text-slate-500 rounded">
                  {{ getSourceConfig(book.source)?.label || book.source }}
                </span>
                <span v-else-if="book.format" class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium bg-slate-100 text-slate-500 rounded uppercase">
                  {{ book.format }}
                </span>
                <span v-else class="text-xs text-slate-300">—</span>
              </td>
              <!-- 分类 -->
              <td class="py-2.5 px-2 hidden lg:table-cell">
                <div class="flex items-center gap-1">
                  <span
                    v-for="s in (book.subjects || []).slice(0, 2)"
                    :key="s"
                    class="px-1.5 py-0.5 text-[10px] font-medium bg-indigo-50 text-indigo-600 rounded"
                  >{{ s }}</span>
                  <span v-if="!book.subjects?.length" class="text-xs text-slate-300">—</span>
                </div>
              </td>
              <!-- 标注 -->
              <td class="py-2.5 px-2 text-center">
                <span v-if="book.annotation_count > 0" class="text-xs font-medium text-amber-500/80 tabular-nums">{{ book.annotation_count }}</span>
                <span v-else class="text-xs text-slate-300">—</span>
              </td>
              <!-- 时间 -->
              <td class="py-2.5 px-2 hidden sm:table-cell">
                <span class="text-[11px] text-slate-400 tabular-nums whitespace-nowrap">{{ formatTime(book.created_at) }}</span>
              </td>
              <!-- 操作 -->
              <td class="py-2.5 pl-2 pr-3">
                <div class="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    @click="openMetadata(book, $event)"
                    class="p-1 text-slate-300 hover:text-indigo-500 rounded-md hover:bg-indigo-50 transition-all"
                    title="编辑信息"
                  >
                    <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" />
                    </svg>
                  </button>
                  <button
                    @click="handleDeleteClick(book.content_id, $event)"
                    class="p-1 rounded-md transition-all"
                    :class="deleteConfirmId === book.content_id
                      ? 'text-rose-600 bg-rose-50'
                      : 'text-slate-300 hover:text-rose-500 hover:bg-rose-50'"
                    :title="deleteConfirmId === book.content_id ? '确认删除？' : '删除'"
                  >
                    <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
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
              <a
                v-if="isExternalSource(contextMenuBook.source)"
                :href="getSourceConfig(contextMenuBook.source)?.deepLink(contextMenuBook.external_id)"
                @click="closeContextMenu()"
                class="w-full text-left px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 active:bg-slate-100 flex items-center gap-3"
              >
                <svg class="w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
                </svg>
                {{ getSourceConfig(contextMenuBook.source)?.openLabel || '打开' }}
              </a>
              <button
                @click="openBook(contextMenuBook, true); closeContextMenu()"
                class="w-full text-left px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 active:bg-slate-100 flex items-center gap-3"
              >
                <svg class="w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                </svg>
                查看标注
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

    <!-- Annotation Sidebar -->
    <BookAnnotationSidebar
      :book="sidebarBook"
      :visible="sidebarVisible"
      @close="closeSidebar"
      @open-metadata="handleSidebarOpenMetadata"
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
