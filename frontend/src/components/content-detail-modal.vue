<script setup>
import { ref, computed, watch, watchEffect, toRef, onBeforeUnmount } from 'vue'
import { getContent, analyzeContent, toggleFavorite } from '@/api/content'
import { useScrollLock } from '@/composables/useScrollLock'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import dayjs from 'dayjs'
import { formatTimeFull } from '@/utils/time'

const props = defineProps({
  visible: Boolean,
  contentId: String,
  hasPrev: { type: Boolean, default: false },
  hasNext: { type: Boolean, default: false },
  currentIndex: { type: Number, default: -1 },
  totalCount: { type: Number, default: 0 },
})

const emit = defineEmits(['close', 'favorite', 'note', 'prev', 'next'])
useScrollLock(toRef(props, 'visible'))

const content = ref(null)
const loading = ref(false)
const analyzing = ref(false)
const transitioning = ref(false)
const videoRef = ref(null)
const videoError = ref(false)

// DOMPurify: 所有链接强制新窗口打开
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

// 初始化 Markdown 解析器
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
})

// 键盘导航 — watchEffect 自动清理，避免事件泄漏
watchEffect((onCleanup) => {
  if (props.visible) {
    const handler = (e) => {
      if (e.key === 'ArrowLeft' && props.hasPrev) {
        e.preventDefault()
        emit('prev')
      } else if (e.key === 'ArrowRight' && props.hasNext) {
        e.preventDefault()
        emit('next')
      }
    }
    document.addEventListener('keydown', handler)
    onCleanup(() => document.removeEventListener('keydown', handler))
  }
})

// 监听 contentId 变化，加载数据
watch(() => props.contentId, async (newId) => {
  if (newId && props.visible) {
    contentViewMode.value = 'best'
    transitioning.value = true
    await loadContent()
    transitioning.value = false
  }
}, { immediate: true })

// 弹窗打开时始终重新加载（修复切换 tab 后 contentId 未变的情况）
watch(() => props.visible, async (val) => {
  if (val && props.contentId) {
    transitioning.value = true
    await loadContent()
    transitioning.value = false
  }
})

async function loadContent() {
  if (!props.contentId) return

  loading.value = true
  videoError.value = false
  try {
    const res = await getContent(props.contentId)
    if (res.code === 0) {
      content.value = res.data
    }
  } finally {
    loading.value = false
  }
}

// 渲染分析结果为 Markdown
const renderedAnalysis = computed(() => {
  if (!content.value?.analysis_result) return ''

  const analysis = content.value.analysis_result

  // 如果 analysis 是对象，转为 Markdown
  if (typeof analysis === 'object') {
    let markdown = ''

    if (analysis.summary) {
      markdown += `## 摘要\n\n${analysis.summary}\n\n`
    }

    if (analysis.tags && Array.isArray(analysis.tags)) {
      markdown += `**标签:** ${analysis.tags.join(', ')}\n\n`
    }

    if (analysis.sentiment) {
      markdown += `**情感:** ${analysis.sentiment}\n\n`
    }

    if (analysis.category) {
      markdown += `**分类:** ${analysis.category}\n\n`
    }

    // 其他字段
    for (const [key, value] of Object.entries(analysis)) {
      if (!['summary', 'tags', 'sentiment', 'category'].includes(key)) {
        markdown += `**${key}:** ${value}\n\n`
      }
    }

    return md.render(markdown)
  }

  // 如果是字符串，直接渲染
  return md.render(String(analysis))
})

// 渲染处理内容为 Markdown（如果内容看起来像 Markdown）
const renderedContent = computed(() => {
  if (!content.value?.processed_content) return ''

  const text = content.value.processed_content

  // 检查是否包含 Markdown 语法
  if (text.includes('##') || text.includes('**') || text.includes('[](')) {
    return md.render(text)
  }

  // 否则按纯文本处理，保留换行
  return `<pre class="whitespace-pre-wrap">${text}</pre>`
})

