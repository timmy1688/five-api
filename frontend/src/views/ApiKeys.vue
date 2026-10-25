<template>
  <div>
    <div class="page-header">
      <div><h3>{{ t('nav.keys') }}</h3><p>{{ t('keys.scopeHint') }}</p></div>
      <el-button type="primary" @click="openCreate">{{ t('keys.create') }}</el-button>
    </div>
    <el-card v-if="summary" shadow="never" style="margin-bottom: 16px">
      <p>{{ t('tenants.sharedLimits') }}：{{ summary.rpm_limit }} / {{ summary.tpm_limit }} / {{ summary.concurrent_limit }}</p>
      <el-descriptions :column="4">
        <el-descriptions-item :label="t('tenants.total')">{{ money(summary.quota_total) }}</el-descriptions-item>
        <el-descriptions-item :label="t('keys.used')">{{ money(summary.quota_used) }}</el-descriptions-item>
        <el-descriptions-item :label="t('keys.occupied')">{{ money(summary.quota_occupied) }}</el-descriptions-item>
        <el-descriptions-item :label="t('keys.remain')">{{ money(summary.quota_remaining) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
    <el-card shadow="never">
      <el-table :data="keys" v-loading="loading" stripe>
        <el-table-column prop="name" :label="t('common.name')" min-width="140" />
        <el-table-column :label="t('keys.prefix')" min-width="130">
          <template #default="{ row }"><code>{{ row.key_prefix }}••••••</code></template>
        </el-table-column>
        <el-table-column v-if="auth.isPlatformAdmin" :label="t('nav.tenants')" min-width="120"><template #default="{ row }">{{ row.tenant_is_system ? t('keys.platformOwn') : row.tenant_name }}</template></el-table-column>
        <el-table-column :label="t('keys.quota')" min-width="180">
          <template #default="{ row }">
            {{ money(row.quota_used) }} / {{ row.quota_total === -1 ? t('keys.shared') : money(row.quota_total) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('common.enabled')" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.is_revoked" type="info">{{ t('keys.revoked') }}</el-tag>
            <el-switch v-else v-model="row.is_enabled" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="210" fixed="right">
          <template #default="{ row }">
            <el-button text @click="detail(row)">{{ t('common.view') }}</el-button>
            <el-button v-if="!row.is_revoked" text type="primary" @click="edit(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm v-if="!row.is_revoked" :title="t('keys.revokeConfirm')" @confirm="revoke(row.id)">
              <template #reference><el-button text type="danger">{{ t('keys.revoke') }}</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-if="total" :current-page="page" :page-size="20" :total="total"
        layout="total, prev, pager, next" @current-change="(p: number) => { page = p; load() }" />
    </el-card>

    <el-dialog v-model="dialog" :title="editingId ? t('keys.edit') : t('keys.create')" width="540px">
      <el-alert v-if="auth.isPlatformAdmin && !editingId" :title="t('keys.platformOwnHint')" type="info" :closable="false" style="margin-bottom:16px" />
      <el-form label-width="130px">
        <el-form-item :label="t('common.name')" required><el-input v-model="form.name" maxlength="128" /></el-form-item>
        <el-form-item :label="t('keys.quota')">
          <el-input-number v-model="form.quota_total" :min="-1" :precision="6" />
          <div>{{ t('keys.sharedHint') }}</div>
        </el-form-item>
        <el-form-item :label="t('keys.allowedModels')">
          <el-select v-model="form.allowed_models" multiple filterable allow-create style="width: 100%">
            <el-option v-for="model in availableModels" :key="model" :label="model" :value="model" />
          </el-select>
          <div>{{ t('keys.modelsHint') }}</div>
        </el-form-item>
        <el-form-item :label="t('keys.expires')">
          <el-date-picker v-model="form.expires_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" clearable />
        </el-form-item>
        <el-collapse>
          <el-collapse-item :title="t('keys.advanced')" name="advanced">
            <el-form-item :label="t('keys.concurrencyLabel')"><el-input-number v-model="form.concurrent_limit" :min="1" :max="1000" /></el-form-item>
            <el-form-item :label="t('keys.rpmLabel')"><el-input-number v-model="form.rpm_limit" :min="-1" /></el-form-item>
            <el-form-item :label="t('keys.tpmLabel')"><el-input-number v-model="form.tpm_limit" :min="-1" /></el-form-item>
            <el-form-item :label="t('keys.allowedIps')">
              <el-select v-model="form.allowed_ips" multiple filterable allow-create style="width: 100%" />
            </el-form-item>
            <template v-if="auth.isPlatformAdmin && editingId">
              <el-form-item :label="t('keys.modelGroup')">
                <el-select v-model="platform.model_group_id" clearable>
                  <el-option v-for="group in groups" :key="group.id" :label="group.name" :value="group.id" />
                </el-select>
              </el-form-item>
              <el-form-item :label="t('keys.resetDay')"><el-input-number v-model="platform.quota_reset_day" :min="1" :max="31" :value-on-clear="null" /></el-form-item>
              <el-form-item :label="t('windows.label')"><WindowLimitsInput v-model="platform.window_limits" /></el-form-item>
              <el-form-item :label="t('keys.auditLabel')"><el-switch v-model="platform.audit_policy" active-value="on" inactive-value="off" /></el-form-item>
            </template>
          </el-collapse-item>
        </el-collapse>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showRaw" :title="t('keys.createdTitle')" :close-on-click-modal="false" @closed="raw = ''">
      <el-alert type="warning" :closable="false" :title="t('keys.createdHint')" style="margin-bottom: 16px" />
      <el-input :model-value="raw" readonly><template #append><el-button @click="copy">{{ t('keys.copy') }}</el-button></template></el-input>
    </el-dialog>

    <el-drawer v-model="showDetail" :title="selected?.name || t('keys.detail')" size="640px">
      <template v-if="selected">
        <el-descriptions :column="2" border>
          <el-descriptions-item :label="t('keys.used')">{{ money(selected.quota_used) }}</el-descriptions-item>
          <el-descriptions-item :label="t('keys.occupied')">{{ money(selected.quota_occupied) }}</el-descriptions-item>
          <el-descriptions-item :label="t('keys.remain')">{{ money(selected.quota_remaining) }}</el-descriptions-item>
          <el-descriptions-item :label="t('keys.expires')">{{ selected.expires_at || t('common.never') }}</el-descriptions-item>
          <el-descriptions-item :label="t('keys.allowedModels')">{{ selected.allowed_models.join(', ') || t('keys.modelsHint') }}</el-descriptions-item>
          <el-descriptions-item :label="t('keys.allowedIps')">{{ selected.allowed_ips.join(', ') || '-' }}</el-descriptions-item>
        </el-descriptions>
        <p>{{ t('keys.recentUsage') }}</p>
        <el-table :data="usage">
          <el-table-column prop="request_id" label="ID" min-width="130" show-overflow-tooltip />
          <el-table-column prop="model_requested" :label="t('keys.allowedModels')" min-width="120" />
          <el-table-column prop="status_code" label="HTTP" width="70" />
          <el-table-column prop="total_tokens" label="Tokens" width="80" />
          <el-table-column label="USD" width="100"><template #default="{ row }">{{ money(row.cost) }}</template></el-table-column>
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { keysApi } from '@/api/keys'
import { modelGroupsApi } from '@/api/model_groups'
import { modelsApi } from '@/api/models'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'
import { useRoute } from 'vue-router'
import WindowLimitsInput from '@/components/WindowLimitsInput.vue'

const auth = useAuthStore()
const route = useRoute()
const { t } = useI18n()
const keys = ref<any[]>([]), groups = ref<any[]>([])
const summary = ref<any>(null), selected = ref<any>(null), usage = ref<any[]>([])
const availableModels = ref<string[]>([])
const page = ref(1), total = ref(0), editingId = ref<number | null>(null)
const loading = ref(false), saving = ref(false), dialog = ref(false), showRaw = ref(false), showDetail = ref(false)
const raw = ref('')
const defaults = () => ({ name: '', quota_total: -1, allowed_models: [] as string[], allowed_ips: [] as string[],
  expires_at: null as string | null, concurrent_limit: 5, rpm_limit: -1, tpm_limit: -1 })
const platformDefaults = () => ({ model_group_id: null as number | null, quota_reset_day: null as number | null,
  window_limits: {} as Record<string, number>, audit_policy: 'off' })
const form = ref(defaults()), platform = ref(platformDefaults())
const money = (value: any) => Number(value) === -1 ? t('common.unlimited') : '$' + Number(value || 0).toFixed(6)

async function load() {
  loading.value = true
  try {
    const res = await keysApi.list(page.value)
    keys.value = res.items; total.value = res.total
    if (!auth.isPlatformAdmin) {
      summary.value = await keysApi.summary()
      availableModels.value = summary.value.allowed_models
    }
  } catch { ElMessage.error(t('keys.loadFailed')) } finally { loading.value = false }
}
function openCreate() {
  editingId.value = null; form.value = defaults(); platform.value = platformDefaults(); dialog.value = true
}
function edit(row: any) {
  editingId.value = row.id
  form.value = Object.fromEntries(Object.keys(defaults()).map(key => [key, row[key] ?? (defaults() as any)[key]])) as ReturnType<typeof defaults>
  platform.value = { model_group_id: row.model_group_id, quota_reset_day: row.quota_reset_day,
    window_limits: { ...row.window_limits }, audit_policy: row.audit_policy }
  dialog.value = true
}
async function save() {
  saving.value = true
  try {
    const data = { ...form.value, ...(auth.isPlatformAdmin && editingId.value ? platform.value : {}) }
    if (editingId.value) await keysApi.update(editingId.value, data)
    else {
      const res = await keysApi.create(data)
      raw.value = res.key; showRaw.value = true
    }
    dialog.value = false
    await load()
  } catch (e: any) { ElMessage.error(typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : t('common.saveFailed')) }
  finally { saving.value = false }
}
async function toggle(row: any) {
  try { await keysApi.update(row.id, { is_enabled: row.is_enabled }) }
  catch { row.is_enabled = !row.is_enabled; ElMessage.error(t('common.updateFailed')) }
}
async function revoke(id: number) {
  try { await keysApi.remove(id); await load() } catch { ElMessage.error(t('common.deleteFailed')) }
}
async function detail(row: any) {
  selected.value = row; usage.value = []; showDetail.value = true
  try { usage.value = (await keysApi.usage(row.id)).items } catch { ElMessage.error(t('keys.loadFailed')) }
}
async function copy() {
  try { await navigator.clipboard.writeText(raw.value); ElMessage.success(t('common.copied')) }
  catch { ElMessage.error(t('keys.copyManual')) }
}
onMounted(async () => {
  await load()
  if (route.query.create === '1') openCreate()
  if (auth.isPlatformAdmin) {
    const results = await Promise.allSettled([modelGroupsApi.listAll(), modelsApi.list()])
    if (results[0].status === 'fulfilled') groups.value = results[0].value
    if (results[1].status === 'fulfilled') availableModels.value = results[1].value.items.map((m: any) => m.model)
  }
})
onUnmounted(() => { raw.value = '' })
</script>
