<template>
  <div>
    <div class="page-header">
      <div>
        <h3>API Keys</h3>
        <p>Create and manage API keys with usage quotas</p>
      </div>
      <el-button v-if="auth.isAdmin()" type="primary" @click="openCreate">Create Key</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="keys" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="Name" min-width="100" show-overflow-tooltip />
        <el-table-column label="Key" min-width="300">
          <template #default="{ row }">
            <div class="key-cell">
              <code class="key-text">{{ visibleKeys[row.id] && row.key_raw ? row.key_raw : row.key_prefix + '••••••••••••••••••••' }}</code>
              <div class="key-actions">
                <el-tooltip v-if="row.key_raw" :content="visibleKeys[row.id] ? 'Hide' : 'Show'" placement="top">
                  <el-button size="small" circle @click="visibleKeys[row.id] = !visibleKeys[row.id]">
                    <el-icon :size="14"><View v-if="!visibleKeys[row.id]" /><Hide v-else /></el-icon>
                  </el-button>
                </el-tooltip>
                <el-tooltip v-if="visibleKeys[row.id] && row.key_raw" content="Copy" placement="top">
                  <el-button size="small" type="primary" circle @click="copyText(row.key_raw)">
                    <el-icon :size="14"><CopyDocument /></el-icon>
                  </el-button>
                </el-tooltip>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Quota (USD)" min-width="220">
          <template #default="{ row }">
            <template v-if="row.quota_total === -1">
              <div style="font-size: 13px">
                <span>Used: <b>${{ row.quota_used.toFixed(4) }}</b></span>
                <span style="margin-left: 8px; color: #94a3b8">/ Unlimited</span>
              </div>
            </template>
            <template v-else>
              <el-progress
                :percentage="Math.min(Math.round(row.quota_used / row.quota_total * 100), 100)"
                :stroke-width="14"
                :text-inside="true"
              />
              <div style="font-size: 12px; color: #64748b; margin-top: 2px">
                ${{ row.quota_used.toFixed(4) }} / ${{ row.quota_total.toFixed(2) }}
                <span style="margin-left: 6px; color: #10b981">Remain: ${{ row.quota_remaining.toFixed(4) }}</span>
              </div>
            </template>
          </template>
        </el-table-column>
        <el-table-column label="Reset" width="64" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.quota_reset_day" size="small" type="info">D{{ row.quota_reset_day }}</el-tag>
            <span v-else style="color: #c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="concurrent_limit" label="Concur." width="72" align="center" />
        <el-table-column label="RPM" width="72" align="center">
          <template #default="{ row }">
            <span v-if="row.rpm_limit === -1" style="color: #c0c4cc">-</span>
            <span v-else>{{ row.rpm_limit }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Enabled" width="76" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_enabled" :disabled="!auth.isAdmin()" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column v-if="auth.isAdmin()" label="Actions" width="250" fixed="right">
          <template #default="{ row }">
            <el-button text type="info" size="small" @click="showDetail(row)">View</el-button>
            <el-button text type="primary" size="small" @click="openEdit(row)">Edit</el-button>
            <el-button text size="small" @click="resetQuota(row.id)">Reset</el-button>
            <el-popconfirm title="Delete this key?" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button text type="danger" size="small">Delete</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
        <el-table-column v-else label="Actions" width="80" fixed="right">
          <template #default="{ row }">
            <el-button text type="info" size="small" @click="showDetail(row)">View</el-button>
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

    <!-- Create / Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="editingId ? 'Edit Key' : 'Create Key'" width="520px">
      <el-form :model="form" label-width="140px">
        <el-form-item label="Name">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="Quota (USD)">
          <el-input-number v-model="form.quota_total" :min="-1" :precision="2" :step="1" style="width: 100%" />
          <div style="font-size: 12px; color: #909399">-1 = unlimited</div>
        </el-form-item>
        <el-form-item label="Reset Day">
          <el-select v-model="form.quota_reset_day" clearable placeholder="No auto-reset" style="width: 100%">
            <el-option label="No auto-reset" :value="null" />
            <el-option v-for="d in 31" :key="d" :label="`Day ${d}`" :value="d" />
          </el-select>
          <div style="font-size: 12px; color: #909399">Monthly reset day. Used quota resets to 0 on this day.</div>
        </el-form-item>
        <el-form-item label="Concurrency">
          <el-input-number v-model="form.concurrent_limit" :min="1" :max="100" />
        </el-form-item>
        <el-form-item label="RPM Limit">
          <el-input-number v-model="form.rpm_limit" :min="-1" :step="10" style="width: 100%" />
          <div style="font-size: 12px; color: #909399">Requests per minute. -1 = unlimited</div>
        </el-form-item>
        <el-form-item label="Allowed Models">
          <el-select v-model="form.allowed_models" multiple filterable allow-create style="width: 100%" placeholder="Empty = all models">
          </el-select>
        </el-form-item>
        <el-form-item label="Allowed IPs">
          <el-select v-model="form.allowed_ips" multiple filterable allow-create style="width: 100%" placeholder="Empty = all IPs allowed">
          </el-select>
          <div style="font-size: 12px; color: #909399">IP addresses or CIDR ranges (e.g. 192.168.1.100, 10.0.0.0/24). Empty = no restriction.</div>
        </el-form-item>
        <el-form-item label="Channel Group">
          <el-input v-model="form.channel_group" placeholder="留空 = 可访问所有渠道" />
          <div style="font-size: 12px; color: #909399">限制此 Key 只能访问对应分组的渠道。留空表示不限制。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">Save</el-button>
      </template>
    </el-dialog>

    <!-- Show Key Dialog -->
    <el-dialog v-model="showKeyDialog" title="API Key Created" width="500px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" style="margin-bottom: 16px">
        This key will only be shown once. Please copy it now.
      </el-alert>
      <el-input :model-value="newKey" readonly>
        <template #append>
          <el-button @click="copyKey">Copy</el-button>
        </template>
      </el-input>
    </el-dialog>

    <!-- Detail Drawer -->
    <el-drawer v-model="detailVisible" title="Key Detail" size="520px">
      <template v-if="detailRow">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="ID">{{ detailRow.id }}</el-descriptions-item>
          <el-descriptions-item label="Name">{{ detailRow.name }}</el-descriptions-item>
          <el-descriptions-item label="Key Prefix">
            <code>{{ detailRow.key_prefix }}...</code>
          </el-descriptions-item>
          <el-descriptions-item label="Full Key">
            <template v-if="detailRow.key_raw">
              <div style="display: flex; align-items: center; gap: 8px">
                <code style="font-size: 12px; word-break: break-all">{{ keyVisible ? detailRow.key_raw : '••••••••••••••••••••••••' }}</code>
                <el-button text size="small" @click="keyVisible = !keyVisible">{{ keyVisible ? 'Hide' : 'Show' }}</el-button>
                <el-button text type="primary" size="small" @click="copyText(detailRow.key_raw)">Copy</el-button>
              </div>
            </template>
            <span v-else style="color: #94a3b8; font-size: 12px">Created before key storage was enabled</span>
          </el-descriptions-item>
          <el-descriptions-item label="Enabled">
            <el-tag :type="detailRow.is_enabled ? 'success' : 'info'" size="small" round>{{ detailRow.is_enabled ? 'Yes' : 'No' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Expires">
            {{ detailRow.expires_at ? formatTime(detailRow.expires_at) : 'Never' }}
          </el-descriptions-item>
          <el-descriptions-item label="Created">{{ formatTime(detailRow.created_at) }}</el-descriptions-item>
        </el-descriptions>

        <div class="detail-section-title">Quota</div>
        <div class="detail-grid">
          <div class="detail-card">
            <div class="detail-card-label">Total</div>
            <div class="detail-card-value">{{ detailRow.quota_total === -1 ? 'Unlimited' : '$' + detailRow.quota_total.toFixed(2) }}</div>
          </div>
          <div class="detail-card">
            <div class="detail-card-label">Used</div>
            <div class="detail-card-value" style="color: #6366f1">${{ detailRow.quota_used.toFixed(4) }}</div>
          </div>
          <div class="detail-card">
            <div class="detail-card-label">Remaining</div>
            <div class="detail-card-value" style="color: #10b981">{{ detailRow.quota_remaining === -1 ? 'Unlimited' : '$' + detailRow.quota_remaining.toFixed(4) }}</div>
          </div>
          <div class="detail-card">
            <div class="detail-card-label">Reset Day</div>
            <div class="detail-card-value">{{ detailRow.quota_reset_day ? 'Day ' + detailRow.quota_reset_day : '-' }}</div>
          </div>
        </div>

        <div class="detail-section-title">Limits</div>
        <div class="detail-grid">
          <div class="detail-card">
            <div class="detail-card-label">Concurrency</div>
            <div class="detail-card-value">{{ detailRow.concurrent_limit }}</div>
          </div>
          <div class="detail-card">
            <div class="detail-card-label">RPM</div>
            <div class="detail-card-value">{{ detailRow.rpm_limit === -1 ? 'Unlimited' : detailRow.rpm_limit }}</div>
          </div>
        </div>

        <div class="detail-section-title">Allowed Models</div>
        <div v-if="detailRow.allowed_models.length > 0" style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px">
          <el-tag v-for="m in detailRow.allowed_models" :key="m" size="small">{{ m }}</el-tag>
        </div>
        <div v-else style="color: #94a3b8; font-size: 13px; margin-bottom: 16px">All models allowed</div>

        <div class="detail-section-title">Allowed IPs</div>
        <div v-if="detailRow.allowed_ips && detailRow.allowed_ips.length > 0" style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px">
          <el-tag v-for="ip in detailRow.allowed_ips" :key="ip" size="small" type="info">{{ ip }}</el-tag>
        </div>
        <div v-else style="color: #94a3b8; font-size: 13px; margin-bottom: 16px">No IP restriction</div>

        <div class="detail-section-title">Channel Group</div>
        <div style="margin-bottom: 16px">
          <el-tag v-if="detailRow.channel_group" size="small" type="info">{{ detailRow.channel_group }}</el-tag>
          <span v-else style="color: #94a3b8; font-size: 13px">All channels accessible</span>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { keysApi } from '@/api/keys'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { View, Hide, CopyDocument } from '@element-plus/icons-vue'
import dayjs from 'dayjs'

const auth = useAuthStore()

const keys = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const dialogVisible = ref(false)
const showKeyDialog = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const newKey = ref('')
const detailVisible = ref(false)
const detailRow = ref<any>(null)
const keyVisible = ref(false)
const visibleKeys = reactive<Record<number, boolean>>({})

function formatTime(t: string) {
  return dayjs(t).format('YYYY-MM-DD HH:mm:ss')
}

function showDetail(row: any) {
  detailRow.value = row
  keyVisible.value = false
  detailVisible.value = true
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('Copied')
  } catch {
    ElMessage.error('Copy failed')
  }
}

const emptyForm = () => ({
  name: '', quota_total: -1, concurrent_limit: 5, rpm_limit: -1,
  allowed_models: [] as string[],
  allowed_ips: [] as string[],
  channel_group: '',
  quota_reset_day: null as number | null,
})
const form = ref(emptyForm())

async function load() {
  loading.value = true
  try {
    const res = await keysApi.list(page.value)
    keys.value = res.items
    total.value = res.total
  } catch {
    ElMessage.error('Failed to load keys')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row: any) {
  editingId.value = row.id
  form.value = {
    name: row.name,
    quota_total: row.quota_total,
    concurrent_limit: row.concurrent_limit,
    rpm_limit: row.rpm_limit,
    allowed_models: [...row.allowed_models],
    allowed_ips: [...(row.allowed_ips || [])],
    channel_group: row.channel_group || '',
    quota_reset_day: row.quota_reset_day ?? null,
  }
  dialogVisible.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editingId.value) {
      await keysApi.update(editingId.value, form.value)
      ElMessage.success('Updated')
    } else {
      const res = await keysApi.create(form.value)
      newKey.value = res.key
      showKeyDialog.value = true
    }
    dialogVisible.value = false
    await load()
  } catch {
    ElMessage.error('Save failed')
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await keysApi.remove(id)
    ElMessage.success('Deleted')
    await load()
  } catch {
    ElMessage.error('Delete failed')
  }
}

async function toggleEnabled(row: any) {
  try {
    await keysApi.update(row.id, { is_enabled: row.is_enabled })
  } catch {
    row.is_enabled = !row.is_enabled
    ElMessage.error('Update failed')
  }
}

async function resetQuota(id: number) {
  try {
    await keysApi.resetQuota(id)
    ElMessage.success('Quota reset')
    await load()
  } catch {
    ElMessage.error('Reset failed')
  }
}

async function copyKey() {
  try {
    await navigator.clipboard.writeText(newKey.value)
    ElMessage.success('Copied')
  } catch {
    ElMessage.error('Copy failed, please copy manually')
  }
}

onMounted(load)
</script>

<style scoped>
.key-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.key-text {
  font-size: 12px;
  word-break: break-all;
  color: #334155;
}

.key-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.detail-section-title {
  font-size: 14px;
  font-weight: 600;
  color: #334155;
  margin: 20px 0 10px;
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 8px;
}

.detail-card {
  background: #f8fafc;
  border-radius: 10px;
  padding: 12px 14px;
}

.detail-card-label {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 600;
}

.detail-card-value {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
</style>
