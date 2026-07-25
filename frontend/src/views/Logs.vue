<template>
  <div>
    <div class="page-header">
      <div>
        <h3>Request Logs</h3>
        <p>Inspect API requests, token usage, costs, and errors</p>
      </div>
      <el-popconfirm v-if="auth.hasPermission('log:write')" title="Delete logs older than 90 days?" @confirm="cleanupLogs">
        <template #reference>
          <el-button type="warning" plain>Cleanup</el-button>
        </template>
      </el-popconfirm>
    </div>

    <el-card shadow="never" style="margin-bottom: 20px">
      <el-form :inline="true" :model="filters" style="padding: 20px 20px 0">
        <el-form-item label="Model">
          <el-input v-model="filters.model" placeholder="gpt-4o" clearable style="width: 150px" />
        </el-form-item>
        <el-form-item label="Key">
          <el-input
            v-model="filters.api_key_name"
            placeholder="Search key name"
            clearable
            style="width: 180px"
            @keyup.enter="search"
          />
        </el-form-item>
        <el-form-item label="Status">
          <el-select v-model="filters.status_code" clearable placeholder="All" style="width: 100px">
            <el-option label="200" :value="200" />
            <el-option label="400" :value="400" />
            <el-option label="429" :value="429" />
            <el-option label="500" :value="500" />
            <el-option label="502" :value="502" />
          </el-select>
        </el-form-item>
        <el-form-item label="Date">
          <el-date-picker v-model="dateRange" type="daterange" start-placeholder="Start" end-placeholder="End" style="width: 260px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">Search</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <el-table :data="logs" v-loading="loading" stripe @row-click="showDetail" style="cursor: pointer">
        <el-table-column prop="created_at" label="Time" width="165">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="api_key_name" label="Key" min-width="80" show-overflow-tooltip />
        <el-table-column prop="model_requested" label="Model" min-width="120" show-overflow-tooltip />
        <el-table-column prop="provider" label="Provider" width="90">
          <template #default="{ row }"><el-tag size="small" round>{{ row.provider }}</el-tag></template>
        </el-table-column>
        <el-table-column label="Input" width="80" align="right">
          <template #default="{ row }">
            <span class="token-input">{{ row.prompt_tokens.toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Output" width="80" align="right">
          <template #default="{ row }">
            <span class="token-output">{{ row.completion_tokens.toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Cache" width="90">
          <template #default="{ row }">
            <template v-if="row.cached_tokens > 0">
              <span class="token-cache">{{ row.cached_tokens.toLocaleString() }}</span>
              <el-tag size="small" type="success" round style="margin-left: 4px; font-size: 10px; padding: 0 4px">HIT</el-tag>
            </template>
            <span v-else class="token-miss">-</span>
          </template>
        </el-table-column>
        <el-table-column label="Cost" width="86" align="right">
          <template #default="{ row }"><span style="font-weight: 500">${{ row.cost.toFixed(4) }}</span></template>
        </el-table-column>
        <el-table-column prop="latency_ms" label="Latency" width="76" align="right">
          <template #default="{ row }">{{ row.latency_ms }}ms</template>
        </el-table-column>
        <el-table-column prop="status_code" label="Status" width="72" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status_code === 200 ? 'success' : 'danger'" size="small" round>{{ row.status_code }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Failover" width="82" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.failed_over" size="small" type="warning">Yes</el-tag>
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

    <el-drawer v-model="drawerVisible" title="Log Detail" size="540px">
      <div v-loading="detailLoading">
        <template v-if="detail">
          <!-- Request Info -->
          <el-descriptions :column="1" border>
            <el-descriptions-item label="Request ID">
              <code style="font-size: 12px">{{ detail.request_id }}</code>
            </el-descriptions-item>
            <el-descriptions-item label="Key">{{ detail.api_key_name }} (#{{ detail.api_key_id }})</el-descriptions-item>
            <el-descriptions-item label="Channel">{{ detail.channel_name }}</el-descriptions-item>
            <el-descriptions-item label="Model">{{ detail.model_requested }} &rarr; {{ detail.model_actual }}</el-descriptions-item>
            <el-descriptions-item label="Provider">{{ detail.provider }}</el-descriptions-item>
            <el-descriptions-item label="Endpoint">{{ detail.endpoint }}</el-descriptions-item>
            <el-descriptions-item label="Stream">{{ detail.is_stream ? 'Yes' : 'No' }}</el-descriptions-item>
            <el-descriptions-item label="Status">
              <el-tag :type="detail.status_code === 200 ? 'success' : 'danger'" size="small" round>{{ detail.status_code }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="Failover">{{ detail.failed_over ? 'Yes' : 'No' }}</el-descriptions-item>
            <el-descriptions-item label="Latency">{{ detail.latency_ms }}ms</el-descriptions-item>
            <el-descriptions-item label="IP">{{ detail.ip_address }}</el-descriptions-item>
            <el-descriptions-item label="Time">{{ detail.created_at }}</el-descriptions-item>
            <el-descriptions-item v-if="detail.error_message" label="Error">
              <el-text type="danger">{{ detail.error_message }}</el-text>
            </el-descriptions-item>
          </el-descriptions>

          <!-- Token Usage -->
          <div class="token-section-title">Token Usage</div>
          <div class="token-grid">
            <div class="token-card">
              <div class="token-card-label">Input Tokens</div>
              <div class="token-card-value" style="color: #6366f1">{{ detail.prompt_tokens.toLocaleString() }}</div>
            </div>
            <div class="token-card">
              <div class="token-card-label">Output Tokens</div>
              <div class="token-card-value" style="color: #10b981">{{ detail.completion_tokens.toLocaleString() }}</div>
            </div>
            <div class="token-card">
              <div class="token-card-label">Cached Tokens</div>
              <div class="token-card-value">
                <span :style="{ color: detail.cached_tokens > 0 ? '#f59e0b' : '#cbd5e1' }">
                  {{ detail.cached_tokens.toLocaleString() }}
                </span>
                <el-tag v-if="detail.cached_tokens > 0" size="small" type="success" round style="margin-left: 6px; font-size: 10px">HIT</el-tag>
                <el-tag v-else size="small" type="info" round style="margin-left: 6px; font-size: 10px">MISS</el-tag>
              </div>
            </div>
            <div class="token-card">
              <div class="token-card-label">Total Tokens</div>
              <div class="token-card-value" style="color: #334155">{{ detail.total_tokens.toLocaleString() }}</div>
            </div>
          </div>

          <!-- Cache & Cost Summary -->
          <div class="cost-bar">
            <div class="cost-bar-item">
              <span class="cost-bar-label">Cache Hit Rate</span>
              <span class="cost-bar-value">
                <template v-if="detail.prompt_tokens > 0 && detail.cached_tokens > 0">
                  {{ (detail.cached_tokens / detail.prompt_tokens * 100).toFixed(1) }}%
                </template>
                <template v-else>
                  <span style="color: #cbd5e1">N/A</span>
                </template>
              </span>
            </div>
            <div class="cost-bar-item">
              <span class="cost-bar-label">Cost</span>
              <span class="cost-bar-value cost-highlight">${{ detail.cost.toFixed(6) }}</span>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { logsApi } from '@/api/logs'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

const auth = useAuthStore()

const logs = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<any>(null)
const dateRange = ref<[Date, Date] | null>(null)

const filters = ref({
  model: '',
  api_key_name: '',
  status_code: undefined as number | undefined,
})

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
    if (dateRange.value) {
      params.start_date = dayjs(dateRange.value[0]).format('YYYY-MM-DDTHH:mm:ss')
      params.end_date = dayjs(dateRange.value[1]).endOf('day').format('YYYY-MM-DDTHH:mm:ss')
    }
    const res = await logsApi.list(params)
    logs.value = res.items
    total.value = res.total
  } catch {
    ElMessage.error('Failed to load logs')
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

async function showDetail(row: any) {
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

async function cleanupLogs() {
  try {
    const res = await logsApi.cleanup()
    ElMessage.success(`Cleaned up ${res.deleted} logs`)
    await load()
  } catch {
    ElMessage.error('Cleanup failed')
  }
}

onMounted(load)
</script>

<style scoped>
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
</style>
