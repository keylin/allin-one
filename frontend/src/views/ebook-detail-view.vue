<script setup>
import { ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getEbookDetail, listAnnotations, createAnnotation, updateAnnotation, deleteAnnotation } from '@/api/ebook'
import { colorOptions, colorMap, annotationColor } from '@/config/annotation-colors'
import { formatTimeShort } from '@/utils/time'
import AnnotationCard from '@/components/annotation-card.vue'
import AnnotationForm from '@/components/annotation-form.vue'
import EbookMetadataModal from '@/components/ebook-metadata-modal.vue'

const route = useRoute()
const router = useRouter()

const contentId = route.params.id

// Book detail
const book = ref(null)
const loading = ref(true)

// Annotations
const chapters = ref([])
const flatAnnotations = ref([])
const totalAnnotations = ref(0)
const loadingAnnotations = ref(false)

// Filters
const searchQuery = ref('')
const filterColor = ref('')
const filterType = ref('')
let searchTimer = null

// Chapter collapse state
const collapsedChapters = ref(new Set())

// New annotation form
const showForm = ref(false)

// Metadata modal
const metadataVisible = ref(false)

// Delete confirm
const deleteConfirmId = ref(null)
let deleteConfirmTimer = null

async function fetchBook() {
  try {
    const res = await getEbookDetail(contentId)
    if (res.code === 0) book.value = res.data
  } catch (e) {
    console.error('Failed to fetch book:', e)
  }
}

async function fetchAnnotations() {
  loadingAnnotations.value = true
  try {
    const params = { group_by_chapter: true }
    if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
    if (filterColor.value) params.color = filterColor.value
    if (filterType.value) params.type = filterType.value

    const res = await listAnnotations(contentId, params)
    if (res.code === 0) {
      chapters.value = res.data.chapters || []
      totalAnnotations.value = res.data.total || 0
    }
  } catch (e) {
    console.error('Failed to fetch annotations:', e)
  } finally {
    loadingAnnotations.value = false
  }
}

function toggleChapter(idx) {
  const s = new Set(collapsedChapters.value)
  if (s.has(idx)) {
    s.delete(idx)
  } else {
    s.add(idx)
  }
  collapsedChapters.value = s
}

async function handleCreate(data) {
  try {
    const res = await createAnnotation(contentId, data)
    if (res.code === 0) {
      showForm.value = false
      fetchAnnotations()
    }
  } catch (e) {
    console.error('Failed to create annotation:', e)
  }
}

async function handleUpdate(data) {
  try {
    const res = await updateAnnotation(contentId, data.id, {
      note: data.note,
      color: data.color,
    })
    if (res.code === 0) fetchAnnotations()
  } catch (e) {
    console.error('Failed to update annotation:', e)
  }
}

function handleDeleteClick(annId) {
  if (deleteConfirmId.value === annId) {
    doDelete(annId)
  } else {
    deleteConfirmId.value = annId
    clearTimeout(deleteConfirmTimer)
    deleteConfirmTimer = setTimeout(() => { deleteConfirmId.value = null }, 3000)
  }
}

async function doDelete(annId) {
  deleteConfirmId.value = null
  clearTimeout(deleteConfirmTimer)
  try {
    const res = await deleteAnnotation(contentId, annId)
    if (res.code === 0) fetchAnnotations()
  } catch (e) {
    console.error('Failed to delete annotation:', e)
  }
}

function goBack() {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/ebook')
  }
}

function clearFilters() {
  searchQuery.value = ''
  filterColor.value = ''
  filterType.value = ''
}

const hasFilters = () => searchQuery.value || filterColor.value || filterType.value

// Debounced search
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(fetchAnnotations, 300)
})

watch(filterColor, fetchAnnotations)
watch(filterType, fetchAnnotations)

