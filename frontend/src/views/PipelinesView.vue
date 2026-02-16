<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ExecutionsTab from '@/components/pipeline/executions-tab.vue'
import TemplatesTab from '@/components/pipeline/templates-tab.vue'
import PromptsTab from '@/components/pipeline/prompts-tab.vue'

const route = useRoute()
const router = useRouter()

// ---- Tab ----
const activeTab = ref(route.query.tab || 'executions')

function switchTab(tab) {
  activeTab.value = tab
  const query = { ...route.query, tab }
  if (tab === 'executions') delete query.tab
  router.replace({ query }).catch(() => {})
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Tab 栏 -->
    <div class="border-b border-slate-100 bg-white px-4 pt-3 pb-0 shrink-0">
      <div class="flex items-center gap-1">
        <button
          class="px-4 py-2.5 text-sm font-medium border-b-2 transition-all duration-200"
          :class="activeTab === 'executions'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-slate-500 hover:text-slate-700'"
          @click="switchTab('executions')"
        >
          执行记录
        </button>
        <button
          class="px-4 py-2.5 text-sm font-medium border-b-2 transition-all duration-200"
          :class="activeTab === 'templates'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-slate-500 hover:text-slate-700'"
          @click="switchTab('templates')"
        >
          流水线模板
        </button>
        <button
          class="px-4 py-2.5 text-sm font-medium border-b-2 transition-all duration-200"
          :class="activeTab === 'prompts'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-slate-500 hover:text-slate-700'"
          @click="switchTab('prompts')"
        >
          提示词模板
        </button>
        <button
          class="px-4 py-2.5 text-sm font-medium border-b-2 transition-all duration-200"
          :class="activeTab === 'debug'
            ? 'border-indigo-600 text-indigo-600'
            : 'border-transparent text-slate-500 hover:text-slate-700'"
          @click="switchTab('debug')"
        >
          单步骤验证
        </button>
      </div>
    </div>

    <!-- Tab Content -->
    <ExecutionsTab v-if="activeTab === 'executions'" />
    <TemplatesTab v-else-if="activeTab === 'templates'" key="templates" section="templates" />
    <PromptsTab v-else-if="activeTab === 'prompts'" />
    <TemplatesTab v-else-if="activeTab === 'debug'" key="debug" section="debug" />
  </div>
</template>
