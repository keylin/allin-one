import { watch, onUnmounted } from 'vue'

// 这些目标上的双击不触发关闭
const INTERACTIVE_SELECTOR = 'a, button, input, textarea, select, img, video, audio, [role="button"]'

/**
 * 双击关闭 composable（仅移动端 < 768px）
 *
 * 在目标元素上监听 touchend，300ms 内两次点击且位置偏差 ≤ 30px 视为双击。
 *
 * @param {Ref} targetRef - 绑定目标元素
 * @param {Object} options
 * @param {Function} options.onClose - 双击时调用
 */
export function useDoubleTapClose(targetRef, options = {}) {
  const { onClose } = options

  let lastTapTime = 0
  let lastTapX = 0
  let lastTapY = 0

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
      // 双击确认 → 触发关闭
      if (onClose) onClose()

      // 触觉反馈
      if (navigator.vibrate) navigator.vibrate(50)

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
}
