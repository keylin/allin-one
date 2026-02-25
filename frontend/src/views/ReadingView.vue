<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listEbooks, listRecentAnnotations, listAnnotations } from '@/api/ebook'
import { isExternalSource, getSourceConfig } from '@/config/external-sources'
import { formatTimeShort } from '@/utils/time'

const router = useRouter()

const loading = ref(true)
const books = ref([])
const recentAnnotations = ref([])
const sortBy = ref('updated_at')

// Annotation detail modal
const annotationBook = ref(null)
const bookAnnotations = ref([])
const loadingAnnotations = ref(false)

// Hero: last read book (has progress > 0 and last_read_at)
const lastReadBook = computed(() => {
  return books.value.find(b => b.progress > 0 && b.last_read_at)
})

// Grid books: sorted per sortBy
const sortedBooks = computed(() => {
  const list = [...books.value]
  if (sortBy.value === 'updated_at') {
    // already default from API
    return list
  } else if (sortBy.value === 'progress') {
    return list.sort((a, b) => (b.progress || 0) - (a.progress || 0))
  } else if (sortBy.value === 'title') {
    return list.sort((a, b) => (a.title || '').localeCompare(b.title || '', 'zh'))
  }
  return list
})

async function fetchBooks() {
  try {
    const res = await listEbooks({ page: 1, page_size: 100, sort_by: 'updated_at', sort_order: 'desc' })
    if (res.code === 0) books.value = res.data
  } catch (e) {
    console.error('Failed to fetch books:', e)
  }
}

async function fetchAnnotationsData() {
  try {
    const res = await listRecentAnnotations(10)
    if (res.code === 0) recentAnnotations.value = res.data
  } catch (e) {
    console.error('Failed to fetch annotations:', e)
  }
}

function openBook(book) {
  // External source: open in native app
  const srcCfg = getSourceConfig(book.source)
  if (srcCfg && book.external_id) {
    window.open(srcCfg.deepLink(book.external_id), '_self')
    return
  }
  // Show annotations for this book
  showBookAnnotations(book)
}

async function showBookAnnotations(book) {
  annotationBook.value = book
  loadingAnnotations.value = true
  bookAnnotations.value = []
  try {
    const res = await listAnnotations(book.content_id)
    if (res.code === 0) bookAnnotations.value = res.data
  } catch (e) {
    console.error('Failed to fetch book annotations:', e)
  } finally {
    loadingAnnotations.value = false
  }
}

function closeAnnotations() {
  annotationBook.value = null
  bookAnnotations.value = []
}

function formatProgress(p) {
  return Math.round((p || 0) * 100)
}

const colorMap = {
  yellow: 'bg-amber-400',
  green: 'bg-emerald-400',
  blue: 'bg-blue-400',
  pink: 'bg-pink-400',
  purple: 'bg-violet-400',
}

function annotationColor(color) {
  return colorMap[color] || 'bg-amber-400'
}

onMounted(async () => {
  loading.value = true
  await Promise.all([fetchBooks(), fetchAnnotationsData()])
  loading.value = false
})
</script>

