import { ref, computed, reactive } from 'vue'
import { defineStore } from 'pinia'
import api from '@/api'
import { useToast } from '@/composables/useToast'

/**
 * 全局播放器 Store —— 音频/视频后台播放的唯一所有者。
 *
 * - 媒体元素放在 module-level（非 ref），避免 Vue 代理 DOM 对象
 * - 音频用 <audio>（iOS 锁屏/切后台可继续播放），视频用挂在 body 上的隐藏 <video>
 *   （HTMLVideoElement 才能进画中画，元素常驻 App 级别，切路由/关面板不中断）
 * - 内嵌播放器（PodcastPlayer）不再自带 <audio>，而是把播放请求交给本 store，
 *   自身只作为"当前进度的视图 + 控制面板"；面板关闭/切换条目时播放自然延续
 * - 视频内嵌播放器（Artplayer）销毁时若仍在播放，把音轨 handoff 到全局 <video>，
 *   底部迷你播放条可继续控制，并提供画中画入口
 * - Media Session：锁屏/系统媒体控件显示标题封面，支持播放/暂停/±15s/拖动
 */

const SKIP_SECONDS = 15
const RATE_STORAGE_KEY = 'player.playbackRate'
const LOAD_TIMEOUT_MS = 15000

let audioEl = null
let videoEl = null
// 当前承载播放的元素（audioEl 或 videoEl）
let currentEl = null

function getAudioEl() {
  if (!audioEl) {
    audioEl = new Audio()
    audioEl.preload = 'auto'
  }
  return audioEl
}

function getVideoEl() {
  if (!videoEl) {
    videoEl = document.createElement('video')
    videoEl.preload = 'auto'
    videoEl.setAttribute('playsinline', '')
    videoEl.setAttribute('webkit-playsinline', '')
    // 不能 display:none —— 部分浏览器对不渲染的 video 不允许进画中画；放到视口外即可
    Object.assign(videoEl.style, {
      position: 'fixed',
      width: '1px',
      height: '1px',
      left: '-9999px',
      top: '0',
      opacity: '0',
      pointerEvents: 'none',
    })
    document.body.appendChild(videoEl)
  }
  return videoEl
}

function readStoredRate() {
  try {
    const v = parseFloat(localStorage.getItem(RATE_STORAGE_KEY))
    return v > 0 && v <= 4 ? v : 1
  } catch {
    return 1
  }
}

// iOS 检测（含伪装为 Mac 的 iPadOS）
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
// iOS standalone PWA 禁用了 PIP API
const isStandalone = window.navigator.standalone === true
  || !!window.matchMedia?.('(display-mode: standalone)').matches

