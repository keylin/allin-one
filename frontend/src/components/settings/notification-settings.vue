<script setup>
import { ref } from 'vue'

const props = defineProps({
  form: { type: Object, required: true },
  fieldErrors: { type: Object, required: true },
  isDirty: { type: Boolean, required: true },
  groupSaving: { type: Boolean, required: false, default: false },
  groupId: { type: String, required: true }, // 'smtp' or 'notify'
})

const emit = defineEmits(['update:form', 'save', 'validate-field'])

// Password visibility
const visiblePasswords = ref({})

function togglePassword(key) {
  visiblePasswords.value[key] = !visiblePasswords.value[key]
}

// Group definitions
const groupDefs = {
  smtp: {
    title: '邮件推送 (SMTP)',
    icon: 'M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75',
    color: 'text-blue-500 bg-blue-50',
    keys: [
      { key: 'smtp_host', label: 'SMTP 服务器', type: 'text', description: '如 smtp.qq.com' },
      { key: 'smtp_port', label: 'SMTP 端口', type: 'text', description: 'SSL: 465, TLS: 587' },
      { key: 'smtp_user', label: 'SMTP 用户名', type: 'text', description: '登录邮箱账号' },
      { key: 'smtp_password', label: 'SMTP 密码', type: 'password', description: '邮箱授权码或密码' },
      { key: 'notify_email', label: '收件人邮箱', type: 'email', description: '多个用逗号分隔' },
    ],
  },
  notify: {
    title: '通知渠道',
    icon: 'M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0',
    color: 'text-rose-500 bg-rose-50',
    keys: [
      { key: 'notify_webhook', label: 'Webhook URL', type: 'url', description: '通知 Webhook 地址' },
      { key: 'notify_dingtalk_webhook', label: '钉钉机器人 Webhook', type: 'url', description: '钉钉群机器人 Webhook URL' },
    ],
  },
}

function getGroup() {
  return groupDefs[props.groupId] || groupDefs.smtp
}

function updateField(key, value) {
  emit('update:form', { ...props.form, [key]: value })
}
</script>

<template>
  <div class="px-4 py-4 max-w-3xl">
    <!-- 分组标题 -->
    <div class="flex items-center gap-3 mb-5">
      <div class="w-8 h-8 rounded-lg flex items-center justify-center" :class="getGroup().color">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" :d="getGroup().icon" />
        </svg>
      </div>
      <h3 class="text-sm font-semibold text-slate-800">{{ getGroup().title }}</h3>
    </div>

    <div class="space-y-5">
      <!-- 表单字段 -->
      <div v-for="item in getGroup().keys" :key="item.key">
        <label class="block text-sm font-medium text-slate-700 mb-1.5">{{ item.label }}</label>
        <div class="relative">
          <input
            :value="form[item.key]"
            :type="item.type === 'password' && !visiblePasswords[item.key] ? 'password' : item.type === 'number' ? 'number' : 'text'"
            :placeholder="item.description"
            class="w-full px-3.5 py-2.5 bg-white border rounded-xl text-sm text-slate-700 placeholder-slate-300 focus:ring-2 outline-none transition-all duration-200"
            :class="[
              fieldErrors[item.key]
                ? 'border-rose-300 focus:ring-rose-500/20 focus:border-rose-400'
                : 'border-slate-200 focus:ring-indigo-500/20 focus:border-indigo-400',
              item.type === 'password' ? 'pr-10' : ''
            ]"
            @input="updateField(item.key, $event.target.value)"
            @blur="$emit('validate-field', item.key, item.type)"
          />
          <!-- 密码显示/隐藏切换 -->
          <button
            v-if="item.type === 'password'"
            type="button"
            class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
            @click="togglePassword(item.key)"
          >
            <svg v-if="visiblePasswords[item.key]" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.64 0 8.577 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.64 0-8.577-3.007-9.963-7.178z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
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
          {{ groupSaving ? '保存中...' : `保存${getGroup().title}` }}
        </span>
      </button>
    </div>
  </div>
</template>
