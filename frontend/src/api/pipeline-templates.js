import api from './index'

export function listTemplates() {
  return api.get('/pipeline-templates')
}

export function getStepDefinitions() {
  return api.get('/pipeline-templates/step-definitions')
}

export function createTemplate(data) {
  return api.post('/pipeline-templates', data)
}

export function updateTemplate(id, data) {
  return api.put(`/pipeline-templates/${id}`, data)
}

export function deleteTemplate(id) {
  return api.delete(`/pipeline-templates/${id}`)
}
