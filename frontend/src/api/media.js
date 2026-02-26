import api from './index'

export function listMedia(params = {}) {
  return api.get('/media/list', { params })
}

export function deleteMedia(contentId) {
  return api.delete(`/media/${contentId}`)
}

export function toggleMediaFavorite(mediaId) {
  return api.post(`/media/${mediaId}/favorite`)
}

// 复用视频下载提交端点
export function downloadMedia(url, sourceId = null) {
  return api.post('/video/download', { url, source_id: sourceId })
}
