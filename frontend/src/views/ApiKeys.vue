<template>
  <div>
    <div class="page-header">
      <div>
        <h3>API Keys</h3>
        <p>Create and manage API keys with usage quotas</p>
      </div>
      <el-button type="primary" @click="openCreate">Create Key</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="keys" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="Name" min-width="100" show-overflow-tooltip />
        <el-table-column prop="key_prefix" label="Key" width="110">
          <template #default="{ row }">
            <code style="font-size: 12px">{{ row.key_prefix }}...</code>
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
        <el-table-column label="Enabled" width="76" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_enabled" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column label="Actions" width="200" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">Edit</el-button>
            <el-button text size="small" @click="resetQuota(row.id)">Reset</el-button>
            <el-popconfirm title="Delete this key?" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button text type="danger" size="small">Delete</el-button>
              </template>
            </el-popconfirm>
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
        <el-form-item label="Allowed Models">
          <el-select v-model="form.allowed_models" multiple filterable allow-create style="width: 100%" placeholder="Empty = all models">
          </el-select>
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { keysApi } from '@/api/keys'
import { ElMessage } from 'element-plus'

const keys = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const dialogVisible = ref(false)
const showKeyDialog = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const newKey = ref('')

const emptyForm = () => ({
  name: '', quota_total: -1, concurrent_limit: 5, allowed_models: [] as string[],
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
    allowed_models: [...row.allowed_models],
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
