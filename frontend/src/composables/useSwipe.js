import { watch, onUnmounted } from 'vue'

/**
 * 触摸手势处理 composable
 * 滑动过程中直接操作 DOM transform（绕过 Vue 响应式），确保 60fps
 *
 * @param {Ref} targetRef - 目标元素的 ref
 * @param {Object} options
 * @param {number} options.threshold - 触发手势的最小滑动距离（px），默认 80
 * @param {Function} options.onSwipeLeft
 * @param {Function} options.onSwipeRight
 * @param {Function} options.onSwipeUp
 * @param {Function} options.onSwipeDown
 */
export function useSwipe(targetRef, options = {}) {
  const {
    threshold = 80,
    onSwipeLeft,
    onSwipeRight,
    onSwipeUp,
    onSwipeDown
  } = options

  // 全部用普通变量，touchmove 不触发 Vue 响应式
  let startX = 0
  let startY = 0
  let endX = 0
  let endY = 0
  let swiping = false
  let directionLocked = false // 方向已锁定
  let isHorizontal = false    // 锁定为水平方向

  const handleTouchStart = (e) => {
    const x = e.touches[0].clientX
    // 排除屏幕左右边缘 30px——让给浏览器原生前进/后退手势
    if (x < 30 || x > window.innerWidth - 30) return

    startX = x
    startY = e.touches[0].clientY
    endX = x
    endY = startY
    swiping = true
    directionLocked = false
    isHorizontal = false

    const el = currentEl
    if (el) {
      el.style.willChange = 'transform'
      // 清除可能残留的 transition，让拖拽即时响应
      el.style.transition = 'none'
    }
  }

  const handleTouchMove = (e) => {
    if (!swiping) return

    endX = e.touches[0].clientX
    endY = e.touches[0].clientY

    const deltaX = endX - startX
    const deltaY = endY - startY

    // 首次超过 10px 时锁定方向
    if (!directionLocked && (Math.abs(deltaX) > 10 || Math.abs(deltaY) > 10)) {
      directionLocked = true
      isHorizontal = Math.abs(deltaX) > Math.abs(deltaY)
    }

    // 水平滑动时直接操作 DOM（只允许右滑）
    if (directionLocked && isHorizontal && currentEl) {
      const offset = Math.max(0, deltaX)
      currentEl.style.transform = `translateX(${offset}px)`
    }
  }

  const handleTouchEnd = () => {
    if (!swiping) return
    swiping = false

    const deltaX = endX - startX
    const deltaY = endY - startY
    const el = currentEl

    const absDx = Math.abs(deltaX)
    const absDy = Math.abs(deltaY)

    let triggered = false

    if (absDx > absDy) {
      // 水平手势
      if (deltaX > threshold && onSwipeRight) {
        triggered = true
        // 滑出动画：继续向右滑出屏幕
        if (el) {
          let fired = false
          const fire = () => {
            if (fired) return
            fired = true
            // 不 cleanupEl — 元素保持屏幕外，由 Vue 卸载
            onSwipeRight()
          }
          el.style.transition = 'transform 0.15s ease-in'
          el.style.transform = `translateX(${window.innerWidth}px)`
          el.addEventListener('transitionend', fire, { once: true })
          // 兜底：180ms 后强制触发，防止 transitionend 不触发
          setTimeout(fire, 180)
        } else {
          onSwipeRight()
        }
      } else if (deltaX < -threshold && onSwipeLeft) {
        triggered = true
        onSwipeLeft()
      }
    } else {
      if (deltaY > threshold && onSwipeDown) {
        triggered = true
        onSwipeDown()
      } else if (deltaY < -threshold && onSwipeUp) {
        triggered = true
        onSwipeUp()
      }
    }

    // 未触发手势 → 回弹动画
    if (!triggered && el) {
      el.style.transition = 'transform 0.2s ease-out'
      el.style.transform = ''
      const onEnd = () => {
        el.removeEventListener('transitionend', onEnd)
        cleanupEl(el)
      }
      el.addEventListener('transitionend', onEnd, { once: true })
      setTimeout(() => cleanupEl(el), 220)
    }
  }

  function cleanupEl(el) {
    if (!el) return
    el.style.willChange = ''
    el.style.transition = ''
    el.style.transform = ''
  }

  // 动态绑定/解绑：targetRef 可能由 v-if 延迟渲染
  let currentEl = null

  function attachListeners(el) {
    if (!el || el === currentEl) return
    detachListeners()
    currentEl = el
    el.addEventListener('touchstart', handleTouchStart, { passive: true })
    el.addEventListener('touchmove', handleTouchMove, { passive: true })
    el.addEventListener('touchend', handleTouchEnd, { passive: true })
  }

  function detachListeners() {
    if (currentEl) {
      cleanupEl(currentEl)
      currentEl.removeEventListener('touchstart', handleTouchStart)
      currentEl.removeEventListener('touchmove', handleTouchMove)
      currentEl.removeEventListener('touchend', handleTouchEnd)
    }
    currentEl = null
  }

  watch(() => targetRef.value, (el) => {
    if (el) {
      attachListeners(el)
    } else {
      detachListeners()
    }
  }, { immediate: true })

  onUnmounted(() => {
    detachListeners()
  })
}
