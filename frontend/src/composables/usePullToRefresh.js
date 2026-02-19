import { ref, watch, onUnmounted } from 'vue'

/**
 * 下拉刷新 composable（PWA standalone 模式无浏览器手势，需自行实现）
 *
 * @param {Ref} scrollContainerRef - 滚动容器的 ref
 * @param {Object} options
 * @param {Function} options.onRefresh - 刷新回调（async），完成后自动重置
 * @param {number} options.threshold - 触发刷新的最小下拉距离（px），默认 64
 * @returns {{ isPulling: Ref<boolean>, pullDistance: Ref<number>, isRefreshing: Ref<boolean> }}
 */
export function usePullToRefresh(scrollContainerRef, options = {}) {
  const { onRefresh, threshold = 64 } = options

  const isPulling = ref(false)
  const pullDistance = ref(0)
  const isRefreshing = ref(false)

  let startY = 0
  let startX = 0
  let activated = false   // 当前手势是否已激活为下拉刷新
  let locked = false      // 方向锁定：一旦确定为水平滑动则整个手势忽略

  function handleTouchStart(e) {
    if (isRefreshing.value) return
    const el = scrollContainerRef.value
    if (!el || el.scrollTop > 2) return

    startY = e.touches[0].clientY
    startX = e.touches[0].clientX
    activated = false
    locked = false
  }

  function handleTouchMove(e) {
    if (isRefreshing.value || locked) return
    const el = scrollContainerRef.value
    if (!el) return

    const currentY = e.touches[0].clientY
    const currentX = e.touches[0].clientX
    const deltaY = currentY - startY
    const deltaX = currentX - startX

    // 方向判定（首次超过 10px 时锁定）
    if (!activated && Math.abs(deltaY) < 10 && Math.abs(deltaX) < 10) return
    if (!activated) {
      if (Math.abs(deltaX) > Math.abs(deltaY)) {
        // 水平滑动，忽略整个手势
        locked = true
        return
      }
      if (deltaY <= 0) return // 向上滑，忽略
      if (el.scrollTop > 2) return // 非顶部
      activated = true
    }

    if (!activated) return

    e.preventDefault()

    // 阻尼衰减
    let distance = deltaY
    if (distance > threshold) {
      distance = threshold + (distance - threshold) * 0.4
    }
    pullDistance.value = Math.max(0, distance)
    isPulling.value = true
  }

  async function handleTouchEnd() {
    if (!activated || isRefreshing.value) {
      isPulling.value = false
      pullDistance.value = 0
      return
    }

    if (pullDistance.value >= threshold) {
      isRefreshing.value = true
      pullDistance.value = threshold // 保持在阈值位置显示 spinner
      isPulling.value = false
      try {
        if (onRefresh) await onRefresh()
      } finally {
        isRefreshing.value = false
        pullDistance.value = 0
      }
    } else {
      // 未达阈值，回弹
      isPulling.value = false
      pullDistance.value = 0
    }

    activated = false
  }

  // 动态绑定/解绑（同 useSwipe 模式）
  let currentEl = null

  function attachListeners(el) {
    if (!el || el === currentEl) return
    detachListeners()
    currentEl = el
    el.addEventListener('touchstart', handleTouchStart, { passive: true })
    el.addEventListener('touchmove', handleTouchMove, { passive: false })
    el.addEventListener('touchend', handleTouchEnd, { passive: true })
  }

  function detachListeners() {
    if (!currentEl) return
    currentEl.removeEventListener('touchstart', handleTouchStart)
    currentEl.removeEventListener('touchmove', handleTouchMove)
    currentEl.removeEventListener('touchend', handleTouchEnd)
    currentEl = null
  }

  watch(() => scrollContainerRef.value, (el) => {
    if (el) {
      attachListeners(el)
    } else {
      detachListeners()
    }
  }, { immediate: true })

  onUnmounted(() => {
    detachListeners()
  })

  return { isPulling, pullDistance, isRefreshing }
}
