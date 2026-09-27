<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.groups') }}</h3>
        <p>{{ t('groups.subtitle') }}</p>
      </div>
      <el-button v-if="auth.hasPermission('model_group:write')" type="primary" @click="openCreate">{{ t('groups.create') }}</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="id" :label="t('common.id')" width="60" />
        <el-table-column prop="name" :label="t('common.name')" min-width="150" show-overflow-tooltip />
        <el-table-column :label="t('nav.models')" min-width="300">
          <template #default="{ row }">
            <div style="display: flex; flex-wrap: wrap; gap: 4px">
              <el-tag v-for="m in row.models" :key="m" size="small">{{ m }}</el-tag>
              <span v-if="!row.models || row.models.length === 0" style="color: #94a3b8; font-size: 13px">{{ t('groups.empty') }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.created')" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column v-if="auth.hasPermission('model_group:write')" :label="t('common.actions')" width="140" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm :title="t('groups.deleteConfirm')" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button text type="danger" size="small">{{ t('common.delete') }}</el-button>
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

    <el-dialog v-model="dialogVisible" :title="editingId ? t('groups.edit') : t('groups.create')" width="520px">
      <el-form :model="form" label-width="100px">
        <el-form-item :label="t('common.name')">
          <el-input v-model="form.name" :placeholder="t('groups.namePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('nav.models')">
          <el-select v-model="form.models" multiple filterable allow-create style="width: 100%" :placeholder="t('groups.modelsPlaceholder')">
            <el-option v-for="m in availableModels" :key="m" :label="m" :value="m" />
          </el-select>
          <div style="font-size: 12px; color: #909399">{{ t('groups.empty') }}</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { modelGroupsApi } from '@/api/model_groups'
import { modelsApi } from '@/api/models'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t } = useI18n()
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
    ElMessage.error(t('groups.loadFailed'))
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
    ElMessage.success(t('common.saved'))
    await load()
  } catch {
    ElMessage.error(t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await modelGroupsApi.remove(id)
    ElMessage.success(t('common.deleted'))
    await load()
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : t('common.deleteFailed'))
  }
}

onMounted(() => { load(); loadAvailableModels() })
</script>
