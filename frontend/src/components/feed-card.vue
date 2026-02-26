<script setup>
import { computed } from 'vue'
import { formatTimeShort } from '@/utils/time'
import ContentMetaRow from '@/components/common/content-meta-row.vue'

const props = defineProps({
  item: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['click', 'favorite', 'tag-click'])

function handleCardClick() {
  emit('click', props.item)
}


const mediaIcons = {
  text: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z',
  video: 'M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z',
  audio: 'M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z',
  image: 'M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z',
  ebook: 'M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25',
  mixed: 'M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z',
}

const mediaColors = {
  text: 'text-slate-400',
  video: 'text-violet-500',
  audio: 'text-rose-500',
  image: 'text-emerald-500',
  ebook: 'text-amber-500',
  mixed: 'text-indigo-500',
}

const relTime = computed(() => {
  const time = props.item.published_at || props.item.collected_at
  return time ? formatTimeShort(time) : ''
})

const summaryText = computed(() => props.item.summary_text || '')
const tags = computed(() => props.item.tags?.slice(0, 2) || [])
// 从 content_type（后端派生）或 media_items 推断媒体类型
const derivedMediaType = computed(() => {
  if (props.item.content_type) return props.item.content_type
  const items = props.item.media_items || []
  if (items.some(m => m.media_type === 'ebook')) return 'ebook'
  if (items.some(m => m.media_type === 'video')) return 'video'
  if (items.some(m => m.media_type === 'audio')) return 'audio'
  if (items.some(m => m.media_type === 'image')) return 'image'
  return 'text'
})
const mediaIcon = computed(() => mediaIcons[derivedMediaType.value] || mediaIcons.text)
const mediaColor = computed(() => mediaColors[derivedMediaType.value] || mediaColors.text)

const sentimentColor = computed(() => {
  const s = props.item.sentiment
  if (!s) return ''
  if (s === 'positive' || s === '正面') return 'bg-emerald-400'
  if (s === 'negative' || s === '负面') return 'bg-rose-400'
  return 'bg-slate-300'
})

// 音频时长（从后端 audio_duration 字段获取）
const audioDuration = computed(() => {
  if (derivedMediaType.value !== 'audio') return ''
  return props.item.audio_duration || ''
})

const showThumbnail = computed(() => !props.compact && props.item.has_thumbnail)
const thumbnailUrl = computed(() => showThumbnail.value ? `/api/media/${props.item.id}/thumbnail` : null)

// 计算已读状态
const isRead = computed(() => (props.item.view_count || 0) > 0)

function onThumbError(e) {
  e.target.style.display = 'none'
}
</script>

<template>
  <!-- 紧凑模式 -->
  <article
    v-if="compact"
    class="group bg-white rounded-lg border border-slate-200/80 border-l-2 overflow-hidden cursor-pointer relative transition-all duration-150 ease-out"
    :class="[
      (selected || !isRead) ? 'border-l-indigo-500' : 'border-l-transparent',
      selected
        ? 'bg-indigo-50/60 border-indigo-200 ring-1 ring-indigo-200/50 shadow-sm'
        : 'border-slate-200/80 hover:bg-slate-50 hover:border-slate-300',
    ]"
    @click="handleCardClick"
  >
    <div class="flex items-center gap-2 py-1.5 px-3">
      <!-- 媒体类型图标 -->
      <svg :class="mediaColor" class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" :d="mediaIcon" />
      </svg>
      <span v-if="audioDuration" class="text-xs md:text-[10px] font-medium text-rose-400 tabular-nums shrink-0">{{ audioDuration }}</span>

      <!-- 标题 -->
      <h3
        class="flex-1 min-w-0 text-sm leading-tight truncate transition-colors duration-200"
        :class="[
          isRead
            ? 'text-slate-400 font-normal group-hover:text-slate-600'
            : 'text-slate-800 font-semibold group-hover:text-indigo-700',
        ]"
      >
        {{ item.title }}
      </h3>

      <!-- 元信息 -->
      <span class="text-xs text-slate-400 shrink-0 truncate max-w-[80px]">{{ item.source_name || '' }}</span>
      <span v-if="relTime" class="text-xs text-slate-400 shrink-0 whitespace-nowrap">{{ relTime }}</span>

      <!-- 收藏 -->
      <button
        class="shrink-0 p-2 md:p-0.5 rounded transition-all duration-200"
        :class="item.is_favorited ? 'text-amber-400 hover:text-amber-500' : 'text-slate-200 hover:text-amber-400'"
        @click.stop="emit('favorite', item.id)"
      >
        <svg class="w-3.5 h-3.5" :fill="item.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
        </svg>
      </button>
    </div>
  </article>

  <!-- 舒适模式 -->
  <article
    v-else
    class="group bg-white rounded-xl border border-slate-200/80 border-l-[3px] overflow-hidden cursor-pointer relative"
    :class="[
      'transition-all duration-200 ease-out',
      (selected || !isRead) ? 'border-l-indigo-500' : 'border-l-transparent',
      selected
        ? 'bg-indigo-50/60 border-indigo-200 ring-1 ring-indigo-200/50 shadow-sm'
        : 'border-slate-200/80 md:hover:shadow-md md:hover:border-slate-300 md:hover:-translate-y-0.5',
    ]"
    @click="handleCardClick"
  >
    <!-- 双击爱心动画 -->
    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="scale-0 opacity-100"
      enter-to-class="scale-100 opacity-100"
      leave-active-class="transition-all duration-500 ease-in"
      leave-from-class="scale-100 opacity-100"
      leave-to-class="scale-150 opacity-0"
    >
      <div
        v-if="showHeartAnimation"
        class="absolute inset-0 flex items-center justify-center z-20 pointer-events-none"
      >
        <svg class="w-12 h-12 text-rose-500 drop-shadow-lg" fill="currentColor" viewBox="0 0 24 24">
          <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.174 2.25 8.25 2.25 5.322 4.714 3 7.688 3A5.5 5.5 0 0112 5.052 5.5 5.5 0 0116.313 3c2.973 0 5.437 2.322 5.437 5.25 0 3.925-2.438 7.111-4.739 9.256a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.219l-.022.012-.007.004-.003.001a.752.752 0 01-.704 0l-.003-.001z" />
        </svg>
      </div>
    </Transition>

    <div class="flex">
      <!-- 视频封面（左侧） -->
      <div
        v-if="showThumbnail"
        class="relative shrink-0 w-20 sm:w-24 md:w-36 bg-slate-100 overflow-hidden"
      >
        <img
          :src="thumbnailUrl"
          :alt="item.title"
          loading="lazy"
          class="w-full h-full object-cover"
          @error="onThumbError"
        />
        <!-- 播放图标 overlay (仅视频) -->
        <div v-if="derivedMediaType === 'video'" class="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/20 transition-colors duration-200">
          <div class="w-8 h-8 rounded-full bg-white/80 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            <svg class="w-4 h-4 text-slate-700 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
            </svg>
          </div>
        </div>
      </div>

      <!-- 内容区域 -->
      <div class="flex-1 min-w-0 py-3 px-3 md:px-4">
        <!-- 第一行：标题 + 收藏 -->
        <div class="flex items-start gap-2">
          <!-- 媒体类型小图标 + 音频时长 + sentiment 色点（移动端隐藏） -->
          <div class="hidden md:flex items-center gap-1.5 shrink-0 mt-0.5">
            <svg :class="mediaColor" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" :d="mediaIcon" />
            </svg>
            <span v-if="audioDuration" class="text-xs md:text-[10px] font-medium text-rose-400 tabular-nums">{{ audioDuration }}</span>
            <span
              v-if="sentimentColor"
              :class="sentimentColor"
              class="w-2 h-2 rounded-full inline-block"
            />
          </div>

          <h3
            :class="[
              isRead
                ? 'text-slate-400 font-normal group-hover:text-slate-600'
                : 'text-slate-800 font-semibold group-hover:text-indigo-700',
              'flex-1 min-w-0 text-sm leading-snug transition-colors duration-200 line-clamp-2 md:line-clamp-1'
            ]"
          >
            {{ item.title }}
          </h3>

          <button
            class="shrink-0 p-2 md:p-1 rounded-lg transition-all duration-200"
            :class="item.is_favorited ? 'text-amber-400 hover:text-amber-500 hover:bg-amber-50' : 'text-slate-200 hover:text-amber-400 hover:bg-slate-50'"
            @click.stop="emit('favorite', item.id)"
          >
            <svg class="w-5 h-5 md:w-4 md:h-4" :fill="item.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
            </svg>
          </button>
        </div>

        <!-- 第二行：摘要 -->
        <div class="mt-1">
          <p v-if="summaryText" :class="isRead ? 'text-xs text-slate-300 leading-relaxed line-clamp-2' : 'text-xs text-slate-500 leading-relaxed line-clamp-2'">
            {{ summaryText }}
          </p>
          <p v-else-if="item.status === 'pending'" class="text-xs text-slate-400 italic">
            等待分析...
          </p>
          <p v-else-if="item.status === 'processing'" class="text-xs text-indigo-400 italic">
            正在处理...
          </p>
        </div>

        <!-- 第三行：元信息 -->
        <div class="mt-1.5 flex items-center gap-2">
          <ContentMetaRow
            class="flex-1 min-w-0"
            :source-name="item.source_name || '未知来源'"
            :published-at="item.published_at"
            :collected-at="item.collected_at"
            :view-count="item.view_count || 0"
            :favorited-at="item.favorited_at"
            :tags="tags"
            :show-tags="true"
            :max-tags="2"
            @tag-click="emit('tag-click', $event)"
          />
          <!-- 重复折叠指示器 -->
          <span
            v-if="item.duplicate_count > 0"
            class="shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium text-slate-400 bg-slate-100 rounded"
            :title="`另有 ${item.duplicate_count} 条来自其他源的相似内容`"
          >
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.5a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.75" />
            </svg>
            {{ item.duplicate_count + 1 }} 源
          </span>
        </div>
      </div>
    </div>
  </article>
</template>
