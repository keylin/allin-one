<script setup>
import { ref, watch, computed } from 'vue'
import DetailDrawer from '@/components/detail-drawer.vue'
import { getFilm, getFilmStats, updateWatchRecord, updateFilmNote, deleteFilm, enrichFilm, WATCH_STATUS_OPTIONS, statusMeta } from '@/api/films'
import { formatTimeShort } from '@/utils/time'
import { useToast } from '@/composables/useToast'
import { useDoubleTapClose } from '@/composables/useDoubleTapClose'

const props = defineProps({
  visible: { type: Boolean, default: false },
  contentId: { type: String, default: null },
})
const emit = defineEmits(['close', 'updated', 'deleted'])

const { success, error: showError } = useToast()

const loading = ref(false)
const film = ref(null)
const saving = ref(false)

// editable form
const form = ref({ status: 'unmarked', my_rating: null, watched_at: '', tags: [], comment: '' })
const tagInput = ref('')
const knownTags = ref([])
const tmdbConfigured = ref(false)
const bodyRef = ref(null)
// 移动端：空白处双击关闭抽屉
useDoubleTapClose(bodyRef, { onClose: () => emit('close') })
const note = ref('')
const noteDirty = ref(false)
const deleteConfirm = ref(false)
let deleteTimer = null

async function load() {
  if (!props.contentId) return
  loading.value = true
  try {
    const res = await getFilm(props.contentId)
    if (res.code === 0) {
      film.value = res.data
      const r = res.data.record || {}
      form.value = {
        status: r.status || 'unmarked',
        my_rating: r.my_rating ?? null,
        watched_at: r.watched_at || '',
        tags: [...(r.tags || [])],
        comment: r.comment || '',
      }
      note.value = res.data.user_note || ''
      noteDirty.value = false
    }
  } finally {
    loading.value = false
  }
  loadKnownTags()
}

async function loadKnownTags() {
  try {
    const res = await getFilmStats()
    if (res.code === 0) {
      knownTags.value = res.data.tags || []
      tmdbConfigured.value = !!res.data.tmdb_configured
    }
  } catch { /* ignore */ }
}

watch(() => [props.visible, props.contentId], ([v]) => {
  if (v) load()
  else { deleteConfirm.value = false }
}, { immediate: true })

async function saveRecord(partial) {
  if (!film.value) return
  saving.value = true
  try {
    const res = await updateWatchRecord(film.value.content_id, partial)
    if (res.code === 0) {
      film.value = res.data
      emit('updated', res.data)
    } else {
      showError(res.message || '保存失败')
    }
  } catch (e) {
    showError('保存失败')
  } finally {
    saving.value = false
  }
}

function setStatus(value) {
  const next = form.value.status === value ? 'unmarked' : value
  form.value.status = next
  const payload = { status: next }
  if (next === 'watched' && !form.value.watched_at) {
    // 记不起什么时候看的很常见，默认上映日期而不是今天；后端同样兜底
    const fallback = film.value?.release_date || (film.value?.year ? `${film.value.year}-01-01` : '')
    if (fallback) {
      form.value.watched_at = fallback
      payload.watched_at = fallback
    }
  }
  saveRecord(payload)
}

function setRating(value) {
  const next = form.value.my_rating === value ? null : value
  form.value.my_rating = next
  saveRecord({ my_rating: next })
}

function saveWatchedAt() {
  saveRecord({ watched_at: form.value.watched_at || '' })
}

function addTag(raw) {
  const tag = (raw ?? tagInput.value).trim()
  tagInput.value = ''
  if (!tag || form.value.tags.includes(tag)) return
  form.value.tags = [...form.value.tags, tag]
  saveRecord({ tags: form.value.tags })
}

function removeTag(tag) {
  form.value.tags = form.value.tags.filter(t => t !== tag)
  saveRecord({ tags: form.value.tags })
}

const tagSuggestions = computed(() => knownTags.value.filter(t => !form.value.tags.includes(t)).slice(0, 12))

function saveComment() {
  saveRecord({ comment: form.value.comment })
}

async function saveNote() {
  if (!film.value) return
  saving.value = true
  try {
    const res = await updateFilmNote(film.value.content_id, note.value)
    if (res.code === 0) {
      film.value = res.data
      noteDirty.value = false
      success('长评已保存')
    }
  } finally {
    saving.value = false
  }
}

