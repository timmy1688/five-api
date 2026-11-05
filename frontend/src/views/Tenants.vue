<template>
  <div>
    <div class="page-header">
      <div><h3>{{ t('nav.tenants') }}</h3><p>{{ t('tenants.subtitle') }}</p></div>
      <el-button type="primary" @click="openCreate">{{ t('tenants.create') }}</el-button>
    </div>
    <el-card shadow="never">
      <el-table :data="tenants" v-loading="loading">
        <el-table-column prop="username" :label="t('login.username')" min-width="140" show-overflow-tooltip />
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
          <el-button v-if="row.account_id" text @click="resetPassword(row)">{{ t('tenants.resetPassword') }}</el-button>
        </template></el-table-column>
      </el-table>
      <el-pagination :current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next"
        @current-change="(p: number) => { page = p; load() }" />
    </el-card>

    <el-dialog v-model="dialog" :title="editingId ? t('common.edit') : t('tenants.create')" width="520px">
      <el-form label-width="130px">
        <el-form-item :label="t('login.username')" :required="!editingId">
          <el-input v-model="form.username" maxlength="64" autocomplete="off" :disabled="!!editingId" :placeholder="t('tenants.usernameHint')" />
        </el-form-item>
        <el-form-item :label="t('common.description')"><el-input v-model="form.description" maxlength="256" /></el-form-item>
        <template v-if="!editingId">
          <el-form-item :label="t('tenants.total')"><el-input-number v-model="form.quota_total" :min="0" :precision="6" /></el-form-item>
          <el-alert type="info" :closable="false" :title="t('tenants.passwordAuto')" />
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

    <el-dialog v-model="quotaDialog" :title="t('tenants.adjustQuota') + ' · ' + quotaTarget" width="520px">
      <el-descriptions :column="2" border size="small" class="quota-summary">
        <el-descriptions-item :label="t('tenants.total')">{{ money(fromMicro(quotaBase.total)) }}</el-descriptions-item>
        <el-descriptions-item :label="t('keys.remain')">{{ money(fromMicro(quotaBase.remaining)) }}</el-descriptions-item>
        <el-descriptions-item :label="t('keys.used')">{{ money(fromMicro(quotaBase.used)) }}</el-descriptions-item>
        <el-descriptions-item :label="t('keys.occupied')">{{ money(fromMicro(quotaBase.occupied)) }}</el-descriptions-item>
      </el-descriptions>
      <el-form label-width="150px" style="margin-top: 16px" @submit.prevent>
        <el-form-item :label="t('tenants.quotaMode')">
          <el-radio-group v-model="quotaMode">
            <el-radio-button value="add">{{ t('tenants.quotaAdd') }}</el-radio-button>
            <el-radio-button value="reduce">{{ t('tenants.quotaReduce') }}</el-radio-button>
            <el-radio-button value="set">{{ t('tenants.quotaSet') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="t('tenants.quotaAmount')">
          <el-input-number v-model="quotaAmount" :min="0" :precision="6" :controls="false" style="width: 200px" />
        </el-form-item>
        <el-form-item :label="t('tenants.quotaAfter')">
          <strong :class="{ 'quota-bad': quotaProblem }" class="quota-after">{{ money(fromMicro(quotaAfter)) }}</strong>
        </el-form-item>
        <el-alert v-if="quotaProblem" type="error" :closable="false" show-icon
          :title="t('tenants.quotaFloor', { min: money(fromMicro(quotaFloor)) })" />
        <el-form-item :label="t('tenants.reason')" style="margin-top: 16px">
          <el-input v-model="reason" maxlength="256" :placeholder="t('tenants.reasonOptional')" />
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="quotaDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" :disabled="quotaProblem || quotaUnchanged" @click="saveQuota">{{ t('common.save') }}</el-button></template>
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
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import TemporaryPasswordDialog from '@/components/TemporaryPasswordDialog.vue'
import { tenantsApi } from '@/api/tenants'
import { modelsApi } from '@/api/models'
import { useI18n } from '@/i18n'
import { operationId as newOperationId } from '@/utils/operation_id'
const { t } = useI18n()
const tenants = ref<any[]>([]), models = ref<string[]>([])
const total = ref(0), page = ref(1), loading = ref(false), saving = ref(false), editingId = ref<number | null>(null)
const dialog = ref(false), quotaDialog = ref(false)
const selectedId = ref(0), reason = ref(''), operationId = ref('')
// Budget amounts are kept in millionths of a dollar so additions never pick up float noise.
type QuotaMode = 'add' | 'reduce' | 'set'
const MICRO = 1_000_000
const toMicro = (value: any) => Math.round(Number(value || 0) * MICRO)
const fromMicro = (micro: number) => micro / MICRO
const quotaTarget = ref(''), quotaMode = ref<QuotaMode>('add'), quotaAmount = ref(0)
const quotaBase = ref({ total: 0, used: 0, occupied: 0, remaining: 0 })
const quotaAfter = computed(() => {
  const amount = toMicro(quotaAmount.value)
  if (quotaMode.value === 'set') return amount
  return quotaMode.value === 'add' ? quotaBase.value.total + amount : quotaBase.value.total - amount
})
const quotaFloor = computed(() => quotaBase.value.used + quotaBase.value.occupied)
const quotaProblem = computed(() => quotaAfter.value < 0 || quotaAfter.value < quotaFloor.value)
const quotaUnchanged = computed(() => quotaAfter.value === quotaBase.value.total)
// The generated login password is shown once and dropped when the dialog closes.
const issued = ref({ open: false, title: '', username: '', password: '', hint: '' })
// The username is also the tenant name; the server fills it in.
const defaults = () => ({ description: '', username: '', quota_total: 0,
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
    if (editingId.value) await tenantsApi.update(editingId.value, { description: form.value.description,
      allowed_models: form.value.allowed_models, max_keys: form.value.max_keys,
      rpm_limit: form.value.rpm_limit, tpm_limit: form.value.tpm_limit, concurrent_limit: form.value.concurrent_limit })
    else {
      const created = await tenantsApi.create(form.value)
      showPassword(t('tenants.accountCreated'), created.username, created.temporary_password, t('tenants.passwordHint'))
    }
    dialog.value = false; await load()
  } catch (e) { failure(e) } finally { saving.value = false }
}
async function toggle(row: any) {
  try { await tenantsApi.update(row.id, { is_enabled: row.is_enabled }) }
  catch (e) { row.is_enabled = !row.is_enabled; failure(e) }
}
async function openQuota(row: any) {
  try {
    // Read the live figures so a change made elsewhere is not overwritten from a stale table row.
    const fresh = await tenantsApi.get(row.id)
    quotaBase.value = {
      total: toMicro(Math.max(0, Number(fresh.quota_total))), used: toMicro(fresh.quota_used),
      occupied: toMicro(fresh.quota_occupied), remaining: toMicro(fresh.quota_remaining),
    }
  } catch (e) { failure(e); return }
  selectedId.value = row.id; quotaTarget.value = row.username
  quotaMode.value = 'add'; quotaAmount.value = 0; reason.value = ''
  operationId.value = newOperationId(); quotaDialog.value = true
}
async function saveQuota() {
  if (quotaProblem.value || quotaUnchanged.value) return
  saving.value = true
  try {
    await tenantsApi.quota(selectedId.value, {
      quota_total: fromMicro(quotaAfter.value).toFixed(6), reason: reason.value.trim(), operation_id: operationId.value,
    })
    quotaDialog.value = false; await load()
  } catch (e) { failure(e) } finally { saving.value = false }
}
function showPassword(title: string, username: string, password: string | null, hint: string) {
  if (!password) return
  issued.value = { open: true, title, username, password, hint }
}
async function resetPassword(row: any) {
  try {
    await ElMessageBox.confirm(t('tenants.resetConfirm', { name: row.username }), t('tenants.resetPassword'), {
      type: 'warning', confirmButtonText: t('tenants.resetPassword'), cancelButtonText: t('common.cancel'),
    })
  } catch { return }
  try {
    const res = await tenantsApi.password(row.id)
    showPassword(t('tenants.resetPassword'), row.username, res.temporary_password, t('tenants.resetDone'))
  } catch (e) { failure(e) }
}
onMounted(async () => {
  await load()
  try { models.value = (await modelsApi.list()).items.map((m: any) => m.model) } catch { /* form accepts model names */ }
})
</script>

<style scoped>
.quota-after {
  font-size: 18px;
}

.quota-bad {
  color: var(--el-color-danger);
}
</style>
