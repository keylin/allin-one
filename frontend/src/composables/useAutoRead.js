import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
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
 * @param {Ref} options.contentStats - 内容统计 ref（用于乐观更新）
 * @returns {Object}
 */
export function useAutoRead({ items, leftPanelRef, loadStats, contentStats }) {
  const hasScrolled = ref(false)
  const pendingReadIds = ref(new Set())
  const autoActivateTimer = ref(null)
  const AUTO_ACTIVATE_DELAY = 3000

  // [D] O(1) 查找：用 Map 替代 find
  const itemMap = computed(() => new Map(items.value.map(i => [i.id, i])))

  // [E] 记录 itemId → DOM element 映射，用于标记后 unobserve
  const elementMap = new Map()

  // [F] 已观察的 itemId 集合，增量观察新卡片
  const observedIds = new Set()

  // --- IntersectionObserver 回调 ---
  function handleCardVisible(entry) {
    if (!hasScrolled.value) return
    // 根容器不可见时跳过（移动端详情覆盖时 display:none 使 rootBounds 为 null）
    if (!entry.rootBounds || entry.rootBounds.height === 0) return

    const itemId = entry.target.dataset.itemId
    const item = itemMap.value.get(itemId)

    // 已读过或不存在则跳过
    if (!item || (item.view_count || 0) > 0) return

    // 卡片完全滚出顶部视野 → 标记已读
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

    const item = itemMap.value.get(itemId)
    if (!item || (item.view_count || 0) > 0) return

    pendingReadIds.value.add(itemId)

    // 立即更新本地状态（乐观更新）
    item.view_count = 1
    item.last_viewed_at = new Date().toISOString()

    // [C] 未读计数乐观更新
    if (contentStats && contentStats.value) {
      if (contentStats.value.unread > 0) contentStats.value.unread--
      contentStats.value.read++
    }

    // [E] 标记后立即取消观察
    const el = elementMap.get(itemId)
    if (el) {
      unobserve(el)
      elementMap.delete(itemId)
      observedIds.delete(itemId)
    }

    debouncedBatchSubmit()
  }

  // 防抖批量提交已读（300ms）
  const debouncedBatchSubmit = useDebounce(async () => {
    if (pendingReadIds.value.size === 0) return

    const ids = Array.from(pendingReadIds.value)
    pendingReadIds.value.clear()

    try {
      await batchMarkRead(ids)
      // loadStats 作为校准（乐观更新已在 markAsRead 中完成）
      loadStats()
    } catch (err) {
      console.error('批量标记已读失败:', err)
      // 失败时回滚本地状态
      ids.forEach(id => {
        const item = itemMap.value.get(id)
        if (item) {
          item.view_count = 0
          item.last_viewed_at = null
        }
        pendingReadIds.value.add(id)
      })
      // 回滚 stats
      if (contentStats && contentStats.value) {
        contentStats.value.unread += ids.length
        contentStats.value.read = Math.max(0, contentStats.value.read - ids.length)
      }
    }
  }, 300)

  // 初始化 IntersectionObserver
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

    if (!isContainerScrollable()) {
      autoActivateTimer.value = setTimeout(() => {
        if (!hasScrolled.value && !isContainerScrollable()) {
          hasScrolled.value = true
        }
      }, AUTO_ACTIVATE_DELAY)
    }
  }

  // [F] 监听 items 变化，增量观察新卡片（只对新增的调用 observe）
  watch(items, () => {
    nextTick(() => {
      const container = leftPanelRef.value
      if (!container) return

      const cards = container.querySelectorAll('[data-item-id]')
      cards.forEach(card => {
        const itemId = card.dataset.itemId
        if (observedIds.has(itemId)) return // 已观察，跳过

        const item = itemMap.value.get(itemId)
        if (item && (item.view_count || 0) === 0) {
          observe(card)
          observedIds.add(itemId)
          elementMap.set(itemId, card)
        }
      })

      checkAndActivateAutoRead()
    })
  }, { flush: 'post' })

  // 窗口 resize 处理（防抖）
  const handleResize = useDebounce(() => {
    checkAndActivateAutoRead()
  }, 300)

  // [A] 左栏滚动到底部时标记所有可见的未读卡片
  function handleScrollBottom(distanceToBottom) {
    if (!hasScrolled.value || distanceToBottom >= 100) return

    const container = leftPanelRef.value
    if (!container) return

    const containerRect = container.getBoundingClientRect()

    for (const item of items.value) {
      if ((item.view_count || 0) > 0) continue

      const el = elementMap.get(item.id)
      if (!el) continue

      const rect = el.getBoundingClientRect()
      // 卡片在容器可视区域内
      if (rect.bottom > containerRect.top && rect.top < containerRect.bottom) {
        markAsRead(item.id)
      }
    }
  }

  onMounted(() => {
    const container = leftPanelRef.value
    if (container) {
      container.addEventListener('scroll', () => {
        hasScrolled.value = true
      }, { once: true })
    }
    window.addEventListener('resize', handleResize)
  })

  onUnmounted(() => {
    disconnect()
    pendingReadIds.value.clear()
    hasScrolled.value = false
    observedIds.clear()
    elementMap.clear()
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
