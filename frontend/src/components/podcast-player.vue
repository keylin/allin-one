<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { usePlayerStore } from '@/stores/player'

/**
 * 播客内嵌播放器 —— 不持有 <audio>，播放请求交给全局 playerStore。
 * 面板关闭 / 切换条目 / 切路由时本组件销毁，但播放在 store 里延续，
 * 底部迷你播放条接管控制（本组件离开视口时同样显示迷你条）。
 */

const props = defineProps({
  audioUrl: { type: String, required: true },
  title: { type: String, default: '' },
  artworkUrl: { type: String, default: '' },
  duration: { type: String, default: '' },
  episode: { type: String, default: '' },
  contentId: { type: String, default: '' },
  playbackPosition: { type: Number, default: 0 },
})

const playerStore = usePlayerStore()

const rootRef = ref(null)
const progressBarRef = ref(null)
const isDragging = ref(false)
// 未接入全局播放时的本地进度（初始为服务端记录的位置，可被拖动/±15s 修改）
const localPosition = ref(props.playbackPosition || 0)
const dragPosition = ref(0)

const speeds = [1, 1.25, 1.5, 2]
const instanceId = `podcast-${Math.random().toString(36).slice(2)}`

// 全局播放器当前是否正在播放本条内容
const isActive = computed(() => playerStore.isActive(props.contentId, 'audio'))
const isPlaying = computed(() => isActive.value && playerStore.isPlaying)
const isLoading = computed(() => isActive.value && playerStore.isLoading)
const playbackRate = computed(() => playerStore.playbackRate)

// Format seconds to mm:ss or hh:mm:ss
function formatDuration(secs) {
  if (!secs || isNaN(secs)) return '0:00'
  const s = Math.floor(secs)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  return `${m}:${String(sec).padStart(2, '0')}`
}

// Parse iTunes duration string (e.g. "28:12" or "1:02:30" or "1692") to seconds
function parseDuration(dur) {
  if (!dur) return 0
  if (/^\d+$/.test(dur)) return parseInt(dur, 10)
  const parts = dur.split(':').map(Number)
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  return 0
}

const totalDuration = computed(() => {
  if (isActive.value && playerStore.duration > 0) return playerStore.duration
  return parseDuration(props.duration)
})

const currentTime = computed(() => {
  if (isDragging.value) return dragPosition.value
  return isActive.value ? playerStore.currentTime : localPosition.value
})

const displayDuration = computed(() => {
  if (totalDuration.value > 0) return formatDuration(totalDuration.value)
  return props.duration || ''
})

const progressPercent = computed(() => {
  if (!totalDuration.value) return 0
  return Math.max(0, Math.min(100, (currentTime.value / totalDuration.value) * 100))
})

// 接入全局播放器时记住最后位置，停止后仍显示在原处
watch(() => playerStore.currentTime, (t) => {
  if (isActive.value) localPosition.value = t
})

// 切换条目（父组件复用本实例）时重置本地状态并重新登记
watch(() => props.contentId, () => {
  localPosition.value = props.playbackPosition || 0
  registerVisibility()
})
watch(() => props.playbackPosition, (p) => {
  if (!isActive.value) localPosition.value = p || 0
})

function mediaInfo(position) {
  return {
    contentId: props.contentId,
    kind: 'audio',
    title: props.title,
    streamUrl: props.audioUrl,
    thumbnailUrl: props.artworkUrl,
    position,
    progressPath: `/media/${props.contentId}/progress`,
  }
}

function togglePlay() {
  if (isActive.value) {
    playerStore.toggle()
  } else {
    playerStore.load(mediaInfo(localPosition.value))
  }
}

function cycleSpeed() {
  const idx = speeds.indexOf(playbackRate.value)
  const next = speeds[(idx + 1) % speeds.length]
  playerStore.setRate(next)
}

function skipBy(delta) {
  if (isActive.value) {
    playerStore.skip(delta)
  } else {
    const max = totalDuration.value || Infinity
    localPosition.value = Math.max(0, Math.min(localPosition.value + delta, max))
  }
}

