import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useIntersectionObserver } from '@/composables/useIntersectionObserver'
import { useDebounce } from '@/composables/useDebounce'
import { batchMarkRead } from '@/api/content'

/**
 * 自动标记已读 composable
 * 通过 IntersectionObserver 检测卡片滚出视野顶部后自动标记已读
 *
 * 核心逻辑：卡片完全滚出顶部视野时立即标记（类似 Twitter/X）
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
  const autoActivateTimer = ref(null)
  const AUTO_ACTIVATE_DELAY = 3000

  // --- IntersectionObserver 回调 ---
  // 简化逻辑：卡片完全滚出顶部视野 → 标记已读
  function handleCardVisible(entry) {
    if (!hasScrolled.value) return

    const itemId = entry.target.dataset.itemId
    const item = items.value.find(i => i.id === itemId)

    // 已读过或不存在则跳过
    if (!item || (item.view_count || 0) > 0) return

    // 卡片完全滚出顶部视野 → 标记已读
    // root 已设为 leftPanelRef，rootBounds 即容器边界，无需手动获取
    if (!entry.isIntersecting) {
      const topEdge = entry.rootBounds ? entry.rootBounds.top : 0
      if (entry.boundingClientRect.bottom < topEdge + 10) {
        markAsRead(itemId)
      }
    }
  }

  // 标记单个 item 为已读（加入批量队列）
  function markAsRead(itemId) {
    if (pendingReadIds.value.has(itemId)) return

    pendingReadIds.value.add(itemId)

    // 立即更新本地状态（不等 API 返回，让用户感觉更即时）
    const item = items.value.find(i => i.id === itemId)
    if (item) {
      item.view_count = 1
      item.last_viewed_at = new Date().toISOString()
    }

    debouncedBatchSubmit()
  }

  // 防抖批量提交已读（300ms 更及时）
  const debouncedBatchSubmit = useDebounce(async () => {
    if (pendingReadIds.value.size === 0) return

    const ids = Array.from(pendingReadIds.value)
    pendingReadIds.value.clear()

    try {
      await batchMarkRead(ids)
      // 刷新统计数据
      await loadStats()
    } catch (err) {
      console.error('批量标记已读失败:', err)
      // 失败时回滚本地状态并重新加入队列
      ids.forEach(id => {
        const item = items.value.find(i => i.id === id)
        if (item) {
          item.view_count = 0
          item.last_viewed_at = null
        }
        pendingReadIds.value.add(id)
      })
    }
  }, 300)

  // 初始化 IntersectionObserver
  // 使用精确边界和多个 threshold 确保更频繁的回调
  const { observe, unobserve, disconnect } = useIntersectionObserver(
    handleCardVisible,
    {
      root: leftPanelRef,
      threshold: [0, 0.1],
      rootMargin: '0px 0px 0px 0px'
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
    hasScrolled.value = false
    if (autoActivateTimer.value) {
      clearTimeout(autoActivateTimer.value)
    }
    window.removeEventListener('resize', handleResize)
  })

  return {
    hasScrolled,
    pendingReadIds,
    markAsRead,
    handleScrollBottom,
    observe,
    unobserve,
    disconnect,
  }
}
