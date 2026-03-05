import { ref } from 'vue'
import { defineStore } from 'pinia'
import api from '@/api'
import { useToast } from '@/composables/useToast'

// Module-level Audio instance — NOT in Vue reactive system to avoid overhead/proxy issues
let audioEl = null

function getAudio() {
  if (!audioEl) {
    audioEl = new Audio()
    audioEl.preload = 'auto'
  }
  return audioEl
}

export const usePlayerStore = defineStore('player', () => {
  // { contentId, title, streamUrl, thumbnailUrl, progressPath }
  const activeMedia = ref(null)
  const isPlaying = ref(false)
  const isLoading = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  // 'mini' = 底部播放条显示, 'hidden' = 不显示
  const displayMode = ref('hidden')

  let saveInterval = null
  // 并发 handoff 保护：每次 handoff 递增，await 后校验是否仍为当前代
  let handoffGen = 0

  function bindAudioEvents() {
    const audio = getAudio()
    audio.ontimeupdate = () => {
      currentTime.value = audio.currentTime
      duration.value = isFinite(audio.duration) ? audio.duration : 0
    }
    audio.onplay = () => { isPlaying.value = true; isLoading.value = false }
    audio.onpause = () => { isPlaying.value = false }
    audio.onended = () => {
      isPlaying.value = false
      saveProgress()
    }
  }

  function unbindAudioEvents() {
    const audio = getAudio()
    audio.ontimeupdate = null
    audio.onplay = null
    audio.onpause = null
    audio.onended = null
  }

  function startSaveInterval() {
    stopSaveInterval()
    saveInterval = setInterval(saveProgress, 15000)
    document.addEventListener('visibilitychange', onVisChange)
  }

  function stopSaveInterval() {
    if (saveInterval) {
      clearInterval(saveInterval)
      saveInterval = null
    }
    document.removeEventListener('visibilitychange', onVisChange)
  }

  function onVisChange() {
    if (document.visibilityState === 'hidden') saveProgress()
  }

  async function saveProgress() {
    const media = activeMedia.value
    if (!media?.contentId || !audioEl) return
    const pos = Math.floor(audioEl.currentTime || 0)
    if (pos < 3) return
    try {
      await api.put(media.progressPath, { position: pos })
    } catch { /* ignore */ }
  }

  /**
   * 关闭弹窗时接管播放 — 从 VideoPlayer/PodcastPlayer 提取进度，用全局 audio 继续播放音轨
   * @param {object} mediaInfo - { contentId, title, streamUrl, thumbnailUrl, position, progressPath }
   */
  async function handoff(mediaInfo) {
    const gen = ++handoffGen

    // 保存上一个媒体的进度
    if (activeMedia.value) {
      // 先快照进度再清理，防止 src 被清空后 currentTime 归零
      const pos = Math.floor(audioEl?.currentTime || 0)
      stopSaveInterval()
      if (pos >= 3) {
        api.put(activeMedia.value.progressPath, { position: pos }).catch(() => {})
      }
    }

    const audio = getAudio()
    unbindAudioEvents()
    bindAudioEvents()

    activeMedia.value = {
      contentId: mediaInfo.contentId,
      title: mediaInfo.title,
      streamUrl: mediaInfo.streamUrl,
      thumbnailUrl: mediaInfo.thumbnailUrl || '',
      progressPath: mediaInfo.progressPath,
    }
    displayMode.value = 'mini'
    isLoading.value = true
    currentTime.value = mediaInfo.position || 0
    duration.value = 0

    // 加载音频流
    audio.src = mediaInfo.streamUrl
    audio.load()

    try {
      let loadFailed = false
      await new Promise((resolve) => {
        const onCanPlay = () => { cleanup(); resolve() }
        const onError = () => { cleanup(); loadFailed = true; resolve() }
        const cleanup = () => {
          audio.removeEventListener('canplay', onCanPlay)
          audio.removeEventListener('error', onError)
        }
        audio.addEventListener('canplay', onCanPlay)
        audio.addEventListener('error', onError)
        setTimeout(() => { cleanup(); resolve() }, 10000)
      })

      // 并发保护：若在 await 期间又触发了新 handoff，放弃本次
      if (gen !== handoffGen) return

      if (loadFailed) {
        const { error } = useToast()
        error('音频加载失败，无法后台播放')
        stop()
        return
      }

      if (mediaInfo.position > 0) {
        audio.currentTime = mediaInfo.position
      }
      await audio.play()
      if (gen !== handoffGen) return

      isLoading.value = false
      startSaveInterval()
    } catch {
      if (gen !== handoffGen) return
      const { error } = useToast()
      error('音频播放失败，无法后台播放')
      stop()
    }
  }

  function pause() {
    getAudio().pause()
  }

  function resume() {
    getAudio().play().catch(() => {})
  }

  function seek(t) {
    const audio = getAudio()
    audio.currentTime = t
    currentTime.value = t
  }

  function stop() {
    ++handoffGen // 取消进行中的 handoff
    // 先快照进度再清空 src
    const pos = Math.floor(audioEl?.currentTime || 0)
    stopSaveInterval()
    const media = activeMedia.value
    if (media?.contentId && pos >= 3) {
      api.put(media.progressPath, { position: pos }).catch(() => {})
    }
    const audio = getAudio()
    audio.pause()
    audio.src = ''
    unbindAudioEvents()
    activeMedia.value = null
    isPlaying.value = false
    isLoading.value = false
    currentTime.value = 0
    duration.value = 0
    displayMode.value = 'hidden'
  }

  return {
    activeMedia,
    isPlaying,
    isLoading,
    currentTime,
    duration,
    displayMode,
    handoff,
    pause,
    resume,
    seek,
    stop,
    saveProgress,
  }
})
