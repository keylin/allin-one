<script setup>
import { ref, watch, toRef, computed } from 'vue'
import { useScrollLock } from '@/composables/useScrollLock'
import { useToast } from '@/composables/useToast'
import {
  getEbookDetail,
  updateEbookMetadata,
  searchBookMetadata,
  applyBookMetadata,
} from '@/api/ebook'

const props = defineProps({
  visible: Boolean,
  contentId: { type: String, default: null },
})

const emit = defineEmits(['close', 'updated'])
useScrollLock(toRef(props, 'visible'))
const { success, error: showError } = useToast()

// Form state
const loading = ref(false)
const saving = ref(false)
const form = ref({
  title: '',
  author: '',
  description: '',
  isbn: '',
  publisher: '',
  language: '',
  subjects: [],
  publish_date: '',
  series: '',
  page_count: null,
})
const newTag = ref('')

// Search state
const searchQuery = ref('')
const structuredSearch = ref({ title: '', author: '', isbn: '' })
const userEdited = ref(false)
const searching = ref(false)
const searchResults = ref([])
const applying = ref(false)

// Active tab for mobile
const activeTab = ref('edit')

// Load book detail when modal opens
watch(() => [props.visible, props.contentId], async ([visible, id]) => {
  if (visible && id) {
    await loadDetail(id)
  } else {
    resetForm()
  }
}, { immediate: true })

