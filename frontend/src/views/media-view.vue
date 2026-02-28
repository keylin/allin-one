<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { formatTimeShort } from '@/utils/time'
import { listMedia, deleteMedia, downloadMedia, toggleMediaFavorite, retryMedia } from '@/api/media'
import { incrementView } from '@/api/content'
import { listSources } from '@/api/sources'
import ConfirmDialog from '@/components/confirm-dialog.vue'
import VideoPlayer from '@/components/video-player.vue'
import IframeVideoPlayer from '@/components/iframe-video-player.vue'
import PodcastPlayer from '@/components/podcast-player.vue'
import ImageLightbox from '@/components/image-lightbox.vue'
import { useToast } from '@/composables/useToast'
import { useScrollLock } from '@/composables/useScrollLock'

const route = useRoute()
const router = useRouter()
const toast = useToast()

// --- 类型 Tab ---
const activeTab = ref(route.query.type || '')
const tabs = [
  { value: '', label: '全部' },
  { value: 'video', label: '视频' },
  { value: 'audio', label: '音频' },
  { value: 'image', label: '图片' },
]
const tabTypeLabel = computed(() => {
  const map = { '': '媒体', video: '视频', audio: '音频', image: '图片' }
  return map[activeTab.value] || '媒体'
})

// --- 下载表单 ---
const mediaUrl = ref('')
const submitting = ref(false)
const showDownloadForm = ref(false)

// --- 数据 & 加载 ---
const mediaItems = ref([])
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

// --- 播放器状态 ---
const playerVisible = ref(false)
const selectedId = ref(null)
const videoPlayerRef = ref(null)

// --- 图片 Lightbox ---
const lightboxVisible = ref(false)
const lightboxImages = ref([])
const lightboxIndex = ref(0)

useScrollLock(playerVisible)

// --- 删除 ---
const showDeleteDialog = ref(false)
const deletingItem = ref(null)

// --- 失败详情弹窗 ---
const showErrorDialog = ref(false)
const errorItem = ref(null)
const retrying = ref(false)

// Mobile filter collapse
const showMobileFilters = ref(false)
const activeFilterCount = computed(() => {
  let count = 0
  if (filterStatus.value && filterStatus.value !== 'completed') count++
  if (filterPlatform.value) count++ // only shown for video tab
  if (filterSourceId.value) count++
  return count
})

// --- 排序选项（图片 Tab 隐藏时长排序）---
const allSortOptions = [
  { value: 'published_at:desc', label: '最新发布' },
  { value: 'collected_at:desc', label: '最新采集' },
  { value: 'duration:desc', label: '时长最长' },
  { value: 'last_played_at:desc', label: '最近播放' },
]
const sortOptions = computed(() =>
  activeTab.value === 'image'
    ? allSortOptions.filter(o => !o.value.startsWith('duration') && !o.value.startsWith('last_played_at'))
    : allSortOptions
)

const currentSort = computed({
  get: () => `${sortBy.value}:${sortOrder.value}`,
  set: (val) => {
    const [field, order] = val.split(':')
    sortBy.value = field
    sortOrder.value = order
  },
})

const hasMore = computed(() => mediaItems.value.length < totalCount.value)

const hasActiveFilters = computed(() => {
  return filterPlatform.value || filterSourceId.value || (filterStatus.value && filterStatus.value !== 'completed')
})

const emptyStateType = computed(() => {
  if (searchQuery.value.trim()) return 'search'
  if (hasActiveFilters.value) return 'filter'
  return 'empty'
})

const selectedItem = computed(() => {
  if (!selectedId.value) return null
  return mediaItems.value.find(d => d.id === selectedId.value) || null
})

// --- 播放器导航 ---
const currentPlayerIndex = computed(() => {
  if (!selectedId.value) return -1
  return mediaItems.value.findIndex(d => d.id === selectedId.value)
})
const hasPrevMedia = computed(() => currentPlayerIndex.value > 0)
const hasNextMedia = computed(() => currentPlayerIndex.value >= 0 && currentPlayerIndex.value < mediaItems.value.length - 1)

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'completed', label: '已完成' },
  { value: 'pending', label: '排队中' },
  { value: 'failed', label: '失败' },
]

const statusStyles = {
  pending: 'bg-slate-100 text-slate-600',
  completed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-100 text-rose-700 ring-1 ring-rose-200',
}

const statusLabels = {
  pending: '排队中',
  completed: '已完成',
  failed: '失败',
}

// --- 纵横比检测（视频封面）---
const detectedOrientations = ref({})

function isPortrait(d) {
  const w = d.media_info?.width
  const h = d.media_info?.height
  if (w && h) return h > w
  return detectedOrientations.value[d.id] === 'portrait'
}

function onThumbnailLoad(event, itemId) {
  const img = event.target
  if (img.naturalHeight > img.naturalWidth) {
    detectedOrientations.value[itemId] = 'portrait'
  }
}

