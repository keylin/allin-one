import { ref, watch, onUnmounted } from 'vue'

// 这些目标上的双击不触发收藏
const INTERACTIVE_SELECTOR = 'a, button, input, textarea, select, img, video, audio, [role="button"]'

/**
 * 双击收藏 composable（仅移动端 < 768px）
 *
 * 在目标元素上监听 touchend，300ms 内两次点击且位置偏差 ≤ 30px 视为双击。
 *
 * @param {Ref} targetRef - 绑定目标元素
 * @param {Object} options
 * @param {Function} options.onFavorite - 双击时调用
 * @returns {{ heartVisible, heartX, heartY }} - 爱心动画位置（视口坐标，配合 fixed 定位使用）
 */
export function useDoubleTapFavorite(targetRef, options = {}) {
  const { onFavorite } = options

  const heartVisible = ref(false)
  const heartX = ref(0)
  const heartY = ref(0)

  let lastTapTime = 0
  let lastTapX = 0
  let lastTapY = 0
  let heartTimer = null

  function handleTouchEnd(e) {
    // 仅移动端
    if (window.innerWidth >= 768) return

    const touch = e.changedTouches[0]
    if (!touch) return

    // 排除交互元素（链接、按钮、图片等）
    if (e.target.closest(INTERACTIVE_SELECTOR)) return

    const now = Date.now()
    const x = touch.clientX
    const y = touch.clientY
    const delta = now - lastTapTime
    const dist = Math.sqrt((x - lastTapX) ** 2 + (y - lastTapY) ** 2)

    if (delta > 0 && delta < 300 && dist <= 30) {
      // 双击确认 → 触发收藏
      if (onFavorite) onFavorite()

      // 爱心显示在点击位置（视口坐标，配合 fixed 定位使用）
      heartX.value = x
      heartY.value = y
      heartVisible.value = true

      // 触觉反馈
      if (navigator.vibrate) navigator.vibrate(50)

      clearTimeout(heartTimer)
      heartTimer = setTimeout(() => {
        heartVisible.value = false
      }, 800)

      // 重置，防止三连击
      lastTapTime = 0
    } else {
      lastTapTime = now
      lastTapX = x
      lastTapY = y
    }
  }

  let currentEl = null

  function attach(el) {
    if (!el || el === currentEl) return
    detach()
    currentEl = el
    el.addEventListener('touchend', handleTouchEnd, { passive: true })
  }

  function detach() {
    if (currentEl) {
      currentEl.removeEventListener('touchend', handleTouchEnd)
      currentEl = null
    }
    clearTimeout(heartTimer)
  }

  watch(
    () => targetRef.value,
    (el) => {
      if (el) attach(el)
      else detach()
    },
    { immediate: true }
  )

  onUnmounted(detach)

  return { heartVisible, heartX, heartY }
}
