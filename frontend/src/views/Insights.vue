<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <h3>{{ t('nav.insights') }}</h3>
        <p>{{ t('insights.subtitle') }}</p>
      </div>
      <el-radio-group v-model="days" size="small" @change="load">
        <el-radio-button :value="1">1d</el-radio-button>
        <el-radio-button :value="7">7d</el-radio-button>
        <el-radio-button :value="30">30d</el-radio-button>
        <el-radio-button :value="90">90d</el-radio-button>
      </el-radio-group>
    </div>

    <el-row :gutter="12">
      <el-col v-for="card in cards" :key="card.label" :xs="12" :sm="12" :md="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">{{ card.label }}</div>
          <div class="stat-value" :class="card.tone">{{ card.value }}</div>
          <div class="stat-hint">{{ card.hint }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never" class="block">
          <template #header><span class="card-title">{{ t('insights.trend') }}</span></template>
          <v-chart v-if="cache?.trend.length" :option="trendOption" autoresize style="height: 260px" />
          <el-empty v-else :description="t('insights.noData')" :image-size="60" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="block">
          <template #header>
            <div class="card-head">
              <span class="card-title">{{ t('insights.breakdown') }}</span>
              <el-radio-group v-model="breakdown" size="small">
                <el-radio-button value="by_model">{{ t('nav.models') }}</el-radio-button>
                <el-radio-button value="by_key">Key</el-radio-button>
                <el-radio-button value="by_channel">{{ t('nav.channels') }}</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <el-table :data="breakdownRows" size="small" max-height="260">
            <el-table-column :label="t('common.name')" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ row.model || row.api_key_name || row.channel_name || '-' }}</template>
            </el-table-column>
            <el-table-column :label="t('insights.hitRate')" width="120">
              <template #default="{ row }">
                <el-progress :percentage="pct(row.hit_rate)" :stroke-width="8" :color="rateColor(row.hit_rate)" />
              </template>
            </el-table-column>
            <el-table-column :label="t('insights.savings')" width="96" align="right">
              <template #default="{ row }">{{ money(row.cache_savings) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <div>
            <span class="card-title">{{ t('insights.sessions') }}</span>
            <span class="card-sub">{{ t('insights.sessionsHint') }}</span>
          </div>
          <el-select v-model="sort" size="small" style="width: 140px" @change="loadSessions">
            <el-option :label="t('insights.sortCost')" value="cost" />
            <el-option :label="t('insights.sortRecent')" value="recent" />
            <el-option :label="t('insights.sortRequests')" value="requests" />
          </el-select>
        </div>
      </template>
      <el-table :data="sessions" size="small" @row-click="openSession" row-class-name="clickable">
        <el-table-column :label="t('insights.session')" width="120">
          <template #default="{ row }"><code>{{ row.session_id.slice(0, 8) }}</code></template>
        </el-table-column>
        <el-table-column prop="api_key_name" label="Key" min-width="120" show-overflow-tooltip />
        <el-table-column prop="model" :label="t('nav.models')" min-width="140" show-overflow-tooltip />
        <el-table-column prop="requests" :label="t('insights.requests')" width="80" align="right" />
        <el-table-column :label="t('insights.cost')" width="100" align="right">
          <template #default="{ row }"><b>{{ money(row.cost) }}</b></template>
        </el-table-column>
        <el-table-column :label="t('insights.hitRate')" width="130">
          <template #default="{ row }">
            <el-progress :percentage="pct(row.hit_rate)" :stroke-width="8" :color="rateColor(row.hit_rate)" />
          </template>
        </el-table-column>
        <el-table-column :label="t('insights.savings')" width="96" align="right">
          <template #default="{ row }">{{ money(row.cache_savings) }}</template>
        </el-table-column>
        <el-table-column :label="t('insights.duration')" width="90" align="right">
          <template #default="{ row }">{{ duration(row.first_at, row.last_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('insights.lastActive')" width="150">
          <template #default="{ row }">{{ fmt(row.last_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="drawerOpen" :title="t('insights.sessionDetail')" size="760px">
      <div v-if="current" class="drawer-summary">
        <span><code>{{ current.session_id }}</code></span>
        <span>{{ current.api_key_name }}</span>
        <span>{{ money(current.cost) }}</span>
        <span>{{ t('insights.hitRate') }} {{ pct(current.hit_rate) }}%</span>
      </div>
      <el-table v-loading="detailLoading" :data="detail" size="small">
        <el-table-column :label="t('insights.time')" width="150">
          <template #default="{ row }">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('nav.models')" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.model_actual || row.model_requested }}</template>
        </el-table-column>
        <el-table-column prop="status_code" :label="t('insights.status')" width="64" align="center" />
        <el-table-column :label="t('insights.input')" width="110" align="right">
          <template #default="{ row }">
            {{ row.prompt_tokens.toLocaleString() }}
            <div v-if="row.cached_tokens" class="muted">{{ t('insights.cachedShort') }} {{ row.cached_tokens.toLocaleString() }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="completion_tokens" :label="t('insights.output')" width="80" align="right" />
        <el-table-column :label="t('insights.cost')" width="90" align="right">
          <template #default="{ row }">{{ money(row.cost) }}</template>
        </el-table-column>
      </el-table>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import { insightsApi, type CacheStats, type SessionRow } from '@/api/insights'
import { useI18n } from '@/i18n'

use([CanvasRenderer, BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent])

const { t } = useI18n()
const days = ref(7)
const sort = ref('cost')
const loading = ref(false)
const cache = ref<CacheStats | null>(null)
const sessions = ref<SessionRow[]>([])
const breakdown = ref<'by_model' | 'by_key' | 'by_channel'>('by_model')
const drawerOpen = ref(false)
const detailLoading = ref(false)
const current = ref<SessionRow | null>(null)
const detail = ref<any[]>([])

const pct = (rate: number) => Math.round(rate * 1000) / 10
const money = (value: number) => `${value < 0 ? '-' : ''}$${Math.abs(value).toFixed(4)}`
const fmt = (value: string) => dayjs(value).format('MM-DD HH:mm:ss')
const rateColor = (rate: number) => (rate >= 0.6 ? '#10b981' : rate >= 0.3 ? '#f59e0b' : '#ef4444')

function duration(start: string, end: string) {
  const minutes = dayjs(end).diff(dayjs(start), 'minute')
  if (minutes < 60) return `${minutes}m`
  return `${Math.floor(minutes / 60)}h${minutes % 60}m`
}

const cards = computed(() => {
  const total = cache.value?.total
  const cost = total?.cost ?? 0
  const savings = total?.cache_savings ?? 0
  return [
    { label: t('insights.hitRate'), value: `${pct(total?.hit_rate ?? 0)}%`, hint: t('insights.hitRateHint'), tone: '' },
    { label: t('insights.savings'), value: money(savings), hint: t('insights.savingsHint', { pct: cost + savings > 0 ? Math.round(savings / (cost + savings) * 100) : 0 }), tone: savings >= 0 ? 'good' : 'bad' },
    { label: t('insights.cachedTokens'), value: (total?.cached_tokens ?? 0).toLocaleString(), hint: t('insights.writeTokens', { n: (total?.cache_write_tokens ?? 0).toLocaleString() }), tone: '' },
    { label: t('insights.cost'), value: money(cost), hint: t('insights.requestsCount', { n: (total?.requests ?? 0).toLocaleString() }), tone: '' },
  ]
})

const breakdownRows = computed(() => cache.value?.[breakdown.value] ?? [])

const trendOption = computed(() => {
  const rows = cache.value?.trend ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: [t('insights.hitRate'), t('insights.savings')], bottom: 0 },
    grid: { left: 48, right: 48, top: 16, bottom: 40 },
    xAxis: { type: 'category', data: rows.map(r => r.date?.slice(5)) },
    yAxis: [
      { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
      { type: 'value', axisLabel: { formatter: '${value}' } },
    ],
    series: [
      { name: t('insights.hitRate'), type: 'line', smooth: true, data: rows.map(r => pct(r.hit_rate)), itemStyle: { color: '#3b82f6' } },
      { name: t('insights.savings'), type: 'bar', yAxisIndex: 1, data: rows.map(r => Number(r.cache_savings.toFixed(4))), itemStyle: { color: '#10b981' } },
    ],
  }
})

