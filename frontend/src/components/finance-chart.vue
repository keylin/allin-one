<script setup>
import { computed, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, CandlestickChart, BarChart } from 'echarts/charts'
import {
  TitleComponent, TooltipComponent, GridComponent,
  DataZoomComponent, LegendComponent, MarkLineComponent,
} from 'echarts/components'

use([
  CanvasRenderer, LineChart, CandlestickChart, BarChart,
  TitleComponent, TooltipComponent, GridComponent,
  DataZoomComponent, LegendComponent, MarkLineComponent,
])

const props = defineProps({
  series: { type: Array, default: () => [] },
  category: { type: String, default: 'macro' },
  sourceName: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  compareMode: { type: String, default: 'raw' }, // raw | yoy | mom
  zoomStart: { type: Number, default: 0 },       // dataZoom start %
})

const emit = defineEmits(['dateClick'])
const chartRef = ref(null)

function onChartClick(params) {
  const date = params.name || (params.data && params.data.date)
  if (date) emit('dateClick', date)
}

// ---- helpers ----

function getVal(p) {
  return p.close ?? p.unit_nav ?? p.value ?? null
}

/** 同比: 找同月去年数据点 */
function computeYoY(series) {
  const map = new Map()
  series.forEach(p => map.set(p.date, p))

  return series.map(p => {
    const cur = getVal(p)
    // "2025-03" → "2024-03", "2025-03-15" → "2024-03-15"
    const prevDate = p.date.replace(/^\d{4}/, y => String(Number(y) - 1))
    const prev = map.get(prevDate)
    const prevVal = prev ? getVal(prev) : null
    let pct = null
    if (cur != null && prevVal != null && prevVal !== 0) {
      pct = ((cur - prevVal) / Math.abs(prevVal)) * 100
    }
    return { date: p.date, pct }
  })
}

/** 环比: 与上一期比较 */
function computeMoM(series) {
  return series.map((p, i) => {
    const cur = getVal(p)
    const prevVal = i > 0 ? getVal(series[i - 1]) : null
    let pct = null
    if (cur != null && prevVal != null && prevVal !== 0) {
      pct = ((cur - prevVal) / Math.abs(prevVal)) * 100
    }
    return { date: p.date, pct }
  })
}

// ---- common style ----

const tooltipStyle = {
  backgroundColor: 'rgba(255,255,255,0.96)',
  borderColor: '#e2e8f0',
  textStyle: { color: '#334155', fontSize: 12 },
}
const axisLabelStyle = { color: '#94a3b8', fontSize: 10 }
const splitLineStyle = { lineStyle: { color: '#f1f5f9' } }

function makeDataZoom(dates, opts = {}) {
  const xAxisIndex = opts.xAxisIndex
  return [
    {
      type: 'slider', start: props.zoomStart, end: 100, height: 24, bottom: 10,
      borderColor: '#e2e8f0', fillerColor: 'rgba(99,102,241,0.08)',
      ...(xAxisIndex != null ? { xAxisIndex } : {}),
    },
    { type: 'inside', ...(xAxisIndex != null ? { xAxisIndex } : {}) },
  ]
}

// ---- main option ----

const option = computed(() => {
  if (!props.series.length) return {}

  const dates = props.series.map(p => p.date)

  // 同比 / 环比 → 柱状图
  if (props.compareMode === 'yoy' || props.compareMode === 'mom') {
    const compared = props.compareMode === 'yoy'
      ? computeYoY(props.series)
      : computeMoM(props.series)
    return buildCompareOption(dates, compared)
  }

  // 原始值
  if (props.category === 'stock' || (props.series[0] && props.series[0].open !== undefined)) {
    return buildCandlestickOption(dates)
  }
  if (props.series[0] && props.series[0].unit_nav !== undefined) {
    return buildNavOption(dates)
  }
  return buildLineOption(dates)
})

// ---- compare bar chart (YoY / MoM) ----

function buildCompareOption(dates, compared) {
  const label = props.compareMode === 'yoy' ? '同比' : '环比'
  const values = compared.map(c => c.pct)

  return {
    tooltip: {
      trigger: 'axis',
      ...tooltipStyle,
      formatter(params) {
        const p = params[0]
        const v = p.value
        if (v == null) return `${p.name}<br/>${label}: --`
        const sign = v > 0 ? '+' : ''
        return `${p.name}<br/>${label}: <b>${sign}${v.toFixed(2)}%</b>`
      },
    },
    grid: { left: 60, right: 20, top: 30, bottom: 70 },
    xAxis: {
      type: 'category', data: dates,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: axisLabelStyle,
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: splitLineStyle,
      axisLabel: { ...axisLabelStyle, formatter: '{value}%' },
    },
    dataZoom: makeDataZoom(dates),
    series: [{
      type: 'bar',
      data: values.map(v => ({
        value: v,
        itemStyle: {
          color: v == null ? '#cbd5e1'
            : v > 0 ? 'rgba(239,68,68,0.7)'
            : v < 0 ? 'rgba(16,185,129,0.7)'
            : '#cbd5e1',
        },
      })),
      barMaxWidth: 20,
      markLine: {
        silent: true,
        data: [{ yAxis: 0, lineStyle: { color: '#94a3b8', type: 'solid', width: 1 }, label: { show: false } }],
      },
    }],
  }
}

