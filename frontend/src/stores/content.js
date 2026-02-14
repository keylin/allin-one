import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listContent as apiList,
  getContent as apiGet,
  toggleFavorite as apiFavorite,
  updateNote as apiNote,
  batchDeleteContent as apiBatchDelete,
  deleteAllContent as apiDeleteAll,
} from '@/api/content'

export const useContentStore = defineStore('content', () => {
  const items = ref([])
  const total = ref(0)
  const loading = ref(false)
  const currentPage = ref(1)
  const pageSize = ref(20)

  async function fetchContent(params = {}) {
    loading.value = true
    try {
      const res = await apiList({
        page: currentPage.value,
        page_size: pageSize.value,
        ...params,
      })
      if (res.code === 0) {
        items.value = res.data
        total.value = res.total
      }
    } finally {
      loading.value = false
    }
  }

  async function toggleFavorite(id) {
    const res = await apiFavorite(id)
    if (res.code === 0) {
      const item = items.value.find(i => i.id === id)
      if (item) item.is_favorited = res.data.is_favorited
    }
    return res
  }

  async function updateNote(id, note) {
    return await apiNote(id, note)
  }

  async function batchDelete(ids) {
    const res = await apiBatchDelete(ids)
    if (res.code === 0) await fetchContent()
    return res
  }

  async function deleteAll() {
    const res = await apiDeleteAll()
    if (res.code === 0) await fetchContent()
    return res
  }

  return { items, total, loading, currentPage, pageSize, fetchContent, toggleFavorite, updateNote, batchDelete, deleteAll }
})