// --- 数据获取 ---
let searchTimer = null
async function fetchMedia(append = false) {
  if (append) {
    loadingMore.value = true
    currentPage.value++
  } else {
    loading.value = true
    currentPage.value = 1
    mediaItems.value = []
  }
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
      status: filterStatus.value,
    }
    if (activeTab.value) params.media_type = activeTab.value
    if (filterPlatform.value) params.platform = filterPlatform.value
    if (filterSourceId.value) params.source_id = filterSourceId.value
    if (searchQuery.value.trim()) params.search = searchQuery.value.trim()

    const res = await listMedia(params)
    if (res.code === 0) {
      if (append) {
        mediaItems.value.push(...res.data)
      } else {
        mediaItems.value = res.data
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
  if (activeTab.value) query.type = activeTab.value
  if (filterStatus.value !== 'completed') query.status = filterStatus.value
  if (filterPlatform.value && activeTab.value === 'video') query.platform = filterPlatform.value
  if (filterSourceId.value) query.source_id = filterSourceId.value
  if (searchQuery.value) query.q = searchQuery.value
  if (sortBy.value !== 'published_at') query.sort_by = sortBy.value
  if (sortOrder.value !== 'desc') query.sort_order = sortOrder.value
  router.replace({ query }).catch(() => {})
}

watch(activeTab, () => {
  // 切到图片 Tab 时，duration/last_played_at 排序不可用，自动重置
  if (activeTab.value === 'image' && (sortBy.value === 'duration' || sortBy.value === 'last_played_at')) {
    sortBy.value = 'published_at'
    sortOrder.value = 'desc'
  }
  filterPlatform.value = ''
  syncQueryParams()
  fetchMedia()
})

watch([filterStatus, filterPlatform, filterSourceId, sortBy, sortOrder], () => {
  syncQueryParams()
  fetchMedia()
})

watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    syncQueryParams()
    fetchMedia()
  }, 300)
})

// --- 下载提交 ---
async function handleSubmit() {
  if (!mediaUrl.value.trim()) return
  submitting.value = true
  try {
    const res = await downloadMedia(mediaUrl.value)
    if (res.code === 0) {
      toast.success('媒体下载任务已提交')
      mediaUrl.value = ''
      showDownloadForm.value = false
      // 切到"排队中"筛选以查看新提交的任务
      filterStatus.value = 'pending'
    } else {
      toast.error(res.message || '提交失败')
    }
  } catch {
    toast.error('提交下载任务失败')
  } finally {
    submitting.value = false
  }
}

// --- 选中媒体 ---
function selectItem(item) {
  // 失败项：打开错误详情弹窗而非播放器
  if (item.status === 'failed') {
    errorItem.value = item
    showErrorDialog.value = true
    return
  }
  if (item.media_type === 'image') {
    // 图片：直接打开 Lightbox（不用全屏 overlay）
    const imgUrl = item.media_info?.file_url || `/api/media/${item.content_id}/thumbnail`
    lightboxImages.value = [imgUrl]
    lightboxIndex.value = 0
    lightboxVisible.value = true
    return
  }
  // 视频/音频：打开全屏 overlay
  if (selectedId.value === item.id && playerVisible.value) return
  if (videoPlayerRef.value) videoPlayerRef.value.destroy()
  selectedId.value = item.id
  playerVisible.value = true
  if (item.status === 'completed' && item.content_id) {
    incrementView(item.content_id).catch(() => {})
  }
}

function closePlayer() {
  if (videoPlayerRef.value) videoPlayerRef.value.destroy()
  playerVisible.value = false
}

function goToPrevMedia() {
  const idx = currentPlayerIndex.value
  if (idx <= 0) return
  const prev = mediaItems.value[idx - 1]
  if (prev.status === 'failed') return
  if (videoPlayerRef.value) videoPlayerRef.value.destroy()
  selectedId.value = prev.id
  if (prev.status === 'completed' && prev.content_id) {
    incrementView(prev.content_id).catch(() => {})
  }
}

function goToNextMedia() {
  const idx = currentPlayerIndex.value
  if (idx < 0 || idx >= mediaItems.value.length - 1) return
  const next = mediaItems.value[idx + 1]
  if (next.status === 'failed') return
  if (videoPlayerRef.value) videoPlayerRef.value.destroy()
  selectedId.value = next.id
  if (next.status === 'completed' && next.content_id) {
    incrementView(next.content_id).catch(() => {})
  }
  // 预加载更多
  if (idx + 1 >= mediaItems.value.length - 3 && hasMore.value) loadMore()
}

// --- 收藏 ---
async function handleFavorite(d, event) {
  if (event) event.stopPropagation()
  if (!d.id) return
  const prev = d.is_favorited
  d.is_favorited = !prev
  try {
    const res = await toggleMediaFavorite(d.id)
    if (res.code === 0) {
      d.is_favorited = res.data.is_favorited
      toast.success(res.data.is_favorited ? '已收藏' : '已取消收藏')
    } else {
      d.is_favorited = prev
      toast.error('操作失败')
    }
  } catch {
    d.is_favorited = prev
    toast.error('网络错误')
  }
}

// --- 删除 ---
function openDelete(d, event) {
  if (event) event.stopPropagation()
  deletingItem.value = d
  showDeleteDialog.value = true
}

