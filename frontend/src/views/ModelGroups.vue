<template>
  <div>
    <div class="page-header">
      <div>
        <h3>Model Groups</h3>
        <p>Group models and assign them to API keys</p>
      </div>
      <el-button v-if="auth.hasPermission('model_group:write')" type="primary" @click="openCreate">Create Group</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="Name" min-width="150" show-overflow-tooltip />
        <el-table-column label="Models" min-width="300">
          <template #default="{ row }">
            <div style="display: flex; flex-wrap: wrap; gap: 4px">
              <el-tag v-for="m in row.models" :key="m" size="small">{{ m }}</el-tag>
              <span v-if="!row.models || row.models.length === 0" style="color: #94a3b8; font-size: 13px">No models (all allowed)</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Created" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column v-if="auth.hasPermission('model_group:write')" label="Actions" width="140" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">Edit</el-button>
            <el-popconfirm title="Delete this group? Keys referencing it will lose group restriction." @confirm="handleDelete(row.id)">
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

    <el-dialog v-model="dialogVisible" :title="editingId ? 'Edit Group' : 'Create Group'" width="520px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="Name">
          <el-input v-model="form.name" placeholder="e.g. Basic, Premium" />
        </el-form-item>
        <el-form-item label="Models">
          <el-select v-model="form.models" multiple filterable allow-create style="width: 100%" placeholder="Select or type model names">
            <el-option v-for="m in availableModels" :key="m" :label="m" :value="m" />
          </el-select>
          <div style="font-size: 12px; color: #909399">Select models from channels or type custom names. Empty = all models allowed.</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">Save</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { modelGroupsApi } from '@/api/model_groups'
import { modelsApi } from '@/api/models'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

const auth = useAuthStore()

const items = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)

const emptyForm = () => ({ name: '', models: [] as string[] })
const form = ref(emptyForm())
const availableModels = ref<string[]>([])

async function loadAvailableModels() {
  try {
    const res = await modelsApi.list()
    availableModels.value = (res.items || []).map((m: any) => m.model)
  } catch { /* ignore */ }
}

function formatTime(t: string) {
  return dayjs(t).format('YYYY-MM-DD HH:mm:ss')
}

async function load() {
  loading.value = true
  try {
    const res = await modelGroupsApi.list(page.value)
    items.value = res.items
    total.value = res.total
  } catch {
    ElMessage.error('Failed to load model groups')
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
  form.value = { name: row.name, models: [...(row.models || [])] }
  dialogVisible.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editingId.value) {
      await modelGroupsApi.update(editingId.value, form.value)
    } else {
      await modelGroupsApi.create(form.value)
    }
    dialogVisible.value = false
    ElMessage.success('Saved')
    await load()
  } catch {
    ElMessage.error('Save failed')
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await modelGroupsApi.remove(id)
    ElMessage.success('Deleted')
    await load()
  } catch {
    ElMessage.error('Delete failed')
  }
}

onMounted(() => { load(); loadAvailableModels() })
</script>