<template>
  <div class="flex flex-col h-full overflow-y-auto">
    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-24">
      <svg class="w-8 h-8 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
      </svg>
    </div>

    <template v-else>
      <div class="px-4 md:px-6 lg:px-8 py-5 space-y-8 max-w-6xl mx-auto w-full">

        <!-- ===== Section A: 最近在读 Hero ===== -->
        <section v-if="lastReadBook" class="bg-white rounded-2xl border border-slate-200/60 overflow-hidden shadow-sm">
          <div class="flex flex-col sm:flex-row">
            <!-- Cover -->
            <div
              class="sm:w-40 md:w-48 shrink-0 aspect-[2/3] sm:aspect-auto bg-gradient-to-br from-slate-100 to-slate-200 relative cursor-pointer"
              @click="openBook(lastReadBook)"
            >
              <img
                v-if="lastReadBook.cover_url"
                :src="lastReadBook.cover_url"
                :alt="lastReadBook.title"
                class="absolute inset-0 w-full h-full object-cover"
              />
              <div v-else class="absolute inset-0 flex items-center justify-center p-4">
                <svg class="w-12 h-12 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
                </svg>
              </div>
            </div>
            <!-- Info -->
            <div class="flex-1 p-5 sm:p-6 flex flex-col justify-center gap-3">
              <div>
                <p class="text-xs font-medium text-indigo-500 uppercase tracking-wider mb-1.5">最近在读</p>
                <h2 class="text-lg sm:text-xl font-bold text-slate-900 tracking-tight leading-snug line-clamp-2">
                  {{ lastReadBook.title }}
                </h2>
                <p v-if="lastReadBook.author" class="text-sm text-slate-500 mt-1">{{ lastReadBook.author }}</p>
              </div>
              <!-- Progress -->
              <div class="space-y-1.5">
                <div class="flex items-center gap-3">
                  <div class="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      class="h-full bg-indigo-500 rounded-full transition-all"
                      :style="{ width: formatProgress(lastReadBook.progress) + '%' }"
                    />
                  </div>
                  <span class="text-sm font-semibold text-slate-700 tabular-nums">{{ formatProgress(lastReadBook.progress) }}%</span>
                </div>
                <div class="flex items-center gap-2 text-xs text-slate-400">
                  <span v-if="lastReadBook.section_title">{{ lastReadBook.section_title }}</span>
                  <span v-if="lastReadBook.section_title && lastReadBook.last_read_at" class="text-slate-200">·</span>
                  <span v-if="lastReadBook.last_read_at">{{ formatTimeShort(lastReadBook.last_read_at) }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Empty hero: no books with progress -->
        <section v-else class="bg-white rounded-2xl border border-slate-200/60 p-8 sm:p-12 text-center shadow-sm">
          <div class="w-16 h-16 mx-auto mb-4 bg-slate-100 rounded-2xl flex items-center justify-center">
            <svg class="w-8 h-8 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
            </svg>
          </div>
          <p class="text-base font-medium text-slate-700 mb-1">还没有阅读记录</p>
          <p class="text-sm text-slate-400 mb-5">同步书籍后即可在这里查看阅读进度</p>
          <button
            @click="router.push('/ebook')"
            class="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-xl hover:bg-indigo-100 transition-colors"
          >
            前往图书管理
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>
        </section>

        <!-- ===== Section B: All Books Grid ===== -->
        <section v-if="books.length > 0">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-bold text-slate-900 tracking-tight">全部书籍</h3>
            <select
              v-model="sortBy"
              class="text-xs text-slate-500 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none cursor-pointer transition-all"
            >
              <option value="updated_at">最近阅读</option>
              <option value="progress">阅读进度</option>
              <option value="title">书名</option>
            </select>
          </div>

          <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            <div
              v-for="book in sortedBooks"
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
                      <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                    </svg>
                  </div>
                </div>

                <!-- External source badge -->
                <span v-if="isExternalSource(book.source)" class="absolute top-2 left-2 px-1.5 py-0.5 text-[10px] font-medium bg-slate-800/70 text-white rounded flex items-center gap-0.5">
                  <svg v-if="book.source === 'apple_books'" class="w-2.5 h-2.5" viewBox="0 0 24 24" fill="currentColor"><path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.8-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/></svg>
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
                  <template v-if="book.progress > 0">
                    <span class="shrink-0 font-medium text-indigo-500/80">{{ formatProgress(book.progress) }}%</span>
                    <span class="text-slate-200 shrink-0">·</span>
                  </template>
                  <span v-if="book.last_read_at" class="truncate">{{ formatTimeShort(book.last_read_at) }}</span>
                  <span v-else class="truncate">{{ book.author || '未知作者' }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- ===== Section C: Recent Annotations ===== -->
        <section v-if="recentAnnotations.length > 0">
          <h3 class="text-base font-bold text-slate-900 tracking-tight mb-4">最近标注</h3>
          <div class="bg-white rounded-2xl border border-slate-200/60 divide-y divide-slate-100 overflow-hidden shadow-sm">
            <div
              v-for="ann in recentAnnotations"
              :key="ann.id"
              class="flex gap-3 px-4 py-3.5 hover:bg-slate-50/80 cursor-pointer transition-colors"
              @click="showBookAnnotations({ content_id: ann.content_id, title: ann.book_title, author: ann.book_author, cover_url: ann.cover_url })"
            >
              <!-- Color bar -->
              <div class="w-1 shrink-0 rounded-full self-stretch" :class="annotationColor(ann.color)" />
              <!-- Content -->
              <div class="flex-1 min-w-0">
                <p class="text-xs text-slate-400 mb-1 truncate">
                  {{ ann.book_title }}
                  <span v-if="ann.book_author" class="text-slate-300">· {{ ann.book_author }}</span>
                </p>
                <p v-if="ann.selected_text" class="text-sm text-slate-700 leading-relaxed line-clamp-3">
                  {{ ann.selected_text }}
                </p>
                <p v-if="ann.note" class="text-xs text-slate-500 mt-1 line-clamp-1 italic">
                  {{ ann.note }}
                </p>
                <p class="text-[10px] text-slate-300 mt-1.5">{{ formatTimeShort(ann.created_at) }}</p>
              </div>
            </div>
          </div>
        </section>

      </div>
    </template>

    <!-- Annotations detail modal -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition-opacity duration-150"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-opacity duration-100"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div v-if="annotationBook" class="fixed inset-0 z-50 flex items-end sm:items-center justify-center" @click.self="closeAnnotations">
          <div class="absolute inset-0 bg-black/30" @click="closeAnnotations" />
          <div class="relative z-10 bg-white rounded-t-2xl sm:rounded-2xl w-full sm:w-[28rem] shadow-2xl overflow-hidden pb-safe max-h-[80vh] flex flex-col">
            <!-- Header -->
            <div class="px-5 pt-5 pb-3 border-b border-slate-100 shrink-0">
              <h3 class="text-lg font-bold text-slate-900 leading-snug line-clamp-2">{{ annotationBook.title }}</h3>
              <p v-if="annotationBook.author" class="text-sm text-slate-500 mt-0.5">{{ annotationBook.author }}</p>
            </div>
            <!-- Content -->
            <div class="flex-1 overflow-y-auto">
              <div v-if="loadingAnnotations" class="flex items-center justify-center py-12">
                <svg class="w-6 h-6 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
              </div>
              <div v-else-if="bookAnnotations.length === 0" class="text-center py-12">
                <p class="text-sm text-slate-400">暂无标注</p>
              </div>
              <div v-else class="divide-y divide-slate-100">
                <div
                  v-for="ann in bookAnnotations"
                  :key="ann.id"
                  class="flex gap-3 px-5 py-3.5"
                >
                  <div class="w-1 shrink-0 rounded-full self-stretch" :class="annotationColor(ann.color)" />
                  <div class="flex-1 min-w-0">
                    <p v-if="ann.selected_text" class="text-sm text-slate-700 leading-relaxed">
                      {{ ann.selected_text }}
                    </p>
                    <p v-if="ann.note" class="text-xs text-slate-500 mt-1.5 italic">
                      {{ ann.note }}
                    </p>
                    <p class="text-[10px] text-slate-300 mt-1.5">{{ formatTimeShort(ann.created_at) }}</p>
                  </div>
                </div>
              </div>
            </div>
            <!-- Close -->
            <button
              @click="closeAnnotations"
              class="w-full py-3 text-sm text-slate-500 font-medium border-t border-slate-100 hover:bg-slate-50 active:bg-slate-100 shrink-0"
            >
              关闭
            </button>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
