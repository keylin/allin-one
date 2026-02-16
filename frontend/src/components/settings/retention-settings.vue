<script setup>
import { ref } from 'vue'
import { clearExecutions, clearCollections, previewCleanup, manualCleanup, getSettings } from '@/api/settings'
import { useToast } from '@/composables/useToast'

const props = defineProps({
  form: { type: Object, required: true },
  fieldErrors: { type: Object, required: true },
  isDirty: { type: Boolean, required: true },
  groupSaving: { type: Boolean, required: false, default: false },
})

const emit = defineEmits(['update:form', 'save', 'validate-field', 'refresh-settings'])

const toast = useToast()

// Group definition
const group = {
  title: '内容保留',
  icon: 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z',
  color: 'text-amber-500 bg-amber-50',
  keys: [
    { key: 'cleanup_content_time', label: '内容清理时间', type: 'time', description: '每天执行内容清理的时间（本地时区）' },
    { key: 'cleanup_records_time', label: '记录清理时间', type: 'time', description: '每天执行记录清理的时间（本地时区）' },
    { key: 'default_retention_days', label: '默认保留天数', type: 'number', description: '数据源未单独设置时的全局默认值（0 表示永久保留）' },
    { key: 'collection_retention_days', label: '采集记录保留天数', type: 'number', description: '超过此天数的已完成采集记录将被自动清理（0 表示永久保留）' },
    { key: 'collection_min_keep', label: '每个数据源最少保留记录数', type: 'number', description: '即使超过保留天数，也至少保留最新的 N 条记录' },
    { key: 'execution_retention_days', label: '执行记录保留天数', type: 'number', description: '超过此天数的已完成执行记录将被自动清理（0 表示永久保留）' },
    { key: 'execution_max_count', label: '执行记录数量上限', type: 'number', description: '超过上限的旧记录将被自动清理（0 表示不限制）' },
  ],
}

function updateField(key, value) {
  emit('update:form', { ...props.form, [key]: value })
}

// ---- 手动清理 ----
const clearingExecutions = ref(false)
const clearingCollections = ref(false)
const previewingCleanup = ref(false)
const cleaningManually = ref(false)
const confirmDialog = ref({ visible: false, title: '', message: '', onConfirm: null })

function showConfirm(title, message, onConfirm) {
  confirmDialog.value = { visible: true, title, message, onConfirm }
}

function closeConfirm() {
  confirmDialog.value = { visible: false, title: '', message: '', onConfirm: null }
}

function handleClearExecutions() {
  showConfirm(
    '清理执行记录',
    '将删除所有已完成、失败、已取消的执行记录及其步骤数据。正在运行和等待中的记录不受影响。确定继续？',
    async () => {
      closeConfirm()
      clearingExecutions.value = true
      try {
        const res = await clearExecutions()
        if (res.code === 0) {
          toast.success(`已清理 ${res.data.deleted} 条执行记录`)
        } else {
          toast.error(res.message || '清理失败')
        }
      } catch (e) {
        toast.error('清理失败: ' + (e.message || '网络错误'))
      } finally {
        clearingExecutions.value = false
      }
    }
  )
}

function handleClearCollections() {
  showConfirm(
    '清理采集记录',
    '将删除所有已完成和失败的采集记录。正在运行的记录不受影响。确定继续？',
    async () => {
      closeConfirm()
      clearingCollections.value = true
      try {
        const res = await clearCollections()
        if (res.code === 0) {
          toast.success(`已清理 ${res.data.deleted} 条采集记录`)
        } else {
          toast.error(res.message || '清理失败')
        }
      } catch (e) {
        toast.error('清理失败: ' + (e.message || '网络错误'))
      } finally {
        clearingCollections.value = false
      }
    }
  )
}

