<template>
  <el-dialog
    :model-value="modelValue" :title="t('channels.checkTitle', { name: channel?.name || '' })"
    width="min(1100px, 95vw)" top="5vh" :close-on-click-modal="false"
    :close-on-press-escape="!running" :show-close="!running"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <p class="check-hint">{{ t('channels.checkHint') }}</p>
    <el-form label-position="top">
      <el-form-item :label="t('channels.checkModels')">
        <el-select v-model="selectedModels" multiple filterable :multiple-limit="5" :disabled="running" style="width:100%">
          <el-option v-for="model in availableModels" :key="model" :value="model" :label="model" />
        </el-select>
      </el-form-item>
    </el-form>
    <el-alert v-if="!availableModels.length" :title="t('channels.checkNoModels')" type="info" :closable="false" />
    <p v-if="running" role="status">
      {{ t('channels.checkProgress', { model: runningModel, current: currentIndex, total: batchSize }) }}
    </p>
    <p v-else-if="results.length" role="status">
      {{ t(skippedCount ? 'channels.checkSummarySkipped' : 'channels.checkSummary', { passed: passedCount, total: checkedCount, skipped: skippedCount }) }}
    </p>
    <el-table v-if="results.length" :data="results" max-height="480" stripe class="check-table">
      <el-table-column :label="t('common.model')" min-width="145" show-overflow-tooltip>
        <template #default="{ row }">
          <div>{{ row.model }}</div>
          <small v-if="row.actualModel !== row.model" class="muted">→ {{ row.actualModel }}</small>
        </template>
      </el-table-column>
      <el-table-column :label="t('channels.checkItem')" min-width="145">
        <template #default="{ row }">{{ t(kindLabels[row.kind as ChannelCheckKind]) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.status')" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ t(statusLabels[row.status as CheckStatus]) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="HTTP" width="70">
        <template #default="{ row }">{{ row.status_code ?? '—' }}</template>
      </el-table-column>
      <el-table-column :label="t('channels.checkLatency')" width="100">
        <template #default="{ row }">{{ finished(row.status) ? `${row.latency_ms} ms` : '—' }}</template>
      </el-table-column>
      <el-table-column :label="t('channels.checkDetails')" min-width="240">
        <template #default="{ row }">
          <span v-if="row.error" class="check-error">{{ row.error }}</span>
          <span v-else-if="row.skip_reason === 'models_endpoint_unavailable'" class="check-skipped">{{ t('channels.checkModelsUnavailable', { code: row.status_code }) }}</span>
          <span v-else-if="row.first_text_ms != null">{{ t('channels.checkFirstText', { ms: row.first_text_ms }) }}</span>
          <span v-else-if="row.status === 'passed'">{{ t('channels.checkValidResponse') }}</span>
          <span v-else>—</span>
        </template>
      </el-table-column>
    </el-table>
    <div v-if="results.length" class="check-cards">
      <article v-for="row in results" :key="`${row.model}:${row.kind}`" class="check-card">
        <div class="check-card-head">
          <strong>{{ row.model }} · {{ t(kindLabels[row.kind]) }}</strong>
          <el-tag :type="statusType(row.status)" size="small">{{ t(statusLabels[row.status]) }}</el-tag>
        </div>
        <div v-if="finished(row.status)" class="muted">
          HTTP {{ row.status_code ?? '—' }} · {{ row.latency_ms }} ms
          <template v-if="row.first_text_ms != null"> · {{ t('channels.checkFirstText', { ms: row.first_text_ms }) }}</template>
        </div>
        <div v-if="row.error" class="check-error">{{ row.error }}</div>
        <div v-else-if="row.skip_reason === 'models_endpoint_unavailable'" class="check-skipped">{{ t('channels.checkModelsUnavailable', { code: row.status_code ?? '—' }) }}</div>
        <small v-if="row.actualModel !== row.model" class="muted">→ {{ row.actualModel }}</small>
      </article>
    </div>
    <template #footer>
      <el-button v-if="running" :disabled="stopRequested" @click="stopRequested = true">
        {{ t(stopRequested ? 'channels.checkStopping' : 'channels.checkStop') }}
      </el-button>
      <el-button v-else @click="emit('update:modelValue', false)">{{ t('channels.checkClose') }}</el-button>
      <el-button type="primary" :loading="running" :disabled="!selectedModels.length || running" @click="runChecks">
        {{ t('channels.checkRun') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { channelsApi, type ChannelCheckKind, type ChannelCheckResult } from '@/api/channels'
import { useI18n } from '@/i18n'
import type { MessageKey } from '@/i18n/messages'

interface TestChannel {
  id: number
  name: string
  provider: string
  models: string[]
  model_mapping: Record<string, string>
}

const props = defineProps<{ modelValue: boolean; channel: TestChannel | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const { t } = useI18n()
type CheckStatus = ChannelCheckResult['status'] | 'pending' | 'running' | 'not_run'
type ResultRow = Omit<ChannelCheckResult, 'status'> & { model: string; actualModel: string; status: CheckStatus }
const selectedModels = ref<string[]>([])
const results = ref<ResultRow[]>([])
const running = ref(false)
const stopRequested = ref(false)
const runningModel = ref('')
const currentIndex = ref(0)
const batchSize = ref(0)
const availableModels = computed(() => (props.channel?.models || []).filter((model) => {
  const actual = (props.channel?.model_mapping?.[model] || model).toLowerCase()
  return !['embedding', 'whisper', 'tts', 'sora', 'dall-e', 'image', 'rerank'].some(word => actual.includes(word))
}))
const passedCount = computed(() => results.value.filter(row => row.status === 'passed').length)
const checkedCount = computed(() => results.value.filter(row => finished(row.status) && row.status !== 'skipped').length)
const skippedCount = computed(() => results.value.filter(row => row.status === 'skipped').length)

const kindLabels: Record<ChannelCheckKind, MessageKey> = {
  models: 'channels.checkModelsList', chat: 'channels.checkChat', chat_stream: 'channels.checkChatStream',
  responses: 'channels.checkResponses', responses_stream: 'channels.checkResponsesStream',
  messages: 'channels.checkMessages', messages_stream: 'channels.checkMessagesStream',
}
const statusLabels: Record<CheckStatus, MessageKey> = {
  passed: 'channels.checkPassed', failed: 'channels.checkFailed', timeout: 'channels.checkTimeout',
  pending: 'channels.checkPending', running: 'channels.checkRunning', not_run: 'channels.checkNotRun',
  skipped: 'channels.checkSkipped',
}
function statusType(status: CheckStatus) {
  return status === 'passed' ? 'success' : status === 'failed' ? 'danger' : ['timeout', 'skipped'].includes(status) ? 'warning' : 'info'
}
function finished(status: CheckStatus) {
  return status === 'passed' || status === 'failed' || status === 'timeout' || status === 'skipped'
}

watch(() => props.modelValue, (visible) => {
  if (!visible) return
  selectedModels.value = availableModels.value.slice(0, 1)
  results.value = []
  stopRequested.value = false
})

async function runChecks() {
  const channel = props.channel
  if (!channel || running.value || !selectedModels.value.length) return
  const models = [...selectedModels.value]
  const kinds: ChannelCheckKind[] = channel.provider === 'anthropic'
    ? ['models', 'messages', 'messages_stream']
    : ['models', 'chat', 'chat_stream', 'responses', 'responses_stream']
  results.value = models.flatMap(model => kinds.map(kind => ({
    model, actualModel: channel.model_mapping?.[model] || model, kind, status: 'pending' as const,
    status_code: null, latency_ms: 0, first_text_ms: null, error: '',
  })))
  running.value = true
  stopRequested.value = false
  batchSize.value = models.length
  try {
    for (const [index, model] of models.entries()) {
      if (stopRequested.value) break
      currentIndex.value = index + 1
      runningModel.value = model
      for (const row of results.value.filter(row => row.model === model)) row.status = 'running'
      try {
        const response = await channelsApi.test(channel.id, model)
        const offset = results.value.findIndex(row => row.model === model)
        results.value.splice(offset, kinds.length, ...response.checks.map(check => ({
          ...check, model, actualModel: response.actual_model,
        })))
      } catch (error: any) {
        const detail = error?.response?.data?.detail
        const message = typeof detail === 'string' ? detail : t('channels.testRequestFailed')
        for (const row of results.value.filter(row => row.model === model)) {
          row.status = 'failed'
          row.error = message
        }
        if ([401, 403, 429].includes(error?.response?.status)) stopRequested.value = true
      }
    }
  } finally {
    for (const row of results.value) if (row.status === 'pending') row.status = 'not_run'
    running.value = false
  }
}
</script>

<style scoped>
.check-hint { color: #606266; line-height: 1.6; margin: 0 0 18px; }
.check-error { color: #c45656; overflow-wrap: anywhere; white-space: pre-wrap; }
.check-skipped { color: #8a6500; }
.muted { color: #86909c; }
.check-cards { display: none; }
@media (max-width: 600px) {
  .check-table { display: none; }
  .check-cards { display: grid; gap: 8px; max-height: 43vh; overflow: auto; }
  .check-card { border: 1px solid #ebeef5; border-radius: 6px; padding: 10px; font-size: 12px; line-height: 1.6; }
  .check-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
  .check-card-head strong { overflow-wrap: anywhere; }
  .check-card-head .el-tag { flex-shrink: 0; }
}
</style>
