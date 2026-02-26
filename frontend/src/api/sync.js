import api from './index'

export function getSyncStatus() {
  return api.get('/sync/status')
}

export { setupEbookSync } from './ebook'

export function setupVideoSync(sourceType = 'sync.bilibili') {
  return api.post('/video/sync/setup', null, { params: { source_type: sourceType } })
}

export function triggerSync(sourceType, options = {}) {
  return api.post(`/sync/run/${sourceType}`, { options })
}

export function linkCredential(sourceType, credentialId) {
  return api.post('/sync/link-credential', {
    source_type: sourceType,
    credential_id: credentialId,
  })
}

/**
 * SSE 进度流 — 监听同步进度
 * @param {string} progressId
 * @param {function} onUpdate - 每次进度变更回调 (event: object)
 * @param {function} onDone - 同步完成回调 (event: object)
 * @param {function} onError - 错误回调 (message: string)
 * @returns {AbortController} 用于取消连接
 */
export function streamSyncProgress(progressId, onUpdate, onDone, onError) {
  const controller = new AbortController()
  const apiKey = localStorage.getItem('api_key')

  fetch(`/api/sync/progress/${progressId}`, {
    headers: {
      ...(apiKey ? { 'X-API-Key': apiKey } : {}),
    },
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        onError?.(`请求失败: ${response.status}`)
        return
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6)
          if (data === '[DONE]') {
            onDone?.()
            return
          }
          try {
            const event = JSON.parse(data)
            if (event.error) {
              onError?.(event.error)
              return
            }
            onUpdate?.(event)
            // Terminal states
            if (event.status === 'completed' || event.status === 'failed') {
              onDone?.(event)
              return
            }
          } catch {
            // skip unparseable lines
          }
        }
      }
      onDone?.()
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError?.(err.message || '网络错误')
      }
    })

  return controller
}
