<script setup>
import { ref, computed } from 'vue'
import IframeVideoPlayer from '@/components/iframe-video-player.vue'
import PodcastPlayer from '@/components/podcast-player.vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { formatTimeFull, formatTimeShort } from '@/utils/time'

const props = defineProps({
  item: { type: Object, required: true },
  isMobileOverlay: { type: Boolean, default: false },
  analyzing: { type: Boolean, default: false },
  enriching: { type: Boolean, default: false },
  enrichResults: { type: Array, default: null },
  showEnrichModal: { type: Boolean, default: false },
  applyingEnrich: { default: null },
})

const emit = defineEmits(['analyze', 'favorite', 'enrich', 'apply-enrich', 'close-enrich', 'back'])

// Markdown & DOMPurify setup
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

const md = new MarkdownIt({ html: true, linkify: true, typographer: true })

const contentViewMode = ref('best') // 'best' | 'processed' | 'raw'


// --- Computed ---
const renderedAnalysis = computed(() => {
  if (!props.item?.analysis_result) return ''
  const analysis = props.item.analysis_result
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
  if (!props.item?.processed_content) return ''
  const text = props.item.processed_content
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
  if (!props.item?.raw_data) return ''
  try {
    const raw = typeof props.item.raw_data === 'string'
      ? JSON.parse(props.item.raw_data)
      : props.item.raw_data
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

// 音频媒体项
const audioMedia = computed(() => {
  return props.item?.media_items?.find(m => m.media_type === 'audio' && m.original_url)
})

// 音频播放地址：已下载用本地 stream API，否则用远程 URL
const audioPlayUrl = computed(() => {
  if (!audioMedia.value) return ''
  if (audioMedia.value.status === 'downloaded') {
    return `/api/audio/${props.item.id}/stream`
  }
  return audioMedia.value.original_url
})

// 解析 raw_data
const parsedRawData = computed(() => {
  if (!props.item?.raw_data) return null
  try {
    const raw = typeof props.item.raw_data === 'string'
      ? JSON.parse(props.item.raw_data)
      : props.item.raw_data
    return raw && typeof raw === 'object' ? raw : null
  } catch { return null }
})

const podcastMeta = computed(() => parsedRawData.value?.podcast_meta || null)
const itunesMeta = computed(() => parsedRawData.value?.itunes || null)

// 是否两个版本都有内容，支持切换
const hasBothVersions = computed(() => {
  return !!props.item?.processed_content && hasRawContent.value
})

// 当前展示的正文 HTML（根据 contentViewMode 选择）
const displayedBodyHtml = computed(() => {
  const mode = contentViewMode.value
  if (mode === 'raw' && hasRawContent.value) return renderedRawContent.value
  if (mode === 'processed' && props.item?.processed_content) return renderedContent.value
  // 'best' 模式：优先 processed，否则 raw
  if (props.item?.processed_content) return renderedContent.value
  if (hasRawContent.value) return renderedRawContent.value
  return ''
})

// 当前展示模式的标签
const currentViewLabel = computed(() => {
  if (contentViewMode.value === 'raw') return '原文'
  if (contentViewMode.value === 'processed') return '处理版'
  // best 模式下显示实际选中的版本
  return props.item?.processed_content ? '处理版' : '原文'
})

function toggleContentView() {
  if (contentViewMode.value === 'raw' || (contentViewMode.value === 'best' && !props.item?.processed_content)) {
    contentViewMode.value = 'processed'
  } else {
    contentViewMode.value = 'raw'
  }
}

function resetViewMode() {
  contentViewMode.value = 'best'
}

function formatTime(t) {
  return formatTimeFull(t)
}

function renderEnrichMarkdown(text) {
  return DOMPurify.sanitize(md.render(text))
}

function formatBytes(len) {
  if (len < 1024) return `${len} B`
  return `${(len / 1024).toFixed(1)} KB`
}

defineExpose({ resetViewMode })
</script>

<template>
  <!-- 移动端 sticky header -->
  <div v-if="isMobileOverlay" class="sticky top-0 z-10 bg-white/95 backdrop-blur-sm border-b border-slate-100 px-3 py-2">
    <!-- Row 1: 返回 + 来源 · 时间 + 内容切换 chip -->
    <div class="flex items-center gap-1.5">
      <button class="shrink-0 p-2 -ml-2 rounded-lg text-slate-500 active:bg-slate-100 transition-colors" @click="emit('back')">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
        </svg>
      </button>
      <div class="flex-1 min-w-0 flex items-center gap-1.5 text-xs text-slate-400">
        <span class="inline-flex items-center gap-1 font-medium text-slate-500 truncate">
          <span class="w-1.5 h-1.5 rounded-full bg-indigo-400 shrink-0"></span>
          {{ item.source_name || '未知来源' }}
        </span>
        <span class="text-slate-300 shrink-0">&middot;</span>
        <span v-if="item.published_at" class="shrink-0">{{ formatTimeShort(item.published_at) }}</span>
      </div>
      <button
        v-if="hasBothVersions"
        class="shrink-0 inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full border border-slate-200 text-slate-500 active:bg-slate-100 transition-all"
        @click="toggleContentView"
      >
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
        </svg>
        {{ currentViewLabel }}
      </button>
    </div>
    <!-- Row 2: 标题（最多2行） -->
    <h2 class="mt-1 text-base font-bold text-slate-900 line-clamp-2 pl-1" :title="item.title">{{ item.title }}</h2>
  </div>

  <!-- 桌面端标题 + 操作按钮 + 元信息 -->
  <div v-else>
    <div class="flex items-start justify-between gap-3">
      <h2 class="text-base md:text-xl font-bold text-slate-900 mb-1 md:mb-2 min-w-0 line-clamp-2" :title="item.title">{{ item.title }}</h2>
      <div class="hidden md:flex items-center gap-1 shrink-0">
        <a
          v-if="item.url"
          :href="item.url"
          target="_blank"
          rel="noopener"
          class="p-1.5 rounded-lg text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 transition-all"
          title="查看原文"
        >
          <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
          </svg>
        </a>
        <button
          class="p-1.5 rounded-lg transition-all disabled:opacity-40"
          :class="analyzing ? 'text-indigo-600 animate-spin' : 'text-slate-400 hover:text-indigo-600 hover:bg-indigo-50'"
          :disabled="analyzing"
          title="重新分析"
          @click="emit('analyze')"
        >
          <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
          </svg>
        </button>
        <button
          class="p-1.5 rounded-lg transition-all"
          :class="item.is_favorited
            ? 'text-amber-500 hover:bg-amber-50'
            : 'text-slate-400 hover:text-amber-500 hover:bg-amber-50'"
          :title="item.is_favorited ? '取消收藏' : '收藏'"
          @click="emit('favorite')"
        >
          <svg class="w-4.5 h-4.5" :fill="item.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
          </svg>
        </button>
      </div>
    </div>
    <div class="flex items-center gap-1.5 md:gap-2 text-xs md:text-sm text-slate-400 flex-wrap">
      <!-- 移动端收藏+跳转 -->
      <div class="flex items-center gap-0.5 md:hidden -ml-1">
        <button
          class="p-1 rounded-md transition-all"
          :class="item.is_favorited ? 'text-amber-500' : 'text-slate-400'"
          @click="emit('favorite')"
        >
          <svg class="w-4 h-4" :fill="item.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
          </svg>
        </button>
        <a
          v-if="item.url"
          :href="item.url"
          target="_blank"
          rel="noopener"
          class="p-1 rounded-md text-slate-400 hover:text-indigo-600 transition-all"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
          </svg>
        </a>
      </div>
      <span class="inline-flex items-center gap-1.5 font-medium text-slate-500">
        <span class="w-2 h-2 rounded-full bg-indigo-400 shrink-0"></span>
        {{ item.source_name || '未知来源' }}
      </span>
      <span v-if="item.author" class="text-slate-400 hidden md:inline">{{ item.author }}</span>
      <span class="text-slate-300">&middot;</span>
      <span v-if="item.published_at" title="发布时间">发布于 {{ formatTime(item.published_at) }}</span>
      <span v-if="item.created_at" title="采集时间" class="text-slate-400 hidden md:inline">采集于 {{ formatTime(item.created_at) }}</span>
      <span v-if="item.reading_time_min" class="inline-flex items-center gap-1 text-slate-400 hidden md:inline-flex">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        约 {{ item.reading_time_min }} 分钟
      </span>
    </div>
    <!-- 操作按钮组（富化对比 + 收藏） -->
    <div class="mt-3 hidden md:flex items-center gap-2">
      <!-- 查看来源按钮 -->
      <a
        v-if="item.url"
        :href="item.url"
        target="_blank"
        rel="noopener noreferrer"
        class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300 hover:text-slate-800 transition-all"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
        </svg>
        查看来源
      </a>
      <!-- 富化对比按钮 -->
      <button
        v-if="item.url"
        class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        :class="enriching
          ? 'bg-emerald-50 text-emerald-700 border-emerald-200 animate-pulse'
          : 'bg-white text-emerald-700 border-emerald-200 hover:bg-emerald-50 hover:border-emerald-300'"
        :disabled="enriching"
        @click="emit('enrich')"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
        </svg>
        {{ enriching ? '富化中...' : '富化对比' }}
      </button>

      <!-- 切换原文/处理版按钮 -->
      <button
        v-if="hasBothVersions"
        class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300 hover:text-slate-800 transition-all"
        @click="toggleContentView"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
        </svg>
        {{ currentViewLabel === '处理版' ? '查看原文' : '查看处理版' }}
      </button>

      <!-- 收藏按钮 -->
      <button
        class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-all"
        :class="item.is_favorited
          ? 'bg-amber-50 text-amber-600 border-amber-200 hover:bg-amber-100'
          : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50 hover:border-slate-300'"
        @click="emit('favorite')"
      >
        <svg class="w-3.5 h-3.5" :fill="item.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
        </svg>
        {{ item.is_favorited ? '已收藏' : '收藏' }}
      </button>
    </div>
  </div>

  <!-- 内容 + 操作按钮容器（移动端 flex-col min-h 确保按钮在下半屏） -->
  <div :class="isMobileOverlay ? 'flex flex-col min-h-[50vh]' : ''">
    <!-- 视频播放器 -->
    <div :class="isMobileOverlay ? 'px-4 py-2' : ''">
      <IframeVideoPlayer
        v-if="item.media_items?.some(m => m.media_type === 'video')"
        :key="'vp-' + item.id"
        :video-url="item.url"
        :title="item.title || '视频播放'"
      />
    </div>

    <!-- 播客音频播放器 -->
    <div :class="isMobileOverlay ? 'px-4 py-2' : ''">
      <PodcastPlayer
        v-if="audioMedia"
        :key="'ap-' + item.id"
        :audio-url="audioPlayUrl"
        :title="item.title"
        :artwork-url="podcastMeta?.artwork_url || itunesMeta?.image || ''"
        :duration="itunesMeta?.duration || ''"
        :episode="itunesMeta?.episode || ''"
        :content-id="item.id"
        :playback-position="item.playback_position || 0"
      />
    </div>

    <!-- AI 分析结果 -->
    <div v-if="item.analysis_result" class="border-l-4 border-l-indigo-400" :class="isMobileOverlay ? 'mx-4 my-2 bg-slate-50 rounded-lg p-3' : 'bg-slate-50 rounded-xl p-6'">
      <h3 class="text-sm md:text-base font-semibold text-slate-900 mb-3 md:mb-4 flex items-center gap-2">
        <svg class="w-4 md:w-5 h-4 md:h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
        AI 分析
      </h3>
      <div class="prose prose-sm max-w-none markdown-content" v-html="renderedAnalysis"></div>
    </div>

    <!-- 正文内容（智能选择最佳版本） -->
    <div v-if="displayedBodyHtml" class="relative" :class="isMobileOverlay ? 'px-4 py-2' : 'bg-white rounded-xl p-6 shadow-sm border border-slate-100'">
      <div v-if="hasBothVersions && !isMobileOverlay" class="absolute top-4 right-4 z-10">
        <button
          class="inline-flex items-center gap-1.5 px-2.5 md:px-3 py-1 text-xs font-medium rounded-lg border border-slate-200 text-slate-500 hover:text-slate-700 hover:border-slate-300 bg-white transition-all shadow-sm"
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

    <!-- 弹性间距：内容短时将按钮推到下半屏 -->
    <div v-if="isMobileOverlay" class="flex-1"></div>

    <!-- 移动端操作按钮栏（收藏 + 原文） -->
    <div v-if="isMobileOverlay" class="px-4 py-3 flex items-center justify-center gap-3">
      <button
        class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-all"
        :class="item.is_favorited
          ? 'bg-amber-50 text-amber-600 border-amber-200 active:bg-amber-100'
          : 'bg-white text-slate-600 border-slate-200 active:bg-slate-50'"
        @click="emit('favorite')"
      >
        <svg class="w-3.5 h-3.5" :fill="item.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
        </svg>
        {{ item.is_favorited ? '已收藏' : '收藏' }}
      </button>
      <a
        v-if="item.url"
        :href="item.url"
        target="_blank"
        rel="noopener noreferrer"
        class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 active:bg-slate-50 transition-all"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
        </svg>
        原文
      </a>
    </div>
  </div>

  <!-- Slot for chat messages -->
  <div :class="isMobileOverlay ? 'px-4 !mt-2' : '!mt-3'"><slot></slot></div>

  <!-- 富化对比弹窗 -->
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="showEnrichModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm" @click.self="emit('close-enrich')">
        <div class="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden">
          <!-- 弹窗头部 -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100 shrink-0">
            <div>
              <h3 class="text-lg font-bold text-slate-900">富化对比</h3>
              <p class="text-xs text-slate-400 mt-0.5 truncate max-w-md">{{ item?.url }}</p>
            </div>
            <button
              class="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all"
              @click="emit('close-enrich')"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- 加载态 -->
          <div v-if="enriching" class="flex-1 flex flex-col items-center justify-center py-20">
            <svg class="w-12 h-12 animate-spin text-emerald-400 mb-4" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <p class="text-sm font-medium text-slate-600">正在并行抓取三种来源...</p>
            <p class="text-xs text-slate-400 mt-1">L1 HTTP / Crawl4AI / L3 Browserless</p>
          </div>

          <!-- 结果态 -->
          <div v-else-if="enrichResults" class="flex-1 overflow-y-auto p-6">
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div
                v-for="result in enrichResults"
                :key="result.level"
                class="flex flex-col rounded-xl border transition-all"
                :class="result.success ? 'border-slate-200 bg-white' : 'border-red-100 bg-red-50/30'"
              >
                <!-- 卡片头部 -->
                <div class="px-4 py-3 border-b" :class="result.success ? 'border-slate-100' : 'border-red-100'">
                  <div class="flex items-center justify-between mb-1.5">
                    <h4 class="text-sm font-semibold text-slate-800">{{ result.label }}</h4>
                    <span
                      class="inline-flex px-2 py-0.5 text-xs font-medium rounded-full"
                      :class="result.success ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'"
                    >
                      {{ result.success ? '成功' : '失败' }}
                    </span>
                  </div>
                  <div class="flex items-center gap-3 text-xs text-slate-400">
                    <span>{{ result.elapsed_seconds }}s</span>
                    <span v-if="result.success">{{ formatBytes(result.content_length) }}</span>
                    <span v-if="result.error" class="text-red-400 truncate" :title="result.error">{{ result.error }}</span>
                  </div>
                </div>

                <!-- 内容预览 -->
                <div class="flex-1 px-4 py-3 max-h-80 overflow-y-auto">
                  <div
                    v-if="result.success && result.content"
                    class="prose prose-sm max-w-none markdown-content text-slate-600 text-xs leading-relaxed"
                    v-html="renderEnrichMarkdown(result.content)"
                  ></div>
                  <div v-else class="flex items-center justify-center h-24">
                    <p class="text-xs text-slate-400">{{ result.error || '无内容' }}</p>
                  </div>
                </div>

                <!-- 操作按钮 -->
                <div class="px-4 py-3 border-t" :class="result.success ? 'border-slate-100' : 'border-red-100'">
                  <button
                    v-if="result.success"
                    class="w-full px-4 py-2 text-sm font-medium rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                    :class="applyingEnrich === result.level
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-emerald-600 text-white hover:bg-emerald-700'"
                    :disabled="applyingEnrich !== null"
                    @click="emit('apply-enrich', result)"
                  >
                    {{ applyingEnrich === result.level ? '应用中...' : '应用此结果' }}
                  </button>
                  <div v-else class="text-center text-xs text-slate-400 py-1.5">
                    抓取失败，不可应用
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

<style scoped>
/* 内容区域溢出控制 */
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
