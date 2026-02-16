import { ref, onMounted, onUnmounted } from 'vue'

/**
 * IntersectionObserver composable
 * 用于检测元素进入/离开视口
 *
 * @param {Function} callback - 元素可见性变化时的回调函数 (entry, observer) => void
 * @param {Object} options - IntersectionObserver 配置选项
 * @returns {Object} { observe, unobserve, disconnect }
 */
export function useIntersectionObserver(callback, options = {}) {
  const observer = ref(null)
  const observedElements = new Set()

  const defaultOptions = {
    root: null,
    rootMargin: '0px',
    threshold: 0.7, // 70% 可见即触发
    ...options
  }

  onMounted(() => {
    if ('IntersectionObserver' in window) {
      observer.value = new IntersectionObserver((entries) => {
        entries.forEach(entry => callback(entry, observer.value))
      }, defaultOptions)
    } else {
      console.warn('IntersectionObserver 不支持，自动标记已读功能已降级')
    }
  })

  onUnmounted(() => {
    if (observer.value) {
      observer.value.disconnect()
      observedElements.clear()
    }
  })

  /**
   * 开始观察元素
   */
  const observe = (element) => {
    if (observer.value && element && !observedElements.has(element)) {
      observer.value.observe(element)
      observedElements.add(element)
    }
  }

  /**
   * 停止观察元素
   */
  const unobserve = (element) => {
    if (observer.value && element) {
      observer.value.unobserve(element)
      observedElements.delete(element)
    }
  }

  /**
   * 断开所有观察
   */
  const disconnect = () => {
    if (observer.value) {
      observer.value.disconnect()
      observedElements.clear()
    }
  }

  return { observe, unobserve, disconnect }
}
