<template>
  <div v-loading="loading">
    <!-- Time range selector -->
    <div class="page-header">
      <div>
        <h3>{{ t('nav.overview') }}</h3>
        <p>{{ t('dash.subtitle') }}</p>
      </div>
      <el-radio-group v-model="days" size="small" @change="reload">
        <el-radio-button :value="1">1d</el-radio-button>
        <el-radio-button :value="7">7d</el-radio-button>
        <el-radio-button :value="30">30d</el-radio-button>
        <el-radio-button :value="90">90d</el-radio-button>
      </el-radio-group>
    </div>

    <!-- Stat cards (6) -->
    <el-row :gutter="12" style="margin-bottom: 12px">
      <el-col :xs="12" :sm="8" :md="8" :lg="4" v-for="card in cards" :key="card.label">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">{{ card.label }}</div>
          <div class="stat-value">{{ card.value }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Throughput metrics -->
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between">
          <span style="font-weight: 600">{{ t('dash.throughput') }}</span>
          <span style="font-size: 12px; color: #8a9099">{{ t('dash.refresh') }}</span>
        </div>
      </template>
      <div class="throughput-grid">
        <div class="throughput-item" v-for="item in throughputCards" :key="item.label">
          <div class="throughput-label">{{ item.label }}</div>
          <div class="throughput-value" :style="{ color: item.color }">{{ item.value }}</div>
          <div class="throughput-unit">{{ item.unit }}</div>
        </div>
      </div>
    </el-card>

    <!-- Row 1: Cost & Tokens + Top Models -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :xs="24" :lg="16" class="chart-col">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">{{ t('dash.costTokens', { days }) }}</span></template>
          <v-chart :option="usageChartOption" style="height: 320px" autoresize />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="8" class="chart-col">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">{{ t('dash.topModels') }}</span></template>
          <v-chart :option="modelChartOption" style="height: 320px" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <!-- Row 2: Gateway Error Rate + Channel Usage -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :xs="24" :lg="12" class="chart-col">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">{{ t('dash.errorRate', { days }) }}</span></template>
          <v-chart :option="errorChartOption" style="height: 280px" autoresize />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12" class="chart-col">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">{{ t('dash.channelUsage') }}</span></template>
          <v-chart :option="channelChartOption" style="height: 280px" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <!-- Row 3: Latency -->
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header><span style="font-weight: 600">{{ t('dash.latency', { days }) }}</span></template>
      <div class="latency-grid">
        <div class="latency-item">
          <div class="latency-label">P50</div>
          <div class="latency-value" style="color: #10b981">{{ latencyData.p50.toLocaleString() }}ms</div>
        </div>
        <div class="latency-item">
          <div class="latency-label">P95</div>
          <div class="latency-value" style="color: #f59e0b">{{ latencyData.p95.toLocaleString() }}ms</div>
        </div>
        <div class="latency-item">
          <div class="latency-label">P99</div>
          <div class="latency-value" style="color: #ef4444">{{ latencyData.p99.toLocaleString() }}ms</div>
        </div>
      </div>
      <v-chart v-if="latencyData.trend.length > 0" :option="latencyChartOption" style="height: 260px; margin-top: 12px" autoresize />
    </el-card>

    <!-- Row 4: Top Keys -->
    <el-card shadow="never">
      <template #header><span style="font-weight: 600">{{ t('dash.topKeys', { days }) }}</span></template>
      <el-table :data="topKeys" stripe size="small" :show-header="true">
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="key_name" :label="t('dash.keyName')" min-width="180" show-overflow-tooltip />
        <el-table-column prop="request_count" :label="t('dash.requests')" width="120" align="right">
          <template #default="{ row }">{{ row.request_count.toLocaleString() }}</template>
        </el-table-column>
        <el-table-column prop="total_tokens" :label="t('dash.tokens')" width="140" align="right">
          <template #default="{ row }">{{ row.total_tokens.toLocaleString() }}</template>
        </el-table-column>
        <el-table-column :label="t('dash.cost')" width="120" align="right">
          <template #default="{ row }">
            <span style="font-weight: 600; color: #6366f1">${{ row.cost.toFixed(4) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { statsApi } from '@/api/stats'
import { ElMessage } from 'element-plus'
import { useI18n } from '@/i18n'

const { t } = useI18n()

use([CanvasRenderer, LineChart, BarChart, PieChart, GridComponent, TooltipComponent, LegendComponent])

const loading = ref(false)
const days = ref(7)
const overview = ref<any>({})
const usage = ref<any[]>([])
const models = ref<any[]>([])
const channels = ref<any[]>([])
const errorRate = ref<any[]>([])
const latencyData = ref<any>({ p50: 0, p95: 0, p99: 0, trend: [] })
const throughput = ref<any>({ current_qps: 0, current_rpm: 0, current_tpm: 0, peak_qps: 0, peak_rpm: 0 })
const topKeys = ref<any[]>([])
let refreshTimer: ReturnType<typeof setInterval> | null = null

const cards = computed(() => [
  { label: t('dash.requestsToday'), value: overview.value.requests_today ?? '-' },
  { label: t('dash.costToday'), value: `$${(overview.value.cost_today ?? 0).toFixed(4)}` },
  { label: t('dash.totalCost'), value: `$${(overview.value.total_cost ?? 0).toFixed(2)}` },
  { label: t('dash.tokensToday'), value: (overview.value.tokens_today ?? 0).toLocaleString() },
  { label: t('dash.activeKeys'), value: overview.value.active_keys ?? '-' },
  { label: t('dash.activeChannels'), value: overview.value.active_channels ?? '-' },
])

const throughputCards = computed(() => [
  { label: t('dash.currentQps'), value: throughput.value.current_qps.toFixed(2), unit: t('dash.unitQps'), color: '#6366f1' },
  { label: t('dash.currentRpm'), value: throughput.value.current_rpm.toLocaleString(), unit: t('dash.unitRpm'), color: '#10b981' },
  { label: t('dash.currentTpm'), value: throughput.value.current_tpm.toLocaleString(), unit: t('dash.unitTpm'), color: '#8b5cf6' },
  { label: t('dash.peakQps'), value: throughput.value.peak_qps.toFixed(2), unit: t('dash.unitQps'), color: '#f59e0b' },
  { label: t('dash.peakRpm'), value: throughput.value.peak_rpm.toLocaleString(), unit: t('dash.unitRpm'), color: '#ef4444' },
])

const usageChartOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { data: [t('dash.cost'), t('dash.tokens')], top: 0 },
  grid: { top: 40, bottom: 20, left: 50, right: 50 },
  xAxis: { type: 'category', data: usage.value.map((u: any) => u.date), axisLine: { lineStyle: { color: '#e2e8f0' } }, axisLabel: { color: '#64748b' } },
  yAxis: [
    { type: 'value', name: t('dash.cost'), position: 'left', splitLine: { lineStyle: { color: '#f1f5f9' } }, axisLabel: { color: '#64748b' } },
    { type: 'value', name: t('dash.tokens'), position: 'right', splitLine: { show: false }, axisLabel: { color: '#64748b' } },
  ],
  series: [
    { name: t('dash.cost'), type: 'line', smooth: true, data: usage.value.map((u: any) => u.cost), yAxisIndex: 0, itemStyle: { color: '#6366f1' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(99,102,241,0.15)' }, { offset: 1, color: 'rgba(99,102,241,0)' }] } } },
    { name: t('dash.tokens'), type: 'line', smooth: true, data: usage.value.map((u: any) => u.total_tokens), yAxisIndex: 1, itemStyle: { color: '#10b981' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(16,185,129,0.15)' }, { offset: 1, color: 'rgba(16,185,129,0)' }] } } },
  ],
}))

const modelChartOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { top: 10, bottom: 30, left: 10, right: 10, containLabel: true },
  xAxis: { type: 'category', data: models.value.map((m: any) => m.model), axisLabel: { rotate: 30, color: '#64748b', fontSize: 11 }, axisLine: { lineStyle: { color: '#e2e8f0' } } },
  yAxis: { type: 'value', name: t('dash.cost'), splitLine: { lineStyle: { color: '#f1f5f9' } }, axisLabel: { color: '#64748b' } },
  series: [{ type: 'bar', data: models.value.map((m: any) => m.cost), itemStyle: { color: '#6366f1', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 40 }],
}))

const errorChartOption = computed(() => ({
  tooltip: {
    trigger: 'axis',
    formatter: (params: any) => {
      const p = params[0]
      return t('dash.errorTip', {
        date: p.axisValue,
        rate: p.data,
        errors: errorRate.value[p.dataIndex]?.errors ?? 0,
        total: errorRate.value[p.dataIndex]?.total ?? 0,
      })
    },
  },
  grid: { top: 20, bottom: 20, left: 50, right: 20 },
  xAxis: { type: 'category', data: errorRate.value.map((e: any) => e.date), axisLine: { lineStyle: { color: '#e2e8f0' } }, axisLabel: { color: '#64748b' } },
  yAxis: { type: 'value', name: '%', max: (v: any) => Math.max(v.max * 1.2, 1), splitLine: { lineStyle: { color: '#f1f5f9' } }, axisLabel: { color: '#64748b' } },
  series: [{
    type: 'line', smooth: true, data: errorRate.value.map((e: any) => e.rate),
    itemStyle: { color: '#ef4444' },
    areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(239,68,68,0.15)' }, { offset: 1, color: 'rgba(239,68,68,0)' }] } },
  }],
}))

const channelChartOption = computed(() => {
  const palette = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#14b8a6']
  return {
    tooltip: { trigger: 'item', formatter: '{b}: ${c} ({d}%)' },
    series: [{
      type: 'pie', radius: ['40%', '70%'],
      label: { fontSize: 12 },
      data: channels.value.map((c: any, i: number) => ({
        name: c.channel_name, value: c.cost,
        itemStyle: { color: palette[i % palette.length] },
      })),
    }],
  }
})

const latencyChartOption = computed(() => ({
  tooltip: { trigger: 'axis', formatter: (params: any) => params.map((p: any) => `${p.marker}${p.seriesName}: ${p.data.toLocaleString()}ms`).join('<br/>') },
  legend: { data: ['P50', 'P95', 'P99'], top: 0 },
  grid: { top: 35, bottom: 20, left: 50, right: 20 },
  xAxis: { type: 'category', data: latencyData.value.trend.map((t: any) => t.date), axisLine: { lineStyle: { color: '#e2e8f0' } }, axisLabel: { color: '#64748b' } },
  yAxis: { type: 'value', name: 'ms', splitLine: { lineStyle: { color: '#f1f5f9' } }, axisLabel: { color: '#64748b' } },
  series: [
    { name: 'P50', type: 'line', smooth: true, data: latencyData.value.trend.map((t: any) => t.p50), itemStyle: { color: '#10b981' } },
    { name: 'P95', type: 'line', smooth: true, data: latencyData.value.trend.map((t: any) => t.p95), itemStyle: { color: '#f59e0b' } },
    { name: 'P99', type: 'line', smooth: true, data: latencyData.value.trend.map((t: any) => t.p99), itemStyle: { color: '#ef4444' } },
  ],
}))

async function refreshThroughput() {
  try {
    throughput.value = await statsApi.throughput(days.value)
  } catch { /* silent */ }
}

async function reload() {
  loading.value = true
  try {
    const results = await Promise.allSettled([
      statsApi.overview(),
      statsApi.usage(days.value),
      statsApi.byModel(days.value),
      statsApi.byChannel(days.value),
      statsApi.errorRate(days.value),
      statsApi.latency(days.value),
      statsApi.throughput(days.value),
      statsApi.byKey(days.value),
    ])
    if (results[0].status === 'fulfilled') overview.value = results[0].value
    if (results[1].status === 'fulfilled') usage.value = results[1].value
    if (results[2].status === 'fulfilled') models.value = results[2].value
    if (results[3].status === 'fulfilled') channels.value = results[3].value
    if (results[4].status === 'fulfilled') errorRate.value = results[4].value
    if (results[5].status === 'fulfilled') latencyData.value = results[5].value
    if (results[6].status === 'fulfilled') throughput.value = results[6].value
    if (results[7].status === 'fulfilled') topKeys.value = results[7].value
    if (results.some(r => r.status === 'rejected')) {
      ElMessage.warning(t('dash.statsFailed'))
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  reload()
  refreshTimer = setInterval(refreshThroughput, 10000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.stat-card {
  margin-bottom: 12px;
}

.stat-card :deep(.el-card__body) {
  padding: 12px 14px !important;
}

.stat-label {
  font-size: 13px;
  color: #646a73;
  margin-bottom: 4px;
  white-space: nowrap;
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: #1c1f23;
  font-variant-numeric: tabular-nums;
  line-height: 1.3;
}

.throughput-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 16px;
}

.throughput-item {
  flex: 1;
  text-align: center;
  background: #fafafa;
  border-radius: 6px;
  padding: 12px 8px;
}

.throughput-label {
  font-size: 14px;
  font-weight: 600;
  color: #4e5969;
  margin-bottom: 8px;
}

.throughput-value {
  font-size: 22px;
  font-weight: 600;
  color: #1c1f23;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.throughput-unit {
  font-size: 13px;
  color: #4e5969;
  margin-top: 4px;
}

.latency-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 16px;
}

.latency-item {
  flex: 1;
  text-align: center;
  background: #fafafa;
  border-radius: 6px;
  padding: 12px 8px;
}

.latency-label {
  font-size: 14px;
  font-weight: 600;
  color: #4e5969;
  margin-bottom: 6px;
}

.latency-value {
  font-size: 24px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.chart-col {
  margin-bottom: 20px;
}
</style>
