<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listFilms, getFilmStats, enrichMissing, updateWatchRecord, statusMeta, WATCH_STATUS_OPTIONS } from '@/api/films'
import { useToast } from '@/composables/useToast'
import FilmDetailDrawer from '@/components/film-detail-drawer.vue'
import FilmAddModal from '@/components/film-add-modal.vue'
import StarRating from '@/components/star-rating.vue'

const route = useRoute()
const router = useRouter()
const { success, error: showError, showToast } = useToast()

// ---- state ----
const loading = ref(false)
const loadingMore = ref(false)
const films = ref([])
const totalCount = ref(0)
const page = ref(1)
const pageSize = 60
const stats = ref(null)
const sentinelRef = ref(null)
let observer = null

const searchQuery = ref(route.query.q || '')
const filterStatus = ref(route.query.status || '')
const filterKind = ref(route.query.kind || '')
const filterGenre = ref(route.query.genre || '')
const filterEmby = ref(route.query.in_emby || '')
const filterDecade = ref(route.query.decade || '')
const sortBy = ref(route.query.sort || 'updated_at')

const selectedId = ref(null)
const drawerVisible = ref(false)
const addVisible = ref(false)
const showFilters = ref(false)

// 卡片快捷操作
const sheetFilm = ref(null)          // 移动端操作面板
const busyId = ref(null)
let searchTimer = null
let longPressTimer = null

const QUICK_STATUSES = WATCH_STATUS_OPTIONS.filter(o => ['want', 'watched', 'dropped'].includes(o.value))

const decades = computed(() => {
  const years = stats.value?.years || []
  const set = new Set(years.map(y => Math.floor(y / 10) * 10))
  return [...set].sort((a, b) => b - a)
})

const activeFilterCount = computed(() =>
  [filterStatus.value, filterKind.value, filterGenre.value, filterEmby.value, filterDecade.value].filter(Boolean).length,
)

function buildParams() {
  const params = { page: page.value, page_size: pageSize, sort: sortBy.value, order: sortBy.value === 'title' ? 'asc' : 'desc' }
  if (searchQuery.value.trim()) params.q = searchQuery.value.trim()
  if (filterStatus.value) params.status = filterStatus.value
  if (filterKind.value) params.kind = filterKind.value
  if (filterGenre.value) params.genre = filterGenre.value
  if (filterEmby.value) params.in_emby = filterEmby.value === 'yes'
  if (filterDecade.value) {
    params.year_from = Number(filterDecade.value)
    params.year_to = Number(filterDecade.value) + 9
  }
  return params
}

async function fetchFilms(append = false) {
  if (append) loadingMore.value = true
  else loading.value = true
  try {
    const res = await listFilms(buildParams())
    if (res.code === 0) {
      films.value = append ? [...films.value, ...res.data] : res.data
      totalCount.value = res.total
    }
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

async function fetchStats() {
  try {
    const res = await getFilmStats()
    if (res.code === 0) stats.value = res.data
  } catch { /* ignore */ }
}

function reload() {
  page.value = 1
  fetchFilms(false)
  fetchStats()
}

const hasMore = computed(() => films.value.length < totalCount.value)

function loadMore() {
  if (!hasMore.value || loading.value || loadingMore.value) return
  page.value += 1
  fetchFilms(true)
}

// 无限滚动：sentinel 进入视口 300px 内即加载下一页（移动端不用点按钮）
watch(sentinelRef, (el) => {
  if (observer) { observer.disconnect(); observer = null }
  if (el && 'IntersectionObserver' in window) {
    observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) loadMore()
    }, { rootMargin: '300px' })
    observer.observe(el)
  }
})

function syncQuery() {
  const query = {}
  if (searchQuery.value.trim()) query.q = searchQuery.value.trim()
  if (filterStatus.value) query.status = filterStatus.value
  if (filterKind.value) query.kind = filterKind.value
  if (filterGenre.value) query.genre = filterGenre.value
  if (filterEmby.value) query.in_emby = filterEmby.value
  if (filterDecade.value) query.decade = filterDecade.value
  if (sortBy.value !== 'updated_at') query.sort = sortBy.value
  router.replace({ query }).catch(() => {})
}

watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { syncQuery(); reload() }, 300)
})
watch([filterStatus, filterKind, filterGenre, filterEmby, filterDecade, sortBy], () => { syncQuery(); reload() })

function clearFilters() {
  filterStatus.value = ''
  filterKind.value = ''
  filterGenre.value = ''
  filterEmby.value = ''
  filterDecade.value = ''
}

