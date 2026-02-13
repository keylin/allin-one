<script setup>
import { ref, computed, watch } from 'vue'
import { getContent, analyzeContent, toggleFavorite } from '@/api/content'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { formatTimeFull } from '@/utils/time'

const props = defineProps({
  contentId: { type: String, default: null },
})

const emit = defineEmits(['favorite', 'analyzed'])

const content = ref(null)
const loading = ref(false)
const analyzing = ref(false)
const videoError = ref(false)
const contentViewMode = ref('best') // 'best' | 'processed' | 'raw'

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

const md = new MarkdownIt({ html: true, linkify: true, typographer: true })

watch(() => props.contentId, async (newId) => {
  contentViewMode.value = 'best'
  if (newId) {
    await loadContent()
  } else {
    content.value = null
  }
}, { immediate: true })

async function loadContent() {
  if (!props.contentId) return
  loading.value = true
  videoError.value = false
  try {
    const res = await getContent(props.contentId)
    if (res.code === 0) content.value = res.data
  } finally {
    loading.value = false
  }
}

const renderedAnalysis = computed(() => {
  if (!content.value?.analysis_result) return ''
  const analysis = content.value.analysis_result
  if (typeof analysis === 'object') {
    let markdown = ''
    if (analysis.summary) markdown += `## 摘要\n\n${analysis.summary}\n\n`
    if (analysis.tags && Array.isArray(analysis.tags)) markdown += `**标签:** ${analysis.tags.join(', ')}\n\n`
    if (analysis.sentiment) markdown += `**情感:** ${analysis.sentiment}\n\n`
    if (analysis.category) markdown += `**分类:** ${analysis.category}\n\n`
    for (const [key, value] of Object.entries(analysis)) {
      if (!['summary', 'tags', 'sentiment', 'category'].includes(key)) {
        markdown += `**${key}:** ${value}\n\n`
      }
    }
    return md.render(markdown)
  }
  return md.render(String(analysis))
})

const renderedContent = computed(() => {
  if (!content.value?.processed_content) return ''
  const text = content.value.processed_content
  // HTML 内容 → DOMPurify 清理后直接渲染
  if (/<[a-z][\s\S]*>/i.test(text)) {
    return DOMPurify.sanitize(text, {
      ALLOWED_TAGS: [
        'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'a', 'img', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
        'em', 'strong', 'b', 'i', 'u', 's', 'del', 'sub', 'sup', 'hr',
        'table', 'thead', 'tbody', 'tr', 'td', 'th', 'caption',
        'figure', 'figcaption', 'div', 'span',
      ],
      ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'width', 'height', 'target', 'rel', 'class'],
      ADD_ATTR: ['target'],
      FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'textarea', 'select'],
    })
  }
  // Markdown fallback（兼容历史纯文本数据）
  if (text.includes('##') || text.includes('**') || text.includes('[](')) {
    return md.render(text)
  }
  return `<pre class="whitespace-pre-wrap">${text}</pre>`
})

// 是否两个版本都有内容，支持切换
const hasBothVersions = computed(() => {
  return !!content.value?.processed_content && hasRawContent.value
})

// 当前展示的正文 HTML
const displayedBodyHtml = computed(() => {
  const mode = contentViewMode.value
  if (mode === 'raw' && hasRawContent.value) return renderedRawContent.value
  if (mode === 'processed' && content.value?.processed_content) return renderedContent.value
  if (content.value?.processed_content) return renderedContent.value
  if (hasRawContent.value) return renderedRawContent.value
  return ''
})

const currentViewLabel = computed(() => {
  if (contentViewMode.value === 'raw') return '原文'
  if (contentViewMode.value === 'processed') return '处理版'
  return content.value?.processed_content ? '处理版' : '原文'
})

function toggleContentView() {
  if (contentViewMode.value === 'raw' || (contentViewMode.value === 'best' && !content.value?.processed_content)) {
    contentViewMode.value = 'processed'
  } else {
    contentViewMode.value = 'raw'
  }
}

