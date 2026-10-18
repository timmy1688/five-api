<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.reconcile') }}</h3>
        <p>{{ t('recon.subtitle') }}</p>
      </div>
    </div>

    <el-card shadow="never" class="block">
      <el-form label-position="top" class="params">
        <el-form-item :label="t('recon.file')">
          <el-upload class="uploader" :auto-upload="false" :limit="1" accept=".csv,text/csv" :on-change="onFile" :on-remove="() => (file = null)" :show-file-list="true">
            <el-button>{{ t('recon.choose') }}</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item :label="t('nav.channels')">
          <el-select v-model="channelIds" multiple clearable collapse-tags :placeholder="t('recon.allChannels')" style="width: 100%">
            <el-option v-for="c in channels" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('recon.timezone')">
          <el-select v-model="utcOffset" style="width: 100%">
            <el-option v-for="h in offsets" :key="h" :label="h === 0 ? 'UTC' : `UTC${h > 0 ? '+' : ''}${h}`" :value="h" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-form v-if="columns.length" label-position="top" class="params">
        <el-form-item :label="t('recon.dateColumn')">
          <el-select v-model="mapping.date" style="width: 100%">
            <el-option v-for="c in columns" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('recon.costColumn')">
          <el-select v-model="mapping.cost" style="width: 100%">
            <el-option v-for="c in columns" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('recon.modelColumn')">
          <el-select v-model="mapping.model" style="width: 100%">
            <el-option :label="t('recon.noModel')" value="-" />
            <el-option v-for="c in columns" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="actions">
        <el-button type="primary" :disabled="!file" :loading="running" @click="run">{{ t('recon.run') }}</el-button>
        <span class="hint">{{ t('recon.hint') }}</span>
      </div>
      <el-alert v-if="error" :title="error" type="warning" show-icon :closable="false" style="margin-top: 12px" />
    </el-card>

    <template v-if="result">
      <el-row :gutter="12">
        <el-col v-for="card in cards" :key="card.label" :xs="12" :md="6">
          <el-card shadow="never" class="block">
            <div class="stat-label">{{ card.label }}</div>
            <div class="stat-value" :class="card.tone">{{ card.value }}</div>
          </el-card>
        </el-col>
      </el-row>
      <el-card shadow="never" class="block">
        <el-table :data="result.rows" size="small" max-height="520" :row-class-name="rowClass">
          <el-table-column prop="date" :label="t('recon.date')" width="110" />
          <el-table-column v-if="mapping.model !== '-'" prop="model" :label="t('nav.models')" min-width="180" show-overflow-tooltip />
          <el-table-column :label="t('recon.vendor')" width="120" align="right">
            <template #default="{ row }">{{ money(row.vendor_cost) }}</template>
          </el-table-column>
          <el-table-column :label="t('recon.gateway')" width="120" align="right">
            <template #default="{ row }">{{ money(row.gateway_cost) }}</template>
          </el-table-column>
          <el-table-column :label="t('recon.diff')" width="150" align="right">
            <template #default="{ row }">
              <span :class="row.status">{{ money(row.diff) }}</span>
              <span v-if="row.diff_pct !== null" class="pct">{{ (row.diff_pct * 100).toFixed(1) }}%</span>
            </template>
          </el-table-column>
          <el-table-column prop="requests" :label="t('insights.requests')" width="90" align="right" />
          <el-table-column :label="t('recon.status')" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'match' ? 'success' : row.status === 'over' ? 'danger' : 'warning'">
                {{ t(`recon.${row.status}` as 'recon.match') }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { UploadFile } from 'element-plus'
import client from '@/api/client'
import { channelsApi } from '@/api/channels'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

interface ReconRow {
  date: string
  model: string
  vendor_cost: number
  gateway_cost: number
  diff: number
  diff_pct: number | null
  requests: number
  status: 'match' | 'over' | 'under'
}

const { t } = useI18n()
const auth = useAuthStore()
const file = ref<File | null>(null)
const channels = ref<{ id: number; name: string }[]>([])
const channelIds = ref<number[]>([])
const utcOffset = ref(0)
const offsets = Array.from({ length: 27 }, (_, i) => i - 12)
const columns = ref<string[]>([])
const mapping = ref({ date: '', cost: '', model: '' })
const running = ref(false)
const error = ref('')
const result = ref<{ rows: ReconRow[]; totals: { vendor_cost: number; gateway_cost: number; diff: number; mismatches: number }; skipped: number } | null>(null)

const money = (value: number) => `${value < 0 ? '-' : ''}$${Math.abs(value).toFixed(4)}`

const cards = computed(() => {
  const totals = result.value?.totals
  if (!totals) return []
  return [
    { label: t('recon.vendor'), value: money(totals.vendor_cost), tone: '' },
    { label: t('recon.gateway'), value: money(totals.gateway_cost), tone: '' },
    { label: t('recon.diff'), value: money(totals.diff), tone: Math.abs(totals.diff) < 0.01 ? 'good' : 'bad' },
    { label: t('recon.mismatches'), value: `${totals.mismatches} / ${result.value?.rows.length ?? 0}`, tone: totals.mismatches ? 'bad' : 'good' },
  ]
})

function onFile(upload: UploadFile) {
  file.value = upload.raw ?? null
  columns.value = []
  mapping.value = { date: '', cost: '', model: '' }
  result.value = null
}

const rowClass = ({ row }: { row: ReconRow }) => (row.status === 'match' ? '' : 'row-mismatch')

async function run() {
  if (!file.value) return
  running.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('file', file.value)
    form.append('date_column', mapping.value.date)
    form.append('cost_column', mapping.value.cost)
    form.append('model_column', mapping.value.model)
    form.append('channel_ids', channelIds.value.join(','))
    form.append('utc_offset', String(utcOffset.value))
    const { data } = await client.post('/reconcile', form)
    columns.value = data.columns
    mapping.value = { date: data.mapping.date, cost: data.mapping.cost, model: data.mapping.model || '-' }
    if (data.error) {
      error.value = t(`recon.err_${data.error}` as 'recon.err_no_rows')
      result.value = null
      return
    }
    result.value = data
    if (data.skipped) error.value = t('recon.skipped', { n: data.skipped })
  } catch (e: any) {
    error.value = e?.response?.data?.detail || t('recon.failed')
  } finally {
    running.value = false
  }
}

onMounted(async () => {
  if (!auth.hasPermission('channel:read')) return
  try {
    channels.value = (await channelsApi.list(1, 100)).items
  } catch {
    channels.value = []
  }
})
</script>

<style scoped>
.block {
  margin-bottom: 12px;
}

.params {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0 16px;
}

@media (max-width: 900px) {
  .params {
    grid-template-columns: 1fr;
  }
}

.uploader {
  width: 100%;
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hint {
  font-size: 12px;
  color: #8f959e;
}

.stat-label {
  font-size: 13px;
  color: #646a73;
}

.stat-value {
  margin-top: 4px;
  font-size: 22px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.good {
  color: #10b981;
}

.bad,
.over {
  color: #ef4444;
}

.under {
  color: #f59e0b;
}

.pct {
  margin-left: 6px;
  font-size: 11px;
  color: #8f959e;
}

:deep(.row-mismatch) {
  background: #fff7f7;
}
</style>
