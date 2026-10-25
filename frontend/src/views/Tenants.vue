<template>
  <div>
    <div class="page-header">
      <div><h3>{{ t('nav.tenants') }}</h3><p>{{ t('tenants.subtitle') }}</p></div>
      <el-button type="primary" @click="openCreate">{{ t('tenants.create') }}</el-button>
    </div>
    <el-card shadow="never">
      <el-table :data="tenants" v-loading="loading">
        <el-table-column prop="name" :label="t('common.name')" min-width="140" />
        <el-table-column prop="username" :label="t('login.username')" min-width="120" />
        <el-table-column :label="t('tenants.sharedLimits')" min-width="180"><template #default="{ row }">
          {{ limit(row.rpm_limit) }} RPM / {{ limit(row.tpm_limit) }} TPM / {{ limit(row.concurrent_limit) }}
        </template></el-table-column>
        <el-table-column prop="key_count" label="Keys" width="70" />
        <el-table-column :label="t('tenants.total')" width="130"><template #default="{ row }">{{ money(row.quota_total) }}</template></el-table-column>
        <el-table-column :label="t('keys.used')" width="130"><template #default="{ row }">{{ money(row.quota_used) }}</template></el-table-column>
        <el-table-column :label="t('keys.occupied')" width="130"><template #default="{ row }">{{ money(row.quota_occupied) }}</template></el-table-column>
        <el-table-column :label="t('keys.remain')" width="130"><template #default="{ row }">{{ money(row.quota_remaining) }}</template></el-table-column>
        <el-table-column :label="t('common.enabled')" width="90"><template #default="{ row }">
          <el-switch v-model="row.is_enabled" @change="toggle(row)" />
        </template></el-table-column>
        <el-table-column :label="t('common.actions')" width="240" fixed="right"><template #default="{ row }">
          <el-button text @click="edit(row)">{{ t('common.edit') }}</el-button>
          <el-button text type="primary" @click="openQuota(row)">{{ t('tenants.adjustQuota') }}</el-button>
          <el-button v-if="row.account_id" text @click="openPassword(row)">{{ t('tenants.resetPassword') }}</el-button>
        </template></el-table-column>
      </el-table>
      <el-pagination :current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next"
        @current-change="(p: number) => { page = p; load() }" />
    </el-card>

    <el-dialog v-model="dialog" :title="editingId ? t('common.edit') : t('tenants.create')" width="520px" @closed="form.password = ''">
      <el-form label-width="130px">
        <el-form-item :label="t('common.name')" required><el-input v-model="form.name" maxlength="128" /></el-form-item>
        <el-form-item :label="t('common.description')"><el-input v-model="form.description" maxlength="256" /></el-form-item>
        <template v-if="!editingId">
          <el-form-item :label="t('login.username')" required><el-input v-model="form.username" maxlength="64" autocomplete="off" /></el-form-item>
          <el-form-item :label="t('tenants.tempPassword')" required><el-input v-model="form.password" type="password" show-password autocomplete="new-password" /></el-form-item>
          <el-form-item :label="t('tenants.total')"><el-input-number v-model="form.quota_total" :min="0" :precision="6" /></el-form-item>
          <el-alert type="info" :closable="false" :title="t('tenants.passwordHint')" />
        </template>
        <el-form-item :label="t('keys.allowedModels')">
          <el-select v-model="form.allowed_models" multiple filterable allow-create style="width: 100%">
            <el-option v-for="model in models" :key="model" :label="model" :value="model" />
          </el-select>
          <div>{{ t('tenants.modelsHint') }}</div>
        </el-form-item>
        <el-form-item :label="t('tenants.maxKeys')"><el-input-number v-model="form.max_keys" :min="1" :max="1000" /></el-form-item>
        <el-divider>{{ t('tenants.sharedLimits') }}</el-divider>
        <el-form-item :label="t('keys.rpmLabel')"><el-input-number v-model="form.rpm_limit" :min="-1" :max="1000000" /></el-form-item>
        <el-form-item :label="t('keys.tpmLabel')"><el-input-number v-model="form.tpm_limit" :min="-1" :max="100000000" /></el-form-item>
        <el-form-item :label="t('keys.concurrencyLabel')"><el-input-number v-model="form.concurrent_limit" :min="-1" :max="1000" /></el-form-item>
        <el-alert :title="t('tenants.limitsHint')" type="info" :closable="false" />
      </el-form>
      <template #footer><el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ t('common.save') }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="quotaDialog" :title="t('tenants.adjustQuota')" width="500px">
      <el-alert type="info" :closable="false" :title="t('tenants.quotaHint')" />
      <el-form label-width="130px" style="margin-top: 16px">
        <el-form-item :label="t('tenants.total')"><el-input-number v-model="quota" :min="0" :precision="6" /></el-form-item>
        <el-form-item :label="t('tenants.reason')" required><el-input v-model="reason" maxlength="256" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="quotaDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="saveQuota">{{ t('common.save') }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="passwordDialog" :title="t('tenants.resetPassword')" width="460px" @closed="temporaryPassword = ''">
      <el-alert :title="t('tenants.passwordHint')" type="warning" :closable="false" />
      <el-input v-model="temporaryPassword" type="password" show-password autocomplete="new-password" style="margin-top: 16px" />
      <template #footer><el-button type="primary" :loading="saving" @click="savePassword">{{ t('common.save') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { tenantsApi } from '@/api/tenants'
