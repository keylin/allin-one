<script setup>
import { formatTimeShort } from '@/utils/time'

defineProps({
  sourceName: { type: String, default: '' },
  publishedAt: { type: String, default: null },
  collectedAt: { type: String, default: null },
  viewCount: { type: Number, default: 0 },
  favoritedAt: { type: String, default: null },
  tags: { type: Array, default: () => [] },
  showTags: { type: Boolean, default: false },
  maxTags: { type: Number, default: 2 },
})

const emit = defineEmits(['tag-click'])
</script>

<template>
  <div class="flex items-center justify-between text-[11px] text-slate-400">
    <!-- Left: source + time -->
    <div class="flex items-center gap-1.5 min-w-0">
      <span v-if="sourceName" class="truncate max-w-[100px] text-slate-500 font-medium">{{ sourceName }}</span>
      <template v-if="publishedAt || collectedAt">
        <span v-if="sourceName" class="text-slate-200">&middot;</span>
        <span class="shrink-0 whitespace-nowrap">{{ formatTimeShort(publishedAt || collectedAt) }}</span>
      </template>
    </div>
    <!-- Right: views + favorited + tags -->
    <div class="flex items-center gap-1.5 shrink-0">
      <span v-if="viewCount > 0" class="inline-flex items-center gap-0.5">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
        {{ viewCount }}
      </span>
      <template v-if="favoritedAt">
        <span v-if="viewCount > 0" class="text-slate-200">&middot;</span>
        <span class="inline-flex items-center gap-0.5">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" /></svg>
          {{ formatTimeShort(favoritedAt) }}
        </span>
      </template>
      <template v-if="showTags && tags.length > 0">
        <span
          v-for="tag in tags.slice(0, maxTags)"
          :key="tag"
          class="inline-flex items-center px-1.5 py-0.5 rounded-md text-[11px] font-medium bg-violet-50 text-violet-600 hover:bg-violet-100 hover:text-violet-700 cursor-pointer transition-colors duration-150"
          @click.stop="emit('tag-click', tag)"
        >
          #{{ tag }}
        </span>
      </template>
    </div>
  </div>
</template>