async function loadDetail(id) {
  loading.value = true
  try {
    const res = await getEbookDetail(id)
    if (res.code === 0) {
      const d = res.data
      form.value = {
        title: d.title || '',
        author: d.author || '',
        description: d.description || '',
        isbn: d.isbn || '',
        publisher: d.publisher || '',
        language: d.language || '',
        subjects: d.subjects || [],
        publish_date: d.publish_date || '',
        series: d.series || '',
        page_count: d.page_count || null,
      }
      // Pre-fill search: structured fields for API, display string for input
      structuredSearch.value = {
        title: d.title || '',
        author: d.author || '',
        isbn: d.isbn || '',
      }
      userEdited.value = false
      const parts = []
      if (d.title) parts.push(d.title)
      if (d.author) parts.push(d.author)
      searchQuery.value = parts.join(' ')
    }
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.value = {
    title: '', author: '', description: '', isbn: '',
    publisher: '', language: '', subjects: [], publish_date: '',
    series: '', page_count: null,
  }
  searchQuery.value = ''
  structuredSearch.value = { title: '', author: '', isbn: '' }
  userEdited.value = false
  searchResults.value = []
  activeTab.value = 'edit'
}

// Tags
function addTag() {
  const tag = newTag.value.trim()
  if (tag && !form.value.subjects.includes(tag)) {
    form.value.subjects.push(tag)
  }
  newTag.value = ''
}

function removeTag(index) {
  form.value.subjects.splice(index, 1)
}

function handleTagKeydown(e) {
  if (e.key === 'Enter') {
    e.preventDefault()
    addTag()
  }
}

// Save
async function handleSave() {
  saving.value = true
  try {
    const data = { ...form.value }
    // Convert empty page_count to null
    if (!data.page_count) data.page_count = null
    const res = await updateEbookMetadata(props.contentId, data)
    if (res.code === 0) {
      success('元数据已保存')
      emit('updated')
    } else {
      showError(res.message || '保存失败')
    }
  } catch (e) {
    showError('保存失败')
  } finally {
    saving.value = false
  }
}

// Search
async function handleSearch() {
  if (!searchQuery.value.trim()) return
  searching.value = true
  searchResults.value = []
  try {
    let params
    if (userEdited.value) {
      // 用户手动修改了搜索框，走 freeform 搜索
      params = { query: searchQuery.value.trim() }
    } else {
      // 未修改，走结构化搜索
      params = { ...structuredSearch.value }
    }
    const res = await searchBookMetadata(props.contentId, params)
    if (res.code === 0) {
      searchResults.value = res.data
    }
  } finally {
    searching.value = false
  }
}

// Apply search result
async function handleApply(result) {
  applying.value = true
  try {
    const res = await applyBookMetadata(props.contentId, result)
    if (res.code === 0) {
      success('已应用在线元数据')
      await loadDetail(props.contentId)
      emit('updated')
      activeTab.value = 'edit'
    } else {
      showError(res.message || '应用失败')
    }
  } catch (e) {
    showError('应用失败')
  } finally {
    applying.value = false
  }
}

function close() {
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-150"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="close" />

        <!-- Modal -->
        <div class="relative z-10 bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
          <!-- Header -->
          <div class="flex items-center justify-between px-5 py-3.5 border-b border-slate-100 shrink-0">
            <h2 class="text-base font-semibold text-slate-800">编辑书籍信息</h2>
            <button @click="close" class="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors">
              <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Mobile tabs -->
          <div class="flex border-b border-slate-100 lg:hidden shrink-0">
            <button
              @click="activeTab = 'edit'"
              class="flex-1 py-2.5 text-sm font-medium text-center transition-colors"
              :class="activeTab === 'edit' ? 'text-indigo-600 border-b-2 border-indigo-600' : 'text-slate-500'"
            >
              编辑信息
            </button>
            <button
              @click="activeTab = 'search'"
              class="flex-1 py-2.5 text-sm font-medium text-center transition-colors"
              :class="activeTab === 'search' ? 'text-indigo-600 border-b-2 border-indigo-600' : 'text-slate-500'"
            >
              在线搜索
            </button>
          </div>

          <!-- Loading -->
          <div v-if="loading" class="flex-1 flex items-center justify-center py-20">
            <svg class="w-8 h-8 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
          </div>

          <!-- Content: two-column on desktop, tabs on mobile -->
          <div v-else class="flex-1 flex flex-col lg:flex-row overflow-hidden min-h-0">
            <!-- Left: Edit form -->
            <div
              class="flex-1 overflow-y-auto p-5 space-y-4"
              :class="{ 'hidden lg:block': activeTab !== 'edit' }"
            >
              <!-- Title -->
              <div>
                <label class="block text-xs font-medium text-slate-500 mb-1">书名</label>
                <input
                  v-model="form.title"
                  class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
                />
              </div>

              <!-- Author -->
              <div>
                <label class="block text-xs font-medium text-slate-500 mb-1">作者</label>
                <input
                  v-model="form.author"
                  class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
                />
              </div>

              <!-- Grid fields -->
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block text-xs font-medium text-slate-500 mb-1">ISBN</label>
                  <input
                    v-model="form.isbn"
                    class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
                    placeholder="978-..."
                  />
                </div>
                <div>
                  <label class="block text-xs font-medium text-slate-500 mb-1">出版社</label>
                  <input
                    v-model="form.publisher"
                    class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
                  />
                </div>
                <div>
                  <label class="block text-xs font-medium text-slate-500 mb-1">语言</label>
                  <input
                    v-model="form.language"
                    class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
                    placeholder="zh / en"
                  />
                </div>
                <div>
                  <label class="block text-xs font-medium text-slate-500 mb-1">出版日期</label>
                  <input
                    v-model="form.publish_date"
                    class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
                    placeholder="2024-01-01"
                  />
                </div>
                <div>
                  <label class="block text-xs font-medium text-slate-500 mb-1">页数</label>
                  <input
                    v-model.number="form.page_count"
                    type="number"
                    class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
                  />
                </div>
                <div>
                  <label class="block text-xs font-medium text-slate-500 mb-1">系列</label>
                  <input
                    v-model="form.series"
                    class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
                  />
                </div>
              </div>

              <!-- Subjects / Tags -->
              <div>
                <label class="block text-xs font-medium text-slate-500 mb-1">分类标签</label>
                <div class="flex flex-wrap gap-1.5 mb-2" v-if="form.subjects.length">
                  <span
                    v-for="(tag, i) in form.subjects"
                    :key="i"
                    class="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-indigo-50 text-indigo-700 rounded-full"
                  >
                    {{ tag }}
                    <button @click="removeTag(i)" class="text-indigo-400 hover:text-indigo-600">
                      <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M18 6 6 18M6 6l12 12" />
                      </svg>
                    </button>
                  </span>
                </div>
                <div class="flex gap-2">
                  <input
                    v-model="newTag"
                    @keydown="handleTagKeydown"
                    class="flex-1 bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
                    placeholder="输入标签后回车添加"
                  />
                  <button
                    @click="addTag"
                    class="px-3 py-1.5 text-xs font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors shrink-0"
                  >
                    添加
                  </button>
                </div>
              </div>

              <!-- Description -->
              <div>
                <label class="block text-xs font-medium text-slate-500 mb-1">简介</label>
                <textarea
                  v-model="form.description"
                  rows="3"
                  class="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all resize-none"
                />
              </div>

              <!-- Save button -->
              <div class="pt-2">
                <button
                  @click="handleSave"
                  :disabled="saving"
                  class="w-full py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 active:scale-[0.98] transition-all duration-150 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {{ saving ? '保存中...' : '保存' }}
                </button>
              </div>
            </div>

            <!-- Divider -->
            <div class="hidden lg:block w-px bg-slate-100 shrink-0" />

            <!-- Right: Online search -->
            <div
              class="w-full lg:w-[380px] flex flex-col overflow-hidden shrink-0"
              :class="{ 'hidden lg:flex': activeTab !== 'search' }"
            >
              <!-- Search input -->
              <div class="p-4 border-b border-slate-50 shrink-0">
                <div class="flex gap-2">
                  <input
                    v-model="searchQuery"
                    @input="userEdited = true"
                    @keydown.enter="handleSearch"
                    class="flex-1 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 transition-all"
                    placeholder="搜索书名、作者或 ISBN..."
                  />
                  <button
                    @click="handleSearch"
                    :disabled="searching || !searchQuery.trim()"
                    class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <svg v-if="searching" class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                    </svg>
                    <span v-else>搜索</span>
                  </button>
                </div>
                <p class="mt-1.5 text-[11px] text-slate-400">通过 Google Books 搜索书籍信息</p>
              </div>

              <!-- Search results -->
              <div class="flex-1 overflow-y-auto">
                <div v-if="!searchResults.length && !searching" class="p-8 text-center">
                  <svg class="w-10 h-10 mx-auto mb-2 text-slate-200" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
                  </svg>
                  <p class="text-xs text-slate-400">输入关键词搜索在线书籍信息</p>
                </div>

                <div v-else-if="searching" class="p-8 flex items-center justify-center">
                  <svg class="w-6 h-6 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                  </svg>
                </div>

                <div v-else class="divide-y divide-slate-50">
                  <div
                    v-for="(result, i) in searchResults"
                    :key="i"
                    class="p-3.5 hover:bg-slate-50/80 transition-colors"
                  >
                    <div class="flex gap-3">
                      <!-- Cover thumbnail -->
                      <div class="w-12 h-16 bg-slate-100 rounded-md overflow-hidden shrink-0">
                        <img
                          v-if="result.cover_url"
                          :src="result.cover_url"
                          class="w-full h-full object-cover"
                          loading="lazy"
                        />
                        <div v-else class="w-full h-full flex items-center justify-center">
                          <svg class="w-5 h-5 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
                          </svg>
                        </div>
                      </div>

                      <!-- Info -->
                      <div class="flex-1 min-w-0">
                        <h4 class="text-sm font-medium text-slate-800 line-clamp-1">
                          {{ result.title }}
                          <span v-if="result.is_current" class="ml-1 px-1.5 py-0.5 text-[10px] font-medium bg-green-50 text-green-600 border border-green-200 rounded">当前</span>
                        </h4>
                        <p class="text-xs text-slate-500 mt-0.5 line-clamp-1">{{ result.author }}</p>
                        <div class="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-[11px] text-slate-400">
                          <span v-if="result.publisher">{{ result.publisher }}</span>
                          <span v-if="result.publish_date">{{ result.publish_date }}</span>
                          <span v-if="result.page_count">{{ result.page_count }} 页</span>
                        </div>
                        <div v-if="result.subjects?.length" class="flex flex-wrap gap-1 mt-1.5">
                          <span
                            v-for="s in result.subjects.slice(0, 3)"
                            :key="s"
                            class="px-1.5 py-0.5 text-[10px] bg-slate-100 text-slate-500 rounded"
                          >{{ s }}</span>
                        </div>
                      </div>
                    </div>

                    <!-- Apply button -->
                    <button
                      @click="handleApply(result)"
                      :disabled="applying"
                      class="mt-2.5 w-full py-1.5 text-xs font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 active:scale-[0.98] transition-all disabled:opacity-50"
                    >
                      {{ applying ? '应用中...' : '应用此结果' }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
