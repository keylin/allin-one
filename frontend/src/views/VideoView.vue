<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import dayjs from 'dayjs'
import Artplayer from 'artplayer'
import { downloadVideo, listDownloads } from '@/api/video'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const videoUrl = ref('')
const submitting = ref(false)
const downloads = ref([])
const loading = ref(true)

// 视频播放器相关
const selectedVideo = ref(null)
const playerRef = ref(null)
let artInstance = null

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

async function fetchDownloads() {
  try {
    const res = await listDownloads()
    if (res.code === 0) downloads.value = res.data
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  if (!videoUrl.value.trim()) return
  submitting.value = true
  try {
    const res = await downloadVideo(videoUrl.value)
    if (res.code === 0) {
      toast.success('视频下载任务已提交')
      videoUrl.value = ''
      await fetchDownloads()
    } else {
      toast.error(res.message || '提交失败')
    }
  } catch (error) {
    toast.error('提交下载任务失败')
  } finally {
    submitting.value = false
  }
}

async function playVideo(download) {
  if (!download.content_id || download.status !== 'completed') {
    toast.warning('视频尚未下载完成')
    return
  }

  selectedVideo.value = download

  // 等待 DOM 更新
  await nextTick()

  // 销毁旧实例
  if (artInstance) {
    artInstance.destroy()
    artInstance = null
  }

  // 创建播放器
  if (playerRef.value) {
    try {
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
    } catch (error) {
      toast.error('播放器初始化失败')
      console.error('Artplayer init error:', error)
    }
  }
}

function closePlayer() {
  selectedVideo.value = null
  if (artInstance) {
    artInstance.destroy()
    artInstance = null
  }
}

function formatDuration(seconds) {
  if (!seconds) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatTime(t) {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-'
}

onMounted(() => fetchDownloads())

onBeforeUnmount(() => {
  if (artInstance) {
    artInstance.destroy()
    artInstance = null
  }
})
</script>

<template>
  <div class="p-4 md:p-8 max-w-7xl mx-auto">
    <div class="mb-8">
      <h2 class="text-2xl font-bold text-slate-900 tracking-tight">视频下载与播放</h2>
      <p class="text-sm text-slate-400 mt-1">下载并播放 B 站 / YouTube 视频</p>
    </div>

    <!-- 视频播放器 -->
    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div v-if="selectedVideo" class="bg-white rounded-2xl border border-slate-200/60 shadow-lg overflow-hidden mb-8">
        <div class="flex items-center justify-between p-4 border-b border-slate-100">
          <div class="flex-1 min-w-0">
            <h3 class="text-base font-semibold text-slate-900 truncate">{{ selectedVideo.video_info?.title || '视频播放' }}</h3>
            <div class="flex items-center gap-4 mt-1 text-xs text-slate-400">
              <span v-if="selectedVideo.video_info?.duration">时长: {{ formatDuration(selectedVideo.video_info.duration) }}</span>
              <span v-if="selectedVideo.video_info?.platform" class="capitalize">{{ selectedVideo.video_info.platform }}</span>
            </div>
          </div>
          <button
            @click="closePlayer"
            class="ml-4 p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-50 rounded-lg transition-colors"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div ref="playerRef" class="aspect-video bg-black"></div>
      </div>
    </Transition>

    <!-- 下载表单 -->
    <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-6 mb-6">
      <h3 class="text-sm font-semibold text-slate-800 mb-4">提交下载任务</h3>
      <form class="flex items-center gap-3" @submit.prevent="handleSubmit">
        <input
          v-model="videoUrl"
          type="text"
          placeholder="输入视频 URL（B站/YouTube）"
          class="flex-1 px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none transition-all duration-200"
        />
        <button
          type="submit"
          class="px-5 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 disabled:opacity-50 transition-all duration-200"
          :disabled="submitting"
        >
          <span class="flex items-center gap-1.5">
            <svg v-if="submitting" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            {{ submitting ? '提交中...' : '下载' }}
          </span>
        </button>
      </form>
    </div>

    <!-- 视频列表 -->
    <div class="bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-100">
        <h3 class="text-sm font-semibold text-slate-800">下载记录</h3>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center py-16">
        <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>

      <!-- Empty -->
      <div v-else-if="downloads.length === 0" class="text-center py-16">
        <svg class="w-16 h-16 mx-auto mb-4 text-slate-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
        <p class="text-slate-400 mb-2">暂无下载记录</p>
        <p class="text-xs text-slate-300">在上方输入视频链接开始下载</p>
      </div>

      <!-- Grid -->
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-6">
        <div
          v-for="d in downloads"
          :key="d.id"
          class="group relative bg-slate-50/50 rounded-xl border border-slate-200/60 hover:border-indigo-300 hover:shadow-md transition-all duration-200 overflow-hidden cursor-pointer"
          :class="{ 'opacity-60': d.status !== 'completed' }"
          @click="d.status === 'completed' && playVideo(d)"
        >
          <!-- 缩略图 -->
          <div class="aspect-video bg-gradient-to-br from-slate-100 to-slate-50 flex items-center justify-center relative overflow-hidden">
            <img
              v-if="d.content_id && d.video_info?.has_thumbnail"
              :src="`/api/video/${d.content_id}/thumbnail`"
              class="absolute inset-0 w-full h-full object-cover"
              loading="lazy"
              @error="$event.target.style.display='none'"
            />
            <svg v-else class="w-12 h-12 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>

            <!-- 播放按钮 (仅完成状态) -->
            <div
              v-if="d.status === 'completed'"
              class="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-all duration-200 flex items-center justify-center"
            >
              <div class="w-14 h-14 bg-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transform scale-75 group-hover:scale-100 transition-all duration-200 shadow-lg">
                <svg class="w-6 h-6 text-indigo-600 ml-1" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M8 5v14l11-7z" />
                </svg>
              </div>
            </div>

            <!-- 状态标签 -->
            <span
              class="absolute top-2 right-2 px-2.5 py-1 text-xs font-medium rounded-lg shadow-sm"
              :class="statusStyles[d.status] || 'bg-slate-100 text-slate-600'"
            >
              {{ statusLabels[d.status] || d.status }}
            </span>

            <!-- 时长 (如果有) -->
            <span
              v-if="d.video_info?.duration"
              class="absolute bottom-2 right-2 px-2 py-0.5 text-xs font-medium bg-black/70 text-white rounded"
            >
              {{ formatDuration(d.video_info.duration) }}
            </span>
          </div>

          <!-- 信息 -->
          <div class="p-4">
            <h4 class="text-sm font-medium text-slate-900 line-clamp-2 min-h-[2.5rem]">
              {{ d.video_info?.title || '视频标题' }}
            </h4>
            <div class="mt-2 flex items-center gap-2 text-xs text-slate-400">
              <span v-if="d.video_info?.platform" class="capitalize">{{ d.video_info.platform }}</span>
              <span v-if="d.completed_at">{{ formatTime(d.completed_at) }}</span>
            </div>
            <p v-if="d.error_message" class="mt-2 text-xs text-rose-500 line-clamp-1" :title="d.error_message">
              {{ d.error_message }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
