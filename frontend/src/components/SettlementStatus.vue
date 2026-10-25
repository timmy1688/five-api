<template>
  <el-card shadow="never">
    <div class="recovery-head"><div><h4>{{ t('settlements.title') }}</h4><p class="hint">{{ t('settlements.hint') }}</p></div><el-button :loading="loading" @click="load">{{ t('settlements.refresh') }}</el-button></div>
    <div class="recovery-summary">
      <button v-for="value in statuses.slice(0, 3)" :key="value" class="status-card" :class="[value, { selected: state === value }]" @click="filter(value)">
        <span>{{ stateLabel(value) }}</span><strong>{{ counts[value] || 0 }}</strong>
      </button>
    </div>
    <el-radio-group :model-value="state" @change="(value: string | number | boolean | undefined) => filter(value as State)" class="state-filters">
      <el-radio-button v-for="value in statuses" :key="value" :value="value">{{ stateLabel(value) }}</el-radio-button>
    </el-radio-group>
    <el-table :data="items" v-loading="loading">
      <el-table-column prop="request_id" label="Request ID" min-width="180" show-overflow-tooltip />
      <el-table-column prop="tenant_id" :label="t('nav.tenants')" width="100" />
      <el-table-column :label="t('settlements.state')" width="110"><template #default="{ row }"><el-tag :type="row.state === 'failed' ? 'danger' : row.state === 'uncertain' ? 'warning' : 'info'">{{ stateLabel(row.state) }}</el-tag></template></el-table-column>
      <el-table-column :label="t('keys.occupied')" width="110"><template #default="{ row }">${{ Number(row.occupied).toFixed(6) }}</template></el-table-column>
      <el-table-column prop="last_error" :label="t('settlements.error')" min-width="160" show-overflow-tooltip />
      <el-table-column :label="t('common.actions')" width="210" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.cost !== null && ['pending','failed'].includes(row.state)" text type="primary" @click="retry(row)">{{ t('settlements.retry') }}</el-button>
          <template v-if="['failed','uncertain'].includes(row.state)">
            <el-button text @click="resolve(row, 'release')">{{ t('settlements.release') }}</el-button>
            <el-button v-if="row.cost === null" text type="warning" @click="resolve(row, 'charge_estimate')">{{ t('settlements.charge') }}</el-button>
          </template>
        </template>
      </el-table-column>
      <template #empty><el-empty :image-size="70" :description="t('settlements.empty')" /></template>
    </el-table>
    <el-pagination v-if="total > 20" :current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="(value: number) => { page = value; load() }" />
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import client from '@/api/client'
import { useI18n } from '@/i18n'
const { t } = useI18n()
const props = defineProps<{ initialState?: string }>()
const items = ref<any[]>([]), counts = ref<any>({}), state = ref(props.initialState || 'pending'), loading = ref(false)
const page = ref(1), total = ref(0)
const statuses = ['pending', 'failed', 'uncertain', 'reserved'] as const
type State = typeof statuses[number]
const stateLabel = (value: State) => t(`settlements.${value}`)
function filter(value: State) { state.value = value; page.value = 1; load() }
async function load() {
  loading.value = true
  try {
    const { data } = await client.get('/settlements', { params: { state: state.value, page: page.value, size: 20 } })
    items.value = data.items; counts.value = data.counts; total.value = data.total
  } catch { ElMessage.error(t('common.saveFailed')) } finally { loading.value = false }
}
async function retry(row: any) {
  try { await client.post(`/settlements/${row.id}/retry`); await load() }
  catch (error: any) { ElMessage.error(error?.response?.data?.detail || t('common.saveFailed')) }
}
async function resolve(row: any, action: 'release' | 'charge_estimate') {
  try {
    const { value } = await ElMessageBox.prompt(t(action === 'release' ? 'settlements.releaseHint' : 'settlements.chargeHint'),
      t('settlements.reason'), { inputValidator: text => Boolean(text?.trim()), inputType: 'textarea' })
    await client.post(`/settlements/${row.id}/resolve`, { action, reason: value })
    await load()
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error?.response?.data?.detail || t('common.saveFailed'))
  }
}
onMounted(load)
</script>

<style scoped>
.recovery-head { display: flex; gap: 16px; justify-content: space-between; align-items: flex-start; }
h4 { margin: 0; font-size: 15px; color: #1c1f23; }
.hint { margin: 8px 0 0; color: #646a73; line-height: 1.6; font-size: 13px; }
.recovery-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 22px 0; }
.status-card { text-align: left; padding: 16px; border: 1px solid #e5e9ef; border-radius: 8px; background: #fafbfc; cursor: pointer; color: #646a73; }
.status-card strong { display: block; margin-top: 8px; color: #1c1f23; font-size: 26px; font-weight: 600; }
.status-card.selected { border-color: #92beed; background: #f3f8ff; }
.status-card.failed strong { color: #c83c3c; }
.status-card.uncertain strong { color: #b7791f; }
.state-filters { margin-bottom: 18px; }
@media (max-width: 600px) { .recovery-summary { gap: 8px; } .status-card { padding: 12px; } }
</style>