onMounted(async () => {
  loading.value = true
  await Promise.all([fetchBook(), fetchAnnotations()])
  loading.value = false
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-24">
      <svg class="w-8 h-8 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
      </svg>
    </div>

    <template v-else-if="book">
      <!-- Header -->
      <div class="px-4 pt-3 pb-3 sticky top-0 bg-white/95 backdrop-blur-sm z-10 border-b border-slate-100 shrink-0">
        <div class="flex items-center gap-3">
          <button
            @click="goBack"
            class="shrink-0 p-1.5 -ml-1.5 text-slate-400 hover:text-slate-700 rounded-lg hover:bg-slate-100 transition-all"
          >
            <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
          </button>
          <div class="flex-1 min-w-0">
            <h1 class="text-base font-bold text-slate-900 tracking-tight truncate">{{ book.title }}</h1>
            <div class="flex items-center gap-2 text-xs text-slate-400 mt-0.5">
              <span v-if="book.author" class="truncate">{{ book.author }}</span>
              <template v-if="book.source">
                <span class="text-slate-200">·</span>
                <span class="shrink-0 px-1.5 py-0.5 text-[10px] font-medium bg-slate-100 text-slate-500 rounded">{{ book.source }}</span>
              </template>
            </div>
          </div>
          <button
            @click="metadataVisible = true"
            class="shrink-0 px-3 py-1.5 text-xs font-medium text-slate-500 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors"
          >
            编辑信息
          </button>
        </div>

        <!-- Progress + annotation count -->
        <div class="mt-3 flex items-center gap-3">
          <div class="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
            <div
              class="h-full bg-indigo-500 rounded-full transition-all"
              :style="{ width: Math.round((book.progress?.progress || 0) * 100) + '%' }"
            />
          </div>
          <span class="text-xs font-semibold text-slate-600 tabular-nums shrink-0">
            {{ Math.round((book.progress?.progress || 0) * 100) }}%
          </span>
          <span class="text-slate-200 shrink-0">·</span>
          <span class="text-xs text-slate-400 shrink-0">{{ totalAnnotations }} 条标注</span>
        </div>
      </div>

      <!-- Filters -->
      <div class="px-4 py-2.5 border-b border-slate-100 shrink-0 space-y-2">
        <!-- Search -->
        <div class="relative">
          <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
          </svg>
          <input
            v-model="searchQuery"
            placeholder="搜索标注内容或笔记..."
            class="w-full bg-slate-50 rounded-lg pl-8 pr-3 py-1.5 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 focus:bg-white transition-all"
          />
        </div>
        <!-- Color + type chips -->
        <div class="flex items-center gap-2 flex-wrap">
          <!-- Color filter -->
          <div class="flex items-center gap-1.5">
            <button
              v-for="c in colorOptions"
              :key="c"
              @click="filterColor = filterColor === c ? '' : c"
              class="w-4.5 h-4.5 rounded-full transition-all duration-150"
              :class="[
                colorMap[c],
                filterColor === c ? 'ring-2 ring-offset-1 ring-slate-400 scale-110' : 'opacity-40 hover:opacity-80',
              ]"
              :style="{ width: '18px', height: '18px' }"
            />
          </div>
          <span class="text-slate-200">|</span>
          <!-- Type filter -->
          <button
            @click="filterType = filterType === 'highlight' ? '' : 'highlight'"
            class="px-2 py-0.5 text-[11px] font-medium rounded-full border transition-all"
            :class="filterType === 'highlight'
              ? 'bg-indigo-50 text-indigo-600 border-indigo-200'
              : 'text-slate-400 border-slate-200 hover:text-slate-600'"
          >
            划线
          </button>
          <button
            @click="filterType = filterType === 'note' ? '' : 'note'"
            class="px-2 py-0.5 text-[11px] font-medium rounded-full border transition-all"
            :class="filterType === 'note'
              ? 'bg-indigo-50 text-indigo-600 border-indigo-200'
              : 'text-slate-400 border-slate-200 hover:text-slate-600'"
          >
            笔记
          </button>
          <button
            v-if="hasFilters()"
            @click="clearFilters"
            class="text-[11px] text-slate-400 hover:text-slate-600 transition-colors ml-auto"
          >
            清除
          </button>
        </div>
      </div>

      <!-- Annotations content -->
      <div class="flex-1 overflow-y-auto">
        <div class="px-4 py-4">
          <!-- Loading annotations -->
          <div v-if="loadingAnnotations" class="flex items-center justify-center py-12">
            <svg class="w-6 h-6 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
          </div>

          <!-- Empty state -->
          <div v-else-if="chapters.length === 0" class="text-center py-12">
            <div class="w-12 h-12 mx-auto mb-3 bg-slate-100 rounded-xl flex items-center justify-center">
              <svg class="w-6 h-6 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
              </svg>
            </div>
            <p class="text-sm text-slate-400">暂无标注</p>
            <p v-if="hasFilters()" class="text-xs text-slate-300 mt-1">试试调整筛选条件</p>
          </div>

          <!-- Chapter groups -->
          <div v-else class="space-y-3">
            <div
              v-for="(group, idx) in chapters"
              :key="idx"
              class="bg-white rounded-xl border border-slate-200/60 overflow-hidden shadow-sm"
            >
              <!-- Chapter header -->
              <button
                @click="toggleChapter(idx)"
                class="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-slate-50 transition-colors"
              >
                <svg
                  class="w-3.5 h-3.5 text-slate-400 shrink-0 transition-transform duration-200"
                  :class="{ '-rotate-90': collapsedChapters.has(idx) }"
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                >
                  <path d="m6 9 6 6 6-6" />
                </svg>
                <span class="text-sm font-medium text-slate-700 truncate flex-1">
                  {{ group.chapter || '未分类标注' }}
                </span>
                <span class="text-xs text-slate-400 tabular-nums shrink-0">({{ group.count }})</span>
              </button>
              <!-- Annotations list -->
              <div v-if="!collapsedChapters.has(idx)" class="divide-y divide-slate-100 border-t border-slate-100">
                <AnnotationCard
                  v-for="ann in group.annotations"
                  :key="ann.id"
                  :annotation="ann"
                  :editable="true"
                  @update="handleUpdate"
                  @delete="handleDeleteClick"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Bottom: add annotation -->
      <div class="px-4 py-3 border-t border-slate-100 shrink-0 bg-white">
        <AnnotationForm
          v-if="showForm"
          @submit="handleCreate"
          @cancel="showForm = false"
        />
        <button
          v-else
          @click="showForm = true"
          class="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-xl hover:bg-indigo-100 transition-colors"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          添加标注
        </button>
      </div>
    </template>

    <!-- Metadata modal -->
    <EbookMetadataModal
      v-if="book"
      :visible="metadataVisible"
      :content-id="contentId"
      @close="metadataVisible = false"
      @updated="fetchBook"
    />
  </div>
</template>
