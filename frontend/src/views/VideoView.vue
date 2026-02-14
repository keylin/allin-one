<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { formatTimeShort } from '@/utils/time'
import { downloadVideo, listDownloads, deleteVideo } from '@/api/video'
import { incrementView, toggleFavorite } from '@/api/content'
import { listSources } from '@/api/sources'
import ConfirmDialog from '@/components/confirm-dialog.vue'
import VideoPlayer from '@/components/video-player.vue'
import { useToast } from '@/composables/useToast'
import { useScrollLock } from '@/composables/useScrollLock'

const route = useRoute()
const router = useRouter()
const toast = useToast()

// --- 下载表单 ---
const videoUrl = ref('')
const submitting = ref(false)
const showDownloadForm = ref(false)

// --- 数据 & 加载 ---
const downloads = ref([])
const loading = ref(true)
const loadingMore = ref(false)
const totalCount = ref(0)
const platforms = ref([])
const sentinelRef = ref(null)
let observer = null

// --- 筛选 & 排序 (从 URL 恢复) ---
const filterStatus = ref(route.query.status ?? 'completed')
const filterPlatform = ref(route.query.platform || '')
const filterSourceId = ref(route.query.source_id || '')
const searchQuery = ref(route.query.q || '')
const sources = ref([])
const sortBy = ref(route.query.sort_by || 'published_at')
const sortOrder = ref(route.query.sort_order || 'desc')
const currentPage = ref(1)
const pageSize = 18

// --- 播放器覆盖层 ---
const playerVisible = ref(false)
const selectedId = ref(null)
const videoPlayerRef = ref(null)

useScrollLock(playerVisible)

// --- 删除 ---
const showDeleteDialog = ref(false)
const deletingVideo = ref(null)

// --- 横竖屏检测 ---
const detectedOrientations = ref({})

function isPortrait(d) {
  const w = d.video_info?.width
  const h = d.video_info?.height
  if (w && h) return h > w
  return detectedOrientations.value[d.id] === 'portrait'
}

function onThumbnailLoad(event, videoId) {
  const img = event.target
  if (img.naturalHeight > img.naturalWidth) {
    detectedOrientations.value[videoId] = 'portrait'
  }
}

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'completed', label: '已完成' },
  { value: 'running', label: '下载中' },
  { value: 'pending', label: '等待中' },
  { value: 'failed', label: '失败' },
]

const sortOptions = [
  { value: 'published_at:desc', label: '最新发布' },
  { value: 'collected_at:desc', label: '最新采集' },
  { value: 'duration:desc', label: '时长最长' },
]

const currentSort = computed({
  get: () => `${sortBy.value}:${sortOrder.value}`,
  set: (val) => {
    const [field, order] = val.split(':')
    sortBy.value = field
    sortOrder.value = order
  },
})

const hasMore = computed(() => downloads.value.length < totalCount.value)

const selectedVideo = computed(() => {
  if (!selectedId.value) return null
  return downloads.value.find(d => d.id === selectedId.value) || null
})

const statusStyles = {
  pending: 'bg-slate-100 text-slate-600',
  running: 'bg-indigo-50 text-indigo-700',
  completed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
}

const statusLabels = {
  pending: '等待中',
  running: '下载中',
  completed: '已完成',
  failed: '失败',
}

// --- 数据获取 ---
let searchTimer = null
async function fetchDownloads(append = false) {
  if (append) {
    loadingMore.value = true
    currentPage.value++
  } else {
    loading.value = true
    currentPage.value = 1
    downloads.value = []
  }
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
    }
    params.status = filterStatus.value
    if (filterPlatform.value) params.platform = filterPlatform.value
    if (filterSourceId.value) params.source_id = filterSourceId.value
    if (searchQuery.value.trim()) params.search = searchQuery.value.trim()

    const res = await listDownloads(params)
    if (res.code === 0) {
      if (append) {
        downloads.value.push(...res.data)
      } else {
        downloads.value = res.data
      }
      totalCount.value = res.total
      if (res.platforms) platforms.value = res.platforms
    }
  } finally {
    if (append) {
      loadingMore.value = false
    } else {
      loading.value = false
    }
  }
}

