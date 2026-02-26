<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { listEbooks, listAllAnnotations } from '@/api/ebook'
import { isExternalSource, getSourceConfig } from '@/config/external-sources'
import { formatTimeShort } from '@/utils/time'
import { colorOptions, colorMap } from '@/config/annotation-colors'
import AnnotationCard from '@/components/annotation-card.vue'

const router = useRouter()
const route = useRoute()

const loading = ref(true)
const books = ref([])
const sortBy = ref('updated_at')
const bookViewMode = ref('table')
const selectedBookId = ref('')

// ===== Annotations state =====
const annotations = ref([])
const annotationsTotalCount = ref(0)
const annotationsLoading = ref(false)
const annotationsLoadingMore = ref(false)
const annotationsPage = ref(1)
const annotationsPageSize = 20

const searchQuery = ref(route.query.q || '')
const filterContentId = ref(route.query.book || '')
const filterColor = ref(route.query.color || '')
const filterType = ref(route.query.type || '')
const annotationsSortBy = ref(route.query.sort || 'created_at')

let searchTimer = null



// Grid books: sorted per sortBy
const sortedBooks = computed(() => {
  const list = [...books.value]
  if (sortBy.value === 'updated_at') {
    return list
  } else if (sortBy.value === 'progress') {
    return list.sort((a, b) => (b.progress || 0) - (a.progress || 0))
  } else if (sortBy.value === 'title') {
    return list.sort((a, b) => (a.title || '').localeCompare(b.title || '', 'zh'))
  } else if (sortBy.value === 'annotation_count') {
    return list.sort((a, b) => (b.annotation_count || 0) - (a.annotation_count || 0))
  } else if (sortBy.value === 'last_read_at') {
    return list.sort((a, b) => {
      const ta = a.last_read_at || ''
      const tb = b.last_read_at || ''
      return tb.localeCompare(ta)
    })
  }
  return list
})

const selectedBookTitle = computed(() => {
  if (!selectedBookId.value) return ''
  const b = books.value.find(b => b.content_id === selectedBookId.value)
  return b ? b.title : ''
})

const hasMore = computed(() => annotations.value.length < annotationsTotalCount.value)

async function fetchBooks() {
  try {
    const res = await listEbooks({ page: 1, page_size: 100, sort_by: 'updated_at', sort_order: 'desc' })
    if (res.code === 0) books.value = res.data
  } catch (e) {
    console.error('Failed to fetch books:', e)
  }
}

function syncQueryParams() {
  const query = {}
  if (searchQuery.value) query.q = searchQuery.value
  if (filterContentId.value) query.book = filterContentId.value
  if (filterColor.value) query.color = filterColor.value
  if (filterType.value) query.type = filterType.value
  if (annotationsSortBy.value !== 'created_at') query.sort = annotationsSortBy.value
  router.replace({ query }).catch(() => {})
}

async function fetchAnnotations(append = false) {
  if (append) {
    annotationsLoadingMore.value = true
  } else {
    annotationsLoading.value = true
    annotationsPage.value = 1
  }

  try {
    const params = {
      page: annotationsPage.value,
      page_size: annotationsPageSize,
      sort_by: annotationsSortBy.value,
      sort_order: 'desc',
    }
    if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
    if (filterContentId.value) params.content_id = filterContentId.value
    if (filterColor.value) params.color = filterColor.value
    if (filterType.value) params.type = filterType.value

    const res = await listAllAnnotations(params)
    if (res.code === 0) {
      if (append) {
        annotations.value = [...annotations.value, ...res.data]
      } else {
        annotations.value = res.data
      }
      annotationsTotalCount.value = res.total
    }
  } catch (e) {
    console.error('Failed to fetch annotations:', e)
  } finally {
    annotationsLoading.value = false
    annotationsLoadingMore.value = false
  }
}

function loadMore() {
  if (annotationsLoadingMore.value) return
  annotationsPage.value++
  fetchAnnotations(true)
}

