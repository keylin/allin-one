<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listEbooks, uploadEbook, deleteEbook } from '@/api/ebook'
import EbookReader from '@/components/ebook-reader.vue'

const router = useRouter()

// State
const loading = ref(false)
const books = ref([])
const totalCount = ref(0)
const searchQuery = ref('')
const sortBy = ref('updated_at')
const showUploadArea = ref(false)
const uploading = ref(false)
const uploadError = ref('')
const selectedBookId = ref(null)
const readerVisible = ref(false)

let searchTimer = null

// Fetch books
async function fetchBooks() {
  loading.value = true
  try {
    const params = { page: 1, page_size: 100, sort_by: sortBy.value, sort_order: 'desc' }
    if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
    const res = await listEbooks(params)
    if (res.code === 0) {
      books.value = res.data
      totalCount.value = res.total
    }
  } finally {
    loading.value = false
  }
}

// Upload
async function handleFileSelect(event) {
  const file = event.target.files?.[0]
  if (!file) return
  await doUpload(file)
  event.target.value = ''
}

async function handleDrop(event) {
  event.preventDefault()
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!['epub', 'mobi', 'azw', 'azw3'].includes(ext)) {
    uploadError.value = '不支持的格式，请上传 EPUB 或 MOBI 文件'
    return
  }
  await doUpload(file)
}

async function doUpload(file) {
  uploading.value = true
  uploadError.value = ''
  try {
    const res = await uploadEbook(file)
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
  }
}

// Delete
async function handleDelete(contentId, event) {
  event.stopPropagation()
  if (!confirm('确定删除这本书吗？')) return
  try {
    await deleteEbook(contentId)
    fetchBooks()
  } catch (e) {
    console.error('Delete failed:', e)
  }
}

// Open reader
function openBook(book) {
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

onMounted(fetchBooks)

function formatProgress(p) {
  return Math.round((p || 0) * 100)
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = now - d
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
</script>

<template>
  <div class="flex flex-col h-full">
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
          <option value="updated_at">最近阅读</option>
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
          <option value="updated_at">最近阅读</option>
          <option value="created_at">上传时间</option>
          <option value="title">书名</option>
        </select>
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
              {{ uploading ? '上传中...' : '拖拽文件到这里，或点击选择' }}
            </p>
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
            class="group relative bg-white rounded-xl border border-slate-200/60 overflow-hidden cursor-pointer transition-all duration-200 hover:border-indigo-300 hover:shadow-md"
            @click="openBook(book)"
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

              <!-- Delete button -->
              <button
                @click="handleDelete(book.content_id, $event)"
                class="absolute top-2 right-2 w-6 h-6 flex items-center justify-center bg-black/60 hover:bg-rose-600 text-white rounded-lg opacity-0 group-hover:opacity-100 transition-all duration-200"
              >
                <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>

              <!-- Format badge -->
              <span class="absolute top-2 left-2 px-1.5 py-0.5 text-[10px] font-medium bg-black/60 text-white rounded uppercase">
                {{ book.format }}
              </span>

              <!-- Progress bar -->
              <div v-if="book.progress > 0" class="absolute bottom-0 left-0 right-0 h-1 bg-black/20">
                <div class="h-full bg-indigo-500 transition-all duration-300" :style="{ width: formatProgress(book.progress) + '%' }" />
              </div>
            </div>

            <!-- Info -->
            <div class="p-3">
              <h4 class="text-sm font-medium text-slate-800 line-clamp-2 leading-snug min-h-[2.5rem]">
                {{ book.title || '未知书名' }}
              </h4>
              <div class="mt-1 flex items-center gap-1 text-[11px] text-slate-400">
                <span class="truncate">{{ book.author || '未知作者' }}</span>
                <template v-if="book.progress > 0">
                  <span class="text-slate-200 shrink-0">·</span>
                  <span class="shrink-0">{{ formatProgress(book.progress) }}%</span>
                </template>
              </div>
              <div v-if="book.last_read_at" class="mt-0.5 text-[10px] text-slate-300">
                {{ formatTime(book.last_read_at) }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Reader overlay -->
    <EbookReader
      v-if="readerVisible && selectedBookId"
      :content-id="selectedBookId"
      @close="closeReader"
    />
  </div>
</template>
