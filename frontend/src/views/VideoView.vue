<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import dayjs from 'dayjs'
import Artplayer from 'artplayer'
import { downloadVideo, listDownloads, deleteVideo, saveProgress } from '@/api/video'
import { incrementView } from '@/api/content'
import { listSources } from '@/api/sources'
import ConfirmDialog from '@/components/confirm-dialog.vue'
import { useToast } from '@/composables/useToast'

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

// --- 筛选 & 排序 ---
const filterStatus = ref('completed')
const filterPlatform = ref('')
const filterSourceId = ref('')
const searchQuery = ref('')
const sources = ref([])
const sortBy = ref('published_at')
const sortOrder = ref('desc')
const currentPage = ref(1)
const pageSize = 18

// --- 删除 ---
const showDeleteDialog = ref(false)
const deletingVideo = ref(null)

function openDelete(d, event) {
  event.stopPropagation()
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
      await fetchDownloads()
    } else {
      toast.error(res.message || '删除失败')
    }
  } catch {
    toast.error('删除请求失败')
  }
}

// --- 播放器 ---
const selectedVideo = ref(null)
const playerRef = ref(null)
let artInstance = null

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
  { value: 'published_at:asc', label: '最早发布' },
  { value: 'collected_at:desc', label: '最新抓取' },
  { value: 'collected_at:asc', label: '最早抓取' },
  { value: 'title:asc', label: '标题 A-Z' },
  { value: 'title:desc', label: '标题 Z-A' },
  { value: 'duration:desc', label: '时长最长' },
  { value: 'duration:asc', label: '时长最短' },
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

// 筛选变化时重置并刷新
watch([filterStatus, filterPlatform, filterSourceId, sortBy, sortOrder], () => {
  fetchDownloads()
})

watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
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

// --- 视频播放 ---
async function playVideo(download) {
  if (!download.content_id || download.status !== 'completed') {
    toast.warning('视频尚未下载完成')
    return
  }

  selectedVideo.value = download
  document.body.style.overflow = 'hidden'
  await nextTick()

  if (artInstance) {
    artInstance.destroy()
    artInstance = null
  }

  // 记录查看次数（fire-and-forget）
  if (download.content_id) {
    incrementView(download.content_id).catch(() => {})
  }

  if (playerRef.value) {
    try {
      const savedPosition = download.playback_position || 0
      artInstance = new Artplayer({
        container: playerRef.value,
        url: `/api/video/${download.content_id}/stream`,
        title: download.video_info?.title || '视频播放',
        lang: 'zh-cn',
        volume: 0.8,
        autoplay: false,
        pip: true,
        setting: true,
        playbackRate: true,
        fullscreen: true,
        fullscreenWeb: true,
        aspectRatio: true,
        subtitleOffset: true,
      })
      // 恢复上次播放进度
      if (savedPosition > 0) {
        artInstance.once('ready', () => {
          artInstance.currentTime = savedPosition
        })
      }
    } catch {
      toast.error('播放器初始化失败')
    }
  }
}

function closePlayer() {
  // 保存播放进度（fire-and-forget）
  if (artInstance && selectedVideo.value?.content_id) {
    const position = Math.floor(artInstance.currentTime || 0)
    if (position > 0) {
      saveProgress(selectedVideo.value.content_id, position).catch(() => {})
    }
  }

  selectedVideo.value = null
  document.body.style.overflow = ''
  if (artInstance) {
    artInstance.destroy()
    artInstance = null
  }
}

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
  return t ? dayjs.utc(t).local().format('MM-DD HH:mm') : '-'
}

function onKeydown(e) {
  if (e.key === 'Escape' && selectedVideo.value) closePlayer()
}

onMounted(async () => {
  fetchDownloads()
  try {
    const res = await listSources({ page_size: 100 })
    if (res.code === 0) sources.value = res.data.filter(s => s.media_type === 'video')
  } catch { /* ignore */ }
  document.addEventListener('keydown', onKeydown)
  observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && hasMore.value && !loadingMore.value) {
      fetchDownloads(true)
    }
  })
  nextTick(() => {
    if (sentinelRef.value) observer.observe(sentinelRef.value)
  })
})

watch(sentinelRef, (el) => {
  if (el && observer) observer.observe(el)
})

onBeforeUnmount(() => {
  if (artInstance) {
    artInstance.destroy()
    artInstance = null
  }
  clearTimeout(searchTimer)
  document.removeEventListener('keydown', onKeydown)
  if (observer) observer.disconnect()
})
</script>