async function handleDelete() {
  showDeleteDialog.value = false
  if (!deletingItem.value?.content_id) return
  try {
    const res = await deleteMedia(deletingItem.value.content_id)
    if (res.code === 0) {
      toast.success('已删除')
      if (selectedId.value === deletingItem.value.id) {
        closePlayer()
        selectedId.value = null
      }
      await fetchMedia()
    } else {
      toast.error(res.message || '删除失败')
    }
  } catch {
    toast.error('删除请求失败')
  }
}

// --- 重试下载 ---
async function handleRetry() {
  if (!errorItem.value?.id) return
  retrying.value = true
  try {
    const res = await retryMedia(errorItem.value.id)
    if (res.code === 0) {
      toast.success('已重新提交下载')
      showErrorDialog.value = false
      errorItem.value = null
      await fetchMedia()
    } else {
      toast.error(res.message || '重试失败')
    }
  } catch {
    toast.error('重试请求失败')
  } finally {
    retrying.value = false
  }
}

function handleErrorDialogDelete() {
  showErrorDialog.value = false
  deletingItem.value = errorItem.value
  showDeleteDialog.value = true
}

// --- 键盘 ---
function onKeydown(e) {
  if (e.key === 'Escape' && playerVisible.value) {
    closePlayer()
  }
}