async function handlePreviewCleanup() {
  previewingCleanup.value = true
  try {
    const res = await previewCleanup()
    if (res.code === 0) {
      const msg = `预计删除：\n• 内容项: ${res.data.content_items} 条\n• 采集记录: ${res.data.collection_records} 条\n• 执行记录: ${res.data.executions} 条`
      alert(msg)
    } else {
      toast.error(res.message || '预览失败')
    }
  } catch (e) {
    toast.error('预览失败: ' + (e.message || '网络错误'))
  } finally {
    previewingCleanup.value = false
  }
}

function handleManualCleanup() {
  showConfirm(
    '立即执行清理',
    '将根据当前配置的保留策略执行清理操作。此操作不可撤销，确定继续？',
    async () => {
      closeConfirm()
      cleaningManually.value = true
      try {
        const res = await manualCleanup()
        if (res.code === 0) {
          toast.success('清理完成')
          emit('refresh-settings')
        } else {
          toast.error(res.message || '清理失败')
        }
      } catch (e) {
        toast.error('清理失败: ' + (e.message || '网络错误'))
      } finally {
        cleaningManually.value = false
      }
    }
  )
}
</script>

<template>
  <div class="px-4 py-4 max-w-3xl">
    <!-- 分组标题 -->
    <div class="flex items-center gap-3 mb-5">
      <div class="w-8 h-8 rounded-lg flex items-center justify-center" :class="group.color">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" :d="group.icon" />
        </svg>
      </div>
      <h3 class="text-sm font-semibold text-slate-800">{{ group.title }}</h3>
    </div>

    <div class="space-y-5">
      <!-- 表单字段 -->
      <div v-for="item in group.keys" :key="item.key">
        <label class="block text-sm font-medium text-slate-700 mb-1.5">{{ item.label }}</label>
        <div class="relative">
          <input
            :value="form[item.key]"
            :type="item.type === 'time' ? 'time' : item.type === 'number' ? 'number' : 'text'"
            :placeholder="item.description"
            class="w-full px-3.5 py-2.5 bg-white border rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 outline-none transition-all duration-200"
            :class="fieldErrors[item.key]
              ? 'border-rose-300 focus:ring-rose-500/20 focus:border-rose-400'
              : 'border-slate-200 focus:ring-indigo-500/20 focus:border-indigo-400'"
            @input="updateField(item.key, $event.target.value)"
            @blur="$emit('validate-field', item.key, item.type)"
          />
        </div>
        <!-- 字段错误 -->
        <p v-if="fieldErrors[item.key]" class="mt-1.5 text-xs text-rose-500">{{ fieldErrors[item.key] }}</p>
        <p v-else class="mt-1.5 text-xs text-slate-400">{{ item.description }}</p>
      </div>
    </div>

    <!-- 分组保存按钮 -->
    <div class="mt-6 pt-4 border-t border-slate-100">
      <button
        class="px-5 py-2.5 text-sm font-medium text-white rounded-xl shadow-sm transition-all duration-200 disabled:opacity-50"
        :class="isDirty
          ? 'bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 shadow-indigo-200'
          : 'bg-slate-300 cursor-not-allowed'"
        :disabled="groupSaving || !isDirty"
        @click="$emit('save')"
      >
        <span class="flex items-center gap-1.5">
          <svg v-if="groupSaving" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          {{ groupSaving ? '保存中...' : '保存内容保留' }}
        </span>
      </button>
    </div>

    <!-- 手动清理区域 -->
    <div class="mt-6 pt-5 border-t border-slate-100">
      <h4 class="text-sm font-semibold text-slate-700 mb-3">数据清理状态</h4>

      <!-- 最后执行时间 -->
      <div class="mb-4 p-3 bg-slate-50 rounded-lg">
        <div class="text-xs text-slate-600 space-y-1">
          <p>• 内容最后清理: {{ form.cleanup_content_last_run || '从未执行' }}</p>
          <p>• 记录最后清理: {{ form.cleanup_records_last_run || '从未执行' }}</p>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="flex flex-wrap gap-3">
        <button
          class="px-4 py-2.5 text-sm font-medium text-blue-600 bg-white border border-blue-200 rounded-xl hover:bg-blue-50 hover:border-blue-300 active:bg-blue-100 disabled:opacity-50 transition-all duration-200"
          :disabled="previewingCleanup"
          @click="handlePreviewCleanup"
        >
          <span class="flex items-center gap-1.5">
            <svg v-if="previewingCleanup" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.64 0 8.577 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.64 0-8.577-3.007-9.963-7.178z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            {{ previewingCleanup ? '预览中...' : '预览清理影响' }}
          </span>
        </button>
        <button
          class="px-4 py-2.5 text-sm font-medium text-amber-600 bg-white border border-amber-200 rounded-xl hover:bg-amber-50 hover:border-amber-300 active:bg-amber-100 disabled:opacity-50 transition-all duration-200"
          :disabled="cleaningManually"
          @click="handleManualCleanup"
        >
          <span class="flex items-center gap-1.5">
            <svg v-if="cleaningManually" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
            </svg>
            {{ cleaningManually ? '清理中...' : '立即执行清理' }}
          </span>
        </button>
      </div>
      <p class="mt-3 text-xs text-slate-400">
        立即执行清理会根据上方配置的保留策略删除过期数据。清理前建议先点击「预览清理影响」查看将删除的记录数量。
      </p>

      <!-- 旧的分别清理按钮（保留但收起） -->
      <details class="mt-4">
        <summary class="text-xs text-slate-500 cursor-pointer hover:text-slate-700 transition-colors">
          高级选项：分别清理执行记录或采集记录
        </summary>
        <div class="mt-3 flex flex-wrap gap-3">
          <button
            class="px-4 py-2.5 text-sm font-medium text-rose-600 bg-white border border-rose-200 rounded-xl hover:bg-rose-50 hover:border-rose-300 active:bg-rose-100 disabled:opacity-50 transition-all duration-200"
            :disabled="clearingExecutions"
            @click="handleClearExecutions"
          >
            <span class="flex items-center gap-1.5">
              <svg v-if="clearingExecutions" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
              <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
              </svg>
              {{ clearingExecutions ? '清理中...' : '清理执行记录' }}
            </span>
          </button>
          <button
            class="px-4 py-2.5 text-sm font-medium text-rose-600 bg-white border border-rose-200 rounded-xl hover:bg-rose-50 hover:border-rose-300 active:bg-rose-100 disabled:opacity-50 transition-all duration-200"
            :disabled="clearingCollections"
            @click="handleClearCollections"
          >
            <span class="flex items-center gap-1.5">
              <svg v-if="clearingCollections" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
              <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
              </svg>
              {{ clearingCollections ? '清理中...' : '清理采集记录' }}
            </span>
          </button>
        </div>
      </details>
    </div>

    <!-- ========== 确认对话框 ========== -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition-all duration-200 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-all duration-150 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div v-if="confirmDialog.visible" class="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" @click="closeConfirm" />
          <div class="relative bg-white rounded-2xl shadow-xl max-w-sm w-full p-6">
            <div class="flex items-center gap-3 mb-3">
              <div class="w-10 h-10 rounded-full bg-rose-50 flex items-center justify-center shrink-0">
                <svg class="w-5 h-5 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
              </div>
              <h3 class="text-base font-semibold text-slate-800">{{ confirmDialog.title }}</h3>
            </div>
            <p class="text-sm text-slate-500 leading-relaxed mb-5 pl-[52px]">{{ confirmDialog.message }}</p>
            <div class="flex justify-end gap-2">
              <button
                class="px-4 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all duration-200"
                @click="closeConfirm"
              >
                取消
              </button>
              <button
                class="px-4 py-2 text-sm font-medium text-white bg-rose-500 rounded-xl hover:bg-rose-600 active:bg-rose-700 shadow-sm transition-all duration-200"
                @click="confirmDialog.onConfirm?.()"
              >
                确认清理
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