function skipForward() { skipBy(playerStore.SKIP_SECONDS) }
function skipBackward() { skipBy(-playerStore.SKIP_SECONDS) }

// Progress bar seek
function ratioFromEvent(e) {
  const bar = progressBarRef.value
  if (!bar) return null
  const rect = bar.getBoundingClientRect()
  return Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
}

function previewFromEvent(e) {
  const ratio = ratioFromEvent(e)
  if (ratio === null) return
  dragPosition.value = ratio * (totalDuration.value || 0)
}

function commitSeek() {
  if (!totalDuration.value) return
  if (isActive.value) {
    playerStore.seek(dragPosition.value)
  } else {
    localPosition.value = dragPosition.value
  }
}

function onProgressMouseDown(e) {
  isDragging.value = true
  previewFromEvent(e)
  document.addEventListener('mousemove', onProgressMouseMove)
  document.addEventListener('mouseup', onProgressMouseUp)
}

function onProgressMouseMove(e) {
  if (isDragging.value) previewFromEvent(e)
}

function onProgressMouseUp() {
  commitSeek()
  isDragging.value = false
  document.removeEventListener('mousemove', onProgressMouseMove)
  document.removeEventListener('mouseup', onProgressMouseUp)
}

function onProgressTouchStart(e) {
  isDragging.value = true
  previewFromEvent(e.touches[0])
}

function onProgressTouchMove(e) {
  if (isDragging.value) {
    e.preventDefault()
    previewFromEvent(e.touches[0])
  }
}

function onProgressTouchEnd() {
  commitSeek()
  isDragging.value = false
}

// ---- 可见性登记：本播放器在视口内时隐藏迷你播放条 ----
let observer = null
let lastVisible = false

function registerVisibility() {
  playerStore.registerInline(instanceId, props.contentId, lastVisible)
}

