/**
 * 防抖工具
 * 用于延迟执行函数，多次调用只执行最后一次
 *
 * @param {Function} fn - 要防抖的函数
 * @param {number} delay - 延迟时间（毫秒），默认 300ms
 * @returns {Function} 防抖后的函数
 *
 * @example
 * const debouncedSearch = useDebounce(() => {
 *   console.log('搜索中...')
 * }, 500)
 *
 * // 快速调用多次，只会执行最后一次
 * debouncedSearch()
 * debouncedSearch()
 * debouncedSearch() // 只有这次会在 500ms 后执行
 */
export function useDebounce(fn, delay = 300) {
  let timeout = null

  return (...args) => {
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(() => {
      fn(...args)
      timeout = null
    }, delay)
  }
}
