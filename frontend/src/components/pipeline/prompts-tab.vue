<script setup>
import { ref, onMounted } from 'vue'
import dayjs from 'dayjs'
import { listPromptTemplates, createPromptTemplate, updatePromptTemplate, deletePromptTemplate } from '@/api/prompt-templates'
import PromptTemplateFormModal from '@/components/prompt-template-form-modal.vue'
import ConfirmDialog from '@/components/confirm-dialog.vue'

const promptTemplates = ref([])
const prLoading = ref(false)
const showPromptForm = ref(false)
const editingPrompt = ref(null)
const showDeletePrDialog = ref(false)
const deletingPrId = ref(null)

const typeLabels = {
  news_analysis: '新闻分析',
  summary: '摘要',
  translation: '翻译',
  custom: '自定义',
}

const typeStyles = {
  news_analysis: 'bg-indigo-50 text-indigo-700',
  summary: 'bg-emerald-50 text-emerald-700',
  translation: 'bg-violet-50 text-violet-700',
  custom: 'bg-slate-100 text-slate-600',
}

async function fetchPromptTemplates() {
  prLoading.value = true
  try {
    const res = await listPromptTemplates()
    if (res.code === 0) promptTemplates.value = res.data
  } finally {
    prLoading.value = false
  }
}

function openCreatePrompt() {
  editingPrompt.value = null
  showPromptForm.value = true
}

function openEditPrompt(tpl) {
  editingPrompt.value = tpl
  showPromptForm.value = true
}

async function handlePromptSubmit(formData) {
  let res
  if (editingPrompt.value) {
    res = await updatePromptTemplate(editingPrompt.value.id, formData)
  } else {
    res = await createPromptTemplate(formData)
  }
  if (res.code === 0) {
    showPromptForm.value = false
    await fetchPromptTemplates()
  }
}

function openDeletePrompt(id) {
  deletingPrId.value = id
  showDeletePrDialog.value = true
}

async function handleDeletePrompt() {
  showDeletePrDialog.value = false
  const res = await deletePromptTemplate(deletingPrId.value)
  if (res.code === 0) await fetchPromptTemplates()
}

function formatTime(t) {
  return t ? dayjs.utc(t).local().format('YYYY-MM-DD HH:mm') : '-'
}

onMounted(() => {
  fetchPromptTemplates()
})
</script>

<template>
  <div class="flex-1 overflow-y-auto">
    <div class="px-4 py-4">
      <div class="flex items-center justify-end mb-4">
        <button
          class="px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 active:bg-indigo-800 shadow-sm shadow-indigo-200 transition-all duration-200"
          @click="openCreatePrompt"
        >
          <span class="flex items-center gap-1.5">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            新增
          </span>
        </button>
      </div>

      <!-- Loading -->
      <div v-if="prLoading" class="flex items-center justify-center py-16">
        <svg class="w-8 h-8 animate-spin text-slate-200" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      </div>

      <!-- Empty -->
      <div v-else-if="promptTemplates.length === 0" class="text-center py-16">
        <div class="w-12 h-12 bg-slate-100 rounded-xl flex items-center justify-center mx-auto mb-4">
          <svg class="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
          </svg>
        </div>
        <p class="text-sm text-slate-400">暂无模板</p>
      </div>

      <!-- Table -->
      <div v-else>
        <div class="hidden md:block bg-white rounded-xl border border-slate-200/60 shadow-sm overflow-hidden">
          <table class="w-full">
            <thead class="bg-slate-50/80">
              <tr>
                <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">名称</th>
                <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">类型</th>
                <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">输出格式</th>
                <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">默认</th>
                <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">更新时间</th>
                <th class="px-6 py-3.5 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100">
              <tr v-for="tpl in promptTemplates" :key="tpl.id" class="hover:bg-slate-50/50 transition-colors duration-150">
                <td class="px-6 py-3.5 text-sm font-medium text-slate-900">{{ tpl.name }}</td>
                <td class="px-6 py-3.5">
                  <span class="inline-flex px-2.5 py-1 text-xs font-medium rounded-lg" :class="typeStyles[tpl.template_type] || 'bg-slate-100 text-slate-600'">
                    {{ typeLabels[tpl.template_type] || tpl.template_type }}
                  </span>
                </td>
                <td class="px-6 py-3.5 text-sm text-slate-500">{{ tpl.output_format }}</td>
                <td class="px-6 py-3.5">
                  <span v-if="tpl.is_default" class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md bg-emerald-50 text-emerald-600">是</span>
                  <span v-else class="text-sm text-slate-300">-</span>
                </td>
                <td class="px-6 py-3.5 text-sm text-slate-400">{{ formatTime(tpl.updated_at) }}</td>
                <td class="px-6 py-3.5 text-right">
                  <div class="flex items-center justify-end gap-1.5">
                    <button class="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-all duration-200" @click="openEditPrompt(tpl)">编辑</button>
                    <button class="px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-all duration-200" @click="openDeletePrompt(tpl.id)">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Mobile Cards -->
        <div class="md:hidden space-y-3">
          <div v-for="tpl in promptTemplates" :key="tpl.id" class="bg-white rounded-xl border border-slate-200/60 shadow-sm p-4">
            <div class="flex items-start justify-between gap-2 mb-2">
              <div class="text-sm font-semibold text-slate-900">{{ tpl.name }}</div>
              <span v-if="tpl.is_default" class="inline-flex px-2 py-0.5 text-xs font-medium rounded-md bg-emerald-50 text-emerald-600 shrink-0">默认</span>
            </div>
            <div class="flex flex-wrap items-center gap-2 mb-3 text-xs">
              <span class="inline-flex px-2 py-0.5 font-medium rounded-lg" :class="typeStyles[tpl.template_type] || 'bg-slate-100 text-slate-600'">
                {{ typeLabels[tpl.template_type] || tpl.template_type }}
              </span>
              <span class="text-slate-400">{{ tpl.output_format }}</span>
              <span class="text-slate-400">{{ formatTime(tpl.updated_at) }}</span>
            </div>
            <div class="flex items-center gap-1.5 pt-3 border-t border-slate-100">
              <button class="flex-1 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-all duration-200" @click="openEditPrompt(tpl)">编辑</button>
              <button class="flex-1 px-3 py-2 text-xs font-medium text-rose-600 hover:bg-rose-50 rounded-lg transition-all duration-200" @click="openDeletePrompt(tpl.id)">删除</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Modals -->
    <PromptTemplateFormModal
      :visible="showPromptForm"
      :template="editingPrompt"
      @submit="handlePromptSubmit"
      @cancel="showPromptForm = false"
    />

    <ConfirmDialog
      :visible="showDeletePrDialog"
      title="删除提示词模板"
      message="确定要删除该模板吗？"
      confirm-text="删除"
      :danger="true"
      @confirm="handleDeletePrompt"
      @cancel="showDeletePrDialog = false"
    />
  </div>
</template>