const renderedRawContent = computed(() => {
  if (!content.value?.raw_data) return ''
  try {
    const raw = typeof content.value.raw_data === 'string'
      ? JSON.parse(content.value.raw_data)
      : content.value.raw_data
    if (!raw || typeof raw !== 'object') return ''
    let html = ''
    if (Array.isArray(raw.content) && raw.content.length > 0) {
      const first = raw.content[0]
      html = typeof first === 'object' ? (first.value || '') : String(first)
    }
    if (!html) html = raw.summary || raw.description || ''
    if (!html.trim()) return ''
    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS: [
        'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'a', 'img', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
        'em', 'strong', 'b', 'i', 'u', 's', 'del', 'sub', 'sup', 'hr',
        'table', 'thead', 'tbody', 'tr', 'td', 'th', 'caption',
        'figure', 'figcaption', 'video', 'source', 'audio',
        'div', 'span',
      ],
      ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'width', 'height', 'target', 'rel', 'class'],
      ADD_ATTR: ['target'],
      FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'textarea', 'select'],
    })
  } catch {
    return ''
  }
})

const hasRawContent = computed(() => renderedRawContent.value.length > 0)

const statusLabels = {
  pending: '待处理',
  processing: '处理中',
  analyzed: '已分析',
  failed: '失败',
}
const statusStyles = {
  pending: 'bg-slate-100 text-slate-600',
  processing: 'bg-indigo-50 text-indigo-700',
  analyzed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
}

async function handleAnalyze() {
  if (!props.contentId || analyzing.value) return
  analyzing.value = true
  try {
    await analyzeContent(props.contentId)
    await loadContent()
    emit('analyzed', props.contentId)
  } finally {
    analyzing.value = false
  }
}

async function handleFavorite() {
  if (!props.contentId) return
  await toggleFavorite(props.contentId)
  if (content.value) content.value.is_favorited = !content.value.is_favorited
  emit('favorite', props.contentId)
}

function formatTime(t) {
  return formatTimeFull(t)
}

defineExpose({ content })
</script>

<template>
  <!-- Loading -->
  <div v-if="loading && !content" class="flex-1 flex items-center justify-center">
    <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
    </svg>
  </div>

  <!-- Detail content -->
  <template v-else-if="content">
    <div class="flex-1 overflow-y-auto overflow-x-hidden p-6 space-y-6">
      <!-- Title + meta -->
      <div>
        <h2 class="text-xl font-bold text-slate-900 mb-2">{{ content.title }}</h2>
        <div class="flex items-center gap-3 text-sm text-slate-400 flex-wrap">
          <span class="font-medium text-slate-500">{{ content.source_name || '未知来源' }}</span>
          <span v-if="content.author">{{ content.author }}</span>
          <span>{{ formatTime(content.published_at || content.created_at) }}</span>
          <span
            v-if="content.status"
            class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md"
            :class="statusStyles[content.status] || 'bg-slate-100 text-slate-600'"
          >
            {{ statusLabels[content.status] || content.status }}
          </span>
        </div>
        <div v-if="content.url" class="mt-2 text-sm">
          <a :href="content.url" target="_blank" class="text-indigo-600 hover:underline break-all">
            {{ content.url }}
          </a>
        </div>
      </div>

      <!-- Video player -->
      <div v-if="content.media_type === 'video'" class="bg-black rounded-xl overflow-hidden">
        <video
          :key="content.id"
          controls
          preload="metadata"
          class="w-full max-h-[60vh]"
          :poster="`/api/video/${content.id}/thumbnail`"
          @error="videoError = true"
        >
          <source :src="`/api/video/${content.id}/stream`" type="video/mp4" />
        </video>
        <div v-if="videoError" class="flex items-center justify-center py-8 text-slate-400 text-sm bg-slate-900">
          <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          视频文件未找到
        </div>
      </div>

      <!-- AI analysis -->
      <div v-if="content.analysis_result" class="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-6 border border-indigo-100">
        <h3 class="text-base font-semibold text-slate-900 mb-4 flex items-center gap-2">
          <svg class="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          AI 分析
        </h3>
        <div class="prose prose-sm max-w-none markdown-content" v-html="renderedAnalysis"></div>
      </div>

      <!-- 正文内容（智能选择最佳版本） -->
      <div v-if="displayedBodyHtml" class="bg-slate-50 rounded-xl p-6">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-base font-semibold text-slate-900 flex items-center gap-2">
            <svg class="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
            正文内容
          </h3>
          <button
            v-if="hasBothVersions"
            class="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border border-slate-200 text-slate-500 hover:text-slate-700 hover:border-slate-300 bg-white transition-all"
            @click="toggleContentView"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
            </svg>
            {{ currentViewLabel === '处理版' ? '查看原文' : '查看处理版' }}
          </button>
        </div>
        <div class="prose prose-sm max-w-none markdown-content text-slate-700" v-html="displayedBodyHtml"></div>
      </div>

      <!-- Raw JSON -->
      <details v-if="content.raw_data" class="group">
        <summary class="cursor-pointer text-sm font-medium text-slate-600 hover:text-slate-900 select-none">
          查看原始数据
          <svg class="w-4 h-4 inline-block ml-1 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
          </svg>
        </summary>
        <pre class="mt-3 p-4 bg-slate-900 text-slate-100 rounded-lg text-xs overflow-x-auto">{{ JSON.stringify(typeof content.raw_data === 'string' ? JSON.parse(content.raw_data) : content.raw_data, null, 2) }}</pre>
      </details>
    </div>

    <!-- Bottom action bar -->
    <div class="flex items-center justify-between px-6 py-3 border-t border-slate-100 shrink-0 bg-white">
      <div class="flex items-center gap-2">
        <button
          class="px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors disabled:opacity-40"
          :disabled="analyzing"
          @click="handleAnalyze"
        >
          {{ analyzing ? '分析中...' : '重新分析' }}
        </button>
        <button
          class="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
          :class="content.is_favorited ? 'text-amber-600 hover:bg-amber-50' : 'text-slate-500 hover:bg-slate-100'"
          @click="handleFavorite"
        >
          {{ content.is_favorited ? '取消收藏' : '收藏' }}
        </button>
      </div>
    </div>
  </template>
