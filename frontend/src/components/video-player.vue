<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import Artplayer from 'artplayer'
import { saveProgress } from '@/api/video'

const props = defineProps({
  contentId: { type: String, required: true },
  title: { type: String, default: '视频播放' },
  savedPosition: { type: Number, default: 0 },
})

const containerRef = ref(null)
let art = null

function init() {
  destroy()
  if (!containerRef.value || !props.contentId) return
  try {
    art = new Artplayer({
      container: containerRef.value,
      url: `/api/video/${props.contentId}/stream`,
      poster: `/api/video/${props.contentId}/thumbnail`,
      title: props.title,
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
    if (props.savedPosition > 0) {
      art.once('ready', () => {
        art.currentTime = props.savedPosition
      })
    }
  } catch {
    // silently fail — container may not be ready
  }
}

function destroy() {
  if (art && props.contentId) {
    const position = Math.floor(art.currentTime || 0)
    if (position > 0) {
      saveProgress(props.contentId, position).catch(() => {})
    }
  }
  if (art) {
    art.destroy()
    art = null
  }
}

onMounted(() => {
  if (props.contentId) init()
})

watch(() => props.contentId, (newId, oldId) => {
  if (newId && newId !== oldId) init()
})

defineExpose({ init, destroy })

onBeforeUnmount(() => {
  destroy()
})
</script>

<template>
  <div class="bg-black rounded-xl overflow-hidden">
    <div ref="containerRef" class="aspect-video"></div>
  </div>
</template>