async function loadSessions() {
  sessions.value = (await insightsApi.sessions(days.value, sort.value)).items
}

async function load() {
  loading.value = true
  try {
    const [stats] = await Promise.all([insightsApi.cache(days.value), loadSessions()])
    cache.value = stats
  } catch {
    ElMessage.error(t('insights.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function openSession(row: SessionRow) {
  current.value = row
  drawerOpen.value = true
  detailLoading.value = true
  try {
    detail.value = (await insightsApi.session(row.session_id)).items
  } catch {
    detail.value = []
  } finally {
    detailLoading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.stat-card,
.block {
  margin-bottom: 12px;
}

.stat-label {
  font-size: 13px;
  color: #646a73;
}

.stat-value {
  margin-top: 4px;
  font-size: 22px;
  font-weight: 650;
  color: #1c1f23;
  font-variant-numeric: tabular-nums;
}

.stat-value.good {
  color: #10b981;
}

.stat-value.bad {
  color: #ef4444;
}

.stat-hint {
  margin-top: 2px;
  font-size: 12px;
  color: #8f959e;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-title {
  font-weight: 600;
}

.card-sub {
  margin-left: 8px;
  font-size: 12px;
  color: #8f959e;
}

.drawer-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #474d57;
}

.muted {
  font-size: 11px;
  color: #10b981;
}

:deep(.clickable) {
  cursor: pointer;
}
</style>
