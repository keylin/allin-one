import api from './index'

export function listPipelines(params = {}) {
  return api.get('/pipelines', { params })
}

export function getPipeline(id) {
  return api.get(`/pipelines/${id}`)
}

export function cancelPipeline(id) {
  return api.post(`/pipelines/${id}/cancel`)
}

export function retryPipeline(id) {
  return api.post(`/pipelines/${id}/retry`)
}

export function manualPipeline(data) {
  return api.post('/pipelines/manual', data)
}