// Infinite scroll observer
const sentinelRef = ref(null)
let observer = null

function ensureObserver() {
  if (!observer) {
    observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && hasMore.value && !annotationsLoadingMore.value) {
        loadMore()
      }
    }, { rootMargin: '200px' })
  }
}

watch(sentinelRef, (el, oldEl) => {
  ensureObserver()
  if (oldEl) observer.unobserve(oldEl)
  if (el) observer.observe(el)
})

function goToBook(contentId) {
  router.push(`/ebook/${contentId}`)
}

function selectBook(book) {
  if (selectedBookId.value === book.content_id) {
    // Deselect: show all annotations
    selectedBookId.value = ''
    filterContentId.value = ''
  } else {
    // Select: filter annotations to this book
    selectedBookId.value = book.content_id
    filterContentId.value = book.content_id
  }
}

function clearFilters() {
  searchQuery.value = ''
  filterContentId.value = ''
  selectedBookId.value = ''
  filterColor.value = ''
  filterType.value = ''
}

function openBook(book) {
  const srcCfg = getSourceConfig(book.source)
  if (srcCfg && book.external_id) {
    window.open(srcCfg.deepLink(book.external_id), '_self')
    return
  }
  router.push(`/ebook/${book.content_id}`)
}

function formatProgress(p) {
  return Math.round((p || 0) * 100)
}

// Watchers
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    syncQueryParams()
    fetchAnnotations()
  }, 300)
})

watch([filterContentId, filterColor, filterType, annotationsSortBy], () => {
  syncQueryParams()
  fetchAnnotations()
})

onMounted(async () => {
  loading.value = true
  await fetchBooks()
  loading.value = false
  fetchAnnotations()
})

onUnmounted(() => {
  if (observer) observer.disconnect()
})
</script>