import { modelsApi } from '@/api/models'
import { useI18n } from '@/i18n'
import { operationId as newOperationId } from '@/utils/operation_id'
const { t } = useI18n()
const tenants = ref<any[]>([]), models = ref<string[]>([])
const total = ref(0), page = ref(1), loading = ref(false), saving = ref(false), editingId = ref<number | null>(null)
const dialog = ref(false), quotaDialog = ref(false), passwordDialog = ref(false)
const selectedId = ref(0), quota = ref(0), reason = ref(''), operationId = ref(''), temporaryPassword = ref('')
const defaults = () => ({ name: '', description: '', username: '', password: '', quota_total: 0,
  allowed_models: [] as string[], max_keys: 100, rpm_limit: 120, tpm_limit: 100000, concurrent_limit: 10 })
const form = ref(defaults())
const limit = (value: number) => value === -1 ? t('common.unlimited') : value
const money = (value: any) => Number(value) === -1 ? t('common.unlimited') : '$' + Number(value || 0).toFixed(6)
function failure(e: any) { ElMessage.error(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : t('common.saveFailed')) }
async function load() {
  loading.value = true
  try { const res = await tenantsApi.list(page.value); tenants.value = res.items; total.value = res.total }
  catch (e) { failure(e) } finally { loading.value = false }
}
function openCreate() { editingId.value = null; form.value = defaults(); dialog.value = true }
function edit(row: any) { editingId.value = row.id; form.value = { ...defaults(), ...row, allowed_models: [...row.allowed_models] }; dialog.value = true }
async function save() {
  saving.value = true
  try {
    if (editingId.value) await tenantsApi.update(editingId.value, { name: form.value.name, description: form.value.description,
      allowed_models: form.value.allowed_models, max_keys: form.value.max_keys,
      rpm_limit: form.value.rpm_limit, tpm_limit: form.value.tpm_limit, concurrent_limit: form.value.concurrent_limit })
    else await tenantsApi.create(form.value)
    dialog.value = false; form.value.password = ''; await load()
  } catch (e) { failure(e) } finally { saving.value = false }
}
async function toggle(row: any) {
  try { await tenantsApi.update(row.id, { is_enabled: row.is_enabled }) }
  catch (e) { row.is_enabled = !row.is_enabled; failure(e) }
}
function openQuota(row: any) {
  selectedId.value = row.id; quota.value = Math.max(0, Number(row.quota_total)); reason.value = ''
  operationId.value = newOperationId(); quotaDialog.value = true
}
async function saveQuota() {
  saving.value = true
  try {
    await tenantsApi.quota(selectedId.value, { quota_total: quota.value, reason: reason.value, operation_id: operationId.value })
    quotaDialog.value = false; await load()
  } catch (e) { failure(e) } finally { saving.value = false }
}
function openPassword(row: any) { selectedId.value = row.id; temporaryPassword.value = ''; passwordDialog.value = true }
async function savePassword() {
  saving.value = true
  try { await tenantsApi.password(selectedId.value, temporaryPassword.value); passwordDialog.value = false; temporaryPassword.value = '' }
  catch (e) { failure(e) } finally { saving.value = false }
}
onMounted(async () => {
  await load()
  try { models.value = (await modelsApi.list()).items.map((m: any) => m.model) } catch { /* form accepts model names */ }
})
</script>
