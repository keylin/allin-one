<script setup>
import { ref, watch, computed } from 'vue'
import DetailDrawer from '@/components/detail-drawer.vue'
import { getFilm, getFilmStats, updateWatchRecord, addWatchLog, updateWatchLog, deleteWatchLog, deleteFilm, enrichFilm, setDoubanLink, clearDoubanLink, updateFilmMeta, relinkFilm, searchTmdb, WATCH_STATUS_OPTIONS, statusMeta } from '@/api/films'
import { formatTimeShort } from '@/utils/time'
import { useToast } from '@/composables/useToast'
import { useDoubleTapClose } from '@/composables/useDoubleTapClose'
import StarRating from '@/components/star-rating.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  contentId: { type: String, default: null },
})
const emit = defineEmits(['close', 'updated', 'deleted'])

const { success, error: showError } = useToast()

const loading = ref(false)
const film = ref(null)
const saving = ref(false)

// editable form：片级字段；观看记录（日期/评分/感想）在 logs 里逐条编辑
const form = ref({ status: 'unmarked', my_rating: null, tags: [] })
const logs = ref([])              // [{ id, watched_at, watched_precision, watched_label, my_rating, note, mode, year, month }]
const logDeleteId = ref(null)     // 待二次确认删除的观看记录
const tagInput = ref('')
const knownTags = ref([])
const tmdbConfigured = ref(false)
const bodyRef = ref(null)
// 移动端：空白处双击关闭抽屉
useDoubleTapClose(bodyRef, { onClose: () => emit('close') })
const deleteConfirm = ref(false)
let deleteTimer = null