// ---- 详情 ----
function openFilm(film) {
  if (sheetFilm.value) return
  selectedId.value = film.content_id
  drawerVisible.value = true
}

function closeDrawer() {
  drawerVisible.value = false
}

function patchFilm(updated) {
  const idx = films.value.findIndex(f => f.content_id === updated.content_id)
  if (idx >= 0) films.value[idx] = { ...films.value[idx], ...updated }
}

function onFilmUpdated(updated) {
  patchFilm(updated)
  fetchStats()
}

function onFilmDeleted(contentId) {
  films.value = films.value.filter(f => f.content_id !== contentId)
  totalCount.value = Math.max(0, totalCount.value - 1)
  drawerVisible.value = false
  fetchStats()
}

function onFilmAdded(film) {
  addVisible.value = false
  reload()
  selectedId.value = film.content_id
  drawerVisible.value = true
}

// ---- 卡片快捷操作 ----
async function quickRecord(film, partial) {
  busyId.value = film.content_id
  try {
    const res = await updateWatchRecord(film.content_id, partial)
    if (res.code === 0) {
      patchFilm(res.data)
      if (sheetFilm.value?.content_id === res.data.content_id) sheetFilm.value = { ...sheetFilm.value, ...res.data }
      fetchStats()
    } else {
      showError(res.message || '保存失败')
    }
  } catch {
    showError('保存失败')
  } finally {
    busyId.value = null
  }
}

function quickStatus(film, value) {
  const next = film.record?.status === value ? 'unmarked' : value
  quickRecord(film, { status: next })   // 看过且无日期时后端默认上映日期
}

function quickRating(film, value) {
  // StarRating 给的是 1~10 或 null（再点同一值即清除）
  quickRecord(film, { my_rating: value })
}

// 移动端长按 → 操作面板
function onPointerDown(film, event) {
  if (event.pointerType !== 'touch') return
  longPressTimer = setTimeout(() => {
    sheetFilm.value = film
    longPressTimer = null
  }, 450)
}
function cancelLongPress() {
  if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer = null }
}
function closeSheet() {
  sheetFilm.value = null
}

// ---- 补全元数据 ----
const enriching = ref(false)
const enrichProgress = ref('')

const enrichHint = computed(() => {
  const n = stats.value?.unenriched ?? 0
  const p = stats.value?.partial ?? 0
  const f = stats.value?.enrich_failed ?? 0
  if (!stats.value?.tmdb_configured && n > 0) return `未配置 TMDb API Key，无法补全${p ? `（${p} 部只有海报和 ID）` : ''}；去系统设置 · 影视资料库填写`
  if (n > 0) return `${n} 部可补全，点击开始`
  if (f > 0) return `没有可批量补全的记录；${f} 部 TMDb 搜不到，可在详情里单条重试`
  return '所有记录都有完整元数据'
})

async function runEnrich() {
  if (enriching.value) return
  if ((stats.value?.unenriched ?? 0) === 0) {
    showToast(enrichHint.value, { type: 'info', duration: 6000 })
    return
  }
  enriching.value = true
  let totalOk = 0
  let totalFailed = 0
  try {
    for (let i = 0; i < 20; i++) {
      const res = await enrichMissing(30)
      if (res.code !== 0) { showError(res.message || '补全失败'); break }
      totalOk += res.data.ok
      totalFailed += res.data.processed - res.data.ok
      enrichProgress.value = `已补全 ${totalOk}，剩余 ${res.data.remaining}`
      if (res.data.remaining === 0 || res.data.processed === 0) break
    }
    if (totalFailed) showToast(`补全完成：${totalOk} 部成功，${totalFailed} 部搜不到（详情里可单条重试）`, { type: 'warning', duration: 6000 })
    else success(`补全完成：${totalOk} 部`)
    reload()
  } catch {
    showError('补全失败')
  } finally {
    enriching.value = false
    enrichProgress.value = ''
  }
}

function statusCount(value) {
  return stats.value?.by_status?.[value] ?? 0
}