export const usePlayerStore = defineStore('player', () => {
  // { contentId, kind: 'audio' | 'video', title, artist, streamUrl, thumbnailUrl, progressPath }
  const activeMedia = ref(null)
  const isPlaying = ref(false)
  const isLoading = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  const playbackRate = ref(readStoredRate())
  const isPIP = ref(false)

  // 内嵌播放器可见性登记：instanceId -> { contentId, visible }
  // 当前内容的内嵌播放器在视口内时隐藏迷你播放条，避免双份控件
  const inlinePlayers = reactive(new Map())

  const inlineVisibleForActive = computed(() => {
    const id = activeMedia.value?.contentId
    if (!id) return false
    for (const p of inlinePlayers.values()) {
      if (p.visible && p.contentId === id) return true
    }
    return false
  })

  const showMiniBar = computed(() => !!activeMedia.value && !inlineVisibleForActive.value)

  // 画中画能力（仅视频）
  const canPIP = computed(() => {
    if (activeMedia.value?.kind !== 'video') return false
    if (isIOS && isStandalone) return false
    if (document.pictureInPictureEnabled) return true
    return typeof getVideoEl().webkitSetPresentationMode === 'function'
  })

  let saveInterval = null
  // 并发加载保护：每次 load 递增，await 后校验是否仍为当前代
  let loadGen = 0
  let lastPositionStateAt = 0

  // ---- 媒体元素事件 ----

  function onTimeUpdate() {
    if (!currentEl) return
    currentTime.value = currentEl.currentTime
    duration.value = isFinite(currentEl.duration) ? currentEl.duration : 0
    updatePositionState()
  }
  function onDurationChange() {
    if (!currentEl) return
    duration.value = isFinite(currentEl.duration) ? currentEl.duration : 0
  }
  function onPlay() {
    isPlaying.value = true
    isLoading.value = false
    setPlaybackState('playing')
  }
  function onPause() {
    isPlaying.value = false
    setPlaybackState('paused')
  }
  function onWaiting() { isLoading.value = true }
  function onPlaying() { isLoading.value = false }
  function onEnded() {
    isPlaying.value = false
    saveProgress()
  }
  function onEnterPIP() { isPIP.value = true }
  function onLeavePIP() { isPIP.value = false }
  function onWebKitPresentationChange() {
    isPIP.value = currentEl?.webkitPresentationMode === 'picture-in-picture'
  }

  const listeners = [
    ['timeupdate', onTimeUpdate],
    ['durationchange', onDurationChange],
    ['loadedmetadata', onDurationChange],
    ['play', onPlay],
    ['pause', onPause],
    ['waiting', onWaiting],
    ['playing', onPlaying],
    ['ended', onEnded],
    ['enterpictureinpicture', onEnterPIP],
    ['leavepictureinpicture', onLeavePIP],
    ['webkitpresentationmodechanged', onWebKitPresentationChange],
  ]

  function bindEvents(el) {
    for (const [evt, fn] of listeners) el.addEventListener(evt, fn)
  }

  function unbindEvents(el) {
    if (!el) return
    for (const [evt, fn] of listeners) el.removeEventListener(evt, fn)
  }

  // ---- 进度保存 ----

  function startSaveInterval() {
    stopSaveInterval()
    saveInterval = setInterval(saveProgress, 15000)
    document.addEventListener('visibilitychange', onVisChange)
    window.addEventListener('pagehide', saveProgress)
  }

  function stopSaveInterval() {
    if (saveInterval) {
      clearInterval(saveInterval)
      saveInterval = null
    }
    document.removeEventListener('visibilitychange', onVisChange)
    window.removeEventListener('pagehide', saveProgress)
  }

  function onVisChange() {
    if (document.visibilityState === 'hidden') saveProgress()
  }

  function saveProgress() {
    const media = activeMedia.value
    if (!media?.contentId || !currentEl) return
    const pos = Math.floor(currentEl.currentTime || 0)
    if (pos < 3) return
    api.put(media.progressPath, { position: pos }).catch(() => {})
  }

  // ---- Media Session（锁屏 / 系统媒体控件）----

  function setPlaybackState(state) {
    try {
      if ('mediaSession' in navigator) navigator.mediaSession.playbackState = state
    } catch { /* ignore */ }
  }

  function updatePositionState() {
    if (!('mediaSession' in navigator) || !currentEl) return
    const now = Date.now()
    if (now - lastPositionStateAt < 1000) return
    lastPositionStateAt = now
    const dur = currentEl.duration
    if (!isFinite(dur) || dur <= 0) return
    try {
      navigator.mediaSession.setPositionState({
        duration: dur,
        playbackRate: currentEl.playbackRate || 1,
        position: Math.min(currentEl.currentTime || 0, dur),
      })
    } catch { /* ignore */ }
  }

  function setActionHandler(action, handler) {
    try {
      navigator.mediaSession.setActionHandler(action, handler)
    } catch { /* 浏览器不支持该 action */ }
  }

  function updateMediaSession() {
    if (!('mediaSession' in navigator)) return
    const media = activeMedia.value
    if (!media) {
      try { navigator.mediaSession.metadata = null } catch { /* ignore */ }
      setPlaybackState('none')
      return
    }
    try {
      const artwork = []
      if (media.thumbnailUrl) {
        artwork.push({ src: new URL(media.thumbnailUrl, window.location.origin).href })
      }
      navigator.mediaSession.metadata = new MediaMetadata({
        title: media.title || '',
        artist: media.artist || 'Allin-One',
        artwork,
      })
    } catch { /* ignore */ }
    setActionHandler('play', () => play())
    setActionHandler('pause', () => pause())
    setActionHandler('stop', () => stop())
    setActionHandler('seekbackward', (d) => skip(-(d?.seekOffset || SKIP_SECONDS)))
    setActionHandler('seekforward', (d) => skip(d?.seekOffset || SKIP_SECONDS))
    setActionHandler('seekto', (d) => {
      if (typeof d?.seekTime === 'number') seek(d.seekTime)
    })
  }

  // ---- 加载 / 播放控制 ----

  function normalizeKind(kind) {
    return kind === 'video' ? 'video' : 'audio'
  }

  function isSameMedia(info) {
    const cur = activeMedia.value
    return !!cur && cur.contentId === info.contentId && cur.kind === normalizeKind(info.kind)
  }

  function waitUntilPlayable(el) {
    return new Promise((resolve) => {
      let done = false
      const finish = (ok) => {
        if (done) return
        done = true
        el.removeEventListener('canplay', onCanPlay)
        el.removeEventListener('error', onError)
        clearTimeout(timer)
        resolve(ok)
      }
      const onCanPlay = () => finish(true)
      const onError = () => finish(false)
      const timer = setTimeout(() => finish(true), LOAD_TIMEOUT_MS)
      el.addEventListener('canplay', onCanPlay)
      el.addEventListener('error', onError)
      if (el.readyState >= 3) finish(true)
    })
  }

  /**
   * 加载并（默认）播放一段媒体。若与当前媒体相同则直接续播，不重新加载。
   * @param {object} info - { contentId, kind, title, artist, streamUrl, thumbnailUrl, position, progressPath, pip }
   * @param {object} [opts] - { autoplay = true }
   */
  async function load(info, { autoplay = true } = {}) {
    const kind = normalizeKind(info.kind)

    if (isSameMedia(info) && currentEl?.src) {
      if (typeof info.position === 'number' && Math.abs(info.position - currentEl.currentTime) > 1.5) {
        seek(info.position)
      }
      if (autoplay) await play()
      return
    }

    const gen = ++loadGen

    // 保存上一个媒体的进度并释放其元素
    if (activeMedia.value && currentEl) {
      const pos = Math.floor(currentEl.currentTime || 0)
      if (pos >= 3) api.put(activeMedia.value.progressPath, { position: pos }).catch(() => {})
    }
    stopSaveInterval()
    if (currentEl) {
      exitPIP()
      unbindEvents(currentEl)
      currentEl.pause()
      currentEl.removeAttribute('src')
      currentEl.load()
    }

    const el = kind === 'video' ? getVideoEl() : getAudioEl()
    currentEl = el
    bindEvents(el)

    activeMedia.value = {
      contentId: info.contentId,
      kind,
      title: info.title || '',
      artist: info.artist || '',
      streamUrl: info.streamUrl,
      thumbnailUrl: info.thumbnailUrl || '',
      progressPath: info.progressPath,
    }
    isPIP.value = false
    isLoading.value = true
    isPlaying.value = false
    currentTime.value = info.position || 0
    duration.value = 0

    el.playbackRate = playbackRate.value
    el.src = info.streamUrl
    el.load()
    updateMediaSession()

    // 起播位置：元数据就绪后再 seek（就绪前设置 currentTime 在 iOS 上会被忽略）
    if (info.position > 0) {
      const applyPosition = () => {
        if (gen !== loadGen) return
        try { el.currentTime = info.position } catch { /* ignore */ }
      }
      if (el.readyState >= 1) applyPosition()
      else el.addEventListener('loadedmetadata', applyPosition, { once: true })
    }

    // play() 必须在用户手势的同步调用栈内发起，否则 iOS Safari 会以 NotAllowedError 拒绝首次播放；
    // 浏览器会自行等待数据就绪，不必先 await canplay
    let playPromise = null
    if (autoplay) {
      playPromise = el.play().then(() => true, () => false)
    }

    const ok = await waitUntilPlayable(el)
    if (gen !== loadGen) return

    if (!ok) {
      useToast().error(kind === 'video' ? '视频加载失败，无法后台播放' : '音频加载失败')
      stop()
      return
    }

    isLoading.value = false
    startSaveInterval()

    if (playPromise) {
      const played = await playPromise
      if (gen !== loadGen) return
      if (!played) {
        // 多为自动播放策略拦截：保留已加载状态，等用户点播放
        isLoading.value = false
        isPlaying.value = false
        return
      }
      if (info.pip && kind === 'video') enterPIP()
    }
  }

  /** 内嵌播放器销毁时把播放移交给全局（load 的别名，语义化命名） */
  function handoff(info) {
    return load(info, { autoplay: true })
  }

  async function play() {
    if (!currentEl || !activeMedia.value) return
    try {
      await currentEl.play()
    } catch { /* ignore */ }
  }

  function pause() {
    currentEl?.pause()
  }

  function toggle() {
    if (isPlaying.value) pause()
    else play()
  }

  function seek(t) {
    if (!currentEl) return
    const dur = isFinite(currentEl.duration) && currentEl.duration > 0 ? currentEl.duration : Infinity
    const target = Math.max(0, Math.min(t, dur))
    try { currentEl.currentTime = target } catch { /* ignore */ }
    currentTime.value = target
    lastPositionStateAt = 0
    updatePositionState()
  }

  function skip(delta) {
    if (!currentEl) return
    seek((currentEl.currentTime || 0) + delta)
  }

  function setRate(rate) {
    playbackRate.value = rate
    if (currentEl) currentEl.playbackRate = rate
    try { localStorage.setItem(RATE_STORAGE_KEY, String(rate)) } catch { /* ignore */ }
  }

  // ---- 画中画（仅视频）----

  async function enterPIP() {
    if (!canPIP.value || !videoEl || currentEl !== videoEl) return
    if (isIOS && typeof videoEl.webkitSetPresentationMode === 'function') {
      videoEl.webkitSetPresentationMode('picture-in-picture')
      return
    }
    if (typeof videoEl.requestPictureInPicture === 'function') {
      try {
        await videoEl.requestPictureInPicture()
      } catch {
        if (typeof videoEl.webkitSetPresentationMode === 'function') {
          videoEl.webkitSetPresentationMode('picture-in-picture')
        }
      }
    }
  }

  async function exitPIP() {
    if (!videoEl) return
    if (videoEl.webkitPresentationMode === 'picture-in-picture') {
      videoEl.webkitSetPresentationMode('inline')
      return
    }
    if (document.pictureInPictureElement === videoEl) {
      await document.exitPictureInPicture().catch(() => {})
    }
  }

  function togglePIP() {
    if (isPIP.value) exitPIP()
    else enterPIP()
  }

  // ---- 停止 ----

  function stop() {
    ++loadGen
    const media = activeMedia.value
    if (currentEl) {
      const pos = Math.floor(currentEl.currentTime || 0)
      if (media?.contentId && pos >= 3) {
        api.put(media.progressPath, { position: pos }).catch(() => {})
      }
    }
    stopSaveInterval()
    if (currentEl) {
      exitPIP()
      unbindEvents(currentEl)
      currentEl.pause()
      currentEl.removeAttribute('src')
      currentEl.load()
      currentEl = null
    }
    activeMedia.value = null
    isPlaying.value = false
    isLoading.value = false
    isPIP.value = false
    currentTime.value = 0
    duration.value = 0
    updateMediaSession()
  }

  // ---- 内嵌播放器登记 ----

  function registerInline(instanceId, contentId, visible) {
    inlinePlayers.set(instanceId, { contentId, visible: !!visible })
  }

  function unregisterInline(instanceId) {
    inlinePlayers.delete(instanceId)
  }

  function isActive(contentId, kind = 'audio') {
    return !!activeMedia.value && activeMedia.value.contentId === contentId && activeMedia.value.kind === kind
  }

  return {
    activeMedia,
    isPlaying,
    isLoading,
    currentTime,
    duration,
    playbackRate,
    isPIP,
    canPIP,
    showMiniBar,
    load,
    handoff,
    play,
    resume: play,
    pause,
    toggle,
    seek,
    skip,
    setRate,
    enterPIP,
    exitPIP,
    togglePIP,
    stop,
    saveProgress,
    registerInline,
    unregisterInline,
    isActive,
    SKIP_SECONDS,
  }
})