onMounted(() => {
  if ('IntersectionObserver' in window && rootRef.value) {
    observer = new IntersectionObserver((entries) => {
      lastVisible = entries.some(en => en.isIntersecting)
      registerVisibility()
    }, { threshold: 0.2 })
    observer.observe(rootRef.value)
  } else {
    lastVisible = true
    registerVisibility()
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  playerStore.unregisterInline(instanceId)
  document.removeEventListener('mousemove', onProgressMouseMove)
  document.removeEventListener('mouseup', onProgressMouseUp)
})

// 兼容旧的命令式访问（父组件可查询状态）
function getCurrentTime() {
  return currentTime.value
}

function isCurrentlyPlaying() {
  return isPlaying.value
}

function pausePlayback() {
  if (isActive.value) playerStore.pause()
}

defineExpose({ getCurrentTime, isCurrentlyPlaying, pausePlayback })
</script>

<template>
  <div ref="rootRef" class="rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50/80 to-white overflow-hidden shadow-sm">
    <div class="p-4 md:p-5">
      <!-- Top: artwork + info + controls -->
      <div class="flex items-start gap-3 md:gap-4">
        <!-- Artwork -->
        <div class="shrink-0 w-16 h-16 md:w-20 md:h-20 rounded-xl overflow-hidden bg-indigo-100 shadow-sm">
          <img
            v-if="artworkUrl"
            :src="artworkUrl"
            :alt="title"
            class="w-full h-full object-cover"
            @error="$event.target.style.display = 'none'"
          />
          <div v-if="!artworkUrl" class="w-full h-full flex items-center justify-center">
            <svg class="w-8 h-8 md:w-10 md:h-10 text-indigo-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
            </svg>
          </div>
        </div>

        <!-- Info -->
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-1">
            <span class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold rounded-full bg-indigo-100 text-indigo-600 uppercase tracking-wide">
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
              </svg>
              Podcast
            </span>
            <span v-if="episode" class="text-[10px] text-indigo-400 font-medium">EP {{ episode }}</span>
            <span v-if="isPlaying" class="inline-flex items-center gap-1 text-[10px] text-emerald-600 font-medium">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              后台播放中
            </span>
          </div>
          <p class="text-sm font-semibold text-slate-800 line-clamp-2 leading-snug">{{ title }}</p>
          <p v-if="displayDuration" class="mt-0.5 text-xs text-slate-400">{{ displayDuration }}</p>
        </div>
      </div>

      <!-- Progress bar -->
      <div class="mt-4">
        <div
          ref="progressBarRef"
          class="relative h-2 bg-indigo-100 rounded-full cursor-pointer group"
          @mousedown="onProgressMouseDown"
          @touchstart.passive="onProgressTouchStart"
          @touchmove="onProgressTouchMove"
          @touchend="onProgressTouchEnd"
        >
          <!-- Played -->
          <div
            class="absolute inset-y-0 left-0 bg-indigo-500 rounded-full"
            :style="{ width: progressPercent + '%' }"
          />
          <!-- Thumb -->
          <div
            class="absolute top-1/2 -translate-y-1/2 w-4 h-4 bg-white border-2 border-indigo-500 rounded-full shadow-sm transition-transform"
            :class="isDragging ? 'scale-125' : 'scale-0 group-hover:scale-100'"
            :style="{ left: `calc(${progressPercent}% - 8px)` }"
          />
        </div>
        <!-- Time display -->
        <div class="flex justify-between mt-1.5 text-[11px] text-slate-400 font-medium tabular-nums">
          <span>{{ formatDuration(currentTime) }}</span>
          <span>{{ displayDuration }}</span>
        </div>
      </div>

      <!-- Controls -->
      <div class="mt-3 flex items-center justify-center gap-2 md:gap-3">
        <!-- Speed -->
        <button
          class="px-2 py-1 text-[11px] font-bold rounded-lg border border-indigo-200 text-indigo-600 hover:bg-indigo-50 active:bg-indigo-100 transition-colors min-w-[3rem]"
          @click="cycleSpeed"
          :title="`播放速度 ${playbackRate}x`"
        >
          {{ playbackRate }}x
        </button>

        <!-- Skip back 15s -->
        <button
          class="p-2 rounded-full text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 active:bg-indigo-100 transition-all"
          title="后退15秒"
          @click="skipBackward"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
          </svg>
        </button>

        <!-- Play/Pause -->
        <button
          class="w-12 h-12 flex items-center justify-center rounded-full bg-indigo-500 text-white hover:bg-indigo-600 active:bg-indigo-700 shadow-lg shadow-indigo-200 transition-all"
          :title="isPlaying ? '暂停' : '播放'"
          @click="togglePlay"
        >
          <!-- Loading spinner -->
          <svg v-if="isLoading" class="w-6 h-6 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <!-- Pause -->
          <svg v-else-if="isPlaying" class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
            <path fill-rule="evenodd" d="M6.75 5.25a.75.75 0 01.75-.75H9a.75.75 0 01.75.75v13.5a.75.75 0 01-.75.75H7.5a.75.75 0 01-.75-.75V5.25zm7.5 0A.75.75 0 0115 4.5h1.5a.75.75 0 01.75.75v13.5a.75.75 0 01-.75.75H15a.75.75 0 01-.75-.75V5.25z" clip-rule="evenodd" />
          </svg>
          <!-- Play -->
          <svg v-else class="w-6 h-6 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
            <path fill-rule="evenodd" d="M4.5 5.653c0-1.426 1.529-2.33 2.779-1.643l11.54 6.348c1.295.712 1.295 2.573 0 3.285L7.28 19.991c-1.25.687-2.779-.217-2.779-1.643V5.653z" clip-rule="evenodd" />
          </svg>
        </button>

        <!-- Skip forward 15s -->
        <button
          class="p-2 rounded-full text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 active:bg-indigo-100 transition-all"
          title="前进15秒"
          @click="skipForward"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 15l6-6m0 0l-6-6m6 6H9a6 6 0 000 12h3" />
          </svg>
        </button>

        <!-- Placeholder for symmetry -->
        <div class="min-w-[3rem]"></div>
      </div>
    </div>
  </div>
</template>
