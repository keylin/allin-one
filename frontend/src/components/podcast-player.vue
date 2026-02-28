<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import api from '@/api'

const props = defineProps({
  audioUrl: { type: String, required: true },
  title: { type: String, default: '' },
  artworkUrl: { type: String, default: '' },
  duration: { type: String, default: '' },
  episode: { type: String, default: '' },
  contentId: { type: String, default: '' },
  playbackPosition: { type: Number, default: 0 },
})

const audioRef = ref(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const totalDuration = ref(0)
const isLoading = ref(false)
const playbackRate = ref(1)
const isDragging = ref(false)
const progressBarRef = ref(null)

const speeds = [1, 1.25, 1.5, 2]

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

const displayDuration = computed(() => {
  if (totalDuration.value > 0) return formatDuration(totalDuration.value)
  if (props.duration) return props.duration
  return ''
})

const progressPercent = computed(() => {
  if (!totalDuration.value) return 0
  return (currentTime.value / totalDuration.value) * 100
})

function togglePlay() {
  const audio = audioRef.value
  if (!audio) return
  if (isPlaying.value) {
    audio.pause()
  } else {
    audio.play()
  }
}

function cycleSpeed() {
  const idx = speeds.indexOf(playbackRate.value)
  const next = speeds[(idx + 1) % speeds.length]
  playbackRate.value = next
  if (audioRef.value) audioRef.value.playbackRate = next
}

function skipForward() {
  if (audioRef.value) audioRef.value.currentTime = Math.min(audioRef.value.currentTime + 15, audioRef.value.duration || 0)
}

function skipBackward() {
  if (audioRef.value) audioRef.value.currentTime = Math.max(audioRef.value.currentTime - 15, 0)
}

// Progress bar seek
function seekFromEvent(e) {
  const bar = progressBarRef.value
  if (!bar || !audioRef.value) return
  const rect = bar.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  audioRef.value.currentTime = ratio * (audioRef.value.duration || 0)
}

function onProgressMouseDown(e) {
  isDragging.value = true
  seekFromEvent(e)
  document.addEventListener('mousemove', onProgressMouseMove)
  document.addEventListener('mouseup', onProgressMouseUp)
}

function onProgressMouseMove(e) {
  if (isDragging.value) seekFromEvent(e)
}

function onProgressMouseUp() {
  isDragging.value = false
  document.removeEventListener('mousemove', onProgressMouseMove)
  document.removeEventListener('mouseup', onProgressMouseUp)
}

function onProgressTouchStart(e) {
  isDragging.value = true
  seekFromEvent(e.touches[0])
}

function onProgressTouchMove(e) {
  if (isDragging.value) {
    e.preventDefault()
    seekFromEvent(e.touches[0])
  }
}

function onProgressTouchEnd() {
  isDragging.value = false
}

// Audio event handlers
function onPlay() { isPlaying.value = true }
function onPause() { isPlaying.value = false }
function onTimeUpdate() {
  if (!isDragging.value && audioRef.value) {
    currentTime.value = audioRef.value.currentTime
  }
}
function onLoadedMetadata() {
  if (audioRef.value) {
    totalDuration.value = audioRef.value.duration
    isLoading.value = false
  }
}
function onWaiting() { isLoading.value = true }
function onCanPlay() { isLoading.value = false }

// Save playback position via video progress API (reuses existing endpoint)
async function saveProgress() {
  if (!props.contentId || !audioRef.value || currentTime.value < 5) return
  try {
    await api.put(`/media/${props.contentId}/progress`, {
      position: Math.floor(currentTime.value),
    })
  } catch { /* ignore */ }
}

// Restore position from playbackPosition prop on mount
function restorePosition() {
  if (props.playbackPosition > 0 && audioRef.value) {
    audioRef.value.currentTime = props.playbackPosition
    currentTime.value = props.playbackPosition
  }
}

// Precompute iTunes duration as initial total
onMounted(() => {
  if (props.duration) {
    const parsed = parseDuration(props.duration)
    if (parsed > 0) totalDuration.value = parsed
  }
  restorePosition()
})

// Save progress periodically and on unmount
let saveInterval = null
onMounted(() => {
  saveInterval = setInterval(saveProgress, 30000) // every 30s
})

onBeforeUnmount(() => {
  clearInterval(saveInterval)
  saveProgress()
  // Stop audio
  if (audioRef.value) {
    audioRef.value.pause()
    audioRef.value.src = ''
  }
})
</script>

<template>
  <div class="rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50/80 to-white overflow-hidden shadow-sm">
    <!-- Hidden audio element -->
    <audio
      ref="audioRef"
      :src="audioUrl"
      preload="metadata"
      @play="onPlay"
      @pause="onPause"
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onLoadedMetadata"
      @waiting="onWaiting"
      @canplay="onCanPlay"
    />

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
          <!-- Buffered (simple visual hint) -->
          <div
            class="absolute inset-y-0 left-0 bg-indigo-200 rounded-full transition-all"
            :style="{ width: progressPercent + '%' }"
          />
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
