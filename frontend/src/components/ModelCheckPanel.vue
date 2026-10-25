<template>
  <el-drawer v-model="visible" :title="model.model" size="min(740px, 100%)" @closed="history = []">
    <p class="intro">{{ t('probe.intro') }}</p>
    <el-form label-position="top">
      <el-form-item :label="t('logs.channel')">
        <el-select v-model="channelId" style="width:100%" :disabled="Boolean(busy)" @change="loadHistory"><el-option v-for="channel in model.channels" :key="channel.id" :value="channel.id" :label="channel.name" /></el-select>
      </el-form-item>
    </el-form>
    <div v-if="channel" class="channel-info">
      <p>{{ t('probe.actualModel') }} <code>{{ channel.actual_model }}</code></p>
      <p>{{ t('prices.multiplier') }} ×{{ channel.multiplier ?? '—' }} · {{ t('channels.costMultiplier') }} ×{{ channel.cost_multiplier }}</p>
    </div>
    <el-alert :title="t('probe.limitations')" type="info" :closable="false" show-icon />
    <div class="probe-actions">
      <el-button type="primary" :loading="busy === 'health'" :disabled="Boolean(busy) || !channel?.health_supported" @click="run('health')">{{ t('probe.healthCheck') }}</el-button>
      <el-button :loading="busy === 'capability'" :disabled="Boolean(busy) || !channel?.capability_supported" @click="run('capability')">{{ t('probe.capabilityCheck') }}</el-button>
    </div>
    <p class="intro">{{ busy ? t('probe.running') : t('probe.costHint') }}</p>
    <p v-if="!channel?.capability_supported" class="intro">{{ t('probe.onlySupported') }}</p>
    <p v-if="channel" class="intro">{{ t('probe.nextHealth') }} {{ when(channel.next_health_at) }} · {{ t('probe.nextCapability') }} {{ channel.capability_supported ? when(channel.next_capability_at) : t('probe.onlyGptClaude') }}</p>
    <h4>{{ t('probe.history') }}</h4>
    <div v-loading="loading">
      <el-empty v-if="!history.length && !loading" :image-size="60" :description="t('probe.noHistory')" />
      <article v-for="record in history" :key="record.id" class="probe-result">
        <div class="result-head"><strong>{{ record.kind === 'health' ? t('probe.healthCheck') : t('probe.capabilityCheck') }}</strong><el-tag :type="['healthy','passed'].includes(record.status) ? 'success' : record.status === 'review' ? 'warning' : 'danger'">{{ statusLabel(record.status) }}</el-tag></div>
        <p class="intro">{{ new Date(record.created_at).toLocaleString() }} · {{ record.latency_ms }} ms <template v-if="record.score !== null"> · {{ record.score }}/100</template> · {{ record.suite_version }} · {{ record.run_source === 'scheduled' ? t('probe.scheduled') : t('probe.manual') }}</p>
        <p v-if="record.error" class="probe-error">{{ record.error }}</p>
        <div v-for="check in record.checks" :key="check.name" class="check-line"><el-tag :type="check.passed ? 'success' : 'warning'" size="small">{{ check.passed ? t('probe.passed') : t('probe.review') }}</el-tag><span>{{ check.name }}</span><code>{{ check.actual }}</code></div>
      </article>
    </div>
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
const channel = computed(() => props.model.channels.find((entry: any) => entry.id === channelId.value))
function when(value: string | null) { return value ? new Date(value).toLocaleString() : t('probe.awaiting') }
const statusLabel = (state: 'healthy' | 'passed' | 'review' | 'unavailable') => t(`probe.${state}`)
let sequence = 0
async function loadHistory() {
  if (!channelId.value) return
  const ticket = ++sequence
  loading.value = true
  try {
    const data = await modelsApi.probes(channelId.value, props.model.model)
    if (ticket === sequence) history.value = data.items
  } catch { ElMessage.error(t('models.loadFailed')) } finally { if (ticket === sequence) loading.value = false }
}
async function run(kind: 'health' | 'capability') {
  if (!channelId.value || busy.value) return
  busy.value = kind
  const model = props.model.model, id = channelId.value
  try {
    await modelsApi.probe(id, model, kind)
    if (model === props.model.model && id === channelId.value) await loadHistory()
    emit('updated')
  } catch (error: any) { ElMessage.error(typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : t('probe.failed')) }
  finally { busy.value = '' }
}
watch(() => [visible.value, props.model.model], () => {
  if (visible.value) { channelId.value = props.model.channels[0]?.id; loadHistory() }
}, { immediate: true })
</script>

<style scoped>
.intro { color: #86909c; font-size: 12px; line-height: 1.6; margin: 8px 0 18px; }
.channel-info { background: #f7f8fa; border: 1px solid #edf0f3; border-radius: 8px; padding: 8px 14px; margin-bottom: 18px; font-size: 13px; }
.channel-info p { margin: 8px 0; } .probe-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 20px; }
.probe-actions :deep(.el-button + .el-button) { margin-left: 0; }
h4 { margin: 24px 0 16px; font-size: 14px; }
.probe-result { padding: 16px; border: 1px solid #e6e9ef; border-radius: 8px; margin-bottom: 12px; }
.result-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; font-size: 13px; }
.check-line { display: flex; gap: 8px; margin-top: 10px; align-items: flex-start; flex-wrap: wrap; font-size: 12px; }
.check-line code { overflow-wrap: anywhere; white-space: pre-wrap; line-height: 1.6; flex: 1; min-width: 120px; }
.probe-error { color: #c83c3c; font-size: 13px; }
</style>