// ---- raw chart builders ----

function buildLineOption(dates) {
  const values = props.series.map(p => p.value ?? p.close ?? null)
  const alertPoints = props.series
    .map((p, i) => p.alert ? { coord: [dates[i], values[i]], value: p.alert.label } : null)
    .filter(Boolean)

  return {
    tooltip: { trigger: 'axis', ...tooltipStyle },
    grid: { left: 60, right: 20, top: 30, bottom: 70 },
    xAxis: {
      type: 'category', data: dates,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: axisLabelStyle,
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value', scale: true,
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: splitLineStyle,
      axisLabel: axisLabelStyle,
    },
    dataZoom: makeDataZoom(dates),
    series: [{
      type: 'line', data: values, smooth: true,
      symbol: 'circle', symbolSize: 4, showSymbol: false,
      lineStyle: { color: '#6366f1', width: 2 },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(99,102,241,0.15)' }, { offset: 1, color: 'rgba(99,102,241,0)' }] } },
      itemStyle: { color: '#6366f1' },
      markLine: alertPoints.length ? {
        silent: true,
        data: alertPoints.map(p => ({ yAxis: p.coord[1], label: { formatter: p.value, fontSize: 10 }, lineStyle: { color: '#ef4444', type: 'dashed' } })),
      } : undefined,
    }],
  }
}

function buildCandlestickOption(dates) {
  const ohlc = props.series.map(p => [p.open, p.close, p.low, p.high])
  const volumes = props.series.map(p => p.volume ?? 0)
  const colors = props.series.map(p => (p.close ?? 0) >= (p.open ?? 0))

  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'cross' },
      ...tooltipStyle,
    },
    grid: [
      { left: 60, right: 20, top: 30, height: '55%' },
      { left: 60, right: 20, top: '72%', height: '16%' },
    ],
    xAxis: [
      {
        type: 'category', data: dates, gridIndex: 0,
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { show: false }, axisTick: { show: false },
      },
      {
        type: 'category', data: dates, gridIndex: 1,
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: axisLabelStyle, axisTick: { show: false },
      },
    ],
    yAxis: [
      {
        type: 'value', scale: true, gridIndex: 0,
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: splitLineStyle, axisLabel: axisLabelStyle,
      },
      {
        type: 'value', scale: true, gridIndex: 1,
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { show: false }, axisLabel: { show: false },
      },
    ],
    dataZoom: makeDataZoom(dates, { xAxisIndex: [0, 1] }),
    series: [
      {
        type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: {
          color: '#ef4444', color0: '#10b981',
          borderColor: '#ef4444', borderColor0: '#10b981',
        },
      },
      {
        type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
        data: volumes.map((v, i) => ({
          value: v,
          itemStyle: { color: colors[i] ? 'rgba(239,68,68,0.4)' : 'rgba(16,185,129,0.4)' },
        })),
      },
    ],
  }
}

function buildNavOption(dates) {
  const unitNav = props.series.map(p => p.unit_nav ?? null)
  const cumulativeNav = props.series.map(p => p.cumulative_nav ?? null)
  const hasCumulative = cumulativeNav.some(v => v !== null)

  const seriesList = [
    {
      name: '单位净值', type: 'line', data: unitNav,
      smooth: true, showSymbol: false,
      lineStyle: { color: '#6366f1', width: 2 },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(99,102,241,0.12)' }, { offset: 1, color: 'rgba(99,102,241,0)' }] } },
      itemStyle: { color: '#6366f1' },
    },
  ]
  if (hasCumulative) {
    seriesList.push({
      name: '累计净值', type: 'line', data: cumulativeNav,
      smooth: true, showSymbol: false,
      lineStyle: { color: '#f59e0b', width: 1.5, type: 'dashed' },
      itemStyle: { color: '#f59e0b' },
    })
  }

  return {
    tooltip: { trigger: 'axis', ...tooltipStyle },
    legend: hasCumulative ? {
      data: ['单位净值', '累计净值'], top: 0, right: 20,
      textStyle: { color: '#64748b', fontSize: 11 },
    } : undefined,
    grid: { left: 60, right: 20, top: hasCumulative ? 35 : 20, bottom: 70 },
    xAxis: {
      type: 'category', data: dates,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: axisLabelStyle, axisTick: { show: false },
    },
    yAxis: {
      type: 'value', scale: true,
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: splitLineStyle, axisLabel: axisLabelStyle,
    },
    dataZoom: makeDataZoom(dates),
    series: seriesList,
  }
}

watch(() => props.series, () => {
  if (chartRef.value) chartRef.value.resize()
})
</script>

<template>
  <div class="w-full">
    <div v-if="loading" class="flex items-center justify-center h-80">
      <svg class="w-6 h-6 animate-spin text-slate-300" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>
    <div v-else-if="!series.length" class="flex flex-col items-center justify-center h-80 text-slate-400">
      <svg class="w-12 h-12 mb-3 text-slate-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 3v18h18 M7 16l4-4 3 3 5-6" />
      </svg>
      <span class="text-sm">暂无数据</span>
    </div>
    <VChart
      v-else
      ref="chartRef"
      :option="option"
      :autoresize="true"
      style="height: 380px; width: 100%;"
      @click="onChartClick"
    />
  </div>
</template>
