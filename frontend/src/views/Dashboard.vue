<template>
  <div v-loading="loading">
    <!-- Time range selector -->
    <div class="page-header">
      <div>
        <h3>Overview</h3>
        <p>API usage, cost, and performance at a glance</p>
      </div>
      <el-radio-group v-model="days" size="small" @change="reload">
        <el-radio-button :value="1">1d</el-radio-button>
        <el-radio-button :value="7">7d</el-radio-button>
        <el-radio-button :value="30">30d</el-radio-button>
        <el-radio-button :value="90">90d</el-radio-button>
      </el-radio-group>
    </div>

    <!-- Stat cards (6) -->
    <el-row :gutter="16" style="margin-bottom: 20px">
      <el-col :xs="24" :sm="12" :md="8" :lg="4" v-for="card in cards" :key="card.label">
        <el-card shadow="never" class="stat-card">
          <div class="stat-icon" :style="{ background: card.bg }">
            <el-icon :size="18" color="#fff"><component :is="card.icon" /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-label">{{ card.label }}</div>
            <div class="stat-value">{{ card.value }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Throughput metrics -->
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between">
          <span style="font-weight: 600">Throughput</span>
          <span style="font-size: 12px; color: #94a3b8">Auto-refresh every 10s</span>
        </div>
      </template>
      <div class="throughput-grid">
        <div class="throughput-item" v-for="t in throughputCards" :key="t.label">
          <div class="throughput-label">{{ t.label }}</div>
          <div class="throughput-value" :style="{ color: t.color }">{{ t.value }}</div>
          <div class="throughput-unit">{{ t.unit }}</div>
        </div>
      </div>
    </el-card>

    <!-- Row 1: Cost & Tokens + Top Models -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :xs="24" :lg="16" class="chart-col">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">Cost & Tokens ({{ days }}d)</span></template>
          <v-chart :option="usageChartOption" style="height: 320px" autoresize />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="8" class="chart-col">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">Top Models (by Cost)</span></template>
          <v-chart :option="modelChartOption" style="height: 320px" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <!-- Row 2: Gateway Error Rate + Channel Usage -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :xs="24" :lg="12" class="chart-col">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">Gateway Error Rate ({{ days }}d)</span></template>
          <v-chart :option="errorChartOption" style="height: 280px" autoresize />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12" class="chart-col">
        <el-card shadow="never">
          <template #header><span style="font-weight: 600">Channel Usage (by Cost)</span></template>
          <v-chart :option="channelChartOption" style="height: 280px" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <!-- Row 3: Latency -->
    <el-card shadow="never" style="margin-bottom: 20px">
      <template #header><span style="font-weight: 600">Latency ({{ days }}d)</span></template>
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
      <template #header><span style="font-weight: 600">Top Keys ({{ days }}d)</span></template>
      <el-table :data="topKeys" stripe size="small" :show-header="true">
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="key_name" label="Key Name" min-width="180" show-overflow-tooltip />
        <el-table-column prop="request_count" label="Requests" width="120" align="right">
          <template #default="{ row }">{{ row.request_count.toLocaleString() }}</template>
        </el-table-column>
        <el-table-column prop="total_tokens" label="Tokens" width="140" align="right">
          <template #default="{ row }">{{ row.total_tokens.toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="Cost ($)" width="120" align="right">
          <template #default="{ row }">
            <span style="font-weight: 600; color: #6366f1">${{ row.cost.toFixed(4) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, markRaw } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { statsApi } from '@/api/stats'
import { ElMessage } from 'element-plus'
import { TrendCharts, Coin, Key, Timer, Connection, Ticket } from '@element-plus/icons-vue'

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
  { label: 'Requests Today', value: overview.value.requests_today ?? '-', icon: markRaw(TrendCharts), bg: 'linear-gradient(135deg, #6366f1, #8b5cf6)' },
  { label: 'Cost Today', value: `$${(overview.value.cost_today ?? 0).toFixed(4)}`, icon: markRaw(Coin), bg: 'linear-gradient(135deg, #10b981, #34d399)' },
  { label: 'Total Cost', value: `$${(overview.value.total_cost ?? 0).toFixed(2)}`, icon: markRaw(Timer), bg: 'linear-gradient(135deg, #f59e0b, #fbbf24)' },
  { label: 'Tokens Today', value: (overview.value.tokens_today ?? 0).toLocaleString(), icon: markRaw(Ticket), bg: 'linear-gradient(135deg, #8b5cf6, #a78bfa)' },
  { label: 'Active Keys', value: overview.value.active_keys ?? '-', icon: markRaw(Key), bg: 'linear-gradient(135deg, #ef4444, #f87171)' },
  { label: 'Active Channels', value: overview.value.active_channels ?? '-', icon: markRaw(Connection), bg: 'linear-gradient(135deg, #06b6d4, #22d3ee)' },
])

const throughputCards = computed(() => [
  { label: 'Current QPS', value: throughput.value.current_qps.toFixed(2), unit: 'req/s', color: '#6366f1' },
  { label: 'Current RPM', value: throughput.value.current_rpm.toLocaleString(), unit: 'req/min', color: '#10b981' },
  { label: 'Current TPM', value: throughput.value.current_tpm.toLocaleString(), unit: 'tok/min', color: '#8b5cf6' },
  { label: 'Peak QPS', value: throughput.value.peak_qps.toFixed(2), unit: 'req/s', color: '#f59e0b' },
  { label: 'Peak RPM', value: throughput.value.peak_rpm.toLocaleString(), unit: 'req/min', color: '#ef4444' },
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

const errorChartOption = computed(() => ({
  tooltip: {
    trigger: 'axis',
    formatter: (params: any) => {
      const p = params[0]
      return `${p.axisValue}<br/>Error Rate: ${p.data}%<br/>Errors: ${errorRate.value[p.dataIndex]?.errors ?? 0} / ${errorRate.value[p.dataIndex]?.total ?? 0}`
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
      ElMessage.warning('Some stats failed to load')
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
.stat-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
}

.stat-card {
  margin-bottom: 16px;
}

.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-label {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 2px;
  white-space: nowrap;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.throughput-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 16px;
}

.throughput-item {
  flex: 1;
  text-align: center;
  background: #f8fafc;
  border-radius: 12px;
  padding: 18px 12px;
}

.throughput-label {
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 6px;
}

.throughput-value {
  font-size: 28px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.throughput-unit {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}

.latency-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 16px;
}

.latency-item {
  flex: 1;
  text-align: center;
  background: #f8fafc;
  border-radius: 12px;
  padding: 16px 12px;
}

.latency-label {
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
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