<template>
  <div class="flex flex-col h-full overflow-y-auto lg:overflow-hidden">
    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-24">
      <svg class="w-8 h-8 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
      </svg>
    </div>

    <template v-else>
      <div class="px-4 md:px-6 lg:px-8 py-5 w-full h-full lg:flex lg:gap-6">

        <!-- ===== Left Column: Books ===== -->
        <section v-if="books.length > 0" class="lg:w-[38%] lg:shrink-0 lg:overflow-y-auto lg:pr-2 mb-8 lg:mb-0">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-bold text-slate-900 tracking-tight">全部书籍</h3>
            <div class="flex items-center gap-2">
              <!-- View toggle -->
              <div class="flex items-center bg-slate-100 rounded-lg p-0.5">
                <button
                  @click="bookViewMode = 'grid'"
                  :class="['p-1.5 rounded-md transition-all', bookViewMode === 'grid' ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-400 hover:text-slate-600']"
                  title="网格视图"
                >
                  <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
                  </svg>
                </button>
                <button
                  @click="bookViewMode = 'table'"
                  :class="['p-1.5 rounded-md transition-all', bookViewMode === 'table' ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-400 hover:text-slate-600']"
                  title="表格视图"
                >
                  <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
                  </svg>
                </button>
              </div>
              <!-- Sort -->
              <select
                v-model="sortBy"
                class="text-xs text-slate-500 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none cursor-pointer transition-all"
              >
                <option value="updated_at">最近更新</option>
                <option value="last_read_at">阅读时间</option>
                <option value="annotation_count">标注数量</option>
                <option value="progress">阅读进度</option>
                <option value="title">书名</option>
              </select>
            </div>
          </div>

          <!-- Grid View -->
          <div v-if="bookViewMode === 'grid'" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3 gap-4">
            <div
              v-for="book in sortedBooks"
              :key="book.content_id"
              class="group relative bg-white rounded-xl border overflow-hidden cursor-pointer transition-all duration-200 hover:shadow-md"
              :class="selectedBookId === book.content_id ? 'border-indigo-400 ring-2 ring-indigo-100 shadow-md' : 'border-slate-200/60 hover:border-indigo-300'"
              @click="selectBook(book)"
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

                <!-- Selected check -->
                <div v-if="selectedBookId === book.content_id" class="absolute top-2 right-2 w-6 h-6 bg-indigo-500 rounded-full flex items-center justify-center shadow-lg z-10">
                  <svg class="w-3.5 h-3.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
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
                  <template v-if="book.annotation_count > 0">
                    <span class="shrink-0 font-medium text-amber-500/80">{{ book.annotation_count }} 标注</span>
                    <span class="text-slate-200 shrink-0">·</span>
                  </template>
                  <template v-else-if="book.progress > 0">
                    <span class="shrink-0 font-medium text-indigo-500/80">{{ formatProgress(book.progress) }}%</span>
                    <span class="text-slate-200 shrink-0">·</span>
                  </template>
                  <span v-if="book.last_read_at" class="truncate">{{ formatTimeShort(book.last_read_at) }}</span>
                  <span v-else class="truncate">{{ book.author || '未知作者' }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Table View -->
          <div v-else class="bg-white rounded-xl border border-slate-200/60 overflow-hidden shadow-sm">
            <div
              v-for="book in sortedBooks"
              :key="book.content_id"
              class="flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-all duration-150 hover:bg-slate-50 border-b border-slate-100 last:border-b-0"
              :class="selectedBookId === book.content_id ? 'bg-indigo-50/60 hover:bg-indigo-50' : ''"
              @click="selectBook(book)"
            >
              <!-- Mini cover -->
              <div class="w-9 h-12 shrink-0 rounded-md overflow-hidden bg-gradient-to-br from-slate-100 to-slate-200 border border-slate-200/60">
                <img
                  v-if="book.cover_url"
                  :src="book.cover_url"
                  :alt="book.title"
                  class="w-full h-full object-cover"
                  loading="lazy"
                />
                <div v-else class="w-full h-full flex items-center justify-center">
                  <svg class="w-4 h-4 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
                  </svg>
                </div>
              </div>
              <!-- Info -->
              <div class="flex-1 min-w-0">
                <h4 class="text-sm font-medium text-slate-800 truncate">{{ book.title || '未知书名' }}</h4>
                <div class="flex items-center gap-1.5 mt-0.5 text-xs text-slate-400">
                  <span class="truncate">{{ book.author || '未知作者' }}</span>
                </div>
              </div>
              <!-- Stats -->
              <div class="shrink-0 flex items-center gap-3 text-[11px] text-slate-400">
                <span v-if="book.annotation_count > 0" class="text-amber-500/80 font-medium tabular-nums">{{ book.annotation_count }} 标注</span>
                <span v-if="book.progress > 0" class="text-indigo-500/80 font-medium tabular-nums">{{ formatProgress(book.progress) }}%</span>
                <span v-if="book.last_read_at" class="tabular-nums hidden sm:inline">{{ formatTimeShort(book.last_read_at) }}</span>
              </div>
              <!-- Selected indicator -->
              <div v-if="selectedBookId === book.content_id" class="w-5 h-5 bg-indigo-500 rounded-full flex items-center justify-center shrink-0">
                <svg class="w-3 h-3 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                  <path d="M20 6 9 17l-5-5" />
                </svg>
              </div>
            </div>
          </div>
        </section>

        <!-- ===== Right Column: Annotations ===== -->
        <section class="lg:flex-1 lg:min-w-0 lg:overflow-y-auto">
          <!-- Header -->
          <div class="flex items-center gap-2 mb-3">
            <h3 class="text-base font-bold text-slate-900 tracking-tight">
              <template v-if="selectedBookId">{{ selectedBookTitle }}</template>
              <template v-else>全部标注</template>
            </h3>
            <span class="text-xs text-slate-400 tabular-nums">{{ annotationsTotalCount }} 条</span>
            <button
              v-if="selectedBookId"
              @click="selectedBookId = ''; filterContentId = ''"
              class="text-xs text-indigo-500 hover:text-indigo-700 transition-colors"
            >
              查看全部
            </button>
            <div class="flex-1" />
            <select
              v-model="annotationsSortBy"
              class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none cursor-pointer transition-all"
            >
              <option value="created_at">创建时间</option>
              <option value="updated_at">更新时间</option>
            </select>
          </div>

          <!-- Search & Filters -->
          <div class="bg-white rounded-2xl border border-slate-200/60 shadow-sm overflow-hidden">
            <div class="px-4 pt-3 pb-2.5 space-y-2 border-b border-slate-100">
              <!-- Search -->
              <div class="relative">
                <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
                </svg>
                <input
                  v-model="searchQuery"
                  placeholder="搜索标注内容或笔记..."
                  class="w-full bg-slate-50 rounded-lg pl-8 pr-3 py-1.5 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 focus:bg-white transition-all"
                />
              </div>

              <!-- Filters row -->
              <div class="flex items-center gap-2 flex-wrap pb-0.5">
                <!-- Book filter -->
                <select
                  v-model="filterContentId"
                  class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 outline-none cursor-pointer transition-all focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 max-w-[160px]"
                >
                  <option value="">全部书籍</option>
                  <option v-for="b in books" :key="b.content_id" :value="b.content_id">{{ b.title }}</option>
                </select>

                <!-- Color chips -->
                <div class="flex items-center gap-1.5">
                  <button
                    v-for="c in colorOptions"
                    :key="c"
                    @click="filterColor = filterColor === c ? '' : c"
                    class="rounded-full transition-all duration-150"
                    :class="[
                      colorMap[c],
                      filterColor === c ? 'ring-2 ring-offset-1 ring-slate-400 scale-110' : 'opacity-40 hover:opacity-80',
                    ]"
                    :style="{ width: '16px', height: '16px' }"
                  />
                </div>

                <!-- Type filter -->
                <select
                  v-model="filterType"
                  class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 outline-none cursor-pointer transition-all focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400"
                >
                  <option value="">全部类型</option>
                  <option value="highlight">划线</option>
                  <option value="note">笔记</option>
                </select>

                <button
                  v-if="searchQuery || filterContentId || filterColor || filterType"
                  @click="clearFilters"
                  class="text-[11px] text-slate-400 hover:text-slate-600 transition-colors ml-auto"
                >
                  清除筛选
                </button>
              </div>
            </div>

            <!-- Annotations content -->
            <div class="px-4 py-4">
              <!-- Loading -->
              <div v-if="annotationsLoading" class="flex items-center justify-center py-16">
                <svg class="w-8 h-8 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
              </div>

              <!-- Empty -->
              <div v-else-if="annotations.length === 0" class="text-center py-16">
                <div class="w-14 h-14 mx-auto mb-3 bg-slate-100 rounded-2xl flex items-center justify-center">
                  <svg class="w-7 h-7 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                  </svg>
                </div>
                <p class="text-sm text-slate-500 font-medium mb-1">暂无标注</p>
                <p class="text-xs text-slate-400">在书籍详情页中添加标注</p>
              </div>

              <!-- List -->
              <template v-else>
                <div class="divide-y divide-slate-100">
                  <AnnotationCard
                    v-for="ann in annotations"
                    :key="ann.id"
                    :annotation="ann"
                    :show-book-info="true"
                    :editable="false"
                    @click-book="goToBook"
                  />
                </div>

                <!-- Infinite scroll sentinel -->
                <div ref="sentinelRef" class="flex justify-center py-4">
                  <svg v-if="annotationsLoadingMore" class="w-5 h-5 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                  </svg>
                </div>
              </template>
            </div>
          </div>
        </section>

      </div>
    </template>

  </div>
</template>
