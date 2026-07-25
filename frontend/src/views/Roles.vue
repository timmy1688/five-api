<template>
  <div>
    <div class="page-header">
      <div>
        <h3>Roles & Permissions</h3>
        <p>Manage roles and administrative permissions</p>
      </div>
      <el-button v-if="auth.hasPermission('role:write')" type="primary" @click="openCreate">Create Role</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="Name" min-width="140" />
        <el-table-column prop="description" label="Description" min-width="200" show-overflow-tooltip />
        <el-table-column label="Permissions" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" round>{{ row.permissions.length }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Builtin" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_builtin" size="small" type="warning" round>Yes</el-tag>
            <span v-else style="color: #c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="Created" width="165">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column v-if="auth.hasPermission('role:write')" label="Actions" width="180" fixed="right">
          <template #default="{ row }">
            <el-button text type="info" size="small" @click="showDetail(row)">View</el-button>
            <el-button v-if="!row.is_builtin" text type="primary" size="small" @click="openEdit(row)">Edit</el-button>
            <el-popconfirm v-if="!row.is_builtin" title="Delete this role?" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button text type="danger" size="small">Delete</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Create / Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="editingId ? 'Edit Role' : 'Create Role'" width="620px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="Name">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="Description">
          <el-input v-model="form.description" />
        </el-form-item>
        <el-form-item label="Permissions">
          <div class="perm-matrix">
            <div v-for="group in permGroups" :key="group.resource" class="perm-row">
              <div class="perm-resource">{{ group.resource }}</div>
              <div class="perm-actions">
                <el-checkbox
                  v-for="action in group.actions"
                  :key="action.permission"
                  :model-value="form.permissions.includes(action.permission)"
                  :label="action.action"
                  @change="(val: boolean) => togglePerm(action.permission, val)"
                />
              </div>
            </div>
          </div>
          <div style="margin-top: 8px; display: flex; gap: 8px">
            <el-button size="small" @click="selectAllPerms">Select All</el-button>
            <el-button size="small" @click="selectReadOnly">Read Only</el-button>
            <el-button size="small" @click="form.permissions = []">Clear</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">Save</el-button>
      </template>
    </el-dialog>

    <!-- Detail Drawer -->
    <el-drawer v-model="detailVisible" title="Role Detail" size="480px">
      <template v-if="detailRow">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="ID">{{ detailRow.id }}</el-descriptions-item>
          <el-descriptions-item label="Name">{{ detailRow.name }}</el-descriptions-item>
          <el-descriptions-item label="Description">{{ detailRow.description || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Builtin">{{ detailRow.is_builtin ? 'Yes' : 'No' }}</el-descriptions-item>
        </el-descriptions>
        <div style="font-size: 14px; font-weight: 600; color: #334155; margin: 20px 0 10px">Permissions</div>
        <div style="display: flex; flex-wrap: wrap; gap: 6px">
          <el-tag v-for="p in detailRow.permissions" :key="p" size="small">{{ p }}</el-tag>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { rolesApi } from '@/api/roles'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

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
    ElMessage.error('Failed to load roles')
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
        ElMessage.warning('Name is required')
        saving.value = false
        return
      }
      await rolesApi.create(form.value)
    }
    dialogVisible.value = false
    ElMessage.success('Saved')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'Save failed')
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await rolesApi.remove(id)
    ElMessage.success('Deleted')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'Delete failed')
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
