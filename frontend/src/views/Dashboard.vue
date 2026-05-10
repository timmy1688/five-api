<template>
  <div v-loading="loading">
    <el-row :gutter="20" style="margin-bottom: 24px">
      <el-col :span="6" v-for="card in cards" :key="card.label">
        <el-card shadow="never" class="stat-card">
          <div class="stat-icon" :style="{ background: card.bg }">
            <el-icon :size="20" color="#fff"><component :is="card.icon" /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-label">{{ card.label }}</div>
            <div class="stat-value">{{ card.value }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20">
      <el-col :span="16">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">Cost & Tokens (7 days)</span></template>
          <v-chart :option="usageChartOption" style="height: 320px" autoresize />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">Top Models (by Cost)</span></template>
          <v-chart :option="modelChartOption" style="height: 320px" autoresize />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, markRaw } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { statsApi } from '@/api/stats'
import { ElMessage } from 'element-plus'
import { TrendCharts, Coin, Key, Timer } from '@element-plus/icons-vue'

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent])

const loading = ref(false)
const overview = ref<any>({})
const usage = ref<any[]>([])
const models = ref<any[]>([])

const cards = computed(() => [
  { label: 'Requests Today', value: overview.value.requests_today ?? '-', icon: markRaw(TrendCharts), bg: 'linear-gradient(135deg, #6366f1, #8b5cf6)' },
  { label: 'Cost Today', value: `$${(overview.value.cost_today ?? 0).toFixed(4)}`, icon: markRaw(Coin), bg: 'linear-gradient(135deg, #10b981, #34d399)' },
  { label: 'Total Cost', value: `$${(overview.value.total_cost ?? 0).toFixed(4)}`, icon: markRaw(Timer), bg: 'linear-gradient(135deg, #f59e0b, #fbbf24)' },
  { label: 'Active Keys', value: overview.value.active_keys ?? '-', icon: markRaw(Key), bg: 'linear-gradient(135deg, #ef4444, #f87171)' },
])

const usageChartOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { data: ['Cost ($)', 'Tokens'], top: 0 },
  grid: { top: 40, bottom: 20, left: 50, right: 50 },
  xAxis: { type: 'category', data: usage.value.map((u: any) => u.date), axisLine: { lineStyle: { color: '#e2e8f0' } }, axisLabel: { color: '#64748b' } },
  yAxis: [
    { type: 'value', name: 'Cost ($)', position: 'left', splitLine: { lineStyle: { color: '#f1f5f9' } }, axisLabel: { color: '#64748b' } },
    { type: 'value', name: 'Tokens', position: 'right', splitLine: { show: false }, axisLabel: { color: '#64748b' } },
  ],
  series: [
    { name: 'Cost ($)', type: 'line', smooth: true, data: usage.value.map((u: any) => u.cost), yAxisIndex: 0, itemStyle: { color: '#6366f1' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(99,102,241,0.15)' }, { offset: 1, color: 'rgba(99,102,241,0)' }] } } },
    { name: 'Tokens', type: 'line', smooth: true, data: usage.value.map((u: any) => u.total_tokens), yAxisIndex: 1, itemStyle: { color: '#10b981' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(16,185,129,0.15)' }, { offset: 1, color: 'rgba(16,185,129,0)' }] } } },
  ],
}))

const modelChartOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { top: 10, bottom: 30, left: 10, right: 10, containLabel: true },
  xAxis: { type: 'category', data: models.value.map((m: any) => m.model), axisLabel: { rotate: 30, color: '#64748b', fontSize: 11 }, axisLine: { lineStyle: { color: '#e2e8f0' } } },
  yAxis: { type: 'value', name: 'Cost ($)', splitLine: { lineStyle: { color: '#f1f5f9' } }, axisLabel: { color: '#64748b' } },
  series: [{ type: 'bar', data: models.value.map((m: any) => m.cost), itemStyle: { color: '#6366f1', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 40 }],
}))

onMounted(async () => {
  loading.value = true
  try {
    const results = await Promise.allSettled([statsApi.overview(), statsApi.usage(), statsApi.byModel()])
    if (results[0].status === 'fulfilled') overview.value = results[0].value
    if (results[1].status === 'fulfilled') usage.value = results[1].value
    if (results[2].status === 'fulfilled') models.value = results[2].value
    if (results.some(r => r.status === 'rejected')) {
      ElMessage.warning('Some stats failed to load')
    }
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.stat-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-label {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 2px;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
}
</style>
