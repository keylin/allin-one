<script setup>
import { ref, computed, watch } from 'vue'
import { getContent } from '@/api/content'
import MarkdownIt from 'markdown-it'
import dayjs from 'dayjs'

const props = defineProps({
  visible: Boolean,
  contentId: String,
})

const emit = defineEmits(['close'])

const content = ref(null)
const loading = ref(false)

// 初始化 Markdown 解析器
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
})

// 监听 contentId 变化，加载数据
watch(() => props.contentId, async (newId) => {
  if (newId && props.visible) {
    await loadContent()
  }
}, { immediate: true })

async function loadContent() {
  if (!props.contentId) return

  loading.value = true
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

function formatTime(t) {
  return t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-'
}

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
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      @click.self="emit('close')"
    >
      <div class="bg-white rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        <!-- Header -->
        <div class="flex items-start justify-between p-6 border-b border-slate-100">
          <div class="flex-1 min-w-0 pr-4">
            <h2 class="text-xl font-bold text-slate-900 mb-2">{{ content?.title || '内容详情' }}</h2>
            <div class="flex items-center gap-3 text-sm text-slate-400">
              <span v-if="content?.author">{{ content.author }}</span>
              <span>{{ formatTime(content?.created_at) }}</span>
              <span
                v-if="content?.status"
                class="inline-flex px-2 py-0.5 text-xs font-medium rounded-lg"
                :class="statusStyles[content.status] || 'bg-slate-100 text-slate-600'"
              >
                {{ statusLabels[content.status] || content.status }}
              </span>
            </div>
          </div>
          <button
            @click="emit('close')"
            class="flex-shrink-0 p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-50 rounded-lg transition-colors"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Content -->
        <div class="flex-1 overflow-y-auto p-6">
          <div v-if="loading" class="flex items-center justify-center py-16">
            <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
          </div>

          <div v-else-if="content" class="space-y-6">
            <!-- 原始链接 -->
            <div v-if="content.url" class="text-sm">
              <span class="font-medium text-slate-600">原始链接: </span>
              <a :href="content.url" target="_blank" class="text-indigo-600 hover:underline">
                {{ content.url }}
              </a>
            </div>

            <!-- AI 分析结果 -->
            <div v-if="content.analysis_result" class="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-6 border border-indigo-100">
              <h3 class="text-base font-semibold text-slate-900 mb-4 flex items-center gap-2">
                <svg class="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
                AI 分析
              </h3>
              <div class="prose prose-sm max-w-none markdown-content" v-html="renderedAnalysis"></div>
            </div>

            <!-- 处理后的内容 -->
            <div v-if="content.processed_content" class="bg-slate-50 rounded-xl p-6">
              <h3 class="text-base font-semibold text-slate-900 mb-4">处理后的内容</h3>
              <div class="prose prose-sm max-w-none markdown-content text-slate-700" v-html="renderedContent"></div>
            </div>

            <!-- 原始数据 -->
            <details v-if="content.raw_data" class="group">
              <summary class="cursor-pointer text-sm font-medium text-slate-600 hover:text-slate-900 select-none">
                查看原始数据
                <svg class="w-4 h-4 inline-block ml-1 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                </svg>
              </summary>
              <pre class="mt-3 p-4 bg-slate-900 text-slate-100 rounded-lg text-xs overflow-x-auto">{{ JSON.stringify(JSON.parse(content.raw_data), null, 2) }}</pre>
            </details>
          </div>
        </div>

        <!-- Footer -->
        <div class="flex items-center justify-end gap-3 p-6 border-t border-slate-100">
          <button
            @click="emit('close')"
            class="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 rounded-lg transition-colors"
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
</style>
