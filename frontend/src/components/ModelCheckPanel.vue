<template>
  <el-drawer v-model="visible" :title="model.model" size="min(740px, 100%)" @closed="history = []; historyTotal = 0">
    <p class="intro">{{ t('probe.intro') }}</p>
    <el-form label-position="top">
      <el-form-item :label="t('logs.channel')">
        <el-select v-model="channelId" style="width:100%" :disabled="Boolean(busy)" @change="reloadHistory"><el-option v-for="channel in model.channels" :key="channel.id" :value="channel.id" :label="channel.name" /></el-select>
      </el-form-item>
    </el-form>
    <div v-if="channel" class="channel-info">
      <p>{{ t('probe.actualModel') }} <code>{{ channel.actual_model }}</code></p>
      <p>{{ t('channels.priceMultiplier') }} ×{{ channel.price_multiplier }}<template v-if="channel.pricing_source === 'channel'"> · {{ t('logs.source_channel') }}</template></p>
    </div>
    <el-alert :title="t('probe.limitations')" type="info" :closable="false" show-icon />
    <div class="probe-actions">
      <el-button type="primary" :loading="busy === 'health'" :disabled="Boolean(busy) || !channel?.health_supported" @click="run('health')">{{ t('probe.healthCheck') }}</el-button>
      <el-button :loading="busy === 'capability'" :disabled="Boolean(busy) || !channel?.capability_supported" @click="run('capability')">{{ t('probe.capabilityCheck') }}</el-button>
    </div>
    <p class="intro">{{ busy ? t('probe.running') : t('probe.costHint') }}</p>
    <p v-if="!channel?.capability_supported" class="intro">{{ t('probe.onlySupported') }}</p>
    <p v-if="channel" class="intro">{{ t('probe.nextHealth') }} {{ when(channel.next_health_at) }} · {{ t('probe.nextCapability') }} {{ channel.capability_supported ? when(channel.next_capability_at) : t('probe.onlyGptClaude') }}</p>
    <div class="history-head">
      <h4>{{ t('probe.history') }}</h4>
      <el-radio-group v-model="kindFilter" size="small" @change="reloadHistory">
        <el-radio-button value="">{{ t('probe.filterAll') }}</el-radio-button>
        <el-radio-button value="health">{{ t('probe.kindHealth') }}</el-radio-button>
        <el-radio-button value="capability">{{ t('probe.kindCapability') }}</el-radio-button>
      </el-radio-group>
    </div>
    <el-table :data="history" v-loading="loading" size="small" row-key="id" :row-class-name="rowClass" :empty-text="t('probe.noHistory')">
      <el-table-column type="expand" width="32">
        <template #default="{ row }">
          <div class="probe-detail">
            <p v-if="row.error" class="probe-error">{{ row.error }}</p>
            <div v-for="check in row.checks" :key="check.name" class="check-line">
              <el-tag :type="check.passed ? 'success' : 'warning'" size="small">{{ check.passed ? t('probe.passed') : t('probe.review') }}</el-tag>
              <span>{{ check.name }}</span>
              <code>{{ check.actual }}</code>
            </div>
            <p class="detail-meta">{{ row.actual_model }} · {{ row.suite_version }}</p>
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="t('probe.colTime')" min-width="150">
        <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
      </el-table-column>
      <el-table-column :label="t('probe.colKind')" width="70">
        <template #default="{ row }">{{ row.kind === 'health' ? t('probe.kindHealth') : t('probe.kindCapability') }}</template>
      </el-table-column>
      <el-table-column :label="t('probe.colResult')" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="['healthy', 'passed'].includes(row.status) ? 'success' : row.status === 'review' ? 'warning' : 'danger'">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('probe.colLatency')" width="80" align="right">
        <template #default="{ row }">{{ row.latency_ms }} ms</template>
      </el-table-column>
      <el-table-column :label="t('probe.colScore')" width="64" align="right">
        <template #default="{ row }">{{ row.score ?? '—' }}</template>
      </el-table-column>
      <el-table-column :label="t('probe.colSource')" width="80">
        <template #default="{ row }">{{ row.run_source === 'scheduled' ? t('probe.scheduled') : t('probe.manual') }}</template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="historyTotal > pageSize" v-model:current-page="historyPage" class="history-pager" small background
      layout="total, prev, pager, next" :page-size="pageSize" :total="historyTotal" @current-change="loadHistory" />
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { modelsApi } from '@/api/models'
import { useI18n } from '@/i18n'
const props = defineProps<{ model: any }>()
const emit = defineEmits<{ updated: [] }>()
const visible = defineModel<boolean>({ default: false })
const { t } = useI18n()
const channelId = ref<number>(), history = ref<any[]>([]), loading = ref(false), busy = ref('')
const pageSize = 10
const historyPage = ref(1), historyTotal = ref(0), kindFilter = ref<'' | 'health' | 'capability'>('')
const channel = computed(() => props.model.channels.find((entry: any) => entry.id === channelId.value))
function when(value: string | null) { return value ? new Date(value).toLocaleString() : t('probe.awaiting') }
const statusLabel = (state: 'healthy' | 'passed' | 'review' | 'unavailable') => t(`probe.${state}`)
let sequence = 0
async function loadHistory() {
  if (!channelId.value) return
  const ticket = ++sequence
  loading.value = true
  try {
    const data = await modelsApi.probes(channelId.value, props.model.model, historyPage.value, kindFilter.value)
    if (ticket === sequence) {
      history.value = data.items
      historyTotal.value = data.total
    }
  } catch { ElMessage.error(t('models.loadFailed')) } finally { if (ticket === sequence) loading.value = false }
}
function reloadHistory() {
  historyPage.value = 1
  return loadHistory()
}
function rowClass({ row }: { row: any }) {
  return row.error || row.checks?.length ? '' : 'no-detail'
}
async function run(kind: 'health' | 'capability') {
  if (!channelId.value || busy.value) return
  busy.value = kind
  const model = props.model.model, id = channelId.value
  try {
    await modelsApi.probe(id, model, kind)
    if (model === props.model.model && id === channelId.value) await reloadHistory()
    emit('updated')
  } catch (error: any) { ElMessage.error(typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : t('probe.failed')) }
  finally { busy.value = '' }
}
watch(() => [visible.value, props.model.model], () => {
  if (visible.value) {
    channelId.value = props.model.channels[0]?.id
    kindFilter.value = ''
    reloadHistory()
  }
}, { immediate: true })
</script>

<style scoped>
.intro { color: #86909c; font-size: 12px; line-height: 1.6; margin: 8px 0 18px; }
.channel-info { background: #f7f8fa; border: 1px solid #edf0f3; border-radius: 8px; padding: 8px 14px; margin-bottom: 18px; font-size: 13px; }
.channel-info p { margin: 8px 0; } .probe-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 20px; }
.probe-actions :deep(.el-button + .el-button) { margin-left: 0; }
.history-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin: 24px 0 12px; }
h4 { margin: 0; font-size: 14px; }
.probe-detail { padding: 4px 16px 8px 40px; }
.detail-meta { margin: 10px 0 0; color: #86909c; font-size: 12px; }
.history-pager { margin-top: 12px; justify-content: flex-end; }
:deep(.no-detail .el-table__expand-icon) { visibility: hidden; pointer-events: none; }
.check-line { display: flex; gap: 8px; margin-top: 10px; align-items: flex-start; flex-wrap: wrap; font-size: 12px; }
.check-line code { overflow-wrap: anywhere; white-space: pre-wrap; line-height: 1.6; flex: 1; min-width: 120px; }
.probe-error { margin: 0 0 6px; color: #c83c3c; font-size: 13px; overflow-wrap: anywhere; }
</style>
