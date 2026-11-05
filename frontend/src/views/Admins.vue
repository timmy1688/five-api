<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.admins') }}</h3>
        <p>{{ t('admins.subtitle') }}</p>
      </div>
      <el-button v-if="auth.isPlatformAdmin" type="primary" @click="openCreate">{{ t('admins.add') }}</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="admins" v-loading="loading" stripe>
        <el-table-column prop="id" :label="t('common.id')" width="60" />
        <el-table-column prop="username" :label="t('login.username')" min-width="120" />
        <el-table-column :label="t('admins.role')" width="140">
          <template #default="{ row }">
            <el-tag size="small" round>{{ roleLabel(row.role) }}</el-tag>
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
        <el-table-column v-if="auth.isPlatformAdmin" :label="t('common.actions')" width="240" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-button v-if="row.username !== auth.username" text size="small" @click="resetPassword(row)">
              {{ t('tenants.resetPassword') }}
            </el-button>
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
        <el-form-item v-if="editingId" :label="t('admins.active')">
          <el-switch v-model="form.is_active" />
        </el-form-item>
        <el-alert v-else type="info" :closable="false" :title="t('admins.passwordAuto')" />
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <TemporaryPasswordDialog
      v-model="issued.open"
      :title="issued.title"
      :username="issued.username"
      :password="issued.password"
      :hint="issued.hint"
      @closed="issued.password = ''"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usersApi } from '@/api/users'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t, roleLabel } = useI18n()
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import TemporaryPasswordDialog from '@/components/TemporaryPasswordDialog.vue'

const auth = useAuthStore()
const admins = ref<any[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
// The generated login password is shown once and dropped when the dialog closes.
const issued = ref({ open: false, title: '', username: '', password: '', hint: '' })

const emptyForm = () => ({ username: '', is_active: true })
const form = ref(emptyForm())

function failure(error: any, fallback: string) {
  const detail = error?.response?.data?.detail
  ElMessage.error(typeof detail === 'string' ? detail : fallback)
}

function showPassword(title: string, username: string, password: string | null, hint: string) {
  if (!password) return
  issued.value = { open: true, title, username, password, hint }
}

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

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row: any) {
  editingId.value = row.id
  form.value = { username: row.username, is_active: row.is_active }
  dialogVisible.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editingId.value) {
      await usersApi.update(editingId.value, { is_active: form.value.is_active })
    } else {
      if (!form.value.username) {
        ElMessage.warning(t('admins.required'))
        return
      }
      const created = await usersApi.create({ username: form.value.username })
      showPassword(t('admins.accountCreated'), created.username, created.temporary_password, t('admins.passwordHint'))
    }
    dialogVisible.value = false
    ElMessage.success(t('common.saved'))
    await load()
  } catch (error) {
    failure(error, t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

async function resetPassword(row: any) {
  try {
    await ElMessageBox.confirm(t('tenants.resetConfirm', { name: row.username }), t('tenants.resetPassword'), {
      type: 'warning', confirmButtonText: t('tenants.resetPassword'), cancelButtonText: t('common.cancel'),
    })
  } catch {
    return
  }
  try {
    const res = await usersApi.resetPassword(row.id)
    showPassword(t('tenants.resetPassword'), row.username, res.temporary_password, t('tenants.resetDone'))
  } catch (error) {
    failure(error, t('common.saveFailed'))
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

onMounted(() => { load() })
</script>
