<script setup>
import { computed } from 'vue'
import { usePlayerStore } from '@/stores/player'

const playerStore = usePlayerStore()

const progressPercent = computed(() => {
  if (!playerStore.duration) return 0
  return Math.min(100, (playerStore.currentTime / playerStore.duration) * 100)
})

const isVideo = computed(() => playerStore.activeMedia?.kind === 'video')

function formatTime(secs) {
  if (!secs || isNaN(secs)) return '0:00'
  const s = Math.floor(secs)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  return `${m}:${String(sec).padStart(2, '0')}`
}

function onProgressClick(e) {
  if (!playerStore.duration) return
  const bar = e.currentTarget
  const rect = bar.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  playerStore.seek(ratio * playerStore.duration)
}
</script>

<template>
  <Transition
    enter-active-class="transition-transform duration-300 ease-out"
    enter-from-class="translate-y-full"
    enter-to-class="translate-y-0"
    leave-active-class="transition-transform duration-200 ease-in"
    leave-from-class="translate-y-0"
    leave-to-class="translate-y-full"
  >
    <div
      v-if="playerStore.showMiniBar && playerStore.activeMedia"
      class="fixed bottom-0 left-0 right-0 z-40 bg-white border-t border-slate-200 shadow-[0_-4px_24px_rgb(0,0,0,0.08)]"
      style="padding-bottom: env(safe-area-inset-bottom, 0px)"
    >
      <!-- 顶部进度条 -->
      <div
        class="h-1 bg-slate-100 cursor-pointer group"
        @click="onProgressClick"
      >
        <div
          class="h-full bg-indigo-500 transition-all duration-200 group-hover:bg-indigo-600"
          :style="{ width: progressPercent + '%' }"
        />
      </div>

      <!-- 主体 -->
      <div class="flex items-center gap-2 md:gap-3 px-3 md:px-4 py-2.5">
        <!-- 封面/图标 -->
        <div class="shrink-0 w-10 h-10 rounded-lg overflow-hidden bg-slate-100 flex items-center justify-center">
          <img
            v-if="playerStore.activeMedia.thumbnailUrl"
            :src="playerStore.activeMedia.thumbnailUrl"
            class="w-full h-full object-cover"
            @error="$event.target.style.display = 'none'"
          />
          <svg v-else class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347c-.75.412-1.667-.13-1.667-.986V5.653z" />
          </svg>
        </div>

        <!-- 标题 + 进度时间 -->
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-slate-800 truncate leading-snug">
            {{ playerStore.activeMedia.title }}
          </p>
          <p class="text-xs text-slate-400 tabular-nums mt-0.5">
            {{ formatTime(playerStore.currentTime) }}
            <span v-if="playerStore.duration"> / {{ formatTime(playerStore.duration) }}</span>
            <span v-if="isVideo" class="ml-1.5 text-[10px] text-slate-400">{{ playerStore.isPIP ? '· 小窗中' : '· 视频音轨' }}</span>
          </p>
        </div>

        <!-- 后退 15s -->
        <button
          class="shrink-0 w-8 h-8 hidden sm:flex items-center justify-center rounded-lg text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 active:scale-95 transition-all"
          title="后退15秒"
          @click="playerStore.skip(-playerStore.SKIP_SECONDS)"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
          </svg>
        </button>

        <!-- 播放/暂停 -->
        <button
          class="shrink-0 w-9 h-9 flex items-center justify-center rounded-full bg-indigo-600 text-white hover:bg-indigo-700 active:scale-95 transition-all shadow-sm shadow-indigo-200"
          :title="playerStore.isPlaying ? '暂停' : '播放'"
          @click="playerStore.toggle()"
        >
          <!-- 加载中 -->
          <svg v-if="playerStore.isLoading" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <!-- 暂停 -->
          <svg v-else-if="playerStore.isPlaying" class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path fill-rule="evenodd" d="M6.75 5.25a.75.75 0 01.75-.75H9a.75.75 0 01.75.75v13.5a.75.75 0 01-.75.75H7.5a.75.75 0 01-.75-.75V5.25zm7.5 0A.75.75 0 0115 4.5h1.5a.75.75 0 01.75.75v13.5a.75.75 0 01-.75.75H15a.75.75 0 01-.75-.75V5.25z" clip-rule="evenodd" />
          </svg>
          <!-- 播放 -->
          <svg v-else class="w-4 h-4 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
            <path fill-rule="evenodd" d="M4.5 5.653c0-1.426 1.529-2.33 2.779-1.643l11.54 6.348c1.295.712 1.295 2.573 0 3.285L7.28 19.991c-1.25.687-2.779-.217-2.779-1.643V5.653z" clip-rule="evenodd" />
          </svg>
        </button>

        <!-- 前进 15s -->
        <button
          class="shrink-0 w-8 h-8 hidden sm:flex items-center justify-center rounded-lg text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 active:scale-95 transition-all"
          title="前进15秒"
          @click="playerStore.skip(playerStore.SKIP_SECONDS)"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 15l6-6m0 0l-6-6m6 6H9a6 6 0 000 12h3" />
          </svg>
        </button>

        <!-- 画中画（仅视频） -->
        <button
          v-if="playerStore.canPIP"
          class="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg transition-all active:scale-95"
          :class="playerStore.isPIP ? 'text-indigo-600 bg-indigo-50' : 'text-slate-500 hover:text-indigo-600 hover:bg-indigo-50'"
          :title="playerStore.isPIP ? '退出小窗' : '小窗播放'"
          @click="playerStore.togglePIP()"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <rect x="3" y="5" width="18" height="14" rx="2" />
            <rect x="12" y="11" width="7" height="5" rx="1" fill="currentColor" stroke="none" />
          </svg>
        </button>

        <!-- 关闭 -->
        <button
          class="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 active:scale-95 transition-all"
          title="停止播放"
          @click="playerStore.stop()"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  </Transition>
</template>
