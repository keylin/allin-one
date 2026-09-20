import { ref, onUnmounted } from 'vue'
import { triggerSync, streamSyncProgress } from '@/api/sync'

/**
 * 同步结果 → 一句话摘要。各同步器 result_data 的键不同，统一在这里翻译。
 */
export function summarizeSyncResult(r) {
  if (!r) return ''
  const parts = []
  if (r.new_videos) parts.push(`新增 ${r.new_videos} 条视频`)
  if (r.updated_videos) parts.push(`更新 ${r.updated_videos} 条`)
  if (r.new_books) parts.push(`新增 ${r.new_books} 本`)
  if (r.updated_books) parts.push(`更新 ${r.updated_books} 本`)
  if (r.new_annotations) parts.push(`新增 ${r.new_annotations} 条标注`)
  if (r.new_films) parts.push(`新增 ${r.new_films} 部影片`)
  if (r.changed_films ?? r.updated_films) parts.push(`有变化 ${r.changed_films ?? r.updated_films} 部`)
  if (r.autofilled) parts.push(`自动标记看过 ${r.autofilled} 部`)
  if (r.removed_from_emby) parts.push(`${r.removed_from_emby} 部已不在 Emby`)
  return parts.join(', ')
}

/**
 * 触发一次同步并跟踪 SSE 进度 —— 同步管理页与影视库页共用
 *
 * states: { [sourceType]: { progressId, status, phase, message, current, total } }，同步结束即移除。
 * run(sourceType, options, { onSuccess(summary, resultData), onError(message), onSettled() })
 * 组件卸载时自动断开所有进度流。
 */
export function useSyncRun() {
  const states = ref({})
  const controllers = {}

  function finish(sourceType) {
    delete states.value[sourceType]
    delete controllers[sourceType]
  }

  async function run(sourceType, options = {}, { onSuccess, onError, onSettled } = {}) {
    if (states.value[sourceType]) return
    states.value[sourceType] = { progressId: null, status: 'pending', phase: '', message: '正在排队...', current: 0, total: 0 }

    const fail = (message) => {
      finish(sourceType)
      onError?.(message)
      onSettled?.()
    }

    let res
    try {
      res = await triggerSync(sourceType, options)
    } catch {
      return fail('触发同步失败')
    }
    if (res.code !== 0) return fail(res.message || '触发同步失败')

    states.value[sourceType].progressId = res.data.progress_id
    controllers[sourceType] = streamSyncProgress(
      res.data.progress_id,
      (event) => {
        const state = states.value[sourceType]
        if (!state) return
        state.status = event.status
        state.phase = event.phase
        state.message = event.message
        state.current = event.current
        state.total = event.total
      },
      (event) => {
        if (event?.status === 'failed') return fail(event.error_message || '同步失败')
        finish(sourceType)
        onSuccess?.(summarizeSyncResult(event?.result_data), event?.result_data)
        onSettled?.()
      },
      (msg) => fail(`同步错误: ${msg}`),
    )
  }

  function abortAll() {
    for (const c of Object.values(controllers)) c?.abort()
  }

  onUnmounted(abortAll)

  return { states, run, abortAll }
}