// --- IntersectionObserver 无限滚动 ---
watch(sentinelRef, (el) => {
  if (observer) { observer.disconnect(); observer = null }
  if (el) {
    observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && hasMore.value && !loadingMore.value && !loading.value) {
        fetchMedia(true)
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

// Format duration (seconds number) to iTunes-style string for PodcastPlayer
function formatDurationForPlayer(seconds) {
  if (!seconds) return ''
  return String(Math.floor(seconds))
}

function clearSearch() {
  searchQuery.value = ''
}

function resetFilters() {
  filterStatus.value = 'completed'
  filterPlatform.value = ''
  filterSourceId.value = ''
}

function formatTime(t) {
  return formatTimeShort(t)
}

function formatFileSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

// --- pending 状态自动轮询 ---
let pendingPollTimer = null
function startPendingPoll() {
  stopPendingPoll()
  pendingPollTimer = setInterval(() => {
    const hasPending = mediaItems.value.some(d => d.status === 'pending')
    if (hasPending) fetchMedia()
    else stopPendingPoll()
  }, 15000)
}
function stopPendingPoll() {
  clearInterval(pendingPollTimer)
  pendingPollTimer = null
}
watch(mediaItems, (items) => {
  if (items.some(d => d.status === 'pending') && !pendingPollTimer) startPendingPoll()
}, { deep: false })

onMounted(async () => {
  fetchMedia()
  try {
    const res = await listSources({ page_size: 100 })
    if (res.code === 0) sources.value = res.data
  } catch { /* ignore */ }
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  if (videoPlayerRef.value) videoPlayerRef.value.destroy()
  clearTimeout(searchTimer)
  stopPendingPoll()
  document.removeEventListener('keydown', onKeydown)
  if (observer) observer.disconnect()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Sticky header -->
    <div class="px-4 pt-3 pb-2.5 space-y-2 sticky top-0 bg-white/95 backdrop-blur-sm z-10 border-b border-slate-100 shrink-0">

      <!-- 第一行：类型分段 + 计数 + 排序 + 下载 -->
      <div class="flex items-center gap-2.5">
        <!-- iOS 风格分段式 Tab -->
        <div class="flex items-center bg-slate-100 rounded-lg p-0.5 gap-px shrink-0">
          <button
            v-for="tab in tabs"
            :key="tab.value"
            class="px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 whitespace-nowrap"
            :class="activeTab === tab.value
              ? 'bg-white text-slate-800 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'"
            @click="activeTab = tab.value"
          >
            {{ tab.label }}
          </button>
        </div>

        <!-- 数量 -->
        <span class="text-xs text-slate-400 tabular-nums shrink-0">{{ totalCount }}</span>

        <div class="flex-1" />

        <!-- 排序下拉（桌面端） -->
        <select
          v-model="currentSort"
          class="hidden md:block text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none cursor-pointer transition-all"
        >
          <option v-for="opt in sortOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>

        <!-- 下载媒体 -->
        <button
          class="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 active:scale-95 transition-all duration-150 shadow-sm shrink-0"
          @click="showDownloadForm = !showDownloadForm"
        >
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          <span class="hidden sm:inline">下载媒体</span>
          <span class="sm:hidden">下载</span>
        </button>
      </div>

      <!-- 第二行：搜索 + 状态 + 来源/平台 + 移动端展开 -->
      <div class="flex items-center gap-2">
        <!-- 搜索框 -->
        <div class="relative w-44 md:w-56 shrink-0">
          <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索..."
            class="w-full bg-slate-50 rounded-lg pl-8 pr-3 py-1.5 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 focus:bg-white transition-all"
          />
        </div>

        <!-- 状态筛选（桌面）-->
        <div class="hidden md:flex items-center gap-px bg-slate-100 rounded-lg p-0.5">
          <button
            v-for="opt in statusOptions"
            :key="opt.value"
            class="px-2.5 py-1 text-xs font-medium rounded-md transition-all duration-150 whitespace-nowrap"
            :class="filterStatus === opt.value
              ? 'bg-white text-slate-800 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'"
            @click="filterStatus = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>

        <!-- 平台（仅视频 Tab，桌面）-->
        <select
          v-if="activeTab === 'video' && platforms.length > 0"
          v-model="filterPlatform"
          class="hidden md:block text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all cursor-pointer"
        >
          <option value="">全部平台</option>
          <option v-for="p in platforms" :key="p" :value="p" class="capitalize">{{ p }}</option>
        </select>

        <!-- 来源（桌面）-->
        <select
          v-if="sources.length > 0"
          v-model="filterSourceId"
          class="hidden md:block text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all cursor-pointer"
        >
          <option value="">全部来源</option>
          <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>

        <!-- 移动端：展开筛选 -->
        <button
          class="md:hidden ml-auto p-1.5 rounded-lg border transition-all duration-200 relative"
          :class="showMobileFilters || activeFilterCount > 0
            ? 'bg-indigo-50 border-indigo-300 text-indigo-600'
            : 'bg-slate-50 border-slate-200 text-slate-400 hover:text-slate-600'"
          @click="showMobileFilters = !showMobileFilters"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
          </svg>
          <span
            v-if="activeFilterCount > 0"
            class="absolute -top-1 -right-1 w-3.5 h-3.5 bg-indigo-600 text-white text-[9px] font-bold rounded-full flex items-center justify-center"
          >{{ activeFilterCount }}</span>
        </button>
      </div>

      <!-- 移动端展开的筛选行 -->
      <Transition
        enter-active-class="transition-all duration-200 ease-out"
        enter-from-class="opacity-0 -translate-y-1"
        enter-to-class="opacity-100 translate-y-0"
        leave-active-class="transition-all duration-150 ease-in"
        leave-from-class="opacity-100 translate-y-0"
        leave-to-class="opacity-0 -translate-y-1"
      >
        <div v-if="showMobileFilters" class="md:hidden flex flex-col gap-2 pt-1">
          <!-- 状态 -->
          <div class="flex items-center gap-px bg-slate-100 rounded-lg p-0.5 w-fit">
            <button
              v-for="opt in statusOptions"
              :key="opt.value"
              class="px-2.5 py-1 text-xs font-medium rounded-md transition-all duration-150 whitespace-nowrap"
              :class="filterStatus === opt.value
                ? 'bg-white text-slate-800 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'"
              @click="filterStatus = opt.value"
            >
              {{ opt.label }}
            </button>
          </div>
          <!-- 排序 + 来源 + 平台 -->
          <div class="flex items-center gap-2 flex-wrap">
            <select
              v-model="currentSort"
              class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 outline-none cursor-pointer"
            >
              <option v-for="opt in sortOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
            <select
              v-if="activeTab === 'video' && platforms.length > 0"
              v-model="filterPlatform"
              class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 outline-none cursor-pointer"
            >
              <option value="">全部平台</option>
              <option v-for="p in platforms" :key="p" :value="p" class="capitalize">{{ p }}</option>
            </select>
            <select
              v-if="sources.length > 0"
              v-model="filterSourceId"
              class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 outline-none cursor-pointer"
            >
              <option value="">全部来源</option>
              <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
          </div>
        </div>
      </Transition>
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
            <form class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3" @submit.prevent="handleSubmit">
              <input
                v-model="mediaUrl"
                type="text"
                placeholder="输入视频/音频 URL（B站 / YouTube / 播客等）"
                class="flex-1 px-3.5 py-2 bg-slate-50 border border-slate-200 rounded-lg text-base sm:text-sm text-slate-700 placeholder-slate-400 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 focus:bg-white outline-none transition-all duration-200"
              />
              <button
                type="submit"
                class="px-5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-all duration-200 shrink-0"
                :disabled="submitting || !mediaUrl.trim()"
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
        <div v-else-if="mediaItems.length === 0" class="text-center py-24">
          <div class="w-16 h-16 mx-auto mb-4 bg-slate-100 rounded-2xl flex items-center justify-center">
            <!-- 搜索无结果图标 -->
            <svg v-if="emptyStateType === 'search'" class="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <!-- 筛选无结果图标 -->
            <svg v-else-if="emptyStateType === 'filter'" class="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
            </svg>
            <!-- 默认空状态图标 -->
            <svg v-else class="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-1.5-3.75h1.5m-1.5 0c-.621 0-1.125.504-1.125 1.125v1.5" />
            </svg>
          </div>

          <!-- 搜索无结果 -->
          <template v-if="emptyStateType === 'search'">
            <p class="text-sm text-slate-500 font-medium mb-1">未找到「{{ searchQuery }}」相关的{{ tabTypeLabel }}</p>
            <p class="text-xs text-slate-400 mb-5">尝试其他关键词或清除搜索</p>
            <button
              class="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
              @click="clearSearch"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
              清除搜索
            </button>
          </template>

          <!-- 筛选无结果 -->
          <template v-else-if="emptyStateType === 'filter'">
            <p class="text-sm text-slate-500 font-medium mb-1">当前筛选条件下没有{{ tabTypeLabel }}</p>
            <p class="text-xs text-slate-400 mb-5">尝试调整筛选条件</p>
            <button
              class="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
              @click="resetFilters"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
              </svg>
              重置筛选
            </button>
          </template>

          <!-- 无任何内容 -->
          <template v-else>
            <p class="text-sm text-slate-500 font-medium mb-1">还没有媒体内容</p>
            <p class="text-xs text-slate-400 mb-5">点击「下载媒体」开始添加视频/音频</p>
            <button
              class="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
              @click="showDownloadForm = true"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              下载媒体
            </button>
          </template>
        </div>

        <!-- 媒体卡片网格 -->
        <template v-else>
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
            <div
              v-for="d in mediaItems"
              :key="d.id"
              class="group relative bg-white rounded-xl border overflow-hidden cursor-pointer transition-all duration-200"
              :class="[
                selectedId === d.id && playerVisible
                  ? 'border-indigo-400 ring-1 ring-indigo-400/30 shadow-md'
                  : 'border-slate-200/60 hover:border-indigo-300 hover:shadow-md',
                { 'opacity-60': d.status === 'failed' && d.media_type !== 'video' }
              ]"
              @click="selectItem(d)"
            >
              <!-- ===== 视频卡片封面 ===== -->
              <template v-if="d.media_type === 'video'">
                <div class="aspect-video bg-gradient-to-br from-slate-800 to-slate-900 relative overflow-hidden">
                  <img
                    v-if="d.content_id && d.media_info?.has_thumbnail"
                    :src="d.media_info?.thumbnail_url || `/api/media/${d.content_id}/thumbnail`"
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
                    v-if="d.status !== 'failed' && (d.status === 'completed' || (d.media_type === 'video' && d.content_url))"
                    class="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-all duration-300 flex items-center justify-center"
                  >
                    <div class="w-12 h-12 bg-white/95 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transform scale-75 group-hover:scale-100 transition-all duration-300 shadow-xl">
                      <svg class="w-5 h-5 text-indigo-600 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M8 5v14l11-7z" />
                      </svg>
                    </div>
                  </div>

                  <!-- 失败重试提示 -->
                  <div
                    v-if="d.status === 'failed'"
                    class="absolute inset-0 bg-black/40 group-hover:bg-black/50 transition-all duration-200 flex items-center justify-center"
                  >
                    <div class="w-10 h-10 bg-white/80 group-hover:bg-white/95 rounded-full flex items-center justify-center transition-all duration-200 shadow-lg">
                      <svg class="w-5 h-5 text-rose-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
                      </svg>
                    </div>
                  </div>

                  <!-- 状态标签 -->
                  <span
                    v-if="d.status !== 'completed'"
                    class="absolute top-2 left-2 px-2 py-0.5 text-xs font-medium rounded-md shadow-sm inline-flex items-center gap-1"
                    :class="statusStyles[d.status] || 'bg-slate-100 text-slate-600'"
                  >
                    <svg v-if="d.status === 'pending'" class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    {{ statusLabels[d.status] || d.status }}
                  </span>

                  <!-- 时长角标 -->
                  <span
                    v-if="d.media_info?.duration"
                    class="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 text-[10px] font-medium bg-black/70 text-white rounded"
                  >
                    {{ formatDuration(d.media_info.duration) }}
                  </span>

                  <!-- 删除按钮 -->
                  <button
                    v-if="d.content_id"
                    class="absolute top-2 right-2 w-6 h-6 flex items-center justify-center bg-black/60 hover:bg-rose-600 text-white rounded-lg opacity-0 group-hover:opacity-100 transition-all duration-200"
                    title="删除"
                    @click="openDelete(d, $event)"
                  >
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>

                  <!-- 收藏按钮 -->
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

                  <!-- 播放进度条 -->
                  <div
                    v-if="d.playback_position > 0 && d.media_info?.duration > 0"
                    class="absolute bottom-0 left-0 right-0 h-0.5 bg-black/20"
                  >
                    <div
                      class="h-full bg-indigo-500"
                      :style="{ width: Math.min(100, (d.playback_position / d.media_info.duration) * 100) + '%' }"
                    />
                  </div>
                </div>
              </template>

              <!-- ===== 音频卡片封面 ===== -->
              <template v-else-if="d.media_type === 'audio'">
                <div class="aspect-video bg-gradient-to-br from-indigo-600 to-slate-700 relative overflow-hidden flex items-center justify-center">
                  <!-- 装饰波纹 -->
                  <div class="absolute inset-0 opacity-10">
                    <div class="absolute inset-0 rounded-full border-[40px] border-white/30 scale-150"></div>
                    <div class="absolute inset-0 rounded-full border-[20px] border-white/20 scale-75"></div>
                  </div>
                  <!-- 音频图标 -->
                  <div class="relative flex flex-col items-center gap-2">
                    <div
                      class="w-14 h-14 bg-white/15 backdrop-blur-sm rounded-full flex items-center justify-center group-hover:bg-white/25 transition-all duration-300"
                      :class="d.status === 'completed' ? 'group-hover:scale-110' : ''"
                    >
                      <svg class="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M9 9l10.5-3m0 6.553v3.75a2.25 2.25 0 01-1.632 2.163l-1.32.377a1.803 1.803 0 11-.99-3.467l2.31-.66a2.25 2.25 0 001.632-2.163zm0 0V2.25L9 5.25v10.303m0 0v3.75a2.25 2.25 0 01-1.632 2.163l-1.32.377a1.803 1.803 0 01-.99-3.467l2.31-.66A2.25 2.25 0 009 15.553z" />
                      </svg>
                    </div>
                    <!-- 播放按钮 overlay -->
                    <div
                      v-if="d.status === 'completed'"
                      class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all duration-200"
                    >
                      <div class="w-12 h-12 bg-white/90 rounded-full flex items-center justify-center shadow-xl">
                        <svg class="w-5 h-5 text-indigo-600 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                      </div>
                    </div>
                  </div>

                  <!-- 时长角标 -->
                  <span
                    v-if="d.media_info?.duration"
                    class="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 text-[10px] font-medium bg-black/50 text-white rounded"
                  >
                    {{ formatDuration(d.media_info.duration) }}
                  </span>

                  <!-- 状态标签 -->
                  <span
                    v-if="d.status !== 'completed'"
                    class="absolute top-2 left-2 px-2 py-0.5 text-xs font-medium rounded-md inline-flex items-center gap-1"
                    :class="statusStyles[d.status] || 'bg-slate-100 text-slate-600'"
                  >
                    <svg v-if="d.status === 'pending'" class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    {{ statusLabels[d.status] || d.status }}
                  </span>

                  <!-- 删除 -->
                  <button
                    v-if="d.content_id"
                    class="absolute top-2 right-2 w-6 h-6 flex items-center justify-center bg-black/40 hover:bg-rose-600 text-white rounded-lg opacity-0 group-hover:opacity-100 transition-all duration-200"
                    title="删除"
                    @click="openDelete(d, $event)"
                  >
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>

                  <!-- 收藏 -->
                  <button
                    v-if="d.content_id"
                    class="absolute bottom-1.5 left-1.5 w-6 h-6 flex items-center justify-center rounded-lg transition-all duration-200"
                    :class="d.is_favorited ? 'text-amber-400 bg-black/40' : 'bg-black/40 hover:bg-amber-500/80 text-white opacity-0 group-hover:opacity-100'"
                    :title="d.is_favorited ? '取消收藏' : '收藏'"
                    @click="handleFavorite(d, $event)"
                  >
                    <svg class="w-3.5 h-3.5" :fill="d.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                    </svg>
                  </button>

                  <!-- 播放进度条 -->
                  <div
                    v-if="d.playback_position > 0 && d.media_info?.duration > 0"
                    class="absolute bottom-0 left-0 right-0 h-0.5 bg-black/20"
                  >
                    <div
                      class="h-full bg-indigo-500"
                      :style="{ width: Math.min(100, (d.playback_position / d.media_info.duration) * 100) + '%' }"
                    />
                  </div>
                </div>
              </template>

              <!-- ===== 图片卡片封面 ===== -->
              <template v-else-if="d.media_type === 'image'">
                <div :class="[activeTab === 'image' ? 'aspect-square' : 'aspect-video', 'bg-slate-100 relative overflow-hidden']">
                  <img
                    v-if="d.content_id"
                    :src="d.media_info?.file_url || `/api/media/${d.content_id}/thumbnail`"
                    class="absolute inset-0 w-full h-full object-cover"
                    loading="lazy"
                    @error="$event.target.style.display='none'"
                  />
                  <div v-else class="absolute inset-0 flex items-center justify-center">
                    <svg class="w-10 h-10 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
                    </svg>
                  </div>

                  <!-- 放大提示 -->
                  <div class="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-all duration-200 flex items-center justify-center">
                    <svg class="w-8 h-8 text-white opacity-0 group-hover:opacity-90 transition-opacity duration-200 drop-shadow-lg" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607zM10.5 7.5v6m3-3h-6" />
                    </svg>
                  </div>

                  <!-- 图片标签 -->
                  <span class="absolute top-2 left-2 px-1.5 py-0.5 text-[10px] font-medium bg-black/50 text-white rounded backdrop-blur-sm">
                    图片
                  </span>

                  <!-- 删除 -->
                  <button
                    v-if="d.content_id"
                    class="absolute top-2 right-2 w-6 h-6 flex items-center justify-center bg-black/50 hover:bg-rose-600 text-white rounded-lg opacity-0 group-hover:opacity-100 transition-all duration-200"
                    title="删除"
                    @click="openDelete(d, $event)"
                  >
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>

                  <!-- 收藏按钮 -->
                  <button
                    v-if="d.content_id"
                    class="absolute bottom-1.5 left-1.5 w-6 h-6 flex items-center justify-center rounded-lg transition-all duration-200"
                    :class="d.is_favorited ? 'text-amber-500 bg-black/50' : 'bg-black/50 hover:bg-amber-500/80 text-white opacity-0 group-hover:opacity-100'"
                    :title="d.is_favorited ? '取消收藏' : '收藏'"
                    @click="handleFavorite(d, $event)"
                  >
                    <svg class="w-3.5 h-3.5" :fill="d.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                    </svg>
                  </button>
                </div>
              </template>

              <!-- 标题 & 元信息 -->
              <div class="p-3">
                <h4 class="text-sm font-medium text-slate-800 line-clamp-2 leading-snug min-h-[2.5rem]">
                  {{ d.title || d.media_info?.title || '未知标题' }}
                </h4>
                <div class="mt-1.5 flex items-center gap-1 text-[11px] text-slate-400 flex-wrap">
                  <span v-if="d.media_info?.platform" class="capitalize">{{ d.media_info.platform }}</span>
                  <span v-if="d.media_info?.platform && d.source_name" class="text-slate-200 shrink-0">·</span>
                  <span class="truncate">{{ d.source_name || '手动下载' }}</span>
                  <template v-if="d.published_at || d.created_at">
                    <span class="text-slate-200 shrink-0">·</span>
                    <span class="shrink-0">{{ formatTime(d.published_at || d.created_at) }}</span>
                  </template>
                  <template v-if="d.media_info?.file_size">
                    <span class="text-slate-200 shrink-0">·</span>
                    <span class="shrink-0">{{ formatFileSize(d.media_info.file_size) }}</span>
                  </template>
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
          <div v-else-if="!hasMore && mediaItems.length > 0" class="text-center py-8">
            <div class="inline-flex items-center gap-2 px-4 py-2 bg-slate-100 rounded-full text-xs text-slate-500">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              已加载全部{{ tabTypeLabel }}
            </div>
          </div>

          <!-- sentinel for infinite scroll -->
          <div ref="sentinelRef" class="h-1" />
        </template>

      </div>
    </div>

    <!-- ===== 视频/音频 全屏播放器覆盖层 ===== -->
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
          v-if="playerVisible && selectedItem"
          class="fixed inset-0 z-50 bg-black/90 backdrop-blur-sm flex flex-col"
        >
          <!-- 顶部操作栏 -->
          <div class="absolute top-4 right-4 z-10 flex items-center gap-1">
            <!-- 上一条 -->
            <button
              v-if="hasPrevMedia"
              class="p-2 text-white/60 hover:text-white hover:bg-white/10 rounded-lg transition-all"
              title="上一条"
              @click="goToPrevMedia"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
            </button>
            <!-- 下一条 -->
            <button
              v-if="hasNextMedia"
              class="p-2 text-white/60 hover:text-white hover:bg-white/10 rounded-lg transition-all"
              title="下一条"
              @click="goToNextMedia"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
              </svg>
            </button>
            <!-- 关闭 -->
            <button
              class="p-2 text-white/60 hover:text-white hover:bg-white/10 rounded-lg transition-all"
              @click="closePlayer"
            >
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- 视频播放器 -->
          <template v-if="selectedItem.media_type === 'video'">
            <div class="flex-1 flex items-center justify-center p-4 md:p-8 min-h-0">
              <div class="w-full max-w-5xl">
                <div v-if="selectedItem.status === 'completed' && selectedItem.content_id" class="shadow-2xl">
                  <VideoPlayer
                    ref="videoPlayerRef"
                    :content-id="selectedItem.content_id"
                    :title="selectedItem.title || '视频播放'"
                    :saved-position="selectedItem.playback_position || 0"
                  />
                </div>
                <div v-else-if="selectedItem.content_url" class="shadow-2xl">
                  <IframeVideoPlayer
                    :video-url="selectedItem.content_url"
                    :title="selectedItem.title || '视频播放'"
                  />
                </div>
                <div v-else class="aspect-video bg-gradient-to-br from-slate-800 to-slate-900 rounded-xl flex items-center justify-center shadow-2xl">
                  <span
                    class="inline-flex px-3 py-1 text-sm font-medium rounded-lg"
                    :class="statusStyles[selectedItem.status] || 'bg-slate-100 text-slate-600'"
                  >
                    {{ statusLabels[selectedItem.status] || selectedItem.status }}
                  </span>
                </div>
              </div>
            </div>
            <!-- 底部信息栏 -->
            <div class="shrink-0 px-4 md:px-8 pb-4 md:pb-6">
              <div class="max-w-5xl mx-auto">
                <h2 class="text-lg font-bold text-white mb-1">{{ selectedItem.title || '未知标题' }}</h2>
                <div class="flex items-center gap-3 text-sm text-white/50 flex-wrap">
                  <span v-if="selectedItem.media_info?.platform" class="inline-flex px-2 py-0.5 text-xs font-medium bg-white/10 text-white/70 rounded capitalize">
                    {{ selectedItem.media_info.platform }}
                  </span>
                  <span v-if="selectedItem.media_info?.duration">{{ formatDuration(selectedItem.media_info.duration) }}</span>
                  <span v-if="selectedItem.media_info?.width && selectedItem.media_info?.height">
                    {{ selectedItem.media_info.width }}×{{ selectedItem.media_info.height }}
                  </span>
                  <span v-if="selectedItem.published_at">发布于 {{ formatTime(selectedItem.published_at) }}</span>
                </div>
                <div class="mt-3 flex items-center gap-3">
                  <div class="flex-1"></div>
                  <button
                    v-if="selectedItem.content_id"
                    class="px-4 py-1.5 text-sm font-medium rounded-lg transition-colors"
                    :class="selectedItem.is_favorited ? 'text-amber-400 hover:text-amber-300 hover:bg-white/5' : 'text-white/50 hover:text-white/70 hover:bg-white/5'"
                    @click="handleFavorite(selectedItem)"
                  >
                    {{ selectedItem.is_favorited ? '取消收藏' : '收藏' }}
                  </button>
                  <button
                    v-if="selectedItem.content_id"
                    class="px-4 py-1.5 text-sm font-medium text-rose-400 hover:text-rose-300 hover:bg-white/5 rounded-lg transition-colors"
                    @click="openDelete(selectedItem)"
                  >
                    删除
                  </button>
                </div>
              </div>
            </div>
          </template>

          <!-- 音频播放器（居中 modal） -->
          <template v-else-if="selectedItem.media_type === 'audio'">
            <div class="flex-1 flex items-center justify-center p-4" @click.self="closePlayer">
              <div class="w-full max-w-xl bg-white rounded-2xl overflow-hidden shadow-2xl">
                <!-- 顶部信息 -->
                <div class="px-5 pt-5 pb-2 flex items-start justify-between">
                  <div class="flex-1 min-w-0">
                    <h3 class="text-base font-semibold text-slate-800 line-clamp-2">{{ selectedItem.title || '音频播放' }}</h3>
                    <p v-if="selectedItem.source_name" class="mt-0.5 text-xs text-slate-400">{{ selectedItem.source_name }}</p>
                  </div>
                  <div class="flex items-center gap-2 ml-3 shrink-0">
                    <button
                      v-if="selectedItem.content_id"
                      class="p-1.5 rounded-lg transition-colors"
                      :class="selectedItem.is_favorited ? 'text-amber-500 bg-amber-50' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100'"
                      :title="selectedItem.is_favorited ? '取消收藏' : '收藏'"
                      @click="handleFavorite(selectedItem)"
                    >
                      <svg class="w-4 h-4" :fill="selectedItem.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                      </svg>
                    </button>
                    <button
                      class="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
                      @click="closePlayer"
                    >
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                </div>
                <PodcastPlayer
                  v-if="selectedItem.status === 'completed'"
                  :audio-url="`/api/audio/${selectedItem.content_id}/stream`"
                  :title="selectedItem.title || ''"
                  :duration="formatDurationForPlayer(selectedItem.media_info?.duration)"
                  :content-id="selectedItem.content_id"
                  :playback-position="selectedItem.playback_position || 0"
                />
                <div v-else class="px-5 pb-5 text-center text-sm text-slate-500 py-8">
                  <span :class="statusStyles[selectedItem.status] || ''">{{ statusLabels[selectedItem.status] || selectedItem.status }}</span>
                </div>
              </div>
            </div>
          </template>
        </div>
      </Transition>
    </Teleport>

    <!-- ===== 图片 Lightbox ===== -->
    <ImageLightbox
      :visible="lightboxVisible"
      :images="lightboxImages"
      :start-index="lightboxIndex"
      @close="lightboxVisible = false"
    />

    <!-- 删除确认 -->
    <ConfirmDialog
      :visible="showDeleteDialog"
      title="删除媒体"
      :message="`确定要删除「${deletingItem?.title || '该媒体'}」吗？文件和关联记录将一并清除。`"
      confirm-text="删除"
      :danger="true"
      @confirm="handleDelete"
      @cancel="showDeleteDialog = false"
    />

    <!-- 失败详情弹窗 -->
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
          v-if="showErrorDialog && errorItem"
          class="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
          @click.self="showErrorDialog = false"
        >
          <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
            <!-- 头部 -->
            <div class="px-5 pt-5 pb-3 flex items-start justify-between">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-1">
                  <span class="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-rose-100 text-rose-700 rounded-md ring-1 ring-rose-200">
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                    </svg>
                    下载失败
                  </span>
                </div>
                <h3 class="text-base font-semibold text-slate-800 line-clamp-2">{{ errorItem.title || '未知标题' }}</h3>
              </div>
              <button
                class="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors ml-3 shrink-0"
                @click="showErrorDialog = false"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <!-- 错误信息 -->
            <div class="px-5 pb-4 space-y-3">
              <div v-if="errorItem.error_message" class="bg-rose-50 border border-rose-100 rounded-lg p-3">
                <p class="text-xs font-medium text-rose-600 mb-1">错误信息</p>
                <p class="text-sm text-rose-700 whitespace-pre-wrap break-words">{{ errorItem.error_message }}</p>
              </div>
              <div v-if="errorItem.content_url" class="bg-slate-50 border border-slate-100 rounded-lg p-3">
                <p class="text-xs font-medium text-slate-500 mb-1">原始 URL</p>
                <a :href="errorItem.content_url" target="_blank" rel="noopener" class="text-sm text-indigo-600 hover:text-indigo-700 break-all">
                  {{ errorItem.content_url }}
                </a>
              </div>
            </div>

            <!-- 操作按钮 -->
            <div class="px-5 pb-5 flex items-center gap-3">
              <button
                class="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-all duration-200"
                :disabled="retrying"
                @click="handleRetry"
              >
                <svg v-if="retrying" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
                </svg>
                {{ retrying ? '重试中...' : '重新下载' }}
              </button>
              <button
                class="px-4 py-2 text-sm font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
                @click="handleErrorDialogDelete"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
