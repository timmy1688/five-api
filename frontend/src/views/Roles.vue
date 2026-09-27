<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.roles') }}</h3>
        <p>{{ t('roles.subtitle') }}</p>
      </div>
      <el-button v-if="auth.hasPermission('role:write')" type="primary" @click="openCreate">{{ t('roles.create') }}</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="id" :label="t('common.id')" width="60" />
        <el-table-column prop="name" :label="t('common.name')" min-width="140">
          <template #default="{ row }">{{ roleLabel(row.name) }}</template>
        </el-table-column>
        <el-table-column prop="description" :label="t('roles.description')" min-width="200" show-overflow-tooltip />
        <el-table-column :label="t('roles.permissions')" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" round>{{ row.permissions.length }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('roles.builtin')" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_builtin" size="small" type="warning" round>{{ t('common.yes') }}</el-tag>
            <span v-else style="color: #c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.created')" width="165">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column v-if="auth.hasPermission('role:write')" :label="t('common.actions')" width="180" fixed="right">
          <template #default="{ row }">
            <el-button text type="info" size="small" @click="showDetail(row)">{{ t('common.view') }}</el-button>
            <el-button v-if="!row.is_builtin" text type="primary" size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm v-if="!row.is_builtin" :title="t('roles.deleteConfirm')" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button text type="danger" size="small">{{ t('common.delete') }}</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Create / Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="editingId ? t('roles.edit') : t('roles.create')" width="620px">
      <el-form :model="form" label-width="100px">
        <el-form-item :label="t('common.name')">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item :label="t('roles.description')">
          <el-input v-model="form.description" />
        </el-form-item>
        <el-form-item :label="t('roles.permissions')">
          <div class="perm-matrix">
            <div v-for="group in permGroups" :key="group.resource" class="perm-row">
              <div class="perm-resource">{{ permissionResource(group.resource) }}</div>
              <div class="perm-actions">
                <el-checkbox
                  v-for="action in group.actions"
                  :key="action.permission"
                  :model-value="form.permissions.includes(action.permission)"
                  :label="permissionAction(action.action)"
                  @change="(val: boolean) => togglePerm(action.permission, val)"
                />
              </div>
            </div>
          </div>
          <div style="margin-top: 8px; display: flex; gap: 8px">
            <el-button size="small" @click="selectAllPerms">{{ t('roles.selectAll') }}</el-button>
            <el-button size="small" @click="selectReadOnly">{{ t('roles.readOnly') }}</el-button>
            <el-button size="small" @click="form.permissions = []">{{ t('roles.clear') }}</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- Detail Drawer -->
    <el-drawer v-model="detailVisible" :title="t('roles.detail')" size="480px">
      <template v-if="detailRow">
        <el-descriptions :column="1" border>
          <el-descriptions-item :label="t('common.id')">{{ detailRow.id }}</el-descriptions-item>
          <el-descriptions-item :label="t('common.name')">{{ roleLabel(detailRow.name) }}</el-descriptions-item>
          <el-descriptions-item :label="t('roles.description')">{{ detailRow.description || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('roles.builtin')">{{ detailRow.is_builtin ? t('common.yes') : t('common.no') }}</el-descriptions-item>
        </el-descriptions>
        <div style="font-size: 14px; font-weight: 600; color: #334155; margin: 20px 0 10px">{{ t('roles.permissions') }}</div>
        <div style="display: flex; flex-wrap: wrap; gap: 6px">
          <el-tag v-for="p in detailRow.permissions" :key="p" size="small">{{ permissionLabel(p) }}</el-tag>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { rolesApi } from '@/api/roles'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'
import { en, type MessageKey } from '@/i18n/messages'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

const { t, roleLabel, permissionLabel } = useI18n()

function labeled(prefix: string, value: string) {
  const key = `${prefix}.${value}` as MessageKey
  return key in en ? t(key) : value
}

function permissionResource(resource: string) {
  return labeled('perm', resource)
}

function permissionAction(action: string) {
  return labeled('perm', action)
}

const auth = useAuthStore()
const items = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const detailVisible = ref(false)
const detailRow = ref<any>(null)
const permGroups = ref<any[]>([])
const allPerms = ref<string[]>([])

const emptyForm = () => ({ name: '', description: '', permissions: [] as string[] })
const form = ref(emptyForm())

function formatTime(t: string) {
  return dayjs(t).format('YYYY-MM-DD HH:mm:ss')
}

function togglePerm(perm: string, checked: boolean) {
  if (checked) {
    if (!form.value.permissions.includes(perm)) {
      form.value.permissions.push(perm)
    }
  } else {
    form.value.permissions = form.value.permissions.filter(p => p !== perm)
  }
}

function selectAllPerms() {
  form.value.permissions = [...allPerms.value]
}

function selectReadOnly() {
  form.value.permissions = allPerms.value.filter(p => p.endsWith(':read'))
}

function showDetail(row: any) {
  detailRow.value = row
  detailVisible.value = true
}

async function load() {
  loading.value = true
  try {
    const res = await rolesApi.list()
    items.value = res.items
  } catch {
    ElMessage.error(t('roles.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function loadPermissions() {
  try {
    const groups = await rolesApi.permissions()
    permGroups.value = groups
    allPerms.value = groups.flatMap((g: any) => g.actions.map((a: any) => a.permission))
  } catch { /* silent */ }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row: any) {
  editingId.value = row.id
  form.value = { name: row.name, description: row.description, permissions: [...row.permissions] }
  dialogVisible.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editingId.value) {
      await rolesApi.update(editingId.value, form.value)
    } else {
      if (!form.value.name) {
        ElMessage.warning(t('roles.nameRequired'))
        saving.value = false
        return
      }
      await rolesApi.create(form.value)
    }
    dialogVisible.value = false
    ElMessage.success(t('common.saved'))
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await rolesApi.remove(id)
    ElMessage.success(t('common.deleted'))
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || t('common.deleteFailed'))
  }
}

onMounted(() => { load(); loadPermissions() })
</script>

<style scoped>
.perm-matrix {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.perm-row {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid #f1f5f9;
}

.perm-row:last-child {
  border-bottom: none;
}

.perm-row:nth-child(even) {
  background: #f8fafc;
}

.perm-resource {
  width: 120px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  text-transform: capitalize;
}

.perm-actions {
  display: flex;
  gap: 16px;
}
</style>
