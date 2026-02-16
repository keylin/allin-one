import { ref, onMounted, onUnmounted } from 'vue'

/**
 * 触摸手势处理 composable
 * 用于检测滑动手势（左/右/上/下）
 *
 * @param {Ref} targetRef - 目标元素的 ref
 * @param {Object} options - 配置选项
 * @param {number} options.threshold - 触发手势的最小滑动距离（px），默认 80
 * @param {Function} options.onSwipeLeft - 左滑回调
 * @param {Function} options.onSwipeRight - 右滑回调
 * @param {Function} options.onSwipeUp - 上滑回调
 * @param {Function} options.onSwipeDown - 下滑回调
 * @returns {Object} { isSwiping, swipeOffset }
 */
export function useSwipe(targetRef, options = {}) {
  const {
    threshold = 80,
    onSwipeLeft,
    onSwipeRight,
    onSwipeUp,
    onSwipeDown
  } = options

  const touchStartX = ref(0)
  const touchStartY = ref(0)
  const touchEndX = ref(0)
  const touchEndY = ref(0)
  const isSwiping = ref(false)
  const swipeOffset = ref(0)

  const handleTouchStart = (e) => {
    touchStartX.value = e.touches[0].clientX
    touchStartY.value = e.touches[0].clientY
    isSwiping.value = true
  }

  const handleTouchMove = (e) => {
    if (!isSwiping.value) return

    touchEndX.value = e.touches[0].clientX
    touchEndY.value = e.touches[0].clientY

    const deltaX = touchEndX.value - touchStartX.value
    const deltaY = touchEndY.value - touchStartY.value

    // 水平滑动时更新偏移（只允许右滑，负值置为0）
    if (Math.abs(deltaX) > Math.abs(deltaY)) {
      swipeOffset.value = Math.max(0, deltaX)
    }
  }

  const handleTouchEnd = () => {
    if (!isSwiping.value) return

    const deltaX = touchEndX.value - touchStartX.value
    const deltaY = touchEndY.value - touchStartY.value

    // 水平优先判断
    if (Math.abs(deltaX) > Math.abs(deltaY)) {
      if (deltaX > threshold && onSwipeRight) {
        onSwipeRight()
      } else if (deltaX < -threshold && onSwipeLeft) {
        onSwipeLeft()
      }
    } else {
      // 垂直滑动
      if (deltaY > threshold && onSwipeDown) {
        onSwipeDown()
      } else if (deltaY < -threshold && onSwipeUp) {
        onSwipeUp()
      }
    }

    // 重置状态
    isSwiping.value = false
    swipeOffset.value = 0
    touchStartX.value = 0
    touchStartY.value = 0
    touchEndX.value = 0
    touchEndY.value = 0
  }

  onMounted(() => {
    const el = targetRef.value
    if (!el) return

    // 使用 passive: true 提升滚动性能
    el.addEventListener('touchstart', handleTouchStart, { passive: true })
    el.addEventListener('touchmove', handleTouchMove, { passive: true })
    el.addEventListener('touchend', handleTouchEnd, { passive: true })
  })

  onUnmounted(() => {
    const el = targetRef.value
    if (!el) return

    el.removeEventListener('touchstart', handleTouchStart)
    el.removeEventListener('touchmove', handleTouchMove)
    el.removeEventListener('touchend', handleTouchEnd)
  })

  return { isSwiping, swipeOffset }
}
