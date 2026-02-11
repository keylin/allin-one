import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listSources, createSource as apiCreate, updateSource as apiUpdate, deleteSource as apiDelete, collectSource as apiCollect } from '@/api/sources'

export const useSourcesStore = defineStore('sources', () => {
  const sources = ref([])
  const total = ref(0)
  const loading = ref(false)
  const currentPage = ref(1)
  const pageSize = ref(20)

  async function fetchSources(params = {}) {
    loading.value = true
    try {
      const res = await listSources({
        page: currentPage.value,
        page_size: pageSize.value,
        ...params,
      })
      if (res.code === 0) {
        sources.value = res.data
        total.value = res.total
      }
    } finally {
      loading.value = false
    }
  }

  async function createSource(data) {
    const res = await apiCreate(data)
    if (res.code === 0) await fetchSources()
    return res
  }

  async function updateSource(id, data) {
    const res = await apiUpdate(id, data)
    if (res.code === 0) await fetchSources()
    return res
  }

  async function deleteSource(id, cascade = false) {
    const res = await apiDelete(id, cascade)
    if (res.code === 0) await fetchSources()
    return res
  }

  async function collectSource(id) {
    return await apiCollect(id)
  }

  return { sources, total, loading, currentPage, pageSize, fetchSources, createSource, updateSource, deleteSource, collectSource }
})
