<template>
  <el-card v-loading="loading" shadow="never" class="alerts-card">
    <div class="card-head">
      <div>
        <h4>{{ t('alerts.title') }}</h4>
        <p class="hint">{{ t('alerts.subtitle') }}</p>
      </div>
      <el-button v-if="canWrite" type="primary" :loading="saving" @click="save">{{ t('common.save') }}</el-button>
    </div>
    <el-form label-position="top" :disabled="!canWrite">
      <el-form-item :label="t('alerts.enabled')">
        <el-switch v-model="form.enabled" />
      </el-form-item>

      <el-form-item :label="t('alerts.webhooks')">
        <div class="hook-list">
          <div v-for="(hook, index) in form.webhooks" :key="hook.id || index" class="hook-row">
            <el-select v-model="hook.type" class="hook-type">
              <el-option v-for="type in types" :key="type" :label="t(`alerts.type_${type}` as 'alerts.type_feishu')" :value="type" />
            </el-select>
            <el-input v-model="hook.name" :placeholder="t('alerts.name')" class="hook-name" />
            <el-input v-model="hook.url" :placeholder="t('alerts.url')" class="hook-url" />
            <el-input
              v-if="hook.type === 'feishu' || hook.type === 'dingtalk'"
              v-model="hook.secret"
              type="password"
              show-password
              :placeholder="hook.has_secret ? t('alerts.secretKept') : t('alerts.secret')"
              class="hook-secret"
            />
            <el-button v-if="hook.id" text :loading="testing === hook.id" @click="test(hook.id)">{{ t('alerts.test') }}</el-button>
            <el-button text type="danger" @click="form.webhooks.splice(index, 1)">{{ t('common.delete') }}</el-button>
          </div>
          <el-button v-if="canWrite && form.webhooks.length < 10" plain size="small" @click="addHook">{{ t('alerts.add') }}</el-button>
        </div>
        <p class="hint">{{ t('alerts.webhooksHint') }}</p>
      </el-form-item>

      <el-form-item :label="t('alerts.events')">
        <div class="event-list">
          <div class="event-row">
            <el-checkbox v-model="form.events.budget">{{ t('alerts.budget') }}</el-checkbox>
            <el-input-number v-model="budgetPct" :min="10" :max="100" :step="5" size="small" />
            <span class="muted">%</span>
          </div>
          <div class="event-row">
            <el-checkbox v-model="form.events.channel">{{ t('alerts.channel') }}</el-checkbox>
          </div>
          <div class="event-row">
            <el-checkbox v-model="form.events.errors">{{ t('alerts.errors') }}</el-checkbox>
            <el-input-number v-model="errorPct" :min="5" :max="100" :step="5" size="small" />
            <span class="muted">% · {{ t('alerts.minRequests') }}</span>
            <el-input-number v-model="form.error_min_requests" :min="1" :max="10000" size="small" />
          </div>
        </div>
        <p class="hint">{{ t('alerts.eventsHint') }}</p>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { alertsApi, type AlertSettings, type WebhookType } from '@/api/settings'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t } = useI18n()
const auth = useAuthStore()
const canWrite = computed(() => auth.hasPermission('setting:write'))
const types: WebhookType[] = ['feishu', 'dingtalk', 'wecom', 'generic']
const loading = ref(false)
const saving = ref(false)
const testing = ref('')
const form = reactive<AlertSettings>({
  enabled: false,
  webhooks: [],
  events: { budget: true, channel: true, errors: true },
  budget_threshold: 0.9,
  error_threshold: 0.5,
  error_min_requests: 20,
})
const budgetPct = computed({
  get: () => Math.round(form.budget_threshold * 100),
  set: (value: number) => (form.budget_threshold = value / 100),
})
const errorPct = computed({
  get: () => Math.round(form.error_threshold * 100),
  set: (value: number) => (form.error_threshold = value / 100),
})

function apply(data: AlertSettings) {
  Object.assign(form, data, { webhooks: data.webhooks.map(hook => ({ ...hook, secret: '' })) })
}

function addHook() {
  form.webhooks.push({ name: '', type: 'feishu', url: '', secret: '' })
}

async function save() {
  saving.value = true
  try {
    apply(await alertsApi.save(form))
    ElMessage.success(t('common.saved'))
  } catch {
    ElMessage.error(t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

async function test(id: string) {
  testing.value = id
  try {
    const [result] = (await alertsApi.test(id)).items
    if (result?.ok) ElMessage.success(t('alerts.testOk'))
    else ElMessage.error(t('alerts.testFailed', { error: result?.error || '-' }))
  } catch {
    ElMessage.error(t('alerts.testFailed', { error: '-' }))
  } finally {
    testing.value = ''
  }
}

onMounted(async () => {
  loading.value = true
  try {
    apply(await alertsApi.get())
  } catch {
    ElMessage.error(t('settings.loadFailed'))
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.alerts-card {
  margin-top: 12px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}

h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
  color: #1c1f23;
}

.hint {
  margin: 6px 0 0;
  width: 100%;
  font-size: 13px;
  line-height: 1.5;
  color: #646a73;
}

.hook-list,
.event-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}

.hook-row,
.event-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.hook-type {
  width: 110px;
}

.hook-name {
  width: 120px;
}

.hook-url {
  flex: 1;
  min-width: 200px;
}

.hook-secret {
  width: 160px;
}

.event-row .el-checkbox {
  min-width: 160px;
}

.muted {
  font-size: 13px;
  color: #8f959e;
}
</style>
