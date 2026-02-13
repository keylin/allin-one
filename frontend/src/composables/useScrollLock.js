import { watch, onUnmounted } from 'vue'

let lockCount = 0

function update() {
  lockCount = Math.max(0, lockCount)
  document.body.style.overflow = lockCount > 0 ? 'hidden' : ''
}

/**
 * 当 isLocked 为 true 时锁定 body 滚动。
 * 支持多个 modal 嵌套：只有所有锁都释放后才恢复滚动。
 */
export function useScrollLock(isLocked) {
  watch(isLocked, (val, oldVal) => {
    if (val && !oldVal) { lockCount++; update() }
    if (!val && oldVal) { lockCount--; update() }
  })

  onUnmounted(() => {
    if (isLocked.value && lockCount > 0) { lockCount--; update() }
  })
}
