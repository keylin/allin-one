import { reactive } from 'vue'

// 全局 toast 状态
const toastState = reactive({
  toasts: []
})

let nextId = 0

/**
 * Toast 通知 composable
 *
 * @example
 * const { showToast, success, error, warning, info } = useToast()
 * success('保存成功')
 * error('操作失败', { duration: 5000 })
 */
export function useToast() {
  /**
   * 显示 Toast 通知
   * @param {string} message - 消息内容
   * @param {Object} options - 配置选项
   * @param {string} options.type - 类型: 'success' | 'error' | 'warning' | 'info'
   * @param {number} options.duration - 持续时间(ms)，0 表示不自动关闭
   * @param {string} options.title - 可选标题
   */
  function showToast(message, options = {}) {
    const {
      type = 'info',
      duration = 3000,
      title = null
    } = options

    const id = nextId++
    const toast = {
      id,
      message,
      type,
      title,
      visible: true
    }

    toastState.toasts.push(toast)

    // 自动关闭
    if (duration > 0) {
      setTimeout(() => {
        removeToast(id)
      }, duration)
    }

    return id
  }

  /**
   * 移除指定 Toast
   */
  function removeToast(id) {
    const index = toastState.toasts.findIndex(t => t.id === id)
    if (index !== -1) {
      toastState.toasts.splice(index, 1)
    }
  }

  /**
   * 清除所有 Toast
   */
  function clearAll() {
    toastState.toasts = []
  }

  // 快捷方法
  const success = (message, options = {}) =>
    showToast(message, { ...options, type: 'success' })

  const error = (message, options = {}) =>
    showToast(message, { ...options, type: 'error', duration: options.duration || 5000 })

  const warning = (message, options = {}) =>
    showToast(message, { ...options, type: 'warning' })

  const info = (message, options = {}) =>
    showToast(message, { ...options, type: 'info' })

  return {
    toasts: toastState.toasts,
    showToast,
    removeToast,
    clearAll,
    success,
    error,
    warning,
    info
  }
}
