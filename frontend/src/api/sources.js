import api from './index'

export function listSources(params = {}) {
  return api.get('/sources', { params })
}

export function getSource(id) {
  return api.get(`/sources/${id}`)
}

export function createSource(data) {
  return api.post('/sources', data)
}

export function updateSource(id, data) {
  return api.put(`/sources/${id}`, data)
}

export function deleteSource(id, cascade = false) {
  return api.delete(`/sources/${id}`, { params: { cascade } })
}

export function batchDeleteSources(ids, cascade = false) {
  return api.post('/sources/batch-delete', { ids }, { params: { cascade } })
}

export function collectSource(id) {
  return api.post(`/sources/${id}/collect`)
}

export function collectAllSources() {
  return api.post('/sources/batch-collect')
}

export function getCollectionHistory(id, params = {}) {
  return api.get(`/sources/${id}/history`, { params })
}

export function importOPML(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/sources/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export function exportOPML() {
  return api.get('/sources/export', { responseType: 'blob' })
}

export function cleanupDuplicates() {
  return api.post('/sources/cleanup-duplicates')
}

