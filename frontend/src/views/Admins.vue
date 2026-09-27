<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.admins') }}</h3>
        <p>{{ t('admins.subtitle') }}</p>
      </div>
      <el-button v-if="auth.hasPermission('user:write')" type="primary" @click="openCreate">{{ t('admins.add') }}</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="admins" v-loading="loading" stripe>
        <el-table-column prop="id" :label="t('common.id')" width="60" />
        <el-table-column prop="username" :label="t('login.username')" min-width="120" />
        <el-table-column :label="t('admins.role')" width="140">
          <template #default="{ row }">
            <el-tag size="small" round>{{ roleLabel(row.role_name) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('admins.active')" width="76" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small" round>{{ row.is_active ? t('common.yes') : t('common.no') }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" :label="t('common.created')" width="165">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column v-if="auth.hasPermission('user:write')" :label="t('common.actions')" width="160" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm :title="t('admins.deleteConfirm')" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button text type="danger" size="small">{{ t('common.delete') }}</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editingId ? t('admins.edit') : t('admins.add')" width="420px">
      <el-form :model="form" label-width="100px">
        <el-form-item :label="t('login.username')">
          <el-input v-model="form.username" :disabled="!!editingId" />
        </el-form-item>
        <el-form-item :label="t('admins.password')">
          <el-input v-model="form.password" type="password" show-password :placeholder="editingId ? t('admins.passwordKeep') : ''" />
        </el-form-item>
        <el-form-item :label="t('admins.role')">
          <el-select v-model="form.role_id" style="width: 100%">
            <el-option v-for="r in roles" :key="r.id" :label="roleLabel(r.name)" :value="r.id">
              <span>{{ roleLabel(r.name) }}</span>
              <span style="float: right; font-size: 12px; color: #94a3b8">{{ r.description }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item v-if="editingId" :label="t('admins.active')">
          <el-switch v-model="form.is_active" />
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
import { usersApi } from '@/api/users'
import { rolesApi } from '@/api/roles'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t, roleLabel } = useI18n()
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

const auth = useAuthStore()
const admins = ref<any[]>([])
const roles = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)

const emptyForm = () => ({ username: '', password: '', role_id: null as number | null, is_active: true })
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
    ElMessage.error(t('admins.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function loadRoles() {
  try {
    roles.value = await rolesApi.listAll()
  } catch { /* silent */ }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row: any) {
  editingId.value = row.id
  form.value = { username: row.username, password: '', role_id: row.role_id, is_active: row.is_active }
  dialogVisible.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editingId.value) {
      const data: any = { role_id: form.value.role_id, is_active: form.value.is_active }
      if (form.value.password) data.password = form.value.password
      await usersApi.update(editingId.value, data)
    } else {
      if (!form.value.username || !form.value.password || !form.value.role_id) {
        ElMessage.warning(t('admins.required'))
        saving.value = false
        return
      }
      await usersApi.create(form.value)
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
    await usersApi.remove(id)
    ElMessage.success(t('common.deleted'))
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || t('common.deleteFailed'))
  }
}

onMounted(() => { load(); loadRoles() })
</script>
