<script setup>
import { ref, watch, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listAllAnnotations, listEbooks } from '@/api/ebook'
import { colorOptions, colorMap } from '@/config/annotation-colors'
import { formatTimeShort } from '@/utils/time'
import AnnotationCard from '@/components/annotation-card.vue'

const route = useRoute()
const router = useRouter()

// State
const annotations = ref([])
const totalCount = ref(0)
const loading = ref(false)
const loadingMore = ref(false)
const page = ref(1)
const pageSize = 20

// Books for filter dropdown
const books = ref([])

// Filters (from URL query)
const searchQuery = ref(route.query.q || '')
const filterContentId = ref(route.query.book || '')
const filterColor = ref(route.query.color || '')
const filterType = ref(route.query.type || '')
const sortBy = ref(route.query.sort || 'created_at')

let searchTimer = null

// Sync URL
function syncQueryParams() {
  const query = {}
  if (searchQuery.value) query.q = searchQuery.value
  if (filterContentId.value) query.book = filterContentId.value
  if (filterColor.value) query.color = filterColor.value
  if (filterType.value) query.type = filterType.value
  if (sortBy.value !== 'created_at') query.sort = sortBy.value
  router.replace({ query }).catch(() => {})
}

async function fetchAnnotations(append = false) {
  if (append) {
    loadingMore.value = true
  } else {
    loading.value = true
    page.value = 1
  }

  try {
    const params = {
      page: page.value,
      page_size: pageSize,
      sort_by: sortBy.value,
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
      totalCount.value = res.total
    }
  } catch (e) {
    console.error('Failed to fetch annotations:', e)
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

async function fetchBooks() {
  try {
    const res = await listEbooks({ page: 1, page_size: 200 })
    if (res.code === 0) books.value = res.data
  } catch (e) {
    // ignore
  }
}

function loadMore() {
  page.value++
  fetchAnnotations(true)
}

const hasMore = computed(() => annotations.value.length < totalCount.value)

function goToBook(contentId) {
  router.push(`/ebook/${contentId}`)
}

function clearFilters() {
  searchQuery.value = ''
  filterContentId.value = ''
  filterColor.value = ''
  filterType.value = ''
}

// Watchers
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    syncQueryParams()
    fetchAnnotations()
  }, 300)
})

watch([filterContentId, filterColor, filterType, sortBy], () => {
  syncQueryParams()
  fetchAnnotations()
})

onMounted(() => {
  fetchAnnotations()
  fetchBooks()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Header -->
    <div class="px-4 pt-3 pb-2.5 space-y-2 sticky top-0 bg-white/95 backdrop-blur-sm z-10 border-b border-slate-100 shrink-0">
      <div class="flex items-center gap-2">
        <h1 class="text-base font-bold text-slate-900 tracking-tight">全部标注</h1>
        <span class="text-xs text-slate-400 tabular-nums">{{ totalCount }} 条</span>
        <div class="flex-1" />
        <select
          v-model="sortBy"
          class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none cursor-pointer transition-all"
        >
          <option value="created_at">创建时间</option>
          <option value="updated_at">更新时间</option>
        </select>
      </div>

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

    <!-- Content -->
    <div class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">
        <!-- Loading -->
        <div v-if="loading" class="flex items-center justify-center py-24">
          <svg class="w-8 h-8 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
        </div>

        <!-- Empty -->
        <div v-else-if="annotations.length === 0" class="text-center py-24">
          <div class="w-16 h-16 mx-auto mb-4 bg-slate-100 rounded-2xl flex items-center justify-center">
            <svg class="w-8 h-8 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
            </svg>
          </div>
          <p class="text-sm text-slate-500 font-medium mb-1">暂无标注</p>
          <p class="text-xs text-slate-400">在书籍详情页中添加标注</p>
        </div>

        <!-- List -->
        <div v-else class="bg-white rounded-xl border border-slate-200/60 divide-y divide-slate-100 overflow-hidden shadow-sm">
          <AnnotationCard
            v-for="ann in annotations"
            :key="ann.id"
            :annotation="ann"
            :show-book-info="true"
            :editable="false"
            @click-book="goToBook"
          />
        </div>

        <!-- Load more -->
        <div v-if="!loading && hasMore" class="flex justify-center pt-4 pb-2">
          <button
            @click="loadMore"
            :disabled="loadingMore"
            class="px-6 py-2 text-sm font-medium text-slate-500 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 hover:border-slate-300 disabled:opacity-50 transition-all"
          >
            <template v-if="loadingMore">
              <svg class="w-4 h-4 animate-spin inline mr-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
              加载中...
            </template>
            <template v-else>加载更多</template>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