function syncQueryParams() {
  const query = {}
  if (filterStatus.value !== 'completed') query.status = filterStatus.value
  if (filterPlatform.value) query.platform = filterPlatform.value
  if (filterSourceId.value) query.source_id = filterSourceId.value
  if (searchQuery.value) query.q = searchQuery.value
  if (sortBy.value !== 'published_at') query.sort_by = sortBy.value
  if (sortOrder.value !== 'desc') query.sort_order = sortOrder.value
  router.replace({ query }).catch(() => {})
}

watch([filterStatus, filterPlatform, filterSourceId, sortBy, sortOrder], () => {
  syncQueryParams()
  fetchDownloads()
})

watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    syncQueryParams()
    fetchDownloads()
  }, 300)
})

// --- 下载提交 ---
async function handleSubmit() {
  if (!videoUrl.value.trim()) return
  submitting.value = true
  try {
    const res = await downloadVideo(videoUrl.value)
    if (res.code === 0) {
      toast.success('视频下载任务已提交')
      videoUrl.value = ''
      showDownloadForm.value = false
      await fetchDownloads()
    } else {
      toast.error(res.message || '提交失败')
    }
  } catch {
    toast.error('提交下载任务失败')
  } finally {
    submitting.value = false
  }
}

// --- 选中视频 ---
function selectVideo(download) {
  if (selectedId.value === download.id && playerVisible.value) return
  if (videoPlayerRef.value) videoPlayerRef.value.destroy()
  selectedId.value = download.id
  playerVisible.value = true
  if (download.status === 'completed' && download.content_id) {
    incrementView(download.content_id).catch(() => {})
  }
}

function closePlayer() {
  if (videoPlayerRef.value) videoPlayerRef.value.destroy()
  playerVisible.value = false
}

// --- 收藏 ---
async function handleFavorite(d, event) {
  if (event) event.stopPropagation()
  if (!d.content_id) return
  const res = await toggleFavorite(d.content_id)
  if (res.code === 0) {
    d.is_favorited = res.data.is_favorited
  }
}

// --- 删除 ---
function openDelete(d, event) {
  if (event) event.stopPropagation()
  deletingVideo.value = d
  showDeleteDialog.value = true
}

async function handleDelete() {
  showDeleteDialog.value = false
  if (!deletingVideo.value?.content_id) return
  try {
    const res = await deleteVideo(deletingVideo.value.content_id)
    if (res.code === 0) {
      toast.success('视频已删除')
      if (selectedId.value === deletingVideo.value.id) {
        closePlayer()
        selectedId.value = null
      }
      await fetchDownloads()
    } else {
      toast.error(res.message || '删除失败')
    }
  } catch {
    toast.error('删除请求失败')
  }
}

// --- 键盘 ---
function onKeydown(e) {
  if (e.key === 'Escape' && playerVisible.value) {
    closePlayer()
  }
}

// --- IntersectionObserver 无限滚动 ---
// 通过 watch sentinelRef 自动在元素出现/消失时挂载/卸载 observer
watch(sentinelRef, (el) => {
  if (observer) { observer.disconnect(); observer = null }
  if (el) {
    observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && hasMore.value && !loadingMore.value && !loading.value) {
        fetchDownloads(true)
      }
    }, { rootMargin: '200px' })
    observer.observe(el)
  }
})

