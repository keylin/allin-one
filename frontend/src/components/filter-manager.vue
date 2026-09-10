<script setup>
import { ref, computed, onMounted } from 'vue'
import { useContentFilterStore, makeFilter, emptyConditions } from '@/stores/contentFilter'
import { listSourceOptions } from '@/api/content'
import { useToast } from '@/composables/useToast'

// 过滤器配置端：只管定义的增删改，不参与内容消费。
// 消费端（信息流）只读 pinned 列表并应用，两端通过 store 与 system_settings 解耦。
const cf = useContentFilterStore()
const { success: toastSuccess, error: toastError } = useToast()

const editing = ref(null)      // 正在编辑的副本，null 表示未打开编辑器
const saving = ref(false)
const showSourcePicker = ref(false)
const sourceQuery = ref('')

const mediaOptions = [
  { value: '', label: '不限' },
  { value: 'video', label: '视频' },
  { value: 'audio', label: '音频' },
  { value: 'ebook', label: '电子书' },
]
const readOptions = [
  { value: null, label: '不限' },
  { value: true, label: '仅未读' },
  { value: false, label: '仅已读' },
]
const dateOptions = [
  { value: '', label: '全部时间' },
  { value: 'today', label: '今天' },
  { value: '3d', label: '近 3 天' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
]

const filteredSources = computed(() => {
  const q = sourceQuery.value.trim().toLowerCase()
  if (!q) return cf.sourceOptions
  return cf.sourceOptions.filter(s => (s.name || '').toLowerCase().includes(q))
})

function sourceNames(ids) {
  const map = new Map(cf.sourceOptions.map(s => [String(s.id), s.name]))
  return (ids || []).map(id => map.get(String(id))).filter(Boolean)
}

function summarize(f) {
  const c = f.conditions || {}
  const bits = []
  if (c.source_ids?.length) bits.push(`${c.source_ids.length} 个来源`)
  if (c.media_type) bits.push(mediaOptions.find(m => m.value === c.media_type)?.label)
  if (c.unread === true) bits.push('仅未读')
  if (c.unread === false) bits.push('仅已读')
  if (c.favorited === true) bits.push('仅收藏')
  if (c.date_range) bits.push(dateOptions.find(d => d.value === c.date_range)?.label)
  if (c.tag) bits.push(`#${c.tag}`)
  if (c.q) bits.push(`搜索「${c.q}」`)
  if (c.status) bits.push(`状态 ${c.status}`)
  return bits.length ? bits.join(' · ') : '无条件，等于全部内容'
}

function startCreate() {
  editing.value = makeFilter({ name: '', order: (cf.sorted[cf.sorted.length - 1]?.order ?? 0) + 1 })
  showSourcePicker.value = false
}
function startEdit(f) {
  editing.value = JSON.parse(JSON.stringify(f))
  if (!editing.value.conditions) editing.value.conditions = emptyConditions()
  showSourcePicker.value = false
}
function cancelEdit() { editing.value = null }

function toggleSource(id) {
  const cur = editing.value.conditions.source_ids || []
  const sid = String(id)
  editing.value.conditions.source_ids = cur.includes(sid)
    ? cur.filter(x => x !== sid)
    : [...cur, sid]
}

async function save() {
  const name = (editing.value.name || '').trim()
  if (!name) { toastError('请填写名称'); return }
  saving.value = true
  try {
    await cf.upsert({ ...editing.value, name })
    toastSuccess(`已保存「${name}」`)
    editing.value = null
  } catch (_) {
    toastError('保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(f) {
  if (!confirm(`删除过滤器「${f.name}」？其中 ${f.conditions?.source_ids?.length || 0} 个来源的选择会丢失，需要重新配置。`)) return
  try {
    await cf.remove(f.id)
    toastSuccess(`已删除「${f.name}」`)
  } catch (_) {
    toastError('删除失败')
  }
}

async function togglePinned(f) {
  try {
    await cf.upsert({ ...f, pinned: !f.pinned })
  } catch (_) {
    toastError('操作失败')
  }
}

async function move(f, delta) {
  const list = cf.sorted
  const i = list.findIndex(x => x.id === f.id)
  const j = i + delta
  if (i < 0 || j < 0 || j >= list.length) return
  const a = list[i], b = list[j]
  const ao = a.order ?? 0, bo = b.order ?? 0
  try {
    await cf.upsert({ ...a, order: bo })
    await cf.upsert({ ...b, order: ao })
  } catch (_) {
    toastError('排序失败')
  }
}

onMounted(async () => {
  if (!cf.sourceOptions.length) {
    try {
      const res = await listSourceOptions()
      if (res.code === 0) cf.sourceOptions = res.data
    } catch (_) { /* ignore */ }
  }
  await cf.load()
})
</script>

<template>
  <div class="p-4 md:p-6 max-w-3xl space-y-4">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold text-slate-800">内容过滤器</h3>
        <p class="text-xs text-slate-500 mt-1 leading-relaxed">
          过滤器是一组命名的筛选条件。在这里配置，在信息流顶部作为快捷方式使用。
          勾选「固定」的会出现在信息流顶部。
        </p>
      </div>
      <button
        class="px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors shrink-0"
        @click="startCreate"
      >新建</button>
    </div>

    <!-- 列表 -->
    <div v-if="!editing" class="space-y-2">
      <div
        v-for="(f, i) in cf.sorted"
        :key="f.id"
        class="border border-slate-200 rounded-xl p-3 hover:border-slate-300 transition-colors"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex items-center gap-1.5">
              <span class="text-sm font-medium text-slate-800 truncate">{{ f.name }}</span>
              <span v-if="f.pinned" class="px-1.5 py-0.5 text-[10px] rounded bg-indigo-50 text-indigo-600 border border-indigo-100">固定</span>
            </div>
            <div class="text-xs text-slate-500 mt-1 truncate" :title="sourceNames(f.conditions?.source_ids).join('、')">
              {{ summarize(f) }}
            </div>
          </div>
          <div class="flex items-center gap-1 shrink-0">
            <button class="px-1.5 py-1 text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30" :disabled="i === 0" title="上移" @click="move(f, -1)">↑</button>
            <button class="px-1.5 py-1 text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30" :disabled="i === cf.sorted.length - 1" title="下移" @click="move(f, 1)">↓</button>
            <button class="px-2 py-1 text-xs text-slate-500 hover:text-slate-700 rounded hover:bg-slate-100" @click="togglePinned(f)">
              {{ f.pinned ? '取消固定' : '固定' }}
            </button>
            <button class="px-2 py-1 text-xs text-indigo-600 hover:text-indigo-800 rounded hover:bg-indigo-50" @click="startEdit(f)">编辑</button>
            <button class="px-2 py-1 text-xs text-slate-400 hover:text-rose-600 rounded hover:bg-rose-50" @click="remove(f)">删除</button>
          </div>
        </div>
      </div>
      <div v-if="!cf.sorted.length" class="text-xs text-slate-400 text-center py-8">还没有过滤器，点右上角新建</div>
    </div>

    <!-- 编辑器 -->
    <div v-else class="border border-slate-200 rounded-xl p-4 space-y-4">
      <label class="block">
        <span class="text-xs font-medium text-slate-600">名称</span>
        <input v-model="editing.name" type="text" placeholder="例如：情报"
          class="mt-1 w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300" />
      </label>

      <label class="flex items-center gap-2 text-sm text-slate-700">
        <input v-model="editing.pinned" type="checkbox" class="w-4 h-4 rounded border-slate-300 text-indigo-600" />
        固定到信息流顶部
      </label>

      <div class="h-px bg-slate-100"></div>

      <!-- 来源 -->
      <div>
        <div class="flex items-center justify-between">
          <span class="text-xs font-medium text-slate-600">
            来源{{ editing.conditions.source_ids?.length ? `（已选 ${editing.conditions.source_ids.length}）` : '（不限）' }}
          </span>
          <div class="flex items-center gap-2">
            <button v-if="editing.conditions.source_ids?.length" class="text-xs text-slate-400 hover:text-slate-600" @click="editing.conditions.source_ids = []">清空</button>
            <button class="text-xs text-indigo-600 hover:text-indigo-800" @click="showSourcePicker = !showSourcePicker">
              {{ showSourcePicker ? '收起' : '选择来源' }}
            </button>
          </div>
        </div>
        <div v-if="editing.conditions.source_ids?.length && !showSourcePicker" class="mt-1.5 text-xs text-slate-500 leading-relaxed">
          {{ sourceNames(editing.conditions.source_ids).join('、') }}
        </div>
        <div v-if="showSourcePicker" class="mt-2 border border-slate-200 rounded-lg">
          <div class="p-2 border-b border-slate-100">
            <input v-model="sourceQuery" type="text" placeholder="搜索来源…"
              class="w-full px-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500/20" />
          </div>
          <div class="max-h-56 overflow-y-auto py-1">
            <label
              v-for="s in filteredSources"
              :key="s.id"
              class="flex items-center gap-2 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 cursor-pointer"
            >
              <input
                type="checkbox"
                :checked="(editing.conditions.source_ids || []).includes(String(s.id))"
                class="w-3.5 h-3.5 rounded border-slate-300 text-indigo-600"
                @change="toggleSource(s.id)"
              />
              <span class="truncate">{{ s.name }}</span>
            </label>
            <div v-if="!filteredSources.length" class="px-3 py-4 text-xs text-slate-400 text-center">没有匹配的来源</div>
          </div>
        </div>
      </div>

      <div class="h-px bg-slate-100"></div>

      <!-- 其余维度 -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label class="block">
          <span class="text-xs font-medium text-slate-600">媒体类型</span>
          <select v-model="editing.conditions.media_type" class="mt-1 w-full px-3 py-2 text-sm border border-slate-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20">
            <option v-for="m in mediaOptions" :key="m.value" :value="m.value">{{ m.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs font-medium text-slate-600">阅读状态</span>
          <select v-model="editing.conditions.unread" class="mt-1 w-full px-3 py-2 text-sm border border-slate-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20">
            <option v-for="r in readOptions" :key="String(r.value)" :value="r.value">{{ r.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs font-medium text-slate-600">时间范围</span>
          <select v-model="editing.conditions.date_range" class="mt-1 w-full px-3 py-2 text-sm border border-slate-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20">
            <option v-for="d in dateOptions" :key="d.value" :value="d.value">{{ d.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs font-medium text-slate-600">标签</span>
          <input v-model="editing.conditions.tag" type="text" placeholder="不限"
            class="mt-1 w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/20" />
        </label>
        <label class="block md:col-span-2">
          <span class="text-xs font-medium text-slate-600">标题关键词</span>
          <input v-model="editing.conditions.q" type="text" placeholder="不限"
            class="mt-1 w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/20" />
        </label>
        <label class="flex items-center gap-2 text-sm text-slate-700 md:col-span-2">
          <input
            type="checkbox"
            :checked="editing.conditions.favorited === true"
            class="w-4 h-4 rounded border-slate-300 text-indigo-600"
            @change="editing.conditions.favorited = $event.target.checked ? true : null"
          />
          仅收藏
        </label>
      </div>

      <div class="flex items-center justify-end gap-2 pt-1">
        <button class="px-3 py-1.5 text-xs text-slate-600 hover:text-slate-800 rounded-lg hover:bg-slate-100" @click="cancelEdit">取消</button>
        <button
          class="px-4 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg disabled:opacity-50 transition-colors"
          :disabled="saving"
          @click="save"
        >{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </div>
  </div>
</template>
