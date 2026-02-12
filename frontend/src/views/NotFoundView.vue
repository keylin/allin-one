<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-slate-50/30">
    <div class="text-center px-6">
      <p class="text-7xl font-bold text-slate-200 mb-2">404</p>
      <h1 class="text-xl font-bold text-slate-800 mb-2">页面不存在</h1>
      <p class="text-sm text-slate-500 mb-8">你访问的页面可能已被移除或地址有误</p>
      <div class="flex items-center justify-center gap-3">
        <button
          class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors"
          @click="router.push('/dashboard')"
        >
          返回首页
        </button>
        <button
          class="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
          @click="router.back()"
        >
          返回上页
        </button>
      </div>
    </div>
  </div>
</template>
