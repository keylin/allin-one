import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getSettings, updateSettings } from '@/api/settings'

/**
 * 内容过滤器 — 统一的数据消费状态管理。
 *
 * 三层分离：
 *   定义层  system_settings 的 content.filters（配置端读写）
 *   状态层  本 store：当前激活的过滤器 + 临时覆盖（消费端只读）
 *   消费端  信息流只展示 pinned 过滤器的快捷方式，不承担配置职责
 *
 * 过滤器 = 一组命名的筛选条件，覆盖全部维度；「来源分组」只是其中 source_ids 一维，
 * 不再是独立概念。媒体类型同理并入 conditions，顶部因此只剩一排快捷方式。
 */

const FILTERS_KEY = 'content.filters'
const LEGACY_GROUPS_KEY = 'feed.source_groups'
const ACTIVE_LS_KEY = 'content.active_filter'

export function emptyConditions() {
  return {
    source_ids: [],
    media_type: '',   // '' | video | audio | ebook
    status: '',
    unread: null,     // null 不限 / true 未读 / false 已读
    favorited: null,
    date_range: '',
    tag: '',
    q: '',
  }
}

export function makeFilter(patch = {}) {
  return {
    id: patch.id || `f_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    name: patch.name || '未命名',
    emoji: patch.emoji || '',
    pinned: patch.pinned !== false,
    order: patch.order ?? 0,
    builtin: !!patch.builtin,
    conditions: { ...emptyConditions(), ...(patch.conditions || {}) },
  }
}

// 首次使用时的种子：保持既有默认行为（未读优先），并把媒体类型收进来
function seedFilters() {
  return [
    makeFilter({ id: 'all', name: '全部', pinned: true, order: 0, builtin: true,
      conditions: { unread: true } }),
    makeFilter({ id: 'video', name: '有视频', pinned: false, order: 90, builtin: true,
      conditions: { media_type: 'video' } }),
    makeFilter({ id: 'audio', name: '有音频', pinned: false, order: 91, builtin: true,
      conditions: { media_type: 'audio' } }),
    makeFilter({ id: 'ebook', name: '电子书', pinned: false, order: 92, builtin: true,
      conditions: { media_type: 'ebook' } }),
  ]
}

export const useContentFilterStore = defineStore('contentFilter', () => {
  const filters = ref([])
  const activeId = ref('')
  const overrides = ref({})      // 消费端的临时调整，不写回定义
  const loaded = ref(false)
  const sourceOptions = ref([])  // 供配置端与消费端共用的源清单

  const sorted = computed(() =>
    [...filters.value].sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.name.localeCompare(b.name))
  )
  const pinned = computed(() => sorted.value.filter(f => f.pinned))
  const active = computed(() => filters.value.find(f => f.id === activeId.value) || null)

  // 定义 + 临时覆盖 = 实际生效的条件
  const effective = computed(() => ({
    ...emptyConditions(),
    ...(active.value?.conditions || {}),
    ...overrides.value,
  }))

  const dirty = computed(() => Object.keys(overrides.value).length > 0)

  /** 生效条件 → listContent 的请求参数 */
  const params = computed(() => {
    const c = effective.value
    const p = {}
    const known = new Set(sourceOptions.value.map(s => String(s.id)))
    const ids = (c.source_ids || []).map(String).filter(id => !known.size || known.has(id))
    if (ids.length) p.source_id = ids.join(',')
    if (c.media_type === 'video') p.has_video = true
    if (c.media_type === 'audio') p.has_audio = true
    if (c.media_type === 'ebook') p.has_ebook = true
    if (c.status) p.status = c.status
    if (c.unread === true) p.is_unread = true
    if (c.unread === false) p.is_unread = false
    if (c.favorited === true) p.is_favorited = true
    if (c.tag) p.tag = c.tag
    if (c.q && c.q.trim()) p.q = c.q.trim()
    return p
  })

  function setOverride(key, value) {
    const base = active.value?.conditions?.[key]
    const same = JSON.stringify(base ?? emptyConditions()[key]) === JSON.stringify(value)
    const next = { ...overrides.value }
    if (same) delete next[key]
    else next[key] = value
    overrides.value = next
  }

  function clearOverrides() { overrides.value = {} }

  function activate(id) {
    if (activeId.value === id) return
    activeId.value = id
    overrides.value = {}
    try { localStorage.setItem(ACTIVE_LS_KEY, id) } catch (_) { /* 隐私模式 */ }
  }

  async function persist() {
    const payload = JSON.stringify({ version: 1, filters: filters.value })
    await updateSettings({ [FILTERS_KEY]: payload })
  }

  function upsert(filter) {
    const idx = filters.value.findIndex(f => f.id === filter.id)
    if (idx >= 0) filters.value = filters.value.map((f, i) => (i === idx ? filter : f))
    else filters.value = [...filters.value, filter]
    return persist()
  }

  async function remove(id) {
    const backup = filters.value
    filters.value = filters.value.filter(f => f.id !== id)
    try {
      await persist()
    } catch (e) {
      filters.value = backup
      throw e
    }
    if (activeId.value === id) activate(filters.value[0]?.id || '')
  }

  /** 旧的 feed.source_groups 迁移为过滤器；旧 key 保留不删，便于回退 */
  function migrateLegacy(raw) {
    let groups = []
    try { groups = JSON.parse(raw) } catch (_) { return [] }
    if (!Array.isArray(groups)) return []
    return groups
      .filter(g => g && g.name && Array.isArray(g.source_ids))
      .map((g, i) => makeFilter({
        name: g.name, pinned: true, order: i + 1,
        conditions: { source_ids: g.source_ids.map(String), unread: true },
      }))
  }

  async function load(opts = {}) {
    if (loaded.value && !opts.force) return
    let data = {}
    try {
      const res = await getSettings()
      if (res.code === 0) data = res.data || {}
    } catch (_) { /* 读不到就用种子，不阻塞列表 */ }

    const raw = data[FILTERS_KEY]?.value
    let list = []
    if (raw) {
      try {
        const parsed = JSON.parse(raw)
        list = (Array.isArray(parsed) ? parsed : parsed.filters || []).map(makeFilter)
      } catch (_) { list = [] }
    }
    if (!list.length) {
      list = [...seedFilters(), ...migrateLegacy(data[LEGACY_GROUPS_KEY]?.value || '')]
      filters.value = list
      try { await persist() } catch (_) { /* 首次播种失败不阻塞 */ }
    } else {
      filters.value = list
    }

    let want = ''
    try { want = localStorage.getItem(ACTIVE_LS_KEY) || '' } catch (_) { /* ignore */ }
    activeId.value = filters.value.some(f => f.id === want) ? want : (filters.value[0]?.id || '')
    loaded.value = true
  }

  return {
    filters, activeId, overrides, loaded, sourceOptions,
    sorted, pinned, active, effective, dirty, params,
    setOverride, clearOverrides, activate, upsert, remove, persist, load,
  }
})