const enriching = ref(false)
async function handleEnrich() {
  if (!film.value || enriching.value) return
  enriching.value = true
  try {
    const res = await enrichFilm(film.value.content_id)
    if (res.code === 0) {
      film.value = res.data
      emit('updated', res.data)
      success(res.message || '已补全')
    } else {
      showError(res.message || '补全失败')
    }
  } catch {
    showError('补全失败')
  } finally {
    enriching.value = false
  }
}

async function handleDelete() {
  if (!deleteConfirm.value) {
    deleteConfirm.value = true
    clearTimeout(deleteTimer)
    deleteTimer = setTimeout(() => { deleteConfirm.value = false }, 3000)
    return
  }
  try {
    const res = await deleteFilm(film.value.content_id)
    if (res.code === 0) {
      success('已从资料库删除（Emby 不受影响）')
      emit('deleted', film.value.content_id)
    } else {
      showError(res.message || '删除失败')
    }
  } catch {
    showError('删除失败')
  }
}

const embyProgressLabel = computed(() => {
  const e = film.value?.emby
  if (!e) return ''
  if (film.value.kind === 'series' && e.episodes_total != null) {
    return `${e.episodes_played ?? 0} / ${e.episodes_total} 集`
  }
  if (e.played) return '已播完'
  if (e.progress > 0) return `看到 ${Math.round(e.progress * 100)}%`
  return '未播放'
})

const sourceLabel = computed(() => {
  const map = { emby: 'Emby', tmdb: 'TMDb', manual: '手工', douban: '豆瓣', emby_search: 'Emby 搜索' }
  return (film.value?.sources || []).map(s => map[s] || s).join(' · ')
})

function fmt(iso) {
  return iso ? formatTimeShort(iso) : ''
}
</script>

