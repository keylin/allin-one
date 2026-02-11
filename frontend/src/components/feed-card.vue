<script setup>
import { computed } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const props = defineProps({
  item: { type: Object, required: true },
})

const emit = defineEmits(['click', 'favorite'])

const statusConfig = {
  pending: {
    label: '待处理',
    class: 'bg-slate-100 text-slate-600',
    icon: 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z'
  },
  processing: {
    label: '处理中',
    class: 'bg-indigo-100 text-indigo-700',
    icon: 'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99'
  },
  analyzed: {
    label: '已分析',
    class: 'bg-emerald-100 text-emerald-700',
    icon: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
  },
  failed: {
    label: '失败',
    class: 'bg-rose-100 text-rose-700',
    icon: 'M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z'
  },
}

const mediaTypeConfig = {
  text: {
    icon: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z',
    color: 'text-slate-500',
    bg: 'bg-slate-50'
  },
  video: {
    icon: 'M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h1.5C5.496 19.5 6 18.996 6 18.375m-3.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-1.5A1.125 1.125 0 0118 18.375M20.625 4.5H3.375m17.25 0c.621 0 1.125.504 1.125 1.125M20.625 4.5h-1.5C18.504 4.5 18 5.004 18 5.625m3.75 0v1.5c0 .621-.504 1.125-1.125 1.125M3.375 4.5c-.621 0-1.125.504-1.125 1.125M3.375 4.5h1.5C5.496 4.5 6 5.004 6 5.625m-3.75 0v1.5c0 .621.504 1.125 1.125 1.125m0 0h1.5m-1.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m1.5-3.75C5.496 8.25 6 7.746 6 7.125v-1.5M4.875 8.25C5.496 8.25 6 8.754 6 9.375v1.5m0-5.25v5.25m0-5.25C6 5.004 6.504 4.5 7.125 4.5h9.75c.621 0 1.125.504 1.125 1.125m1.125 2.625h1.5m-1.5 0A1.125 1.125 0 0118 7.125v-1.5m1.125 2.625c-.621 0-1.125.504-1.125 1.125v1.5m2.625-2.625c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125M18 5.625v5.25M7.125 12h9.75m-9.75 0A1.125 1.125 0 016 10.875M7.125 12C6.504 12 6 12.504 6 13.125m0-2.25C6 11.496 5.496 12 4.875 12M18 10.875c0 .621-.504 1.125-1.125 1.125M18 10.875c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125m-12 5.25v-5.25m0 5.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125m-12 0v-1.5c0-.621-.504-1.125-1.125-1.125M18 18.375v-5.25m0 5.25v-1.5c0-.621.504-1.125 1.125-1.125M18 13.125v1.5c0 .621.504 1.125 1.125 1.125M18 13.125c0-.621.504-1.125 1.125-1.125M6 13.125v1.5c0 .621-.504 1.125-1.125 1.125M6 13.125C6 12.504 5.496 12 4.875 12m-1.5 0h1.5m-1.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125M19.125 12h1.5m0 0c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h1.5m14.25 0h1.5',
    color: 'text-violet-600',
    bg: 'bg-violet-50'
  },
  audio: {
    icon: 'M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z',
    color: 'text-rose-600',
    bg: 'bg-rose-50'
  },
  image: {
    icon: 'M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z',
    color: 'text-emerald-600',
    bg: 'bg-emerald-50'
  },
  mixed: {
    icon: 'M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z',
    color: 'text-indigo-600',
    bg: 'bg-indigo-50'
  },
}

const relTime = computed(() => {
  const time = props.item.published_at || props.item.collected_at
  return time ? dayjs(time).fromNow() : ''
})

const collectedTime = computed(() => {
  return props.item.collected_at ? dayjs(props.item.collected_at).format('YYYY-MM-DD HH:mm') : ''
})

const updatedTime = computed(() => {
  return props.item.updated_at ? dayjs(props.item.updated_at).format('YYYY-MM-DD HH:mm') : ''
})

const collectedFromNow = computed(() => {
  return props.item.collected_at ? dayjs(props.item.collected_at).fromNow() : ''
})

const updatedFromNow = computed(() => {
  return props.item.updated_at ? dayjs(props.item.updated_at).fromNow() : ''
})