async function load() {
  if (!props.contentId) return
  loading.value = true
  try {
    const res = await getFilm(props.contentId)
    if (res.code === 0) {
      applyFilm(res.data)
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

// 服务端返回的完整影片 → 表单 + 观看记录编辑态（保留正在编辑的感想草稿）
function applyFilm(data) {
  film.value = data
  const r = data.record || {}
  form.value = { status: r.status || 'unmarked', my_rating: r.my_rating ?? null, tags: [...(r.tags || [])] }
  const drafts = Object.fromEntries(logs.value.map(l => [l.id, l.note]))
  logs.value = (r.logs || []).map(l => ({
    ...l,
    note: l.id in drafts && drafts[l.id] !== (l.note || '') ? drafts[l.id] : (l.note || ''),
    mode: !l.watched_at ? 'none' : (l.watched_precision === 'release' ? 'unknown' : l.watched_precision === 'year' ? 'year' : l.watched_precision === 'month' ? 'month' : 'day'),
    year: l.watched_at ? l.watched_at.slice(0, 4) : '',
    month: l.watched_at ? l.watched_at.slice(0, 7) : '',
    day: l.watched_at || '',
  }))
}

async function saveRecord(partial) {
  if (!film.value) return
  saving.value = true
  try {
    const res = await updateWatchRecord(film.value.content_id, partial)
    if (res.code === 0) {
      applyFilm(res.data)
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
  saveRecord({ status: next })   // 看过不带日期 = 时间不详，不伪造
}

function setRating(value) {
  // 非看过状态下的打分：后端落到最近一次观看（没有则新建）并把片记为看过
  form.value.my_rating = value
  saveRecord({ my_rating: value })
}

// ---- 观看记录：一次观看一条，各自有日期 / 评分 / 感想 ----
async function saveLog(log, partial) {
  if (!film.value) return
  saving.value = true
  try {
    const res = await updateWatchLog(film.value.content_id, log.id, partial)
    if (res.code === 0) {
      applyFilm(res.data)
      emit('updated', res.data)
    } else {
      showError(res.message || '保存失败')
    }
  } catch {
    showError('保存失败')
  } finally {
    saving.value = false
  }
}

async function addLog() {
  if (!film.value) return
  saving.value = true
  try {
    const res = await addWatchLog(film.value.content_id, {})
    if (res.code === 0) {
      applyFilm(res.data)
      emit('updated', res.data)
    } else {
      showError(res.message || '添加失败')
    }
  } catch {
    showError('添加失败')
  } finally {
    saving.value = false
  }
}

async function removeLog(log) {
  if (logDeleteId.value !== log.id) {
    logDeleteId.value = log.id
    setTimeout(() => { if (logDeleteId.value === log.id) logDeleteId.value = null }, 3000)
    return
  }
  logDeleteId.value = null
  saving.value = true
  try {
    const res = await deleteWatchLog(film.value.content_id, log.id)
    if (res.code === 0) {
      applyFilm(res.data)
      emit('updated', res.data)
    } else {
      showError(res.message || '删除失败')
    }
  } catch {
    showError('删除失败')
  } finally {
    saving.value = false
  }
}

// 日期：unknown → 按上映近似（release）；year → YYYY；month → YYYY-MM；day → YYYY-MM-DD（后端按格式判精度）
function setLogDateMode(log, mode) {
  log.mode = mode
  if (mode === 'unknown') saveLog(log, { watched_at: 'release' })   // 主动选「不记得」→ 按上映时间近似
  if (mode === 'day' && !log.day) log.day = new Date().toISOString().slice(0, 10)
  if (mode === 'day' && log.day) saveLog(log, { watched_at: log.day })
  if (mode === 'year' && log.year) saveLog(log, { watched_at: log.year })
  if (mode === 'month' && log.month) saveLog(log, { watched_at: log.month })
}
function saveLogDate(log) {
  if (log.mode === 'day' && log.day) saveLog(log, { watched_at: log.day })
  if (log.mode === 'year' && /^\d{4}$/.test(log.year)) saveLog(log, { watched_at: log.year })
  if (log.mode === 'month' && /^\d{4}-\d{2}$/.test(log.month)) saveLog(log, { watched_at: log.month })
}
function saveLogNote(log) {
  if ((log.note || '').trim() === (film.value?.record?.logs?.find(l => l.id === log.id)?.note || '')) return
  saveLog(log, { note: log.note })
}
const yearOptions = (() => { const y = new Date().getFullYear(); return Array.from({ length: 40 }, (_, i) => String(y - i)) })()

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

// 豆瓣：解析到条目 id 后直达条目页，否则退到搜索页。解析是手动触发、一次生效永久保存。
const doubanUrl = computed(() => film.value?.douban_url || `https://www.douban.com/search?cat=1002&q=${encodeURIComponent(film.value?.title || '')}`)
const doubanBusy = ref(false)
const doubanPaste = ref('')
const doubanPasteOpen = ref(false)

async function resolveDouban(payload = {}, openAfter = false) {
  if (!film.value || doubanBusy.value) return
  doubanBusy.value = true
  try {
    const res = await setDoubanLink(film.value.content_id, payload)
    if (res.code === 0) {
      film.value = res.data
      emit('updated', res.data)
      doubanPasteOpen.value = false
      doubanPaste.value = ''
      if (openAfter) window.open(res.data.douban_url, '_blank', 'noopener')
      else success('豆瓣直达已保存')
    } else {
      showError(res.message || '解析失败')
      doubanPasteOpen.value = true
      if (openAfter) window.open(doubanUrl.value, '_blank', 'noopener')   // 退回搜索页
    }
  } catch {
    showError('解析失败')
    doubanPasteOpen.value = true
  } finally {
    doubanBusy.value = false
  }
}

// 「豆瓣」一个动作：有直达直接开；没有就先解析再开，失败退回搜索页并出现粘贴框
function openDouban() {
  if (!film.value) return
  if (film.value.douban_id) window.open(film.value.douban_url, '_blank', 'noopener')
  else resolveDouban({}, true)
}

// ---- 编辑片名/年份 与 重新识别 ----
const editOpen = ref(false)
const editTitle = ref('')
const editYear = ref('')
const editKind = ref('movie')
const editBusy = ref(false)
const relinkOpen = ref(false)
const relinkQuery = ref('')
const relinkYear = ref('')
const relinkResults = ref([])
const relinkBusy = ref(false)

function startEdit() {
  editTitle.value = film.value?.title || ''
  editYear.value = film.value?.year || ''
  editKind.value = film.value?.kind || 'movie'
  editOpen.value = true
}

async function saveEdit() {
  if (!film.value || editBusy.value) return
  editBusy.value = true
  try {
    const res = await updateFilmMeta(film.value.content_id, {
      title: editTitle.value.trim() || undefined,
      year: editYear.value ? Number(editYear.value) : undefined,
      kind: editKind.value,
    })
    if (res.code === 0) {
      film.value = res.data
      emit('updated', res.data)
      editOpen.value = false
      success(res.message || '已保存')
    } else {
      showError(res.message || '保存失败')
    }
  } catch {
    showError('保存失败')
  } finally {
    editBusy.value = false
  }
}

function startRelink() {
  relinkQuery.value = film.value?.title || ''
  relinkYear.value = film.value?.year || ''
  relinkResults.value = []
  relinkOpen.value = true
  doRelinkSearch()
}

async function doRelinkSearch() {
  if (!relinkQuery.value.trim()) return
  relinkBusy.value = true
  try {
    const res = await searchTmdb(relinkQuery.value.trim(), relinkYear.value ? Number(relinkYear.value) : null)
    relinkResults.value = res.code === 0 ? res.data : []
    if (res.code !== 0) showError(res.message || '搜索失败')
  } catch {
    showError('搜索失败')
  } finally {
    relinkBusy.value = false
  }
}

async function pickRelink(item) {
  if (!film.value || relinkBusy.value) return
  relinkBusy.value = true
  try {
    const res = await relinkFilm(film.value.content_id, item.tmdb_id, item.kind)
    if (res.code === 0) {
      film.value = res.data
      emit('updated', res.data)
      relinkOpen.value = false
      success(res.message || '已重新识别')
    } else {
      showError(res.message || '识别失败')
    }
  } catch {
    showError('识别失败')
  } finally {
    relinkBusy.value = false
  }
}

async function unlinkDouban() {
  if (!film.value) return
  const res = await clearDoubanLink(film.value.content_id)
  if (res.code === 0) { film.value = res.data; emit('updated', res.data) }
}

const sourceLabel = computed(() => {
  const map = { emby: 'Emby', tmdb: 'TMDb', manual: '手工', douban: '豆瓣', emby_search: 'Emby 搜索（旧）' }
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
          <p v-else-if="film.metadata_state !== 'full' && !tmdbConfigured" class="mt-2 text-[11px] text-amber-600/90 leading-relaxed">
            导演、主演、类型和中文简介来自 TMDb：在
            <router-link to="/settings?tab=films" class="underline">系统设置 · 影视资料库</router-link> 填 TMDb API Key 后点「补全元数据」即可补齐。
          </p>
          <div v-if="film.genres?.length" class="mt-2 flex flex-wrap gap-1">
            <span v-for="g in film.genres" :key="g" class="px-1.5 py-0.5 text-[10px] font-medium bg-indigo-50 text-indigo-600 rounded">{{ g }}</span>
          </div>
          <p class="mt-2 text-[11px] text-slate-400">
            来源 {{ sourceLabel || '—' }}<template v-if="film.url"> · <a :href="film.url" target="_blank" rel="noopener" class="text-indigo-400 hover:underline">TMDb</a></template>
            · <button class="text-emerald-600 hover:underline disabled:opacity-50" :disabled="doubanBusy" :title="film.douban_id ? '打开豆瓣条目页' : '解析豆瓣条目并打开；失败则打开搜索页'" @click="openDouban">{{ doubanBusy ? '豆瓣解析中...' : '豆瓣' }}</button><button v-if="film.douban_id" class="ml-0.5 text-slate-300 hover:text-slate-500" title="清除豆瓣直达" @click="unlinkDouban">×</button>
            · <button class="text-slate-400 hover:text-slate-600 hover:underline" @click="startEdit">编辑</button>
            · <button class="text-slate-400 hover:text-slate-600 hover:underline" @click="startRelink">重新识别</button>
            · <button class="text-indigo-400 hover:underline disabled:opacity-50" :disabled="enriching" @click="handleEnrich">{{ enriching ? '补全中...' : '补全元数据' }}</button>
          </p>
          <!-- 编辑片名/年份/类型 -->
          <div v-if="editOpen" class="mt-2 flex flex-wrap items-center gap-1.5">
            <input v-model="editTitle" type="text" placeholder="片名" class="flex-1 min-w-[10rem] px-2 py-1 text-xs bg-white border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300" @keydown.enter.prevent="saveEdit" />
            <input v-model="editYear" type="number" placeholder="年份" class="w-20 px-2 py-1 text-xs bg-white border border-slate-200 rounded-lg outline-none tabular-nums" />
            <select v-model="editKind" class="px-2 py-1 text-xs bg-white border border-slate-200 rounded-lg outline-none"><option value="movie">电影</option><option value="series">剧集</option></select>
            <button class="px-2.5 py-1 text-xs text-white bg-indigo-500 rounded-lg hover:bg-indigo-600 disabled:opacity-50" :disabled="editBusy" @click="saveEdit">{{ editBusy ? '保存中...' : '保存' }}</button>
            <button class="text-xs text-slate-400 hover:text-slate-600" @click="editOpen = false">取消</button>
          </div>
          <!-- 重新识别：搜 TMDb 候选，点选即关联 -->
          <div v-if="relinkOpen" class="mt-2">
            <div class="flex gap-1.5">
              <input v-model="relinkQuery" type="text" placeholder="按片名搜 TMDb" class="flex-1 min-w-0 px-2 py-1 text-xs bg-white border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300" @keydown.enter.prevent="doRelinkSearch" />
              <input v-model="relinkYear" type="number" placeholder="年份" class="w-20 px-2 py-1 text-xs bg-white border border-slate-200 rounded-lg outline-none tabular-nums" @change="doRelinkSearch" />
              <button class="px-2.5 py-1 text-xs text-slate-700 bg-slate-100 rounded-lg hover:bg-slate-200" @click="doRelinkSearch">搜索</button>
              <button class="text-xs text-slate-400 hover:text-slate-600" @click="relinkOpen = false">取消</button>
            </div>
            <div v-if="relinkBusy" class="text-[11px] text-slate-400 mt-1.5">搜索中...</div>
            <ul v-else-if="relinkResults.length" class="mt-1.5 divide-y divide-slate-100 border border-slate-100 rounded-lg overflow-hidden max-h-56 overflow-y-auto">
              <li v-for="item in relinkResults" :key="item.kind + item.tmdb_id" class="flex gap-2 p-2 hover:bg-indigo-50/60 cursor-pointer" @click="pickRelink(item)">
                <div class="w-8 h-11 shrink-0 rounded bg-slate-100 overflow-hidden"><img v-if="item.poster_url" :src="item.poster_url" class="w-full h-full object-cover" /></div>
                <div class="min-w-0"><p class="text-xs font-medium text-slate-800 truncate">{{ item.title }} <span v-if="item.year" class="text-slate-400 font-normal tabular-nums">({{ item.year }})</span></p><p v-if="item.original_title && item.original_title !== item.title" class="text-[11px] text-slate-400 truncate">{{ item.original_title }}</p><p class="text-[10px] text-slate-400"><span class="px-1 rounded bg-slate-100">{{ item.kind === 'series' ? '剧集' : '电影' }}</span><span v-if="item.tmdb_id === film.tmdb_id" class="ml-1 text-emerald-600">当前</span></p></div>
              </li>
            </ul>
            <div v-else-if="relinkQuery && !relinkBusy" class="text-[11px] text-slate-400 mt-1.5">TMDb 没有结果，换个写法再搜（例如去掉标点、用原名）</div>
          </div>
          <div v-if="doubanPasteOpen && !film.douban_id" class="mt-1.5 flex gap-1.5">
            <input
              v-model="doubanPaste"
              type="text"
              placeholder="自动解析没成功：粘贴豆瓣条目链接，如 https://movie.douban.com/subject/1291839/"
              class="flex-1 min-w-0 px-2 py-1 text-xs bg-white border border-slate-200 rounded-lg focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-300 outline-none"
              @keydown.enter.prevent="doubanPaste.trim() && resolveDouban({ url: doubanPaste.trim() })"
            />
            <button class="px-2 py-1 text-xs text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50" :disabled="!doubanPaste.trim() || doubanBusy" @click="resolveDouban({ url: doubanPaste.trim() })">保存</button>
          </div>
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
            :class="form.status === opt.value ? opt.active : 'bg-white text-slate-600 border-slate-200 hover:border-slate-400'"
            @click="setStatus(opt.value)"
          >{{ opt.label }}</button>
        </div>

        <div v-if="form.status !== 'watched'" class="mt-4">
          <p class="text-[11px] text-slate-400 mb-1.5">我的评分 <span class="text-slate-300">· 打分即记为看过</span></p>
          <StarRating :model-value="form.my_rating" size="lg" show-value @update:model-value="setRating" />
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

        <!-- 观看记录：一次观看一条；不同阶段重看各记各的 -->
        <div v-if="form.status === 'watched' || logs.length" class="mt-4">
          <div class="flex items-center justify-between mb-1.5">
            <p class="text-[11px] text-slate-400">观看记录<span v-if="logs.length > 1" class="text-slate-300"> · {{ logs.length }} 次</span></p>
            <button class="text-[11px] text-indigo-500 hover:text-indigo-700 hover:underline disabled:opacity-50" :disabled="saving" @click="addLog">+ {{ logs.length ? '再记一次' : '记一次' }}</button>
          </div>
          <div class="space-y-2">
            <div v-for="(log, idx) in logs" :key="log.id" class="rounded-lg border border-slate-200 bg-white p-2.5">
              <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <span class="text-[11px] text-slate-400 tabular-nums">{{ idx === 0 ? '最近' : `第 ${logs.length - idx} 次` }} · {{ log.watched_label }}</span>
                <StarRating :model-value="log.my_rating" size="md" show-value @update:model-value="saveLog(log, { my_rating: $event })" />
                <button
                  class="ml-auto text-[11px] transition-colors"
                  :class="logDeleteId === log.id ? 'text-rose-600 font-medium' : 'text-slate-300 hover:text-rose-500'"
                  :title="logDeleteId === log.id ? '再点一次确认删除' : '删除这次观看'"
                  @click="removeLog(log)"
                >{{ logDeleteId === log.id ? '确认删除' : '删除' }}</button>
              </div>
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
                <div class="flex bg-slate-100 rounded-lg p-0.5">
                  <button v-for="m in [['unknown','不记得（按上映）'],['year','只记年'],['month','记到月'],['day','具体日期']]" :key="m[0]"
                    class="px-2 py-1 text-[11px] rounded-md transition-all"
                    :class="log.mode === m[0] ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
                    @click="setLogDateMode(log, m[0])">{{ m[1] }}</button>
                </div>
                <select v-if="log.mode === 'year'" v-model="log.year" class="px-2 py-1 text-sm bg-white border border-slate-200 rounded-lg outline-none" @change="saveLogDate(log)">
                  <option value="" disabled>选年份</option>
                  <option v-for="y in yearOptions" :key="y" :value="y">{{ y }}</option>
                </select>
                <input v-else-if="log.mode === 'month'" v-model="log.month" type="month" class="px-2 py-1 text-sm bg-white border border-slate-200 rounded-lg outline-none" @change="saveLogDate(log)" />
                <input v-else-if="log.mode === 'day'" v-model="log.day" type="date" class="px-2 py-1 text-sm bg-white border border-slate-200 rounded-lg outline-none" @change="saveLogDate(log)" />
              </div>
              <textarea
                v-model="log.note"
                rows="2"
                placeholder="这次看完的感想，长短都行，写给以后的自己"
                class="mt-2 w-full px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 focus:bg-white outline-none resize-y"
                @blur="saveLogNote(log)"
              />
            </div>
          </div>
        </div>
      </section>

      <!-- Emby 事实 -->
      <section class="p-5 sm:p-6 border-b border-slate-100">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-xs font-semibold uppercase tracking-wider text-slate-400">Emby 记录</h3>
          <a
            v-if="film.emby_url"
            :href="film.emby_url"
            target="_blank"
            rel="noopener"
            class="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg transition-all"
          ><svg class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>在 Emby 播放</a>
        </div>
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
