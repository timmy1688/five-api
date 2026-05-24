<template>
  <div>
    <div class="page-header">
      <div>
        <h3>Admins</h3>
        <p>Manage administrator accounts and roles</p>
      </div>
      <el-button type="primary" @click="openCreate">Add Admin</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="admins" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="Username" min-width="120" />
        <el-table-column prop="role" label="Role" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small" round>{{ row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Active" width="76" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small" round>{{ row.is_active ? 'Yes' : 'No' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="Created" width="165">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="Actions" width="160" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">Edit</el-button>
            <el-popconfirm title="Delete this admin?" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button text type="danger" size="small">Delete</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editingId ? 'Edit Admin' : 'Add Admin'" width="420px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="Username">
          <el-input v-model="form.username" :disabled="!!editingId" />
        </el-form-item>
        <el-form-item label="Password">
          <el-input v-model="form.password" type="password" show-password :placeholder="editingId ? '留空不修改' : ''" />
        </el-form-item>
        <el-form-item label="Role">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="Admin" value="admin">
              <span>Admin</span>
              <span style="float: right; font-size: 12px; color: #94a3b8">可读写所有功能</span>
            </el-option>
            <el-option label="Viewer" value="viewer">
              <span>Viewer</span>
              <span style="float: right; font-size: 12px; color: #94a3b8">只读权限</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item v-if="editingId" label="Active">
          <el-switch v-model="form.is_active" />
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
import { usersApi } from '@/api/users'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

const admins = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)

const emptyForm = () => ({ username: '', password: '', role: 'viewer', is_active: true })
const form = ref(emptyForm())

function formatTime(t: string) {
  return dayjs(t).format('YYYY-MM-DD HH:mm:ss')
}

async function load() {
  loading.value = true
  try {
    const res = await usersApi.list()
    admins.value = res.items
  } catch {
    ElMessage.error('Failed to load admins')
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
  form.value = { username: row.username, password: '', role: row.role, is_active: row.is_active }
  dialogVisible.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editingId.value) {
      const data: any = { role: form.value.role, is_active: form.value.is_active }
      if (form.value.password) data.password = form.value.password
      await usersApi.update(editingId.value, data)
    } else {
      if (!form.value.username || !form.value.password) {
        ElMessage.warning('Username and password are required')
        saving.value = false
        return
      }
      await usersApi.create(form.value)
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
    await usersApi.remove(id)
    ElMessage.success('Deleted')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'Delete failed')
  }
}

onMounted(load)
</script>
