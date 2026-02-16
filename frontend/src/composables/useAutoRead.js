import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useIntersectionObserver } from '@/composables/useIntersectionObserver'
import { useDebounce } from '@/composables/useDebounce'
import { batchMarkRead } from '@/api/content'

/**
 * 自动标记已读 composable
 * 通过 IntersectionObserver 检测卡片滚出视野后自动标记已读
 *
 * @param {Object} options
 * @param {Ref} options.items - 内容列表 ref
 * @param {Ref} options.leftPanelRef - 左栏滚动容器 ref
 * @param {Function} options.loadStats - 刷新统计数据的回调
 * @returns {Object}
 */
export function useAutoRead({ items, leftPanelRef, loadStats }) {
  const hasScrolled = ref(false)
  const pendingReadIds = ref(new Set())
  const cardPositions = ref(new Map())
  const autoActivateTimer = ref(null)
  const AUTO_ACTIVATE_DELAY = 3000

  // --- IntersectionObserver 回调 ---
  function handleCardVisible(entry) {
    if (!hasScrolled.value) return

    const itemId = entry.target.dataset.itemId
    const item = items.value.find(i => i.id === itemId)

    if (!item || (item.view_count || 0) > 0) {
      cardPositions.value.delete(itemId)
      return
    }

    const currentY = entry.boundingClientRect.top
    const lastY = cardPositions.value.get(itemId)

    if (entry.isIntersecting) {
      cardPositions.value.set(itemId, currentY)
    } else {
      if (lastY !== undefined) {
        const isMovingUp = currentY < lastY
        if (isMovingUp) {
          markAsRead(itemId)
        }
      }
      cardPositions.value.delete(itemId)
    }
  }

  // 标记单个 item 为已读（加入批量队列）
  function markAsRead(itemId) {
    if (!pendingReadIds.value.has(itemId)) {
      pendingReadIds.value.add(itemId)
      debouncedBatchSubmit()
    }
  }

  // 防抖批量提交已读
  const debouncedBatchSubmit = useDebounce(async () => {
    if (pendingReadIds.value.size === 0) return

    const ids = Array.from(pendingReadIds.value)
    pendingReadIds.value.clear()

    try {
      await batchMarkRead(ids)

      // 更新本地状态（立即反映视觉变化）
      ids.forEach(id => {
        const item = items.value.find(i => i.id === id)
        if (item) {
          item.view_count = 1
          item.last_viewed_at = new Date().toISOString()
        }
      })

      // 刷新统计数据
      await loadStats()
    } catch (err) {
      console.error('批量标记已读失败:', err)
      // 失败时重新加入队列（下次重试）
      ids.forEach(id => pendingReadIds.value.add(id))
    }
  }, 500)

  // 初始化 IntersectionObserver
  const { observe, unobserve, disconnect } = useIntersectionObserver(
    handleCardVisible,
    {
      threshold: 0,
      rootMargin: '-100px 0px 0px 0px'
    }
  )

  // 检测容器是否可滚动
  function isContainerScrollable() {
    const container = leftPanelRef.value
    if (!container) return false
    return container.scrollHeight > container.clientHeight
  }

  // 检查并激活自动标记已读功能
  function checkAndActivateAutoRead() {
    if (hasScrolled.value) return

    if (autoActivateTimer.value) {
      clearTimeout(autoActivateTimer.value)
      autoActivateTimer.value = null
    }

    const container = leftPanelRef.value
    if (!container || items.value.length === 0) return

    if (isContainerScrollable()) {
      console.log('[Auto-read] 容器可滚动，等待用户滚动')
    } else {
      console.log('[Auto-read] 容器不可滚动，将在 3 秒后自动激活')
      autoActivateTimer.value = setTimeout(() => {
        if (!hasScrolled.value && !isContainerScrollable()) {
          console.log('[Auto-read] 自动激活（内容少于一页）')
          hasScrolled.value = true
        }
      }, AUTO_ACTIVATE_DELAY)
    }
  }

  // 监听 items 变化，自动观察新卡片
  watch(items, () => {
    nextTick(() => {
      const container = leftPanelRef.value
      if (!container) return

      const cards = container.querySelectorAll('[data-item-id]')
      cards.forEach(card => {
        const itemId = card.dataset.itemId
        const item = items.value.find(i => i.id === itemId)

        if (item && (item.view_count || 0) === 0) {
          observe(card)
        }
      })

      checkAndActivateAutoRead()
    })
  }, { flush: 'post' })

  // 窗口 resize 处理（防抖）
  const handleResize = useDebounce(() => {
    checkAndActivateAutoRead()
  }, 300)

  // 左栏滚动到底部时标记最后一条未读
  function handleScrollBottom(distanceToBottom) {
    if (hasScrolled.value && distanceToBottom < 50) {
      const unreadItems = items.value.filter(i => (i.view_count || 0) === 0)
      if (unreadItems.length > 0) {
        const lastUnread = unreadItems[unreadItems.length - 1]
        markAsRead(lastUnread.id)
      }
    }
  }

  onMounted(() => {
    // 监听首次滚动，激活自动标记已读
    const container = leftPanelRef.value
    if (container) {
      container.addEventListener('scroll', () => {
        hasScrolled.value = true
      }, { once: true })
    }

    // 监听窗口大小变化
    window.addEventListener('resize', handleResize)
  })

  onUnmounted(() => {
    disconnect()
    pendingReadIds.value.clear()
    cardPositions.value.clear()
    hasScrolled.value = false
    if (autoActivateTimer.value) {
      clearTimeout(autoActivateTimer.value)
    }
    window.removeEventListener('resize', handleResize)
  })

  return {
    hasScrolled,
    pendingReadIds,
    cardPositions,
    markAsRead,
    handleScrollBottom,
    observe,
    unobserve,
    disconnect,
  }
}