// 从 raw_data 提取 RSS 原文 HTML 并 sanitize
const renderedRawContent = computed(() => {
  if (!content.value?.raw_data) return ''

  try {
    const raw = typeof content.value.raw_data === 'string'
      ? JSON.parse(content.value.raw_data)
      : content.value.raw_data
    if (!raw || typeof raw !== 'object') return ''

    // 优先 content[0].value（完整 HTML），其次 summary
    let html = ''
    if (Array.isArray(raw.content) && raw.content.length > 0) {
      const first = raw.content[0]
      html = typeof first === 'object' ? (first.value || '') : String(first)
    }
    if (!html) {
      html = raw.summary || raw.description || ''
    }

    if (!html.trim()) return ''

    // DOMPurify sanitize — 只允许安全标签
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

// raw_data 中是否有可渲染的原文（用于控制显示逻辑）
const hasRawContent = computed(() => renderedRawContent.value.length > 0)

const contentViewMode = ref('best') // 'best' | 'processed' | 'raw'

// 当前展示的正文 HTML
const displayedBodyHtml = computed(() => {
  const mode = contentViewMode.value
  if (mode === 'raw' && hasRawContent.value) return renderedRawContent.value
  if (mode === 'processed' && content.value?.processed_content) return renderedContent.value
  // 'best' 模式：优先 processed，否则 raw
  if (content.value?.processed_content) return renderedContent.value
  if (hasRawContent.value) return renderedRawContent.value
  return ''
})

const hasBothVersions = computed(() => {
  return !!content.value?.processed_content && hasRawContent.value
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

async function handleAnalyze() {
  if (!props.contentId || analyzing.value) return
  analyzing.value = true
  try {
    await analyzeContent(props.contentId)
    await loadContent()
    emit('favorite', props.contentId) // trigger parent refresh
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

const statusLabels = {
  pending: '待处理',
  ready: '已就绪',
  processing: '处理中',
  analyzed: '已分析',
  failed: '失败',
}

const statusStyles = {
  pending: 'bg-slate-100 text-slate-600',
  ready: 'bg-sky-50 text-sky-700',
  processing: 'bg-indigo-50 text-indigo-700',
  analyzed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
}
</script>

<template>
  <Transition
    enter-active-class="transition-all duration-200 ease-out"
    enter-from-class="opacity-0"
    enter-to-class="opacity-100"
    leave-active-class="transition-all duration-150 ease-in"
    leave-from-class="opacity-100"
    leave-to-class="opacity-0"
  >
    <div
      v-if="visible"
      class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm md:p-4"
      @click.self="emit('close')"
    >
      <div class="bg-white md:rounded-2xl shadow-2xl md:max-w-4xl w-full h-full md:h-auto md:max-h-[90vh] overflow-hidden flex flex-col">
        <!-- Header -->
        <div class="flex items-start justify-between p-3 md:p-6 border-b border-slate-100">
          <div class="flex-1 min-w-0 pr-2 md:pr-4">
            <h2 class="text-base md:text-xl font-bold text-slate-900 mb-1 md:mb-2 line-clamp-2">{{ content?.title || '内容详情' }}</h2>
            <div class="flex items-center gap-1.5 md:gap-3 text-xs md:text-sm text-slate-400 flex-wrap">
              <span v-if="content?.source_name" class="font-medium text-slate-500">{{ content.source_name }}</span>
              <span v-if="content?.published_at" title="发布时间">发布于 {{ formatTime(content.published_at) }}</span>
              <span v-if="content?.author" class="hidden md:inline">{{ content.author }}</span>
              <span v-if="content?.created_at" title="采集时间" class="text-slate-400/80 hidden md:inline">采集于 {{ formatTime(content.created_at) }}</span>
              <span
                v-if="content?.status"
                class="inline-flex px-1.5 md:px-2 py-0.5 text-[10px] md:text-xs font-medium rounded-md"
                :class="statusStyles[content.status] || 'bg-slate-100 text-slate-600'"
              >
                {{ statusLabels[content.status] || content.status }}
              </span>
            </div>
          </div>
          <button
            @click="emit('close')"
            class="flex-shrink-0 p-1.5 md:p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-50 rounded-lg transition-colors"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Content -->
        <div class="flex-1 overflow-y-auto p-3 md:p-6">
          <div v-if="loading" class="flex items-center justify-center py-16">
            <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
          </div>

          <div
            v-else-if="content"
            class="space-y-6 transition-opacity duration-150"
            :class="transitioning ? 'opacity-0' : 'opacity-100'"
          >

            <div v-if="content.media_items?.some(m => m.media_type === 'video')" class="bg-black rounded-xl overflow-hidden">
              <video
                ref="videoRef"
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

            <!-- AI 分析结果 -->
            <div v-if="content.analysis_result" class="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-4 md:p-6 border border-indigo-100">
              <h3 class="text-base font-semibold text-slate-900 mb-4 flex items-center gap-2">
                <svg class="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
                AI 分析
              </h3>
              <div class="prose prose-sm max-w-none markdown-content" v-html="renderedAnalysis"></div>
            </div>

            <!-- 正文内容（智能选择最佳版本） -->
            <div v-if="displayedBodyHtml" class="bg-slate-50 rounded-xl p-4 md:p-6 relative">
              <div v-if="hasBothVersions" class="absolute top-4 right-4 z-10">
                <button
                  class="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border border-slate-200 text-slate-500 hover:text-slate-700 hover:border-slate-300 bg-white transition-all shadow-sm"
                  @click="toggleContentView"
                >
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                  </svg>
                  {{ currentViewLabel === '处理版' ? '查看原文' : '查看处理版' }}
                </button>
              </div>
              <div class="prose prose-sm max-w-none markdown-content text-slate-700 mt-2" v-html="displayedBodyHtml"></div>
            </div>


          </div>
        </div>

        <!-- Footer -->
        <div class="flex items-center justify-between px-3 py-2.5 md:p-6 border-t border-slate-100">
          <div class="flex items-center gap-1 md:gap-2">
            <button
              v-if="content"
              class="px-2.5 md:px-4 py-1.5 md:py-2 text-xs md:text-sm font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors disabled:opacity-40"
              :disabled="analyzing"
              @click="handleAnalyze"
            >
              {{ analyzing ? '分析中...' : '重新分析' }}
            </button>
            <button
              v-if="content"
              class="px-2.5 md:px-4 py-1.5 md:py-2 text-xs md:text-sm font-medium rounded-lg transition-colors"
              :class="content.is_favorited ? 'text-amber-600 hover:bg-amber-50' : 'text-slate-500 hover:bg-slate-100'"
              @click="handleFavorite"
            >
              {{ content.is_favorited ? '取消收藏' : '收藏' }}
            </button>
          </div>

          <!-- 位置指示器 + 导航 -->
          <div v-if="totalCount > 0" class="flex items-center gap-0.5">
            <button
              :disabled="!hasPrev"
              class="p-1 md:p-1.5 rounded-md transition-colors"
              :class="hasPrev ? 'text-slate-400 hover:text-slate-600 hover:bg-slate-100' : 'opacity-30 cursor-not-allowed text-slate-300'"
              title="上一篇 (←)"
              @click="emit('prev')"
            >
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
            </button>
            <span class="text-[10px] md:text-xs text-slate-400 tabular-nums px-1">{{ currentIndex + 1 }}/{{ totalCount }}</span>
            <button
              :disabled="!hasNext"
              class="p-1 md:p-1.5 rounded-md transition-colors"
              :class="hasNext ? 'text-slate-400 hover:text-slate-600 hover:bg-slate-100' : 'opacity-30 cursor-not-allowed text-slate-300'"
              title="下一篇 (→)"
              @click="emit('next')"
            >
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
              </svg>
            </button>
          </div>

          <button
            @click="emit('close')"
            class="px-2.5 md:px-4 py-1.5 md:py-2 text-xs md:text-sm font-medium text-slate-600 hover:bg-slate-50 rounded-lg transition-colors"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* Markdown 内容样式 */
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

/* RSS 原文内容样式 */
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
