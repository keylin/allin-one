<script setup>
import { ref } from 'vue'

const props = defineProps({
  form: { type: Object, required: true },
  fieldErrors: { type: Object, required: true },
  isDirty: { type: Boolean, required: true },
  groupSaving: { type: Boolean, required: false, default: false },
})

const emit = defineEmits(['update:form', 'save', 'validate-field'])

const showKey = ref(false)

function updateField(key, value) {
  emit('update:form', { ...props.form, [key]: value })
}
</script>

<template>
  <div class="max-w-2xl mx-auto px-4 sm:px-6 py-6 space-y-4">
    <div class="p-5 bg-white rounded-xl border border-slate-200/60 shadow-sm">
      <div class="flex items-center gap-2 mb-1">
        <div class="w-7 h-7 rounded-lg flex items-center justify-center bg-violet-50 text-violet-600">
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2" /><path d="M2 8h20M7 4v16M17 4v16" /></svg>
        </div>
        <h4 class="text-sm font-semibold text-slate-700">影视资料库</h4>
      </div>
      <p class="text-xs text-slate-400 mb-4">
        TMDb API Key 用于手工添加影片时补全元数据与海报，以及 agent 推荐落库时按 ID 定位。
        没有也能用：只能按片名 + 年份建骨架记录。Emby 凭证在「平台凭证」页配置。
      </p>

      <label class="block">
        <span class="text-xs font-medium text-slate-600">TMDb API Key (v3)</span>
        <div class="mt-1 relative">
          <input
            :value="form.tmdb_api_key || ''"
            :type="showKey ? 'text' : 'password'"
            placeholder="在 themoviedb.org → 设置 → API 申请"
            class="w-full px-3.5 py-2.5 pr-16 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 focus:ring-violet-500/20 focus:border-violet-400 outline-none transition-all duration-200"
            @input="updateField('tmdb_api_key', $event.target.value)"
          />
          <button
            type="button"
            class="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-slate-400 hover:text-slate-600 px-2 py-1"
            @click="showKey = !showKey"
          >{{ showKey ? '隐藏' : '显示' }}</button>
        </div>
        <p v-if="fieldErrors.tmdb_api_key" class="mt-1 text-xs text-rose-500">{{ fieldErrors.tmdb_api_key }}</p>
      </label>

      <div class="mt-4 flex items-center justify-end gap-2">
        <span v-if="isDirty" class="text-[11px] text-amber-500">有未保存的修改</span>
        <button
          class="px-4 py-2 text-sm font-medium text-white bg-violet-600 rounded-xl hover:bg-violet-700 active:bg-violet-800 disabled:opacity-50 transition-all duration-200"
          :disabled="!isDirty || groupSaving"
          @click="emit('save')"
        >{{ groupSaving ? '保存中...' : '保存' }}</button>
      </div>
    </div>
  </div>
</template>