<template>
  <div class="p-4 md:p-8 max-w-7xl mx-auto">
    <!-- 页头 -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
      <div>
        <h2 class="text-2xl font-bold text-slate-900 tracking-tight">视频管理</h2>
        <p class="text-sm text-slate-400 mt-1">下载、管理和播放 B站 / YouTube 视频</p>
      </div>
      <button
        class="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 transition-all duration-200"
        @click="showDownloadForm = !showDownloadForm"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
        </svg>
        下载视频
      </button>
    </div>

    <!-- 下载表单（可折叠） -->
    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 -translate-y-2 max-h-0"
      enter-to-class="opacity-100 translate-y-0 max-h-40"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100 translate-y-0 max-h-40"
      leave-to-class="opacity-0 -translate-y-2 max-h-0"
    >
      <div v-if="showDownloadForm" class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-5 mb-6 overflow-hidden">
        <form class="flex items-center gap-3" @submit.prevent="handleSubmit">
          <input
            v-model="videoUrl"
            type="text"
            placeholder="输入视频 URL（B站 / YouTube / 其他平台）"
            class="flex-1 px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200"
          />
          <button
            type="submit"
            class="px-5 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 disabled:opacity-50 transition-all duration-200 shrink-0"
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
        </form>
      </div>
    </Transition>

    <!-- 筛选工具栏 -->
    <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4 mb-6">
      <div class="flex flex-col lg:flex-row lg:items-center gap-4">
        <!-- 搜索 -->
        <div class="relative flex-1 max-w-md">
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索视频标题..."
            class="w-full pl-10 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-700 placeholder-slate-400 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 focus:bg-white outline-none transition-all duration-200"
          />
        </div>

        <div class="flex flex-wrap items-center gap-3">
          <!-- 状态筛选 -->
          <div class="flex items-center gap-1.5">
            <button
              v-for="opt in statusOptions"
              :key="opt.value"
              class="px-3 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200"
              :class="filterStatus === opt.value
                ? 'bg-indigo-50 border-indigo-300 text-indigo-700 shadow-sm'
                : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300 hover:bg-slate-50'"
              @click="filterStatus = opt.value"
            >
              {{ opt.label }}
            </button>
          </div>

          <!-- 平台筛选 -->
          <select
            v-if="platforms.length > 0"
            v-model="filterPlatform"
            class="px-3 py-1.5 text-xs font-medium bg-white border border-slate-200 rounded-lg text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200"
          >
            <option value="">全部平台</option>
            <option v-for="p in platforms" :key="p" :value="p" class="capitalize">{{ p }}</option>
          </select>

          <!-- 来源筛选 -->
          <select
            v-if="sources.length > 0"
            v-model="filterSourceId"
            class="px-3 py-1.5 text-xs font-medium bg-white border border-slate-200 rounded-lg text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200"
          >
            <option value="">全部来源</option>
            <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>

          <!-- 排序 -->
          <select
            v-model="currentSort"
            class="px-3 py-1.5 text-xs font-medium bg-white border border-slate-200 rounded-lg text-slate-600 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200"
          >
            <option v-for="opt in sortOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-24">
      <svg class="w-8 h-8 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <!-- Empty -->
    <div v-else-if="downloads.length === 0" class="text-center py-24">
      <div class="w-20 h-20 mx-auto mb-5 bg-slate-100 rounded-2xl flex items-center justify-center">
        <svg class="w-10 h-10 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      </div>
      <p class="text-slate-500 font-medium mb-1">暂无视频</p>
      <p class="text-sm text-slate-400 mb-5">点击右上角「下载视频」开始添加</p>
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

    <!-- 海报墙 -->
    <div v-else>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
        <div
          v-for="d in downloads"
          :key="d.id"
          class="group relative bg-white rounded-xl border border-slate-200/60 hover:border-indigo-300 hover:shadow-lg transition-all duration-300 overflow-hidden cursor-pointer"
          :class="{ 'opacity-60': d.status !== 'completed' }"
          @click="d.status === 'completed' && playVideo(d)"
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
              <svg class="w-12 h-12 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </div>

            <!-- 悬浮播放按钮 -->
            <div
              v-if="d.status === 'completed'"
              class="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-all duration-300 flex items-center justify-center"
            >
              <div class="w-14 h-14 bg-white/95 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transform scale-75 group-hover:scale-100 transition-all duration-300 shadow-xl">
                <svg class="w-6 h-6 text-indigo-600 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M8 5v14l11-7z" />
                </svg>
              </div>
            </div>

            <!-- 状态标签 -->
            <span
              v-if="d.status !== 'completed'"
              class="absolute top-2 left-2 px-2 py-0.5 text-[10px] font-semibold rounded-md shadow-sm"
              :class="statusStyles[d.status] || 'bg-slate-100 text-slate-600'"
            >
              {{ statusLabels[d.status] || d.status }}
            </span>

            <!-- 时长角标 -->
            <span
              v-if="d.video_info?.duration"
              class="absolute bottom-2 right-2 px-1.5 py-0.5 text-[10px] font-medium bg-black/70 text-white rounded"
            >
              {{ formatDuration(d.video_info.duration) }}
            </span>

            <!-- 平台角标 / 删除按钮 -->
            <span
              v-if="d.video_info?.platform"
              class="absolute top-2 right-2 px-1.5 py-0.5 text-[10px] font-medium bg-white/80 text-slate-600 rounded capitalize backdrop-blur-sm group-hover:opacity-0 transition-opacity duration-200"
            >
              {{ d.video_info.platform }}
            </span>
            <button
              v-if="d.content_id"
              class="absolute top-2 right-2 w-7 h-7 flex items-center justify-center bg-black/60 hover:bg-rose-600 text-white rounded-lg opacity-0 group-hover:opacity-100 transition-all duration-200"
              title="删除视频"
              @click="openDelete(d, $event)"
            >
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>

          <!-- 标题 & 元信息 -->
          <div class="p-3">
            <h4 class="text-xs font-medium text-slate-800 line-clamp-2 leading-relaxed min-h-[2rem]">
              {{ d.video_info?.title || '未知标题' }}
            </h4>
            <div class="mt-1.5 flex items-center gap-2 text-[10px] text-slate-400">
              <span v-if="d.published_at" :title="'发布: ' + formatTime(d.published_at)">{{ formatTime(d.published_at) }}</span>
              <span v-if="d.published_at && d.collected_at" class="text-slate-200">|</span>
              <span v-if="d.collected_at" class="text-slate-300" :title="'抓取: ' + formatTime(d.collected_at)">{{ formatTime(d.collected_at) }}</span>
              <span v-if="!d.published_at && !d.collected_at">{{ formatTime(d.completed_at || d.created_at) }}</span>
            </div>
            <p v-if="d.error_message" class="mt-1 text-[10px] text-rose-500 line-clamp-1" :title="d.error_message">
              {{ d.error_message }}
            </p>
          </div>
        </div>
      </div>

      <!-- 无限滚动 sentinel -->
      <div ref="sentinelRef" class="h-1" />
      <div v-if="loadingMore" class="flex items-center justify-center py-6">
        <svg class="w-6 h-6 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>
      <div v-else-if="!hasMore && downloads.length > 0" class="text-center py-6 text-sm text-slate-400">
        已加载全部视频
      </div>
    </div>
    <ConfirmDialog
      :visible="showDeleteDialog"
      title="删除视频"
      :message="`确定要删除「${deletingVideo?.video_info?.title || '该视频'}」吗？视频文件和关联记录将一并清除。`"
      confirm-text="删除"
      :danger="true"
      @confirm="handleDelete"
      @cancel="showDeleteDialog = false"
    />

    <!-- 视频播放器弹层 -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition-all duration-300 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-all duration-200 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div
          v-if="selectedVideo"
          class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center"
          @click.self="closePlayer"
        >
          <div class="relative max-w-5xl w-full mx-4">
            <!-- 标题栏 -->
            <div class="flex items-center justify-between mb-3">
              <div class="flex-1 min-w-0">
                <h3 class="text-base font-semibold text-white truncate">{{ selectedVideo.video_info?.title || '视频播放' }}</h3>
                <div class="flex items-center gap-4 mt-0.5 text-xs text-white/60">
                  <span v-if="selectedVideo.video_info?.duration">{{ formatDuration(selectedVideo.video_info.duration) }}</span>
                  <span v-if="selectedVideo.video_info?.platform" class="capitalize">{{ selectedVideo.video_info.platform }}</span>
                </div>
              </div>
              <button
                @click="closePlayer"
                class="ml-4 p-2 text-white/60 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
              >
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <!-- 播放器 -->
            <div ref="playerRef" class="aspect-video bg-black rounded-xl overflow-hidden"></div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
