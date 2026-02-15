<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'

const props = defineProps({
  videoUrl: { type: String, required: true },
  title: { type: String, default: '视频播放' },
  aspectRatio: { type: String, default: '16/9' },
})

const iframeRef = ref(null)

/**
 * 检测视频平台
 */
const platform = computed(() => {
  const url = props.videoUrl
  if (!url) return null

  if (url.includes('bilibili.com')) return 'bilibili'
  if (url.includes('youtube.com') || url.includes('youtu.be')) return 'youtube'
  return 'unknown'
})

/**
 * 将视频页面 URL 转换为 embed URL
 */
const embedUrl = computed(() => {
  const url = props.videoUrl
  if (!url) return null

  try {
    // YouTube: watch?v=xxx → embed/xxx
    if (url.includes('youtube.com/watch')) {
      const videoId = new URL(url).searchParams.get('v')
      if (videoId) return `https://www.youtube.com/embed/${videoId}`
    }

    // YouTube Shorts: shorts/xxx → embed/xxx
    if (url.includes('youtube.com/shorts/')) {
      const videoId = url.split('/shorts/')[1].split('?')[0]
      if (videoId) return `https://www.youtube.com/embed/${videoId}`
    }

    // YouTube 短链接: youtu.be/xxx → embed/xxx
    if (url.includes('youtu.be/')) {
      const videoId = url.split('youtu.be/')[1].split('?')[0]
      if (videoId) return `https://www.youtube.com/embed/${videoId}`
    }

    // Bilibili: video/BVxxx → player.bilibili.com/player.html?bvid=BVxxx
    if (url.includes('bilibili.com/video/')) {
      const match = url.match(/video\/(BV[a-zA-Z0-9]+)/)
      if (match) {
        const bvid = match[1]
        return `https://player.bilibili.com/player.html?bvid=${bvid}&autoplay=0&high_quality=1&danmaku=0`
      }
    }

    // 不支持的平台
    return null
  } catch (err) {
    console.error('Failed to parse video URL:', err)
    return null
  }
})

/**
 * 在新窗口打开原始视频链接
 */
function openInPlatform() {
  if (props.videoUrl) {
    window.open(props.videoUrl, '_blank', 'noopener,noreferrer')
  }
}

/**
 * 组件卸载前停止播放
 * 移除 iframe src 来停止音视频播放
 */
onBeforeUnmount(() => {
  if (iframeRef.value) {
    iframeRef.value.src = 'about:blank'
  }
})
</script>

<template>
  <div class="space-y-3">
    <!-- 播放器容器 -->
    <div class="bg-black rounded-xl overflow-hidden" :style="{ aspectRatio }">
      <iframe
        v-if="embedUrl"
        ref="iframeRef"
        :src="embedUrl"
        :title="title"
        class="w-full h-full"
        frameborder="0"
        allowfullscreen
        allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
      />
      <div v-else class="w-full h-full flex items-center justify-center bg-slate-900 text-slate-400">
        <div class="text-center">
          <svg class="w-12 h-12 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <p class="text-sm">不支持的视频平台</p>
        </div>
      </div>
    </div>

    <!-- 原平台观看按钮 -->
    <div v-if="embedUrl" class="flex items-end justify-end px-1">
      <!-- 在原平台观看按钮 -->
      <button
        @click="openInPlatform"
        class="flex-shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-lg transition-colors"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
        </svg>
        <span v-if="platform === 'bilibili'">在 B站 观看</span>
        <span v-else-if="platform === 'youtube'">在 YouTube 观看</span>
        <span v-else>在原平台观看</span>
      </button>
    </div>
  </div>
</template>