const summary = computed(() => {
  // 优先级：analysis_result.summary > processed_content > analysis_result.content > raw_data
  if (props.item.analysis_result) {
    try {
      const parsed = JSON.parse(props.item.analysis_result)
      if (parsed.summary) return parsed.summary.slice(0, 400)
      if (parsed.content) return parsed.content.slice(0, 400)
    } catch {
      // 如果 JSON 解析失败，直接当文本用
      return props.item.analysis_result.slice(0, 400)
    }
  }

  if (props.item.processed_content) {
    return props.item.processed_content.slice(0, 400)
  }

  // 尝试从 raw_data 中提取内容
  if (props.item.raw_data) {
    try {
      const parsed = JSON.parse(props.item.raw_data)
      if (parsed.description) return parsed.description.slice(0, 400)
      if (parsed.content) return parsed.content.slice(0, 400)
      if (parsed.summary) return parsed.summary.slice(0, 400)
    } catch {
      // 忽略解析错误
    }
  }

  return ''
})

const currentStatus = computed(() => statusConfig[props.item.status] || statusConfig.pending)
const currentMediaType = computed(() => mediaTypeConfig[props.item.media_type] || mediaTypeConfig.text)
</script>

<template>
  <article
    class="group bg-white rounded-2xl border border-slate-200/80 overflow-hidden hover:shadow-lg hover:shadow-slate-200/50 hover:border-slate-300/80 transition-all duration-300 cursor-pointer flex flex-col"
    @click="emit('click', item)"
  >
    <!-- 头部 -->
    <div class="p-5 pb-4 flex-1 flex flex-col">
      <!-- 媒体类型图标 + 收藏状态 -->
      <div class="flex items-start justify-between gap-3 mb-3">
        <div
          :class="[currentMediaType.bg, currentMediaType.color]"
          class="p-2.5 rounded-xl shrink-0"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" :d="currentMediaType.icon" />
          </svg>
        </div>

        <button
          class="shrink-0 p-2 rounded-xl transition-all duration-200 -mt-1 -mr-1"
          :class="item.is_favorited ? 'text-amber-500 hover:bg-amber-50' : 'text-slate-300 hover:text-amber-500 hover:bg-slate-50'"
          @click.stop="emit('favorite', item.id)"
        >
          <svg class="w-5 h-5" :fill="item.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
          </svg>
        </button>
      </div>

      <!-- 标题 -->
      <h3 class="text-base font-bold text-slate-900 leading-snug mb-2 group-hover:text-indigo-700 transition-colors duration-200 line-clamp-2">
        {{ item.title }}
      </h3>

      <!-- 文章内容预览 -->
      <div v-if="summary" class="mb-4 flex-1">
        <p class="text-sm text-slate-600 leading-relaxed line-clamp-4">
          {{ summary }}
        </p>
        <button
          class="mt-2 text-xs text-indigo-600 hover:text-indigo-700 font-medium inline-flex items-center gap-1 group/read"
          @click.stop="emit('click', item)"
        >
          <span>阅读全文</span>
          <svg class="w-3.5 h-3.5 group-hover/read:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
          </svg>
        </button>
      </div>
      <div v-else class="flex-1"></div>

      <!-- 元信息 -->
      <div class="space-y-2 text-xs text-slate-500">
        <!-- 第一行：来源、作者、发布时间 -->
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <!-- 来源 -->
          <div class="flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
            </svg>
            <span class="font-medium truncate max-w-[120px]">{{ item.source_name || '未知' }}</span>
          </div>

          <!-- 作者 -->
          <div v-if="item.author" class="flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
            </svg>
            <span class="truncate max-w-[100px]">{{ item.author }}</span>
          </div>

          <!-- 发布时间 -->
          <div v-if="item.published_at" class="flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
            </svg>
            <span>{{ relTime }}</span>
          </div>
        </div>

        <!-- 第二行：抓取时间、更新时间 -->
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
          <!-- 抓取时间 -->
          <div class="flex items-center gap-1.5" :title="`抓取时间: ${collectedTime}`">
            <svg class="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
            <span class="text-indigo-600 font-medium">抓取</span>
            <span class="text-slate-500">{{ collectedTime }} ({{ collectedFromNow }})</span>
          </div>

          <!-- 更新时间 -->
          <div v-if="updatedTime !== collectedTime" class="flex items-center gap-1.5" :title="`更新时间: ${updatedTime}`">
            <svg class="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            <span class="text-emerald-600 font-medium">更新</span>
            <span class="text-slate-500">{{ updatedTime }} ({{ updatedFromNow }})</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部状态栏 -->
    <div class="px-5 py-3 bg-slate-50/50 border-t border-slate-100">
      <div class="flex items-center gap-2">
        <div
          :class="currentStatus.class"
          class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium"
        >
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" :d="currentStatus.icon" />
          </svg>
          <span>{{ currentStatus.label }}</span>
        </div>

        <div v-if="item.language" class="text-xs text-slate-400 ml-auto">
          {{ item.language.toUpperCase() }}
        </div>
      </div>
    </div>
  </article>
</template>
