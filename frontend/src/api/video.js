import api from './index'

export function downloadVideo(url, sourceId = null) {
  return api.post('/video/download', { url, source_id: sourceId })
}

export function listDownloads(params = {}) {
  return api.get('/video/downloads', { params })
}
