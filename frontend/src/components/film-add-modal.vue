<script setup>
import { ref, watch } from 'vue'
import { searchTmdb, createFilm, WATCH_STATUS_OPTIONS } from '@/api/films'
import { useToast } from '@/composables/useToast'

const props = defineProps({
  visible: { type: Boolean, default: false },
  tmdbConfigured: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'added'])

const { error: showError } = useToast()

const query = ref('')
const year = ref('')
const kind = ref('movie')
const status = ref('watched')
const searching = ref(false)
const results = ref([])
const searched = ref(false)
const creating = ref(false)
let timer = null

watch(() => props.visible, (v) => {
  if (v) {
    query.value = ''
    year.value = ''
    results.value = []
    searched.value = false
  }
})

watch(query, () => {
  if (!props.tmdbConfigured) return
  clearTimeout(timer)
  if (!query.value.trim()) { results.value = []; searched.value = false; return }
  timer = setTimeout(doSearch, 400)
})

async function doSearch() {
  if (!query.value.trim()) return
  searching.value = true
  try {
    const res = await searchTmdb(query.value.trim(), year.value ? Number(year.value) : null)
    if (res.code === 0) {
      results.value = res.data
      searched.value = true
    } else {
      showError(res.message || '搜索失败')
    }
  } catch {
    showError('搜索失败')
  } finally {
    searching.value = false
  }
}

async function pick(item) {
  await submit({ tmdb_id: item.tmdb_id, kind: item.kind, title: item.title, year: item.year })
}

async function submitManual() {
  if (!query.value.trim()) return
  await submit({ title: query.value.trim(), year: year.value ? Number(year.value) : null, kind: kind.value })
}

async function submit(payload) {
  creating.value = true
  try {
    const res = await createFilm({ ...payload, status: status.value })
    if (res.code === 0) {
      emit('added', res.data)
    } else {
      showError(res.message || '添加失败')
    }
  } catch {
    showError('添加失败')
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-150"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-100"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="visible" class="fixed inset-0 z-50 flex items-end sm:items-center justify-center" @click.self="emit('close')">
        <div class="absolute inset-0 bg-slate-900/30 backdrop-blur-[2px]" @click="emit('close')" />
        <div class="relative z-10 bg-white rounded-t-2xl sm:rounded-2xl w-full sm:max-w-lg shadow-2xl overflow-hidden max-h-[85vh] flex flex-col">
          <div class="px-5 pt-5 pb-3 border-b border-slate-100">
            <h3 class="text-base font-bold tracking-tight text-slate-900">添加影片</h3>
            <p class="text-xs text-slate-400 mt-0.5">
              {{ tmdbConfigured ? '输入片名从 TMDb 搜索，点选候选即添加' : '未配置 TMDb API Key，只能按片名 + 年份建骨架记录（系统设置 · 影视资料库）' }}
            </p>
          </div>

          <div class="px-5 py-4 space-y-3 overflow-y-auto">
            <div class="flex gap-2">
              <input
                v-model="query"
                type="text"
                placeholder="片名（中文或原名）"
                class="flex-1 min-w-0 px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 focus:bg-white outline-none"
                @keydown.enter.prevent="tmdbConfigured ? doSearch() : submitManual()"
              />
              <input
                v-model="year"
                type="number"
                placeholder="年份"
                class="w-20 px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 focus:bg-white outline-none tabular-nums"
                @change="tmdbConfigured && doSearch()"
              />
            </div>

            <div class="flex items-center gap-2">
              <span class="text-[11px] text-slate-400">加入后标记为</span>
              <div class="flex gap-1">
                <button
                  v-for="opt in WATCH_STATUS_OPTIONS.filter(o => o.value !== 'unmarked')"
                  :key="opt.value"
                  class="px-2 py-1 text-[11px] rounded-md transition-all"
                  :class="status === opt.value ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'"
                  @click="status = opt.value"
                >{{ opt.label }}</button>
              </div>
            </div>

            <!-- TMDb results -->
            <template v-if="tmdbConfigured">
              <div v-if="searching" class="text-xs text-slate-400 py-2">搜索中...</div>
              <ul v-else-if="results.length" class="divide-y divide-slate-100 border border-slate-100 rounded-lg overflow-hidden">
                <li
                  v-for="item in results"
                  :key="item.kind + item.tmdb_id"
                  class="flex gap-3 p-2.5 hover:bg-indigo-50/60 cursor-pointer transition-colors"
                  :class="creating ? 'pointer-events-none opacity-60' : ''"
                  @click="pick(item)"
                >
                  <div class="w-10 h-14 shrink-0 rounded bg-slate-100 overflow-hidden">
                    <img v-if="item.poster_url" :src="item.poster_url" class="w-full h-full object-cover" loading="lazy" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <p class="text-sm font-medium text-slate-800 truncate">{{ item.title }} <span v-if="item.year" class="text-slate-400 font-normal tabular-nums">({{ item.year }})</span></p>
                    <p v-if="item.original_title && item.original_title !== item.title" class="text-xs text-slate-400 truncate">{{ item.original_title }}</p>
                    <p class="text-[10px] text-slate-400 mt-0.5">
                      <span class="px-1 rounded bg-slate-100">{{ item.kind === 'series' ? '剧集' : '电影' }}</span>
                      <span v-if="item.vote_average" class="ml-1 tabular-nums">{{ Number(item.vote_average).toFixed(1) }}</span>
                    </p>
                  </div>
                </li>
              </ul>
              <div v-else-if="searched" class="text-xs text-slate-400 py-2">TMDb 没有匹配结果，可以改用下面的骨架记录</div>
            </template>

            <!-- Manual fallback -->
            <div class="pt-1 border-t border-slate-100">
              <div class="flex items-center gap-2 mt-3">
                <select v-model="kind" class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2 py-1.5 outline-none">
                  <option value="movie">电影</option>
                  <option value="series">剧集</option>
                </select>
                <button
                  class="ml-auto px-3 py-1.5 text-xs font-medium rounded-lg transition-all"
                  :class="query.trim() && !creating ? 'text-slate-700 bg-slate-100 hover:bg-slate-200' : 'text-slate-300 bg-slate-50'"
                  :disabled="!query.trim() || creating"
                  @click="submitManual"
                >{{ creating ? '添加中...' : (tmdbConfigured ? '不走 TMDb，按片名添加' : '按片名添加') }}</button>
              </div>
            </div>
          </div>

          <div class="px-5 py-3 border-t border-slate-100 flex justify-end">
            <button class="text-sm text-slate-500 hover:text-slate-700 transition-colors" @click="emit('close')">关闭</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
