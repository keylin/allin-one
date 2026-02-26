<script setup>
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { listAnnotations } from '@/api/ebook'
import { isExternalSource, getSourceConfig } from '@/config/external-sources'
import { colorOptions, colorMap } from '@/config/annotation-colors'
import { formatTimeShort } from '@/utils/time'
import AnnotationCard from '@/components/annotation-card.vue'
import AnnotationForm from '@/components/annotation-form.vue'
import { createAnnotation, updateAnnotation, deleteAnnotation } from '@/api/ebook'

const props = defineProps({
  book: { type: Object, default: null },
  visible: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'open-metadata'])

const router = useRouter()

// Annotations
const chapters = ref([])
const totalAnnotations = ref(0)
const loadingAnnotations = ref(true)

// Filters
const searchQuery = ref('')
const filterColor = ref('')
const filterType = ref('')
let searchTimer = null

// Chapter collapse
const collapsedChapters = ref(new Set())

// Add annotation form
const showForm = ref(false)

// Delete confirm
const deleteConfirmId = ref(null)
let deleteConfirmTimer = null

async function fetchAnnotations() {
  if (!props.book) return
  loadingAnnotations.value = true
  try {
    const params = { group_by_chapter: true }
    if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
    if (filterColor.value) params.color = filterColor.value
    if (filterType.value) params.type = filterType.value

    const res = await listAnnotations(props.book.content_id, params)
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
  if (s.has(idx)) s.delete(idx)
  else s.add(idx)
  collapsedChapters.value = s
}

async function handleCreate(data) {
  try {
    const res = await createAnnotation(props.book.content_id, data)
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
    const res = await updateAnnotation(props.book.content_id, data.id, {
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
    const res = await deleteAnnotation(props.book.content_id, annId)
    if (res.code === 0) fetchAnnotations()
  } catch (e) {
    console.error('Failed to delete annotation:', e)
  }
}

function close() {
  emit('close')
}

function clearFilters() {
  searchQuery.value = ''
  filterColor.value = ''
  filterType.value = ''
}

const hasFilters = () => searchQuery.value || filterColor.value || filterType.value

// Watch for book change → reload annotations
watch(() => [props.visible, props.book], ([vis, bk]) => {
  if (vis && bk) {
    // Reset state
    chapters.value = []
    totalAnnotations.value = 0
    collapsedChapters.value = new Set()
    showForm.value = false
    searchQuery.value = ''
    filterColor.value = ''
    filterType.value = ''
    fetchAnnotations()
  }
}, { immediate: true })

// Debounced search
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(fetchAnnotations, 300)
})

watch(filterColor, fetchAnnotations)
watch(filterType, fetchAnnotations)
</script>

<template>
  <Teleport to="body">
    <!-- Backdrop -->
    <Transition
      enter-active-class="transition-opacity duration-300"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="visible"
        class="fixed inset-0 z-40 bg-black/25 backdrop-blur-[2px]"
        @click="close"
      />
    </Transition>

    <!-- Sidebar panel -->
    <Transition
      enter-active-class="transition-transform duration-300 ease-out"
      enter-from-class="translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transition-transform duration-200 ease-in"
      leave-from-class="translate-x-0"
      leave-to-class="translate-x-full"
    >
      <div
        v-if="visible && book"
        class="fixed top-0 right-0 bottom-0 z-50 w-full sm:w-[480px] bg-white shadow-2xl flex flex-col border-l border-slate-200/60"
      >
        <!-- Header -->
        <div class="shrink-0 border-b border-slate-100">
          <!-- Top row: close + actions -->
          <div class="flex items-center gap-2 px-4 pt-3 pb-2">
            <button
              @click="close"
              class="p-1.5 -ml-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-all"
              title="关闭"
            >
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
            <div class="flex-1" />
            <!-- External app button -->
            <a
              v-if="isExternalSource(book.source)"
              :href="getSourceConfig(book.source)?.deepLink(book.external_id)"
              class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
            >
              <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
              </svg>
              {{ getSourceConfig(book.source)?.openLabel || '打开' }}
            </a>
            <!-- Edit metadata button -->
            <button
              @click="emit('open-metadata', book)"
              class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors"
            >
              <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" />
              </svg>
              编辑信息
            </button>
          </div>

          <!-- Book info -->
          <div class="flex items-start gap-3 px-4 pb-3">
            <!-- Cover thumbnail -->
            <div class="w-12 h-16 shrink-0 rounded-lg overflow-hidden bg-slate-100 border border-slate-200/60">
              <img
                v-if="book.cover_url"
                :src="book.cover_url"
                :alt="book.title"
                class="w-full h-full object-cover"
              />
              <div v-else class="w-full h-full flex items-center justify-center">
                <svg class="w-5 h-5 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
                </svg>
              </div>
            </div>
            <div class="flex-1 min-w-0">
              <h2 class="text-base font-bold text-slate-900 leading-snug line-clamp-2">{{ book.title || '未知书名' }}</h2>
              <p class="text-xs text-slate-400 mt-0.5 truncate">{{ book.author || '未知作者' }}</p>
              <div class="flex items-center gap-2 mt-1.5">
                <span v-if="isExternalSource(book.source)" class="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium bg-slate-100 text-slate-500 rounded">
                  {{ getSourceConfig(book.source)?.label || book.source }}
                </span>
                <span v-if="book.progress > 0" class="text-xs text-indigo-500 font-medium tabular-nums">
                  {{ Math.round((book.progress || 0) * 100) }}%
                </span>
              </div>
            </div>
          </div>

          <!-- Progress bar -->
          <div v-if="book.progress > 0" class="px-4 pb-3">
            <div class="h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div class="h-full bg-indigo-500 rounded-full transition-all" :style="{ width: Math.round((book.progress || 0) * 100) + '%' }" />
            </div>
          </div>

          <!-- Annotation count + filters -->
          <div class="px-4 pb-2.5 space-y-2">
            <div class="flex items-center gap-2">
              <span class="text-xs font-medium text-slate-600">{{ totalAnnotations }} 条标注</span>
              <div class="flex-1" />
              <!-- Search -->
              <div class="relative">
                <svg class="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-400 pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
                </svg>
                <input
                  v-model="searchQuery"
                  placeholder="搜索标注..."
                  class="w-40 bg-slate-50 rounded-lg pl-7 pr-2 py-1 text-xs text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 focus:bg-white transition-all"
                />
              </div>
            </div>
            <!-- Filter chips -->
            <div class="flex items-center gap-2 flex-wrap">
              <div class="flex items-center gap-1.5">
                <button
                  v-for="c in colorOptions"
                  :key="c"
                  @click="filterColor = filterColor === c ? '' : c"
                  class="w-4 h-4 rounded-full transition-all duration-150"
                  :class="[
                    colorMap[c],
                    filterColor === c ? 'ring-2 ring-offset-1 ring-slate-400 scale-110' : 'opacity-40 hover:opacity-80',
                  ]"
                />
              </div>
              <span class="text-slate-200">|</span>
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
        </div>

        <!-- Annotations content -->
        <div class="flex-1 overflow-y-auto">
          <div class="py-3">
            <!-- Loading -->
            <div v-if="loadingAnnotations" class="flex items-center justify-center py-16">
              <svg class="w-6 h-6 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
            </div>

            <!-- Empty state -->
            <div v-else-if="chapters.length === 0" class="text-center py-16">
              <div class="w-12 h-12 mx-auto mb-3 bg-slate-100 rounded-xl flex items-center justify-center">
                <svg class="w-6 h-6 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                </svg>
              </div>
              <p class="text-sm text-slate-400">暂无标注</p>
              <p v-if="hasFilters()" class="text-xs text-slate-300 mt-1">试试调整筛选条件</p>
            </div>

            <!-- Chapter groups -->
            <div v-else class="space-y-2 px-3">
              <div
                v-for="(group, idx) in chapters"
                :key="idx"
                class="bg-white rounded-xl border border-slate-200/60 overflow-hidden"
              >
                <!-- Chapter header -->
                <button
                  @click="toggleChapter(idx)"
                  class="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-slate-50 transition-colors"
                >
                  <svg
                    class="w-3 h-3 text-slate-400 shrink-0 transition-transform duration-200"
                    :class="{ '-rotate-90': collapsedChapters.has(idx) }"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                  >
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                  <span class="text-xs font-medium text-slate-600 truncate flex-1">
                    {{ group.chapter || '未分类标注' }}
                  </span>
                  <span class="text-[11px] text-slate-400 tabular-nums shrink-0">({{ group.count }})</span>
                </button>
                <!-- Annotations -->
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
        <div class="shrink-0 px-4 py-3 border-t border-slate-100 bg-white">
          <AnnotationForm
            v-if="showForm"
            @submit="handleCreate"
            @cancel="showForm = false"
          />
          <button
            v-else
            @click="showForm = true"
            class="w-full flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-xl hover:bg-indigo-100 transition-colors"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 5v14M5 12h14" />
            </svg>
            添加标注
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
