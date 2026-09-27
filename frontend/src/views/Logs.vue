<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.logs') }}</h3>
        <p>{{ t('logs.subtitle') }}</p>
      </div>
      <el-popconfirm v-if="auth.hasPermission('log:write')" :title="cleanupTitle" @confirm="cleanupLogs">
        <template #reference>
          <el-button type="warning" plain>{{ t('logs.cleanup') }}</el-button>
        </template>
      </el-popconfirm>
    </div>

    <el-card shadow="never" style="margin-bottom: 20px">
      <el-form :inline="true" :model="filters" style="padding: 20px 20px 0">
        <el-form-item :label="t('common.model')">
          <el-input v-model="filters.model" placeholder="gpt-4o" clearable style="width: 150px" />
        </el-form-item>
        <el-form-item :label="t('logs.key')">
          <el-input
            v-model="filters.api_key_name"
            :placeholder="t('logs.keyPlaceholder')"
            clearable
            style="width: 180px"
            @keyup.enter="search"
          />
        </el-form-item>
        <el-form-item :label="t('logs.source')">
          <el-select v-model="filters.error_origin" clearable :placeholder="t('common.all')" style="width: 140px">
            <el-option :label="t('origin.gateway')" value="gateway" />
            <el-option :label="t('origin.official')" value="official" />
            <el-option :label="t('origin.reseller')" value="reseller" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('common.status')">
          <el-select v-model="filters.status_code" clearable :placeholder="t('common.all')" style="width: 100px">
            <el-option label="200" :value="200" />
            <el-option label="400" :value="400" />
            <el-option label="429" :value="429" />
            <el-option label="500" :value="500" />
            <el-option label="502" :value="502" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('logs.date')">
          <el-date-picker v-model="dateRange" type="daterange" :start-placeholder="t('logs.start')" :end-placeholder="t('logs.end')" style="width: 260px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">{{ t('common.search') }}</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <el-table :data="logs" v-loading="loading" stripe @row-click="showDetail" style="cursor: pointer">
        <el-table-column prop="created_at" :label="t('common.time')" width="165">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('logs.recorded')" width="78" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.has_audit" size="small" type="warning" round>{{ t('common.yes') }}</el-tag>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="api_key_name" :label="t('logs.key')" min-width="80" show-overflow-tooltip />
        <el-table-column prop="model_requested" :label="t('common.model')" min-width="120" show-overflow-tooltip />
        <el-table-column prop="provider" :label="t('logs.provider')" width="90">
          <template #default="{ row }"><el-tag size="small" round>{{ row.provider }}</el-tag></template>
        </el-table-column>
        <el-table-column :label="t('logs.input')" width="80" align="right">
          <template #default="{ row }">
            <span class="token-input">{{ row.prompt_tokens.toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.output')" width="80" align="right">
          <template #default="{ row }">
            <span class="token-output">{{ row.completion_tokens.toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.cache')" width="90">
          <template #default="{ row }">
            <template v-if="row.cached_tokens > 0">
              <span class="token-cache">{{ row.cached_tokens.toLocaleString() }}</span>
              <el-tag size="small" type="success" round style="margin-left: 4px; font-size: 10px; padding: 0 4px">HIT</el-tag>
            </template>
            <span v-else class="token-miss">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.cost')" width="86" align="right">
          <template #default="{ row }"><span style="font-weight: 500">${{ row.cost.toFixed(4) }}</span></template>
        </el-table-column>
        <el-table-column prop="latency_ms" :label="t('logs.latency')" width="76" align="right">
          <template #default="{ row }">{{ row.latency_ms }}ms</template>
        </el-table-column>
        <el-table-column :label="t('logs.mark')" width="88" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.keyword_hit" size="small" type="warning">{{ t('common.yes') }}</el-tag>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.errorSource')" width="130">
          <template #default="{ row }">
            <el-tag v-if="row.error_origin" :type="originTag(row.error_origin)" size="small">{{ originLabel(row.error_origin) }}</el-tag>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="status_code" :label="t('common.status')" width="72" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status_code === 200 ? 'success' : 'danger'" size="small" round>{{ row.status_code }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('logs.failover')" width="82" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.failed_over" size="small" type="warning">{{ t('common.yes') }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="total > 0"
        style="margin-top: 16px; justify-content: flex-end"
        :current-page="page"
        :page-size="20"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="(p: number) => { page = p; load() }"
      />
    </el-card>

    <el-drawer v-model="drawerVisible" :title="t('logs.detail')" size="640px">
      <div v-loading="detailLoading">
        <template v-if="detail">
          <el-descriptions :column="1" border>
            <el-descriptions-item :label="t('logs.requestId')">
              <code style="font-size: 12px">{{ detail.request_id }}</code>
            </el-descriptions-item>
            <el-descriptions-item :label="t('logs.auditTitle')">
              <el-button v-if="detail.has_audit" link type="primary" @click="openAudit">{{ t('logs.viewRequest') }}</el-button>
              <span v-else class="muted">{{ t('logs.auditEmpty') }}</span>
            </el-descriptions-item>
            <el-descriptions-item :label="t('logs.key')">{{ detail.api_key_name }} (#{{ detail.api_key_id }})</el-descriptions-item>
            <el-descriptions-item :label="t('logs.channel')">{{ detail.channel_name }}</el-descriptions-item>
            <el-descriptions-item :label="t('common.model')">{{ detail.model_requested }} &rarr; {{ detail.model_actual }}</el-descriptions-item>
            <el-descriptions-item :label="t('logs.provider')">{{ detail.provider }}</el-descriptions-item>
            <el-descriptions-item :label="t('logs.endpoint')">{{ detail.endpoint }}</el-descriptions-item>
            <el-descriptions-item :label="t('logs.stream')">{{ detail.is_stream ? t('common.yes') : t('common.no') }}</el-descriptions-item>
            <el-descriptions-item :label="t('common.status')">
              <el-tag :type="detail.status_code === 200 ? 'success' : 'danger'" size="small" round>{{ detail.status_code }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item :label="t('logs.failover')">{{ detail.failed_over ? t('common.yes') : t('common.no') }}</el-descriptions-item>
            <el-descriptions-item :label="t('logs.latency')">{{ detail.latency_ms }}ms</el-descriptions-item>
            <el-descriptions-item :label="t('logs.ip')">{{ detail.ip_address }}</el-descriptions-item>
            <el-descriptions-item :label="t('common.time')">{{ detail.created_at }}</el-descriptions-item>
            <el-descriptions-item :label="t('logs.mark')">
              {{ detail.keyword_hit ? t('common.yes') : t('common.no') }}
            </el-descriptions-item>
            <el-descriptions-item :label="t('logs.errorSource')">
              <el-tag v-if="detail.error_origin" :type="originTag(detail.error_origin)" size="small">{{ originLabel(detail.error_origin) }}</el-tag>
              <span v-else>{{ t('common.none') }}</span>
            </el-descriptions-item>
          </el-descriptions>

          <!-- Token Usage -->
          <div class="token-section-title">{{ t('logs.tokenUsage') }}</div>
          <div class="token-grid">
            <div class="token-card">
              <div class="token-card-label">{{ t('logs.inputTokens') }}</div>
              <div class="token-card-value" style="color: #6366f1">{{ detail.prompt_tokens.toLocaleString() }}</div>
            </div>
            <div class="token-card">
              <div class="token-card-label">{{ t('logs.outputTokens') }}</div>
              <div class="token-card-value" style="color: #10b981">{{ detail.completion_tokens.toLocaleString() }}</div>
            </div>
            <div class="token-card">
              <div class="token-card-label">{{ t('logs.cachedTokens') }}</div>
              <div class="token-card-value">
                <span :style="{ color: detail.cached_tokens > 0 ? '#f59e0b' : '#cbd5e1' }">
                  {{ detail.cached_tokens.toLocaleString() }}
                </span>
                <el-tag v-if="detail.cached_tokens > 0" size="small" type="success" round style="margin-left: 6px; font-size: 10px">HIT</el-tag>
                <el-tag v-else size="small" type="info" round style="margin-left: 6px; font-size: 10px">MISS</el-tag>
              </div>
            </div>
            <div class="token-card">
              <div class="token-card-label">{{ t('logs.totalTokens') }}</div>
              <div class="token-card-value" style="color: #334155">{{ detail.total_tokens.toLocaleString() }}</div>
            </div>
          </div>

          <!-- Cache & Cost Summary -->
          <div class="cost-bar">
            <div class="cost-bar-item">
              <span class="cost-bar-label">{{ t('logs.hitRate') }}</span>
              <span class="cost-bar-value">
                <template v-if="detail.prompt_tokens > 0 && detail.cached_tokens > 0">
                  {{ (detail.cached_tokens / detail.prompt_tokens * 100).toFixed(1) }}%
                </template>
                <template v-else>
                  <span style="color: #cbd5e1">{{ t('models.na') }}</span>
                </template>
              </span>
            </div>
            <div class="cost-bar-item">
              <span class="cost-bar-label">{{ t('logs.cost') }}</span>
              <span class="cost-bar-value cost-highlight">${{ detail.cost.toFixed(6) }}</span>
            </div>
          </div>

          <div class="token-section-title">{{ t('logs.downstream') }}</div>
          <p class="error-hint">{{ t('logs.downstreamHint') }}</p>
          <div class="error-panel">
            <div><span class="error-key">{{ t('common.status') }}</span> {{ detail.status_code }}</div>
            <div v-if="detail.error_message"><span class="error-key">{{ t('logs.message') }}</span> {{ detail.error_message }}</div>
            <div v-else class="muted">{{ t('logs.noClientError') }}</div>
          </div>

          <div class="token-section-title">{{ t('logs.upstream') }}</div>
          <p class="error-hint">{{ t('logs.upstreamHint') }}</p>
          <div class="error-panel">
            <template v-if="detail.upstream_status_code || detail.upstream_error">
              <div><span class="error-key">{{ t('common.status') }}</span> {{ detail.upstream_status_code || '-' }}</div>
              <div><span class="error-key">{{ t('logs.channel') }}</span> {{ detail.channel_name || '-' }} · {{ originLabel(detail.error_origin) }}</div>
              <pre class="audit-block">{{ detail.upstream_error }}</pre>
            </template>
            <div v-else class="muted">{{ t('logs.noUpstream') }}</div>
          </div>

        </template>
      </div>
    </el-drawer>

    <el-dialog v-model="auditVisible" :title="t('logs.auditTitle')" width="640px">
      <p class="error-hint">{{ t('logs.auditSeparate') }}</p>
      <pre v-loading="auditLoading" class="audit-block audit-dialog">{{ auditText }}</pre>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { logsApi } from '@/api/logs'
import { settingsApi } from '@/api/settings'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t } = useI18n()
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

const auth = useAuthStore()
const retentionDays = ref<number | null>(null)
const cleanupTitle = computed(() => {
  if (retentionDays.value === 0) return t('logs.cleanupConfirmOff')
  if (retentionDays.value != null) return t('logs.cleanupConfirmDays', { days: retentionDays.value })
  return t('logs.cleanupConfirm')
})

const logs = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<any>(null)
const auditVisible = ref(false)
const auditLoading = ref(false)
const auditText = ref('')
const dateRange = ref<[Date, Date] | null>(null)

const filters = ref({
  model: '',
  api_key_name: '',
  status_code: undefined as number | undefined,
  error_origin: '',
})

function originLabel(origin: string) {
  if (origin === 'gateway') return t('origin.gateway')
  if (origin === 'official') return t('origin.official')
  if (origin === 'reseller') return t('origin.reseller')
  return origin || '-'
}

function originTag(origin: string) {
  if (origin === 'official') return 'danger'
  if (origin === 'reseller') return 'warning'
  if (origin === 'gateway') return 'info'
  return 'info'
}

function formatTime(t: string) {
  return dayjs(t).format('YYYY-MM-DD HH:mm:ss')
}

async function load() {
  loading.value = true
  try {
    const params: any = { page: page.value, size: 20 }
    if (filters.value.model) params.model = filters.value.model
    if (filters.value.api_key_name.trim()) params.api_key_name = filters.value.api_key_name.trim()
    if (filters.value.status_code != null) params.status_code = filters.value.status_code
    if (filters.value.error_origin) params.error_origin = filters.value.error_origin
    if (dateRange.value) {
      params.start_date = dayjs(dateRange.value[0]).format('YYYY-MM-DDTHH:mm:ss')
      params.end_date = dayjs(dateRange.value[1]).endOf('day').format('YYYY-MM-DDTHH:mm:ss')
    }
    const res = await logsApi.list(params)
    logs.value = res.items
    total.value = res.total
  } catch {
    ElMessage.error(t('logs.loadFailed'))
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

async function showDetail(row: any) {
  auditVisible.value = false
  auditText.value = ''
  drawerVisible.value = true
  detailLoading.value = true
  try {
    detail.value = await logsApi.get(row.request_id)
  } catch {
    detail.value = row
  } finally {
    detailLoading.value = false
  }
}

async function openAudit() {
  if (!detail.value?.request_id) return
  auditVisible.value = true
  auditLoading.value = true
  auditText.value = ''
  try {
    const res = await logsApi.audit(detail.value.request_id)
    auditText.value = res.audit_request || t('common.empty')
  } catch {
    auditVisible.value = false
    ElMessage.error(t('logs.auditLoadFailed'))
  } finally {
    auditLoading.value = false
  }
}

async function cleanupLogs() {
  try {
    const res = await logsApi.cleanup()
    ElMessage.success(t('logs.cleaned', { count: res.deleted }))
    await load()
  } catch {
    ElMessage.error(t('logs.cleanupFailed'))
  }
}

onMounted(async () => {
  if (auth.hasPermission('setting:read')) {
    try {
      retentionDays.value = (await settingsApi.get()).log_retention_days
    } catch {
      retentionDays.value = null
    }
  }
  await load()
})
</script>

<style scoped>
.muted { color: #86909c; }

.error-hint {
  margin: -4px 0 8px;
  font-size: 13px;
  line-height: 1.5;
  color: #4e5969;
}

.error-panel {
  background: #fff;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 14px;
  line-height: 1.6;
  color: #1d2129;
}

.error-key {
  display: inline-block;
  min-width: 64px;
  margin-right: 8px;
  color: #4e5969;
  font-weight: 600;
}

.token-input { color: #6366f1; font-variant-numeric: tabular-nums; }
.token-output { color: #10b981; font-variant-numeric: tabular-nums; }
.token-cache { color: #f59e0b; font-variant-numeric: tabular-nums; font-size: 13px; }
.token-miss { color: #cbd5e1; }

.token-section-title {
  font-size: 15px;
  font-weight: 600;
  color: #334155;
  margin: 24px 0 12px;
}

.token-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.token-card {
  background: #f8fafc;
  border-radius: 10px;
  padding: 14px 16px;
}

.token-card-label {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 600;
}

.token-card-value {
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  display: flex;
  align-items: center;
}

.cost-bar {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}

.cost-bar-item {
  flex: 1;
  background: #f8fafc;
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.cost-bar-label {
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
}

.cost-bar-value {
  font-size: 16px;
  font-weight: 700;
  color: #334155;
  font-variant-numeric: tabular-nums;
}

.cost-highlight {
  color: #6366f1;
}

.audit-label {
  font-size: 14px;
  font-weight: 650;
  color: #1d2129;
  margin: 12px 0 6px;
}

.audit-block {
  margin: 0;
  background: #f8fafc;
  border-radius: 10px;
  padding: 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: #0f172a;
}

.audit-dialog {
  max-height: 60vh;
}
</style>