onMounted(() => {
  fetchFilms()
  fetchStats()
})
onUnmounted(() => {
  if (observer) observer.disconnect()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Header -->
    <div class="px-4 pt-3 pb-2.5 space-y-2 sticky top-0 bg-white/95 backdrop-blur-sm z-10 border-b border-slate-100 shrink-0">
      <div class="flex items-center gap-2">
        <span class="text-xs text-slate-400 tabular-nums shrink-0">{{ totalCount }} 部</span>
        <span
          v-if="stats"
          class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded-full shrink-0"
          :class="stats.emby_configured ? 'text-emerald-600 bg-emerald-50' : 'text-slate-400 bg-slate-100'"
          :title="stats.emby_configured ? `${stats.in_emby} 部在 Emby 库内` : 'Emby 未配置，去同步管理绑定凭证'"
        >
          <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" /><path d="M16 16h5v5" /></svg>
          <span class="hidden sm:inline">{{ stats.emby_configured ? `Emby ${stats.in_emby}` : 'Emby 未配置' }}</span>
        </span>

        <div class="flex-1" />

        <select
          v-model="sortBy"
          class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2 py-1.5 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 outline-none cursor-pointer transition-all"
        >
          <option value="updated_at">最近更新</option>
          <option value="year">年份</option>
          <option value="my_rating">我的评分</option>
          <option value="community_rating">公共评分</option>
          <option value="last_played">最近播放</option>
          <option value="title">标题</option>
        </select>

        <router-link
          to="/sync"
          class="hidden sm:inline-flex items-center px-2.5 py-1.5 text-xs text-slate-500 hover:text-slate-700 bg-slate-50 hover:bg-slate-100 rounded-lg transition-all"
          title="去同步管理触发 Emby 同步"
        >同步</router-link>
        <button
          class="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg transition-all disabled:cursor-not-allowed"
          :class="(stats?.unenriched ?? 0) > 0 ? 'text-indigo-600 bg-indigo-50 hover:bg-indigo-100' : 'text-slate-400 bg-slate-50'"
          :disabled="enriching"
          :title="enrichHint"
          @click="runEnrich"
        >
          <svg v-if="enriching" class="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
          <template v-if="enriching">{{ enrichProgress || '补全中...' }}</template>
          <template v-else><span class="hidden sm:inline">补全元数据</span><span class="sm:hidden">补全</span><span v-if="(stats?.unenriched ?? 0) > 0" class="ml-0.5 tabular-nums">({{ stats.unenriched }})</span></template>
        </button>
        <button
          class="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white bg-indigo-500 hover:bg-indigo-600 rounded-lg transition-all"
          @click="addVisible = true"
        >
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14" /></svg>
          添加
        </button>
      </div>

      <!-- search + status chips -->
      <div class="flex items-center gap-2">
        <div class="relative flex-1 sm:flex-none sm:w-56">
          <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" /></svg>
          <input
            v-model="searchQuery"
            placeholder="搜索片名 / 原名 / 导演..."
            class="w-full bg-slate-50 rounded-lg pl-8 pr-3 py-1.5 text-sm text-slate-700 placeholder-slate-400 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300 focus:bg-white transition-all"
          />
        </div>
        <div class="hidden sm:flex items-center gap-1">
          <button
            class="px-2 py-1 text-[11px] rounded-md transition-all"
            :class="!filterStatus ? 'bg-slate-800 text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="filterStatus = ''"
          >全部</button>
          <button
            v-for="opt in WATCH_STATUS_OPTIONS"
            :key="opt.value"
            class="px-2 py-1 text-[11px] rounded-md transition-all whitespace-nowrap"
            :class="filterStatus === opt.value ? opt.color : 'text-slate-500 hover:bg-slate-100'"
            @click="filterStatus = filterStatus === opt.value ? '' : opt.value"
          >{{ opt.label }} <span class="opacity-60 tabular-nums">{{ statusCount(opt.value) }}</span></button>
        </div>
        <button
          class="sm:hidden shrink-0 px-2.5 py-1.5 text-xs rounded-lg border transition-all"
          :class="activeFilterCount ? 'border-indigo-300 text-indigo-600 bg-indigo-50' : 'border-slate-200 text-slate-500'"
          @click="showFilters = !showFilters"
        >筛选<span v-if="activeFilterCount"> {{ activeFilterCount }}</span></button>
      </div>

      <!-- filters -->
      <div class="flex items-center gap-2 flex-wrap" :class="showFilters ? '' : 'hidden sm:flex'">
        <select v-model="filterStatus" class="sm:hidden text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2 py-1.5 outline-none">
          <option value="">全部状态</option>
          <option v-for="opt in WATCH_STATUS_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }} ({{ statusCount(opt.value) }})</option>
        </select>
        <select v-model="filterKind" class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2 py-1.5 outline-none cursor-pointer">
          <option value="">全部</option>
          <option value="movie">电影</option>
          <option value="series">剧集</option>
        </select>
        <select v-model="filterGenre" class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2 py-1.5 outline-none cursor-pointer max-w-[140px]">
          <option value="">全部类型</option>
          <option v-for="g in (stats?.genres || [])" :key="g" :value="g">{{ g }}</option>
        </select>
        <select v-model="filterDecade" class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2 py-1.5 outline-none cursor-pointer">
          <option value="">全部年代</option>
          <option v-for="d in decades" :key="d" :value="String(d)">{{ d }}s</option>
        </select>
        <select v-model="filterEmby" class="text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2 py-1.5 outline-none cursor-pointer">
          <option value="">Emby 不限</option>
          <option value="yes">在 Emby 库内</option>
          <option value="no">不在 Emby</option>
        </select>
        <button v-if="activeFilterCount" class="text-[11px] text-slate-400 hover:text-slate-600 transition-colors" @click="clearFilters">清除筛选</button>
      </div>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto">
      <div class="px-4 py-4">
        <div v-if="loading && films.length === 0" class="flex items-center justify-center py-24">
          <svg class="w-8 h-8 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
        </div>

        <div v-else-if="films.length === 0" class="text-center py-24">
          <div class="w-16 h-16 mx-auto mb-4 bg-slate-100 rounded-2xl flex items-center justify-center">
            <svg class="w-8 h-8 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="4" width="20" height="16" rx="2" /><path d="M2 8h20M7 4v16M17 4v16" /></svg>
          </div>
          <p class="text-sm text-slate-500 font-medium mb-1">{{ totalCount === 0 && !activeFilterCount && !searchQuery ? '影视库还是空的' : '没有匹配的影片' }}</p>
          <p class="text-xs text-slate-400">
            <template v-if="totalCount === 0 && !activeFilterCount && !searchQuery">去 <router-link to="/sync" class="text-indigo-500 hover:underline">同步管理</router-link> 拉取 Emby，或点右上角「添加」</template>
            <template v-else>换个筛选条件试试</template>
          </p>
        </div>

        <template v-else>
          <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-7 gap-3 sm:gap-4">
            <div
              v-for="film in films"
              :key="film.content_id"
              class="group relative bg-white rounded-xl border border-slate-200/60 overflow-visible transition-all duration-200 hover:border-indigo-300 hover:shadow-md select-none"
              :class="busyId === film.content_id ? 'opacity-70' : ''"
            >
              <!-- poster → 详情 -->
              <div
                class="aspect-[2/3] bg-gradient-to-br from-slate-100 to-slate-200 relative overflow-hidden rounded-t-xl cursor-pointer"
                @click="openFilm(film)"
                @pointerdown="onPointerDown(film, $event)"
                @pointerup="cancelLongPress"
                @pointercancel="cancelLongPress"
                @pointermove="cancelLongPress"
                @contextmenu.prevent="sheetFilm = film"
              >
                <img v-if="film.poster_url" :src="film.poster_url" :alt="film.title" class="absolute inset-0 w-full h-full object-cover" loading="lazy" />
                <div v-else class="absolute inset-0 flex flex-col items-center justify-center p-3">
                  <span class="text-xs text-slate-400 text-center line-clamp-4 leading-tight">{{ film.title }}</span>
                </div>
                <span
                  v-if="film.record?.status && film.record.status !== 'unmarked'"
                  class="absolute top-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded shadow-sm"
                  :class="statusMeta(film.record.status).color"
                >{{ statusMeta(film.record.status).label }}</span>
                <span v-if="film.in_emby" class="absolute top-1.5 right-1.5 px-1.5 py-0.5 text-[10px] font-medium bg-black/60 text-white rounded" title="在 Emby 库内">E</span>
                <span v-if="film.record?.my_rating" class="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 text-[10px] font-semibold bg-amber-400/90 text-white rounded tabular-nums">★ {{ (film.record.my_rating / 2).toFixed(1).replace('.0', '') }}</span>
                <div v-if="film.emby && film.emby.progress > 0 && film.emby.progress < 1 && !film.emby.played" class="absolute bottom-0 left-0 right-0 h-0.5 bg-black/20">
                  <div class="h-full bg-indigo-400" :style="{ width: Math.round(film.emby.progress * 100) + '%' }" />
                </div>
              </div>

              <!-- info -->
              <div class="p-2 pb-1.5">
                <h4 class="text-xs font-medium text-slate-800 line-clamp-2 leading-snug min-h-[2rem] cursor-pointer" @click="openFilm(film)">{{ film.title }}</h4>
                <div class="mt-0.5 flex items-center gap-1 text-[10px] text-slate-400">
                  <span v-if="film.year" class="tabular-nums">{{ film.year }}</span>
                  <span v-if="film.kind === 'series'" class="px-1 rounded bg-slate-100 text-slate-500">剧</span>
                  <span v-if="film.community_rating" class="ml-auto tabular-nums" title="公共评分">{{ Number(film.community_rating).toFixed(1) }}</span>
                </div>
              </div>

              <!-- quick actions (desktop 常显；移动端长按走面板) -->
              <div class="hidden sm:block px-2 pb-2">
                <div class="flex items-center justify-center py-1">
                  <StarRating :model-value="film.record?.my_rating" size="md" @update:model-value="quickRating(film, $event)" />
                </div>
                <div class="flex items-center justify-center gap-1">
                  <button
                    v-for="opt in QUICK_STATUSES"
                    :key="opt.value"
                    class="px-1.5 py-0.5 text-[10px] rounded transition-all"
                    :class="film.record?.status === opt.value ? opt.color : 'text-slate-400 hover:bg-slate-100 hover:text-slate-600'"
                    :title="film.record?.status === opt.value ? `取消「${opt.label}」` : `标为「${opt.label}」`"
                    @click.stop="quickStatus(film, opt.value)"
                  >{{ opt.label }}</button>
                </div>
              </div>
            </div>
          </div>

          <!-- infinite scroll sentinel + fallback -->
          <div ref="sentinelRef" class="h-1" />
          <div v-if="hasMore" class="flex justify-center py-6">
            <button
              class="px-4 py-1.5 text-xs text-slate-500 bg-slate-50 hover:bg-slate-100 rounded-lg transition-all disabled:opacity-50"
              :disabled="loadingMore"
              @click="loadMore"
            >{{ loadingMore ? '加载中...' : `加载更多（${films.length}/${totalCount}）` }}</button>
          </div>
          <p v-else-if="films.length > pageSize" class="text-center text-[11px] text-slate-300 py-6">已经到底了</p>
        </template>
      </div>
    </div>

    <!-- 移动端操作面板（长按卡片） -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition-opacity duration-150"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-opacity duration-100"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div v-if="sheetFilm" class="fixed inset-0 z-50 flex items-end sm:items-center justify-center" @click.self="closeSheet">
          <div class="absolute inset-0 bg-black/30" @click="closeSheet" />
          <div class="relative z-10 bg-white rounded-t-2xl sm:rounded-2xl w-full sm:w-96 shadow-2xl overflow-hidden pb-safe">
            <div class="px-4 py-3 border-b border-slate-100 flex items-center gap-3">
              <div class="w-10 h-14 rounded bg-slate-100 overflow-hidden shrink-0">
                <img v-if="sheetFilm.poster_url" :src="sheetFilm.poster_url" class="w-full h-full object-cover" />
              </div>
              <div class="min-w-0">
                <p class="text-sm font-medium text-slate-800 truncate">{{ sheetFilm.title }}</p>
                <p class="text-xs text-slate-400">{{ sheetFilm.year }}<span v-if="sheetFilm.directors?.length"> · {{ sheetFilm.directors[0] }}</span></p>
              </div>
            </div>
            <div class="px-4 py-3 space-y-3">
              <div>
                <p class="text-[11px] text-slate-400 mb-1.5">状态</p>
                <div class="flex gap-1.5">
                  <button
                    v-for="opt in WATCH_STATUS_OPTIONS.filter(o => o.value !== 'unmarked')"
                    :key="opt.value"
                    class="flex-1 py-2 text-xs rounded-lg border transition-all"
                    :class="sheetFilm.record?.status === opt.value ? opt.active : 'bg-white text-slate-600 border-slate-200 active:bg-slate-100'"
                    @click="quickStatus(sheetFilm, opt.value)"
                  >{{ opt.label }}</button>
                </div>
              </div>
              <div>
                <p class="text-[11px] text-slate-400 mb-1.5">评分 <span class="text-slate-300">· 点星的左半边是半星</span></p>
                <StarRating :model-value="sheetFilm.record?.my_rating" size="lg" show-value @update:model-value="quickRating(sheetFilm, $event)" />
              </div>
            </div>
            <div class="border-t border-slate-100">
              <button class="w-full text-left px-4 py-3 text-sm text-slate-700 active:bg-slate-100" @click="openFilm({ content_id: sheetFilm.content_id }); sheetFilm = null">查看详情</button>
              <button class="w-full py-3 text-sm text-slate-500 font-medium border-t border-slate-100 active:bg-slate-100" @click="closeSheet">取消</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <FilmDetailDrawer
      :visible="drawerVisible"
      :content-id="selectedId"
      @close="closeDrawer"
      @updated="onFilmUpdated"
      @deleted="onFilmDeleted"
    />

    <FilmAddModal
      :visible="addVisible"
      :tmdb-configured="!!stats?.tmdb_configured"
      @close="addVisible = false"
      @added="onFilmAdded"
    />
  </div>
</template>