</template>

<style scoped>
.markdown-content,
.raw-content {
  overflow-wrap: break-word;
  word-break: break-word;
}
.markdown-content :deep(img),
.raw-content :deep(img) {
  max-width: 100%;
  height: auto;
}
.markdown-content :deep(pre),
.raw-content :deep(pre) {
  overflow-x: auto;
  max-width: 100%;
}
.markdown-content :deep(table),
.raw-content :deep(table) {
  display: block;
  overflow-x: auto;
  max-width: 100%;
}
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3) {
  margin-top: 1.5em;
  margin-bottom: 0.5em;
  font-weight: 600;
  color: #1e293b;
}
.markdown-content :deep(h2) {
  font-size: 1.25em;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 0.3em;
}
.markdown-content :deep(p) {
  margin-bottom: 1em;
  line-height: 1.7;
}
.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  margin-bottom: 1em;
  padding-left: 1.5em;
}
.markdown-content :deep(li) {
  margin-bottom: 0.5em;
}
.markdown-content :deep(code) {
  background: #f1f5f9;
  padding: 0.2em 0.4em;
  border-radius: 0.25em;
  font-size: 0.9em;
  color: #e11d48;
  font-family: 'Monaco', 'Menlo', monospace;
}
.markdown-content :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  padding: 1em;
  border-radius: 0.5em;
  overflow-x: auto;
  margin-bottom: 1em;
}
.markdown-content :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
}
.markdown-content :deep(a) {
  color: #6366f1;
  text-decoration: underline;
}
.markdown-content :deep(a:hover) {
  color: #4f46e5;
}
.markdown-content :deep(blockquote) {
  border-left: 4px solid #e2e8f0;
  padding-left: 1em;
  margin-left: 0;
  color: #64748b;
  font-style: italic;
}
.markdown-content :deep(strong) {
  font-weight: 600;
  color: #1e293b;
}
.raw-content :deep(p) {
  margin-bottom: 1em;
  line-height: 1.7;
}
.raw-content :deep(h1),
.raw-content :deep(h2),
.raw-content :deep(h3),
.raw-content :deep(h4) {
  margin-top: 1.5em;
  margin-bottom: 0.5em;
  font-weight: 600;
  color: #1e293b;
}
.raw-content :deep(a) {
  color: #6366f1;
  text-decoration: underline;
}
.raw-content :deep(a:hover) {
  color: #4f46e5;
}
.raw-content :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 0.5em;
  margin: 1em 0;
}
.raw-content :deep(ul),
.raw-content :deep(ol) {
  margin-bottom: 1em;
  padding-left: 1.5em;
}
.raw-content :deep(li) {
  margin-bottom: 0.5em;
}
.raw-content :deep(blockquote) {
  border-left: 4px solid #e2e8f0;
  padding-left: 1em;
  margin-left: 0;
  color: #64748b;
  font-style: italic;
}
.raw-content :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  padding: 1em;
  border-radius: 0.5em;
  overflow-x: auto;
  margin-bottom: 1em;
}
.raw-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 1em;
}
.raw-content :deep(th),
.raw-content :deep(td) {
  border: 1px solid #e2e8f0;
  padding: 0.5em 0.75em;
  text-align: left;
}
.raw-content :deep(th) {
  background: #f8fafc;
  font-weight: 600;
}
</style>