// --- 工具函数 ---
function formatDuration(seconds) {
  if (!seconds) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatTime(t) {
  return formatTimeShort(t)
}

onMounted(async () => {
  fetchDownloads()
  try {
    const res = await listSources({ page_size: 100 })
    if (res.code === 0) sources.value = res.data
  } catch { /* ignore */ }
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  if (videoPlayerRef.value) videoPlayerRef.value.destroy()
  clearTimeout(searchTimer)
  document.removeEventListener('keydown', onKeydown)
  if (observer) observer.disconnect()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Sticky header -->
    <div class="px-4 pt-3 pb-2 space-y-2.5 sticky top-0 bg-white z-10 border-b border-slate-100 shrink-0">
      <!-- 标题栏 -->
      <div class="flex items-center justify-between">
        <p class="text-xs text-slate-400">{{ totalCount }} 个视频</p>
        <button
          class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-all duration-200 shadow-sm"
          @click="showDownloadForm = !showDownloadForm"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          下载视频
        </button>
      </div>

      <!-- 筛选栏 -->
      <div class="flex flex-wrap items-center gap-3">
        <!-- 搜索 -->
        <div class="relative flex-1 min-w-[200px] max-w-sm">
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索视频标题..."
            class="w-full bg-white rounded-lg pl-9 pr-3 py-2 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 transition-all"
          />
        </div>

        <!-- 状态 pills -->
        <div class="flex items-center gap-1">
          <button
            v-for="opt in statusOptions"
            :key="opt.value"
            class="px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200"
            :class="filterStatus === opt.value
              ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
              : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'"
            @click="filterStatus = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>

        <!-- 平台 -->
        <select
          v-if="platforms.length > 0"
          v-model="filterPlatform"
          class="px-3 py-1.5 text-xs font-medium bg-white border border-slate-200 rounded-lg text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all"
        >
          <option value="">全部平台</option>
          <option v-for="p in platforms" :key="p" :value="p" class="capitalize">{{ p }}</option>
        </select>

        <!-- 来源 -->
        <select
          v-if="sources.length > 0"
          v-model="filterSourceId"
          class="px-3 py-1.5 text-xs font-medium bg-white border border-slate-200 rounded-lg text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all"
        >
          <option value="">全部来源</option>
          <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>

        <!-- 排序 -->
        <div class="flex items-center gap-1 ml-auto">
          <button
            v-for="opt in sortOptions"
            :key="opt.value"
            class="px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200"
            :class="currentSort === opt.value
              ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
              : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'"
            @click="currentSort = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>
    </div>

    <!-- Scrollable content -->
    <div class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">

    <!-- 下载表单（可折叠） -->
    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 -translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 -translate-y-2"
    >
      <div v-if="showDownloadForm" class="mb-5 bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
        <form class="flex items-center gap-3" @submit.prevent="handleSubmit">
          <input
            v-model="videoUrl"
            type="text"
            placeholder="输入视频 URL（B站 / YouTube / 其他平台）"
            class="flex-1 px-3.5 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-700 placeholder-slate-400 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 focus:bg-white outline-none transition-all duration-200"
          />
          <button
            type="submit"
            class="px-5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-all duration-200 shrink-0"
            :disabled="submitting || !videoUrl.trim()"
          >
            <span class="flex items-center gap-1.5">
              <svg v-if="submitting" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
              {{ submitting ? '提交中...' : '开始下载' }}
            </span>
          </button>
          <button
            type="button"
            class="p-2 text-slate-400 hover:text-slate-600 transition-colors"
            @click="showDownloadForm = false"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </form>
      </div>
    </Transition>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-24">
      <svg class="w-8 h-8 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <!-- Empty -->
    <div v-else-if="downloads.length === 0" class="text-center py-24">
      <div class="w-16 h-16 mx-auto mb-4 bg-slate-100 rounded-2xl flex items-center justify-center">
        <svg class="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      </div>
      <p class="text-sm text-slate-500 font-medium mb-1">暂无视频</p>
      <p class="text-xs text-slate-400 mb-5">点击上方「下载视频」按钮开始添加</p>
      <button
        class="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
        @click="showDownloadForm = true"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
        </svg>
        下载第一个视频
      </button>
    </div>

    <!-- 海报墙网格 -->
    <template v-else>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
        <div
          v-for="d in downloads"
          :key="d.id"
          class="group relative bg-white rounded-xl border overflow-hidden cursor-pointer transition-all duration-200"
          :class="[
            selectedId === d.id && playerVisible
              ? 'border-indigo-400 ring-1 ring-indigo-400/30 shadow-md'
              : 'border-slate-200/60 hover:border-indigo-300 hover:shadow-md',
            { 'opacity-60': d.status !== 'completed' }
          ]"
          @click="selectVideo(d)"
        >
          <!-- 封面 -->
          <div class="aspect-video bg-gradient-to-br from-slate-800 to-slate-900 relative overflow-hidden">
            <img
              v-if="d.content_id && d.video_info?.has_thumbnail"
              :src="`/api/video/${d.content_id}/thumbnail`"
              class="absolute inset-0 w-full h-full"
              :class="isPortrait(d) ? 'object-contain' : 'object-cover'"
              loading="lazy"
              @load="onThumbnailLoad($event, d.id)"
              @error="$event.target.style.display='none'"
            />
            <div v-else class="absolute inset-0 flex items-center justify-center">
              <svg class="w-10 h-10 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </div>

            <!-- 悬浮播放按钮 -->
            <div
              v-if="d.status === 'completed'"
              class="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-all duration-300 flex items-center justify-center"
            >
              <div class="w-12 h-12 bg-white/95 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transform scale-75 group-hover:scale-100 transition-all duration-300 shadow-xl">
                <svg class="w-5 h-5 text-indigo-600 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M8 5v14l11-7z" />
                </svg>
              </div>
            </div>

            <!-- 状态标签 -->
            <span
              v-if="d.status !== 'completed'"
              class="absolute top-2 left-2 px-2 py-0.5 text-xs font-medium rounded-md shadow-sm"
              :class="statusStyles[d.status] || 'bg-slate-100 text-slate-600'"
            >
              {{ statusLabels[d.status] || d.status }}
            </span>

            <!-- 时长角标 -->
            <span
              v-if="d.video_info?.duration"
              class="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 text-[10px] font-medium bg-black/70 text-white rounded"
            >
              {{ formatDuration(d.video_info.duration) }}
            </span>

            <!-- 平台角标 / 收藏按钮 / 删除按钮 -->
            <span
              v-if="d.video_info?.platform"
              class="absolute top-2 right-2 px-1.5 py-0.5 text-[10px] font-medium bg-white/80 text-slate-600 rounded capitalize backdrop-blur-sm group-hover:opacity-0 transition-opacity duration-200"
            >
              {{ d.video_info.platform }}
            </span>
            <button
              v-if="d.content_id"
              class="absolute top-2 right-2 w-6 h-6 flex items-center justify-center bg-black/60 hover:bg-rose-600 text-white rounded-lg opacity-0 group-hover:opacity-100 transition-all duration-200"
              title="删除视频"
              @click="openDelete(d, $event)"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
            <button
              v-if="d.content_id"
              class="absolute bottom-1.5 left-1.5 w-6 h-6 flex items-center justify-center rounded-lg transition-all duration-200"
              :class="d.is_favorited ? 'text-amber-500 bg-black/50' : 'bg-black/60 hover:bg-amber-500/80 text-white opacity-0 group-hover:opacity-100'"
              :title="d.is_favorited ? '取消收藏' : '收藏'"
              @click="handleFavorite(d, $event)"
            >
              <svg class="w-3.5 h-3.5" :fill="d.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
              </svg>
            </button>
          </div>

          <!-- 标题 & 元信息 -->
          <div class="p-3">
            <h4 class="text-sm font-medium text-slate-800 line-clamp-2 leading-snug min-h-[2.5rem]">
              {{ d.video_info?.title || '未知标题' }}
            </h4>
            <div class="mt-1.5 flex items-center gap-2 text-[11px] text-slate-400">
              <span v-if="d.published_at">{{ formatTime(d.published_at) }}</span>
              <span v-if="d.published_at && d.collected_at" class="text-slate-200">|</span>
              <span v-if="d.collected_at" class="text-slate-300">{{ formatTime(d.collected_at) }}</span>
              <span v-if="!d.published_at && !d.collected_at">{{ formatTime(d.completed_at || d.created_at) }}</span>
            </div>
            <p v-if="d.error_message" class="mt-1 text-[10px] text-rose-500 line-clamp-1" :title="d.error_message">
              {{ d.error_message }}
            </p>
          </div>
        </div>
      </div>

      <!-- 加载更多 -->
      <div v-if="loadingMore" class="flex items-center justify-center py-8">
        <svg class="w-6 h-6 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>
      <div v-else-if="!hasMore && downloads.length > 0" class="text-center py-8">
        <div class="inline-flex items-center gap-2 px-4 py-2 bg-slate-100 rounded-full text-xs text-slate-500">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          已加载全部视频
        </div>
      </div>

      <!-- sentinel for infinite scroll -->
      <div ref="sentinelRef" class="h-1" />
    </template>

      </div>
    </div>

    <!-- 全屏播放器覆盖层 -->
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
          v-if="playerVisible && selectedVideo"
          class="fixed inset-0 z-50 bg-black/90 backdrop-blur-sm flex flex-col"
        >
          <!-- 关闭按钮 -->
          <button
            class="absolute top-4 right-4 z-10 p-2 text-white/60 hover:text-white hover:bg-white/10 rounded-lg transition-all"
            @click="closePlayer"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>

          <!-- 播放器区域 -->
          <div class="flex-1 flex items-center justify-center p-4 md:p-8 min-h-0">
            <div class="w-full max-w-5xl">
              <!-- Artplayer -->
              <div v-if="selectedVideo.status === 'completed' && selectedVideo.content_id" class="shadow-2xl">
                <VideoPlayer
                  ref="videoPlayerRef"
                  :content-id="selectedVideo.content_id"
                  :title="selectedVideo.video_info?.title || '视频播放'"
                  :saved-position="selectedVideo.playback_position || 0"
                />
              </div>
              <!-- 非完成状态占位 -->
              <div v-else class="aspect-video bg-gradient-to-br from-slate-800 to-slate-900 rounded-xl flex items-center justify-center shadow-2xl">
                <div class="text-center">
                  <span
                    class="inline-flex px-3 py-1 text-sm font-medium rounded-lg mb-2"
                    :class="statusStyles[selectedVideo.status] || 'bg-slate-100 text-slate-600'"
                  >
                    {{ statusLabels[selectedVideo.status] || selectedVideo.status }}
                  </span>
                  <p v-if="selectedVideo.error_message" class="text-xs text-rose-400 mt-2 max-w-md">{{ selectedVideo.error_message }}</p>
                </div>
              </div>
            </div>
          </div>

          <!-- 底部信息栏 -->
          <div class="shrink-0 px-4 md:px-8 pb-4 md:pb-6">
            <div class="max-w-5xl mx-auto">
              <h2 class="text-lg font-bold text-white mb-1">{{ selectedVideo.video_info?.title || '未知标题' }}</h2>
              <div class="flex items-center gap-3 text-sm text-white/50 flex-wrap">
                <span v-if="selectedVideo.video_info?.platform" class="inline-flex px-2 py-0.5 text-xs font-medium bg-white/10 text-white/70 rounded capitalize">
                  {{ selectedVideo.video_info.platform }}
                </span>
                <span v-if="selectedVideo.video_info?.duration">
                  {{ formatDuration(selectedVideo.video_info.duration) }}
                </span>
                <span v-if="selectedVideo.video_info?.width && selectedVideo.video_info?.height">
                  {{ selectedVideo.video_info.width }}×{{ selectedVideo.video_info.height }}
                </span>
                <span v-if="selectedVideo.video_info?.file_size">
                  {{ (selectedVideo.video_info.file_size / 1024 / 1024).toFixed(1) }} MB
                </span>
                <span v-if="selectedVideo.published_at">
                  发布于 {{ formatTime(selectedVideo.published_at) }}
                </span>
              </div>
              <div v-if="selectedVideo.video_info?.description" class="mt-2">
                <p class="text-sm text-white/40 leading-relaxed line-clamp-2">{{ selectedVideo.video_info.description }}</p>
              </div>
              <div class="mt-3 flex items-center gap-3">
                <button
                  v-if="selectedVideo.video_info?.uploader"
                  class="text-xs text-white/40"
                >
                  {{ selectedVideo.video_info.uploader }}
                </button>
                <div class="flex-1"></div>
                <button
                  v-if="selectedVideo.content_id"
                  class="px-4 py-1.5 text-sm font-medium rounded-lg transition-colors"
                  :class="selectedVideo.is_favorited ? 'text-amber-400 hover:text-amber-300 hover:bg-white/5' : 'text-white/50 hover:text-white/70 hover:bg-white/5'"
                  @click="handleFavorite(selectedVideo)"
                >
                  {{ selectedVideo.is_favorited ? '取消收藏' : '收藏' }}
                </button>
                <button
                  v-if="selectedVideo.content_id"
                  class="px-4 py-1.5 text-sm font-medium text-rose-400 hover:text-rose-300 hover:bg-white/5 rounded-lg transition-colors"
                  @click="openDelete(selectedVideo)"
                >
                  删除
                </button>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <ConfirmDialog
      :visible="showDeleteDialog"
      title="删除视频"
      :message="`确定要删除「${deletingVideo?.video_info?.title || '该视频'}」吗？视频文件和关联记录将一并清除。`"
      confirm-text="删除"
      :danger="true"
      @confirm="handleDelete"
      @cancel="showDeleteDialog = false"
    />
  </div>
</template>
