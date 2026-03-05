<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import Artplayer from 'artplayer'
import { saveProgress } from '@/api/video'
import { useToast } from '@/composables/useToast'

const props = defineProps({
  contentId: { type: String, required: true },
  title: { type: String, default: '视频播放' },
  savedPosition: { type: Number, default: 0 },
})

const emit = defineEmits(['error'])
const { info } = useToast()

const containerRef = ref(null)
const hasError = ref(false)
let art = null
let saveInterval = null

function saveCurrentProgress() {
  if (art && props.contentId) {
    const position = Math.floor(art.currentTime || 0)
    if (position > 0) {
      saveProgress(props.contentId, position).catch(() => {})
    }
  }
}

// iOS 检测（包括伪装为 Mac 的 iPadOS 13+）
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)

// PWA standalone 模式检测（iOS standalone WKWebView 禁用了 PIP API）
const isStandalone = window.navigator.standalone === true
  || window.matchMedia('(display-mode: standalone)').matches

// --- 自定义 PIP 逻辑 ---
// Artplayer v5 的 pipMix 在 iOS Safari 15+ 上走标准 requestPictureInPicture 路径，
// 但该 API 在 iOS 上不可靠（经常静默失败）。
// 此外 iOS standalone PWA 完全禁用 PIP API，需降级为"在 Safari 中打开"。

function isPIPActive($video) {
  if (document.pictureInPictureElement === $video) return true
  if ($video.webkitPresentationMode === 'picture-in-picture') return true
  return false
}

async function enterPIP($video) {
  // iOS: 直接用 WebKit API（最可靠）
  if (isIOS && typeof $video.webkitSetPresentationMode === 'function') {
    $video.webkitSetPresentationMode('picture-in-picture')
    return
  }
  // 标准 API
  if (typeof $video.requestPictureInPicture === 'function') {
    try {
      await $video.requestPictureInPicture()
    } catch {
      // 标准 API 失败 → 尝试 WebKit 兜底（iPadOS 等）
      if (typeof $video.webkitSetPresentationMode === 'function') {
        $video.webkitSetPresentationMode('picture-in-picture')
      }
    }
  }
}

async function exitPIP($video) {
  if ($video.webkitPresentationMode === 'picture-in-picture') {
    $video.webkitSetPresentationMode('inline')
    return
  }
  if (document.pictureInPictureElement) {
    await document.exitPictureInPicture().catch(() => {})
  }
}


function init() {
  destroy()
  hasError.value = false
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
      pip: false, // 禁用内置 PIP（在 iOS 上不可靠）
      setting: true,
      playbackRate: true,
      fullscreen: true,
      fullscreenWeb: true,
      aspectRatio: true,
      subtitleOffset: true,
    })

    // 自定义 PIP 控件（兼容 iOS WebKit + 标准 API + PWA standalone 降级）
    const $video = art.template.$video
    const canPIP = document.pictureInPictureEnabled
      || typeof $video.webkitSetPresentationMode === 'function'

    if (isIOS && isStandalone) {
      // iOS standalone PWA: PIP API 不可用，toast 提示用户
      art.controls.add({
        name: 'pip',
        position: 'right',
        index: 30,
        tooltip: '画中画',
        html: art.icons.pip,
        click: () => info('请在 Safari 中打开以使用画中画', { duration: 3000 }),
      })
    } else if (canPIP) {
      art.controls.add({
        name: 'pip',
        position: 'right',
        index: 30,
        tooltip: art.i18n.get('PIP Mode'),
        html: art.icons.pip,
        click: () => {
          if (isPIPActive($video)) {
            exitPIP($video)
          } else {
            enterPIP($video)
          }
        },
      })

      // 同步 PIP 事件到 Artplayer
      $video.addEventListener('enterpictureinpicture', () => art.emit('pip', true))
      $video.addEventListener('leavepictureinpicture', () => art.emit('pip', false))
      if (typeof $video.webkitSetPresentationMode === 'function') {
        $video.addEventListener('webkitpresentationmodechanged', onWebKitPIPChange)
      }
    }

    art.on('error', () => {
      hasError.value = true
      emit('error')
    })
    if (props.savedPosition > 0) {
      art.once('ready', () => {
        art.currentTime = props.savedPosition
      })
    }
    // 每 15 秒自动保存进度 + 切后台时保存
    saveInterval = setInterval(saveCurrentProgress, 15000)
    document.addEventListener('visibilitychange', onVisChange)
  } catch {
    hasError.value = true
    emit('error')
  }
}

function onWebKitPIPChange() {
  if (art) {
    art.emit('pip', art.template.$video.webkitPresentationMode === 'picture-in-picture')
  }
}

function destroy() {
  // 移除 PIP 事件监听（art.destroy() 后 $video 不可访问）
  if (art?.template?.$video) {
    const $video = art.template.$video
    $video.removeEventListener('webkitpresentationmodechanged', onWebKitPIPChange)
  }

  clearInterval(saveInterval)
  saveInterval = null
  document.removeEventListener('visibilitychange', onVisChange)
  saveCurrentProgress()
  if (art) {
    art.destroy()
    art = null
  }
}

function onVisChange() {
  if (document.visibilityState === 'hidden') saveCurrentProgress()
}

onMounted(() => {
  if (props.contentId) init()
})

watch(() => props.contentId, (newId, oldId) => {
  if (newId && newId !== oldId) init()
})

function getCurrentTime() {
  return art?.currentTime ?? 0
}

function isCurrentlyPlaying() {
  return art?.playing ?? false
}

function pausePlayback() {
  if (art) art.pause()
}

defineExpose({ init, destroy, getCurrentTime, isCurrentlyPlaying, pausePlayback })

onBeforeUnmount(() => {
  destroy()
})
</script>

<template>
  <div class="bg-black rounded-xl overflow-hidden">
    <div ref="containerRef" class="aspect-video" :class="{ 'hidden': hasError }"></div>
    <div v-if="hasError" class="aspect-video flex items-center justify-center bg-slate-900">
      <div class="text-center text-slate-400">
        <svg class="w-10 h-10 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" />
        </svg>
        <p class="text-sm font-medium">视频文件未找到</p>
      </div>
    </div>
  </div>
</template>
