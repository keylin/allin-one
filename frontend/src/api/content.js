import api from './index'

export function listContent(params = {}) {
  return api.get('/content', { params })
}

export function getContent(id) {
  return api.get(`/content/${id}`)
}

export function analyzeContent(id) {
  return api.post(`/content/${id}/analyze`)
}

export function toggleFavorite(id) {
  return api.post(`/content/${id}/favorite`)
}

export function updateNote(id, userNote) {
  return api.patch(`/content/${id}/note`, { user_note: userNote })
}

export function incrementView(id) {
  return api.post(`/content/${id}/view`)
}

export function batchDeleteContent(ids) {
  return api.post('/content/batch-delete', { ids })
}

export function deleteAllContent() {
  return api.post('/content/delete-all')
}

export function getContentStats() {
  return api.get('/content/stats')
}

export function enrichContent(id) {
  return api.post(`/content/${id}/enrich`, null, { timeout: 90000 })
}

export function applyEnrichment(id, content, method) {
  return api.post(`/content/${id}/enrich/apply`, { content, method })
}

export function batchMarkRead(ids) {
  return api.post('/content/batch-read', { ids })
}

export function markAllRead(params = {}) {
  return api.post('/content/mark-all-read', params)
}

export function batchFavorite(ids) {
  return api.post('/content/batch-favorite', { ids })
}

export function submitContent(data) {
  return api.post('/content/submit', data)
}

export function uploadContent(formData) {
  return api.post('/content/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function listSourceOptions() {
  return api.get('/sources/options')
}

export function getChatHistory(contentId) {
  return api.get(`/content/${contentId}/chat/history`)
}

export function saveChatHistory(contentId, messages) {
  return api.put(`/content/${contentId}/chat/history`, { messages })
}

export function deleteChatHistory(contentId) {
  return api.delete(`/content/${contentId}/chat/history`)
}

/**
 * 与内容进行 AI 对话（SSE 流式）
 * @returns {AbortController} 用于取消请求
 */
export function chatWithContent(contentId, messages, onChunk, onDone, onError) {
  const controller = new AbortController()
  const apiKey = localStorage.getItem('api_key')

  fetch(`/api/content/${contentId}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { 'X-API-Key': apiKey } : {}),
    },
    body: JSON.stringify({ messages }),
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
          if (data.startsWith('[ERROR] ')) {
            onError?.(data.slice(8))
            return
          }
          onChunk?.(data)
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
