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
const activeTab = ref('read') // 'read' | 'analysis' | 'original' | 'raw'

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

const md = new MarkdownIt({ html: true, linkify: true, typographer: true })

const availableTabs = computed(() => {
  const tabs = []
  if (content.value?.processed_content) {
    tabs.push({ id: 'read', label: '阅读' })
    tabs.push({ id: 'processed_data', label: '处理数据' })
  }
  if (content.value?.analysis_result) {
    tabs.push({ id: 'analysis_data', label: '分析数据' })
  }
  if (content.value?.raw_data) {
    tabs.push({ id: 'raw_data', label: '原始数据' })
  }
  return tabs
})

watch(() => props.contentId, async (newId) => {
  if (newId) {
    await loadContent()
    activeTab.value = 'read'
    // 智能选择默认 Tab
    if (content.value) {
      if (content.value.processed_content) activeTab.value = 'read'
      else if (content.value.analysis_result) activeTab.value = 'analysis_data'
      else if (content.value.raw_data) activeTab.value = 'raw_data'
      else activeTab.value = 'read'
    }
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
          <span v-if="content.published_at" title="发布时间">发布于 {{ formatTime(content.published_at) }}</span>
          <span v-if="content.created_at" title="采集时间" class="text-slate-400/80">采集于 {{ formatTime(content.created_at) }}</span>
        </div>

      </div>

      <!-- Tabs -->
      <div class="border-b border-slate-100 mb-4">
        <div class="flex gap-4">
          <button
            v-for="tab in availableTabs"
            :key="tab.id"
            class="pb-2 text-sm font-medium transition-colors border-b-2"
            :class="activeTab === tab.id ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-slate-500 hover:text-slate-700'"
            @click="activeTab = tab.id"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>

      <!-- Tab Content: Read -->
      <div v-if="activeTab === 'read'" class="space-y-6">
        <!-- Video player -->
        <div v-if="content.media_items?.some(m => m.media_type === 'video')" class="bg-black rounded-xl overflow-hidden">
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

        <!-- Processed Content -->
        <div class="prose prose-sm max-w-none markdown-content text-slate-700" v-html="renderedContent"></div>
      </div>

      <!-- Tab Content: Processed Data -->
      <div v-if="activeTab === 'processed_data'" class="bg-slate-900 rounded-xl p-4 overflow-hidden">
        <pre class="text-xs text-slate-200 font-mono whitespace-pre overflow-auto max-h-[70vh] custom-scrollbar">{{ content.processed_content }}</pre>
      </div>

      <!-- Tab Content: Analysis Data -->
      <div v-if="activeTab === 'analysis_data'" class="bg-slate-900 rounded-xl p-4 overflow-hidden">
        <pre class="text-xs text-slate-200 font-mono whitespace-pre overflow-auto max-h-[70vh] custom-scrollbar">{{ typeof content.analysis_result === 'object' ? JSON.stringify(content.analysis_result, null, 2) : content.analysis_result }}</pre>
      </div>

      <!-- Tab Content: Raw Data -->
      <div v-if="activeTab === 'raw_data'" class="bg-slate-900 rounded-xl p-4 overflow-hidden">
        <pre class="text-xs text-slate-200 font-mono whitespace-pre overflow-auto max-h-[70vh] custom-scrollbar">{{ typeof content.raw_data === 'object' ? JSON.stringify(content.raw_data, null, 2) : content.raw_data }}</pre>
      </div>


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