<template>
  <DetailDrawer :visible="visible" @close="emit('close')">
    <div v-if="loading && !film" class="flex items-center justify-center py-24">
      <svg class="w-6 h-6 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
    </div>

    <div v-else-if="film" ref="bodyRef" class="pb-10">
      <!-- Hero -->
      <div class="flex gap-4 p-5 sm:p-6 border-b border-slate-100">
        <div class="w-28 sm:w-36 shrink-0 aspect-[2/3] rounded-xl overflow-hidden bg-gradient-to-br from-slate-100 to-slate-200 shadow-sm">
          <img v-if="film.poster_url" :src="film.poster_url" :alt="film.title" class="w-full h-full object-cover" />
        </div>
        <div class="min-w-0 flex-1 pr-8">
          <h2 class="text-lg font-bold tracking-tight text-slate-900 leading-snug">{{ film.title }}</h2>
          <p v-if="film.original_title && film.original_title !== film.title" class="text-sm text-slate-400 mt-0.5">{{ film.original_title }}</p>
          <div class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
            <span v-if="film.year" class="tabular-nums">{{ film.year }}</span>
            <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">{{ film.kind === 'series' ? '剧集' : '电影' }}</span>
            <span v-if="film.runtime_min" class="tabular-nums">{{ film.runtime_min }} 分钟</span>
            <span v-if="film.community_rating" class="tabular-nums">TMDb {{ Number(film.community_rating).toFixed(1) }}</span>
            <span v-if="film.countries?.length">{{ film.countries.join(' / ') }}</span>
          </div>
          <p v-if="film.directors?.length" class="mt-2 text-sm text-slate-600"><span class="text-slate-400">导演</span> {{ film.directors.join(' / ') }}</p>
          <p v-else-if="film.metadata_state === 'partial' && !tmdbConfigured" class="mt-2 text-[11px] text-amber-600/90 leading-relaxed">
            导演、主演、类型和中文简介 Emby 的搜索接口给不了，需要 TMDb 数据：在
            <router-link to="/settings?tab=films" class="underline">系统设置 · 影视资料库</router-link> 填 TMDb API Key 后点「补全元数据」即可全部补齐。
          </p>
          <div v-if="film.genres?.length" class="mt-2 flex flex-wrap gap-1">
            <span v-for="g in film.genres" :key="g" class="px-1.5 py-0.5 text-[10px] font-medium bg-indigo-50 text-indigo-600 rounded">{{ g }}</span>
          </div>
          <p class="mt-2 text-[11px] text-slate-400">
            来源 {{ sourceLabel || '—' }}<template v-if="film.url"> · <a :href="film.url" target="_blank" rel="noopener" class="text-indigo-400 hover:underline">TMDb 页面</a></template>
            · <button class="text-indigo-400 hover:underline disabled:opacity-50" :disabled="enriching" @click="handleEnrich">{{ enriching ? '补全中...' : '补全元数据' }}</button>
          </p>
        </div>
      </div>

      <!-- 我的标记 -->
      <section class="p-5 sm:p-6 border-b border-slate-100">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-xs font-semibold uppercase tracking-wider text-slate-400">我的标记</h3>
          <span v-if="film.record?.status_source === 'emby_autofill'" class="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-600" title="状态由 Emby 播放记录自动填入，尚未经你确认">Emby 自动填入</span>
          <span v-else-if="saving" class="text-[10px] text-slate-400">保存中...</span>
        </div>

        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="opt in WATCH_STATUS_OPTIONS.filter(o => o.value !== 'unmarked')"
            :key="opt.value"
            class="px-3 py-1.5 text-xs font-medium rounded-lg border transition-all"
            :class="form.status === opt.value ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200 hover:border-slate-400'"
            @click="setStatus(opt.value)"
          >{{ opt.label }}</button>
        </div>

        <div class="mt-4">
          <p class="text-[11px] text-slate-400 mb-1.5">我的评分</p>
          <div class="flex gap-1">
            <button
              v-for="n in 10"
              :key="n"
              class="w-7 h-7 text-xs rounded-md transition-all tabular-nums"
              :class="form.my_rating != null && n <= form.my_rating ? 'bg-amber-400 text-white' : 'bg-slate-100 text-slate-400 hover:bg-amber-100'"
              @click="setRating(n)"
            >{{ n }}</button>
          </div>
        </div>

        <div class="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label class="block">
            <span class="text-[11px] text-slate-400">看过日期 <span class="text-slate-300">· 记不清就留上映日期</span></span>
            <input
              v-model="form.watched_at"
              type="date"
              class="mt-1 w-full px-3 py-1.5 text-sm bg-white border border-slate-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 outline-none"
              @change="saveWatchedAt"
            />
          </label>
        </div>

        <div class="mt-4">
          <p class="text-[11px] text-slate-400 mb-1.5">标签</p>
          <div class="flex flex-wrap items-center gap-1.5 min-h-[2rem] px-2 py-1.5 bg-white border border-slate-200 rounded-lg focus-within:ring-2 focus-within:ring-indigo-500/20 focus-within:border-indigo-300 transition-all">
            <span
              v-for="t in form.tags"
              :key="t"
              class="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 text-xs bg-indigo-50 text-indigo-700 rounded-md"
            >
              {{ t }}
              <button class="w-4 h-4 rounded hover:bg-indigo-100 text-indigo-400 hover:text-indigo-700 leading-none" :title="`移除 ${t}`" @click="removeTag(t)">×</button>
            </span>
            <input
              v-model="tagInput"
              type="text"
              :placeholder="form.tags.length ? '' : '输入后回车添加'"
              class="flex-1 min-w-[6rem] px-1 py-0.5 text-sm bg-transparent outline-none placeholder-slate-300"
              @keydown.enter.prevent="addTag()"
              @keydown.backspace="!tagInput && form.tags.length && removeTag(form.tags[form.tags.length - 1])"
              @blur="tagInput && addTag()"
            />
          </div>
          <div v-if="tagSuggestions.length" class="mt-1.5 flex flex-wrap gap-1">
            <button
              v-for="t in tagSuggestions"
              :key="t"
              class="px-1.5 py-0.5 text-[11px] text-slate-500 bg-slate-100 hover:bg-indigo-50 hover:text-indigo-600 rounded transition-all"
              @click="addTag(t)"
            >+ {{ t }}</button>
          </div>
        </div>

        <label class="block mt-3">
          <span class="text-[11px] text-slate-400">短评</span>
          <textarea
            v-model="form.comment"
            rows="2"
            placeholder="一两句话，写给以后的自己"
            class="mt-1 w-full px-3 py-2 text-sm bg-white border border-slate-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 outline-none resize-y"
            @blur="saveComment"
          />
        </label>
      </section>

      <!-- Emby 事实 -->
      <section class="p-5 sm:p-6 border-b border-slate-100">
        <h3 class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">Emby 记录</h3>
        <div v-if="film.emby" class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          <div class="bg-slate-50 rounded-lg p-2.5">
            <p class="text-[10px] text-slate-400">库内</p>
            <p class="font-medium" :class="film.emby.in_library ? 'text-emerald-600' : 'text-slate-400'">{{ film.emby.in_library ? '在库' : '已移除' }}</p>
          </div>
          <div class="bg-slate-50 rounded-lg p-2.5">
            <p class="text-[10px] text-slate-400">进度</p>
            <p class="font-medium text-slate-700">{{ embyProgressLabel }}</p>
          </div>
          <div class="bg-slate-50 rounded-lg p-2.5">
            <p class="text-[10px] text-slate-400">播放次数</p>
            <p class="font-medium text-slate-700 tabular-nums">{{ film.emby.play_count || 0 }}</p>
          </div>
          <div class="bg-slate-50 rounded-lg p-2.5">
            <p class="text-[10px] text-slate-400">最后播放</p>
            <p class="font-medium text-slate-700 text-xs">{{ fmt(film.emby.last_played_at) || '—' }}</p>
          </div>
        </div>
        <p v-else class="text-sm text-slate-400">不在 Emby 库中</p>
        <p v-if="film.emby?.last_synced_at" class="mt-2 text-[10px] text-slate-300">同步于 {{ fmt(film.emby.last_synced_at) }}</p>
      </section>

      <!-- 简介 -->
      <section v-if="film.overview || film.cast?.length || film.release_date" class="p-5 sm:p-6 border-b border-slate-100">
        <h3 class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">简介</h3>
        <p v-if="film.overview" class="text-sm text-slate-600 leading-relaxed whitespace-pre-line">{{ film.overview }}</p>
        <dl class="mt-3 grid grid-cols-[3.5rem_1fr] gap-y-1 text-xs">
          <template v-if="film.cast?.length"><dt class="text-slate-300">主演</dt><dd class="text-slate-500">{{ film.cast.join(' / ') }}</dd></template>
          <template v-if="film.release_date"><dt class="text-slate-300">上映</dt><dd class="text-slate-500 tabular-nums">{{ film.release_date }}</dd></template>
          <template v-if="film.provider_ids?.imdb"><dt class="text-slate-300">IMDb</dt><dd><a :href="`https://www.imdb.com/title/${film.provider_ids.imdb}/`" target="_blank" rel="noopener" class="text-indigo-400 hover:underline">{{ film.provider_ids.imdb }}</a></dd></template>
        </dl>
      </section>

      <!-- 长评 -->
      <section class="p-5 sm:p-6 border-b border-slate-100">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-xs font-semibold uppercase tracking-wider text-slate-400">长评 / 笔记</h3>
          <button
            v-if="noteDirty"
            class="text-xs px-2.5 py-1 rounded-lg bg-indigo-500 text-white hover:bg-indigo-600 transition-all"
            :disabled="saving"
            @click="saveNote"
          >保存</button>
        </div>
        <textarea
          v-model="note"
          rows="5"
          placeholder="支持 Markdown，随便写"
          class="w-full px-3 py-2 text-sm bg-white border border-slate-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 outline-none resize-y"
          @input="noteDirty = true"
        />
      </section>

      <!-- 危险区 -->
      <div class="px-5 sm:px-6 pt-4 flex items-center justify-between">
        <p class="text-[10px] text-slate-300">{{ film.external_id }}</p>
        <button
          class="text-xs px-2.5 py-1 rounded-lg transition-all"
          :class="deleteConfirm ? 'bg-rose-600 text-white' : 'text-slate-400 hover:text-rose-500 hover:bg-rose-50'"
          @click="handleDelete"
        >{{ deleteConfirm ? '确认删除记录' : '删除记录' }}</button>
      </div>
    </div>
  </DetailDrawer>
</template>
