<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.teams') }}</h3>
        <p>{{ t('teams.subtitle') }}</p>
      </div>
      <el-button v-if="canWrite" type="primary" @click="openCreate">{{ t('teams.create') }}</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="id" :label="t('common.id')" width="60" />
        <el-table-column :label="t('common.name')" min-width="160">
          <template #default="{ row }">
            <div>{{ row.name }}</div>
            <div v-if="row.description" style="color: #94a3b8; font-size: 12px">{{ row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column :label="t('teams.budget')" min-width="240">
          <template #default="{ row }">
            <template v-if="row.quota_total === -1">
              <span>{{ t('teams.used') }}: <b>${{ row.quota_used.toFixed(4) }}</b></span>
              <el-tag size="small" type="info" style="margin-left: 6px">{{ t('common.unlimited') }}</el-tag>
            </template>
            <template v-else>
              <el-progress
                :percentage="Math.min(Math.round(row.quota_used / (row.quota_total || 1) * 100), 100)"
                :status="row.quota_used >= row.quota_total ? 'exception' : undefined"
                :stroke-width="8"
              />
              <div style="font-size: 12px; color: #64748b">
                ${{ row.quota_used.toFixed(4) }} / ${{ row.quota_total.toFixed(2) }}
              </div>
            </template>
          </template>
        </el-table-column>
        <el-table-column :label="t('teams.resetDay')" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.quota_reset_day" size="small" type="info">D{{ row.quota_reset_day }}</el-tag>
            <span v-else style="color: #c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="key_count" :label="t('teams.keys')" width="80" align="center" />
        <el-table-column :label="t('common.enabled')" width="90" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_enabled" :disabled="!canWrite" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column v-if="canWrite" :label="t('common.actions')" width="220" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm :title="t('teams.resetConfirm')" @confirm="resetQuota(row.id)">
              <template #reference>
                <el-button text type="warning" size="small">{{ t('teams.resetQuota') }}</el-button>
              </template>
            </el-popconfirm>
            <el-popconfirm :title="t('teams.deleteConfirm')" @confirm="handleDelete(row.id)">
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

    <el-dialog v-model="dialogVisible" :title="editingId ? t('teams.edit') : t('teams.create')" width="520px">
      <el-form :model="form" label-width="120px">
        <el-form-item :label="t('common.name')">
          <el-input v-model="form.name" maxlength="128" />
        </el-form-item>
        <el-form-item :label="t('teams.description')">
          <el-input v-model="form.description" maxlength="256" />
        </el-form-item>
        <el-form-item :label="t('teams.budget')">
          <el-input-number v-model="form.quota_total" :min="-1" :precision="2" :step="10" style="width: 100%" />
          <div style="font-size: 12px; color: #909399">{{ t('teams.budgetHint') }}</div>
        </el-form-item>
        <el-form-item :label="t('teams.resetDay')">
          <el-select v-model="form.quota_reset_day" clearable style="width: 100%">
            <el-option v-for="d in 31" :key="d" :label="String(d)" :value="d" />
          </el-select>
          <div style="font-size: 12px; color: #909399">{{ t('teams.resetDayHint') }}</div>
        </el-form-item>
        <el-form-item :label="t('common.enabled')">
          <el-switch v-model="form.is_enabled" />
          <div style="font-size: 12px; color: #909399; margin-left: 8px">{{ t('teams.disabledHint') }}</div>
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
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { teamsApi } from '@/api/teams'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t } = useI18n()
const auth = useAuthStore()
const canWrite = computed(() => auth.hasPermission('team:write'))

const items = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)

const emptyForm = () => ({
  name: '',
  description: '',
  quota_total: -1,
  quota_reset_day: null as number | null,
  is_enabled: true,
})
const form = ref(emptyForm())

function errorDetail(error: any, fallback: string) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

async function load() {
  loading.value = true
  try {
    const res = await teamsApi.list(page.value)
    items.value = res.items
    total.value = res.total
  } catch {
    ElMessage.error(t('teams.loadFailed'))
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
    description: row.description,
    quota_total: row.quota_total,
    quota_reset_day: row.quota_reset_day ?? null,
    is_enabled: row.is_enabled,
  }
  dialogVisible.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editingId.value) {
      await teamsApi.update(editingId.value, form.value)
    } else {
      await teamsApi.create(form.value)
    }
    dialogVisible.value = false
    ElMessage.success(t('common.saved'))
    await load()
  } catch (error: any) {
    ElMessage.error(errorDetail(error, t('common.saveFailed')))
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row: any) {
  try {
    await teamsApi.update(row.id, { is_enabled: row.is_enabled })
  } catch {
    row.is_enabled = !row.is_enabled
    ElMessage.error(t('common.updateFailed'))
  }
}

async function resetQuota(id: number) {
  try {
    await teamsApi.resetQuota(id)
    ElMessage.success(t('common.updated'))
    await load()
  } catch {
    ElMessage.error(t('common.updateFailed'))
  }
}

async function handleDelete(id: number) {
  try {
    await teamsApi.remove(id)
    ElMessage.success(t('common.deleted'))
    await load()
  } catch (error: any) {
    ElMessage.error(errorDetail(error, t('common.deleteFailed')))
  }
}

onMounted(load)
</script>
