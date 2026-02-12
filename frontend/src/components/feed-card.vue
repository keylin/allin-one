<script setup>
import { computed } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.extend(utc)
dayjs.locale('zh-cn')

const props = defineProps({
  item: { type: Object, required: true },
})

const emit = defineEmits(['click', 'favorite'])

const statusConfig = {
  pending: { label: '待处理', class: 'bg-slate-100 text-slate-500' },
  processing: { label: '处理中', class: 'bg-indigo-50 text-indigo-600' },
  analyzed: { label: '已分析', class: 'bg-emerald-50 text-emerald-600' },
  failed: { label: '失败', class: 'bg-rose-50 text-rose-600' },
}

const mediaIcons = {
  text: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z',
  video: 'M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z',
  audio: 'M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z',
  image: 'M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z',
  mixed: 'M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z',
}

const mediaColors = {
  text: 'text-slate-400',
  video: 'text-violet-500',
  audio: 'text-rose-500',
  image: 'text-emerald-500',
  mixed: 'text-indigo-500',
}

const relTime = computed(() => {
  const time = props.item.published_at || props.item.collected_at
  return time ? dayjs.utc(time).local().fromNow() : ''
})

const summaryText = computed(() => props.item.summary_text || '')
const tags = computed(() => props.item.tags?.slice(0, 3) || [])
const currentStatus = computed(() => statusConfig[props.item.status] || statusConfig.pending)
const mediaIcon = computed(() => mediaIcons[props.item.media_type] || mediaIcons.text)
const mediaColor = computed(() => mediaColors[props.item.media_type] || mediaColors.text)

const sentimentColor = computed(() => {
  const s = props.item.sentiment
  if (!s) return ''
  if (s === 'positive' || s === '正面') return 'bg-emerald-400'
  if (s === 'negative' || s === '负面') return 'bg-rose-400'
  return 'bg-slate-300'
})

const showThumbnail = computed(() => props.item.media_type === 'video' && props.item.has_thumbnail)
const thumbnailUrl = computed(() => showThumbnail.value ? `/api/video/${props.item.id}/thumbnail` : null)

function onThumbError(e) {
  e.target.style.display = 'none'
}
</script>

<template>
  <article
    class="group bg-white rounded-xl border border-slate-200/80 overflow-hidden hover:shadow-md hover:border-slate-300 transition-all duration-200 cursor-pointer"
    @click="emit('click', item)"
  >
    <div class="flex">
      <!-- 视频封面（左侧） -->
      <div
        v-if="showThumbnail"
        class="relative shrink-0 w-28 md:w-36 bg-slate-100 overflow-hidden"
      >
        <img
          :src="thumbnailUrl"
          :alt="item.title"
          loading="lazy"
          class="w-full h-full object-cover"
          @error="onThumbError"
        />
        <!-- 播放图标 overlay -->
        <div class="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/20 transition-colors duration-200">
          <div class="w-8 h-8 rounded-full bg-white/80 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            <svg class="w-4 h-4 text-slate-700 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
            </svg>
          </div>
        </div>
      </div>

      <!-- 内容区域 -->
      <div class="flex-1 min-w-0 px-4 py-3">
        <!-- 第一行：标题 + 收藏 -->
        <div class="flex items-start gap-2">
          <!-- 媒体类型小图标 + sentiment 色点 -->
          <div class="flex items-center gap-1.5 shrink-0 mt-0.5">
            <svg :class="mediaColor" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" :d="mediaIcon" />
            </svg>
            <span
              v-if="sentimentColor"
              :class="sentimentColor"
              class="w-2 h-2 rounded-full inline-block"
            />
          </div>

          <h3 class="flex-1 min-w-0 text-sm font-semibold text-slate-800 leading-snug group-hover:text-indigo-700 transition-colors duration-200 line-clamp-1">
            {{ item.title }}
          </h3>

          <button
            class="shrink-0 p-1 rounded-lg transition-all duration-200"
            :class="item.is_favorited ? 'text-amber-500 hover:bg-amber-50' : 'text-slate-300 hover:text-amber-500 hover:bg-slate-50 md:opacity-0 md:group-hover:opacity-100'"
            @click.stop="emit('favorite', item.id)"
          >
            <svg class="w-4 h-4" :fill="item.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
            </svg>
          </button>
        </div>

        <!-- 第二行：摘要 -->
        <div class="mt-1">
          <p v-if="summaryText" class="text-xs text-slate-500 leading-relaxed line-clamp-2">
            {{ summaryText }}
          </p>
          <p v-else-if="item.status === 'pending'" class="text-xs text-slate-400 italic">
            等待分析...
          </p>
          <p v-else-if="item.status === 'processing'" class="text-xs text-indigo-400 italic">
            正在处理...
          </p>
        </div>

        <!-- 第三行：元信息 + 状态 + 标签 -->
        <div class="mt-1.5 flex items-center gap-x-3 flex-wrap text-xs text-slate-400">
          <span class="truncate max-w-[120px] font-medium text-slate-500">{{ item.source_name || '未知来源' }}</span>

          <span v-if="item.author" class="truncate max-w-[80px]">{{ item.author }}</span>

          <span v-if="item.view_count > 0" class="inline-flex items-center gap-0.5">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.64 0 8.577 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.64 0-8.577-3.007-9.963-7.178z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            {{ item.view_count }}
          </span>

          <span v-if="relTime">{{ relTime }}</span>

          <!-- 状态 badge -->
          <span
            :class="currentStatus.class"
            class="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium leading-none"
          >
            {{ currentStatus.label }}
          </span>

          <!-- 标签 -->
          <span
            v-for="tag in tags"
            :key="tag"
            class="text-indigo-500/70 truncate max-w-[80px]"
          >#{{ tag }}</span>
        </div>
      </div>
    </div>
  </article>
</template>
