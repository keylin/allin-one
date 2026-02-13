import { ref, computed } from 'vue'
import { getSettings } from '@/api/settings'

const MODEL_PRESETS = [
  'deepseek-chat',
  'qwen-plus',
  'gpt-4o-mini',
  'Qwen/Qwen2.5-7B-Instruct',
]

const currentLLMModel = ref('')
let fetched = false

async function fetchCurrentModel() {
  if (fetched) return
  try {
    const res = await getSettings()
    if (res.code === 0 && res.data?.llm_model?.value) {
      currentLLMModel.value = res.data.llm_model.value
    }
  } catch { /* ignore */ }
  fetched = true
}

const modelOptions = computed(() => {
  const opts = new Set(MODEL_PRESETS)
  if (currentLLMModel.value) opts.add(currentLLMModel.value)
  return [...opts]
})

export function useModelOptions() {
  fetchCurrentModel()
  return { modelOptions, currentLLMModel }
}
