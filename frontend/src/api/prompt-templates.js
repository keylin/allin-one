import api from './index'

export function listPromptTemplates(params = {}) {
  return api.get('/prompt-templates', { params })
}

export function createPromptTemplate(data) {
  return api.post('/prompt-templates', data)
}

export function updatePromptTemplate(id, data) {
  return api.put(`/prompt-templates/${id}`, data)
}

export function deletePromptTemplate(id) {
  return api.delete(`/prompt-templates/${id}`)
}
