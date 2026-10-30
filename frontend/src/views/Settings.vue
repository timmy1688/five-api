<template>
  <div class="settings-page">
    <div class="page-header"><div><h3>{{ t('nav.settings') }}</h3><p>{{ t('settings.subtitle') }}</p></div></div>
    <el-alert v-if="loadError" :title="t('settings.loadFailed')" type="error" :closable="false" show-icon class="load-error">
      <el-button text type="primary" @click="load">{{ t('settlements.refresh') }}</el-button>
    </el-alert>
    <SettlementNotice />
    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane :label="t('settings.tabGeneral')" name="general">
        <el-card v-loading="loading" shadow="never">
          <el-form v-if="loaded" label-position="top" :disabled="!canWrite">
            <section class="settings-section">        <h4>{{ t('settings.logs') }}</h4>
        <el-form-item :label="t('settings.logRetention')">
          <el-input-number v-model="form.log_retention_days" :min="0" :max="3650" :step="1" />
          <p class="hint">{{ t('settings.logRetentionHint') }}</p>
        </el-form-item>

</section>
            <section class="settings-section">        <h4>{{ t('settings.health') }}</h4>
        <el-form-item :label="t('settings.healthThreshold')">
          <el-input-number v-model="form.channel_health_threshold" :min="1" :max="100" :step="1" />
        </el-form-item>
        <el-form-item :label="t('settings.healthInterval')">
          <el-input-number v-model="form.channel_health_check_interval" :min="10" :max="86400" :step="10" />
          <p class="hint">{{ t('settings.healthHint') }}</p>
        </el-form-item>
</section>
            <section class="settings-section"><h4>{{ t('settings.cache') }}</h4>        <el-form-item :label="t('settings.autoCache')">
          <el-switch v-model="form.auto_cache_control" />
          <p class="hint">{{ t('settings.autoCacheHint') }}</p>
        </el-form-item>
</section>
          </el-form>
          <div class="settings-footer"><span :class="{ changed: dirty }">{{ t(dirty ? 'settings.unsaved' : 'settings.upToDate') }}</span><el-button type="primary" :loading="saving" :disabled="!loaded || !dirty" @click="save">{{ t(activeTab === 'general' ? 'settings.saveGeneral' : 'settings.saveRouting') }}</el-button></div>
        </el-card>
      </el-tab-pane>
      <el-tab-pane :label="t('settings.tabRouting')" name="routing">
        <el-card v-loading="loading" shadow="never">
          <el-form v-if="loaded" label-position="top" :disabled="!canWrite">
            <section class="settings-section">        <h4>{{ t('settings.routing') }}</h4>
        <el-form-item :label="t('settings.sticky')">
          <el-switch v-model="form.sticky_session_enabled" />
          <p class="hint">{{ t('settings.stickyHint') }}</p>
        </el-form-item>
        <el-form-item :label="t('settings.stickyTtl')">
          <el-input-number v-model="form.sticky_session_ttl" :min="60" :max="86400" :step="60" />
        </el-form-item>
        <el-form-item :label="t('settings.strategy')">
          <el-radio-group v-model="form.routing_strategy">
            <el-radio-button value="weighted">{{ t('settings.strategyWeighted') }}</el-radio-button>
            <el-radio-button value="least_busy">{{ t('settings.strategyLeastBusy') }}</el-radio-button>
            <el-radio-button value="latency">{{ t('settings.strategyLatency') }}</el-radio-button>
          </el-radio-group>
          <p class="hint">{{ t('settings.strategyHint') }}</p>
        </el-form-item>
</section>
            <div class="advanced-heading"><h4>{{ t('settings.advanced') }}</h4><p class="hint">{{ t('settings.advancedHint') }}</p></div>
            <el-collapse class="advanced-rules">
              <el-collapse-item :title="t('settings.fallbacks')" name="fallbacks">        <el-form-item :label="t('settings.fallbacks')">
          <div class="fallback-list">
            <div v-for="(rule, index) in fallbacks" :key="index" class="fallback-row">
              <el-select v-model="rule.source" filterable allow-create default-first-option :placeholder="t('settings.fallbackSource')" class="fallback-source">
                <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" />
              </el-select>
              <span class="fallback-arrow">→</span>
              <el-select v-model="rule.targets" multiple filterable allow-create default-first-option :multiple-limit="5" :placeholder="t('settings.fallbackTargets')" class="fallback-targets">
                <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" :disabled="m === rule.source" />
              </el-select>
              <el-button text type="danger" @click="fallbacks.splice(index, 1)">{{ t('common.delete') }}</el-button>
            </div>
            <el-button v-if="canWrite" plain size="small" @click="fallbacks.push({ source: '', targets: [] })">{{ t('settings.fallbackAdd') }}</el-button>
          </div>
          <p class="hint">{{ t('settings.fallbacksHint') }}</p>
        </el-form-item>

</el-collapse-item>
              <el-collapse-item :title="t('settings.downgrade')" name="downgrade">        <el-form-item :label="t('settings.downgrade')">
          <div class="fallback-list">
            <div class="fallback-row">
              <span class="threshold-label">{{ t('settings.downgradeThreshold') }}</span>
              <el-input-number v-model="downgradeThreshold" :min="10" :max="100" :step="5" />
              <span class="fallback-arrow">%</span>
            </div>
            <div v-for="(rule, index) in downgrades" :key="index" class="fallback-row">
              <el-select v-model="rule.source" filterable allow-create default-first-option :placeholder="t('settings.downgradeSource')" class="fallback-source">
                <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" />
              </el-select>
              <span class="fallback-arrow">→</span>
              <el-select v-model="rule.target" filterable allow-create default-first-option :placeholder="t('settings.downgradeTarget')" class="fallback-source">
                <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" :disabled="m === rule.source" />
              </el-select>
              <el-button text type="danger" @click="downgrades.splice(index, 1)">{{ t('common.delete') }}</el-button>
            </div>
            <el-button v-if="canWrite" plain size="small" @click="downgrades.push({ source: '', target: '' })">{{ t('settings.fallbackAdd') }}</el-button>
          </div>
          <p class="hint">{{ t('settings.downgradeHint') }}</p>
        </el-form-item>

</el-collapse-item>
            </el-collapse>
          </el-form>
          <div class="settings-footer"><span :class="{ changed: dirty }">{{ t(dirty ? 'settings.unsaved' : 'settings.upToDate') }}</span><el-button type="primary" :loading="saving" :disabled="!loaded || !dirty" @click="save">{{ t(activeTab === 'general' ? 'settings.saveGeneral' : 'settings.saveRouting') }}</el-button></div>
        </el-card>
      </el-tab-pane>
      <el-tab-pane :label="t('settings.tabAlerts')" name="alerts" lazy><AlertSettings /></el-tab-pane>
      <el-tab-pane :label="t('settings.tabMetrics')" name="metrics" lazy><MetricsToken /></el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { settingsApi, type GatewaySettings } from '@/api/settings'
import AlertSettings from '@/components/AlertSettings.vue'
import MetricsToken from '@/components/MetricsToken.vue'
import SettlementNotice from '@/components/SettlementNotice.vue'
import { modelsApi } from '@/api/models'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t } = useI18n()
const auth = useAuthStore()
const canWrite = computed(() => auth.isPlatformAdmin)
const loading = ref(false)
const saving = ref(false)
const activeTab = ref('general')
const loaded = ref(false), loadError = ref(false)
const saved = reactive({ general: '', routing: '' })
const dirty = computed(() => loaded.value && ['general', 'routing'].includes(activeTab.value) &&
  JSON.stringify(payload(activeTab.value)) !== saved[activeTab.value as 'general' | 'routing'])
const form = reactive<GatewaySettings>({
  log_retention_days: 90,
  channel_health_threshold: 3,
  channel_health_check_interval: 60,
  sticky_session_enabled: true,
  sticky_session_ttl: 900,
  routing_strategy: 'weighted',
  auto_cache_control: false,
})
const fallbacks = ref<{ source: string; targets: string[] }[]>([])
const downgrades = ref<{ source: string; target: string }[]>([])
const downgradeThreshold = ref(80)
const modelOptions = ref<string[]>([])

function apply(data: GatewaySettings, scope = 'all') {
  if (scope !== 'routing') {
    form.log_retention_days = data.log_retention_days
    form.channel_health_threshold = data.channel_health_threshold
    form.channel_health_check_interval = data.channel_health_check_interval
    form.auto_cache_control = data.auto_cache_control ?? false
  }
  if (scope !== 'general') {
    form.sticky_session_enabled = data.sticky_session_enabled
    form.sticky_session_ttl = data.sticky_session_ttl
    form.routing_strategy = data.routing_strategy ?? 'weighted'
    fallbacks.value = Object.entries(data.model_fallbacks ?? {}).map(([source, targets]) => ({ source, targets: [...targets] }))
    downgradeThreshold.value = Math.round((data.budget_downgrade?.threshold ?? 0.8) * 100)
    downgrades.value = Object.entries(data.budget_downgrade?.rules ?? {}).map(([source, target]) => ({ source, target }))
  }
}

function payload(tab: string): Partial<GatewaySettings> {
  return tab === 'general' ? {
    log_retention_days: form.log_retention_days, channel_health_threshold: form.channel_health_threshold,
    channel_health_check_interval: form.channel_health_check_interval, auto_cache_control: form.auto_cache_control,
  } : {
    sticky_session_enabled: form.sticky_session_enabled, sticky_session_ttl: form.sticky_session_ttl,
    routing_strategy: form.routing_strategy, model_fallbacks: fallbackMap(),
    budget_downgrade: downgradeConfig(),
  }
}

function downgradeConfig() {
  const rules: Record<string, string> = {}
  for (const rule of downgrades.value) {
    const source = rule.source.trim()
    if (source && rule.target) rules[source] = rule.target
  }
  return { threshold: downgradeThreshold.value / 100, rules }
}

function fallbackMap(): Record<string, string[]> {
  const map: Record<string, string[]> = {}
  for (const rule of fallbacks.value) {
    const source = rule.source.trim()
    if (source && rule.targets.length) map[source] = rule.targets
  }
  return map
}

async function load() {
  loading.value = true
  try {
    loadError.value = false
    apply(await settingsApi.get())
    loaded.value = true
    saved.general = JSON.stringify(payload('general')); saved.routing = JSON.stringify(payload('routing'))
    if (auth.isPlatformAdmin) {
      modelsApi.list().then(data => {
        modelOptions.value = (data.items || []).map((item: { model: string }) => item.model)
      }).catch(() => {})
    }
  } catch {
    loadError.value = true
    ElMessage.error(t('settings.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const tab = activeTab.value as 'general' | 'routing'
    apply(await settingsApi.save(payload(tab)), tab)
    saved[tab] = JSON.stringify(payload(tab))
    ElMessage.success(t('common.saved'))
  } catch {
    ElMessage.error(t('common.saveFailed'))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.settings-page { max-width: 1180px; margin: 0 auto; }
.settings-tabs { --el-tabs-header-height: 44px; }
.settings-tabs :deep(.el-tabs__header) { margin-bottom: 18px; }
.settings-tabs :deep(.el-tabs__item) { font-weight: 500; }
.settings-tabs :deep(.el-card) { margin-top: 0 !important; border-radius: 10px; }
.settings-section { padding-bottom: 20px; margin-bottom: 20px; border-bottom: 1px solid #edf0f3; }
.settings-section:last-of-type { border-bottom: 0; padding-bottom: 0; margin-bottom: 0; }
.settings-section :deep(.el-form-item) { margin-bottom: 18px; }
.settings-section :deep(.el-form-item:last-child) { margin-bottom: 0; }
.advanced-heading { margin: 24px 0 14px; }
.advanced-heading h4 { margin-bottom: 4px; }
.advanced-rules :deep(.el-collapse-item__header) { font-size: 14px; }
.advanced-rules :deep(.el-collapse-item__content) { padding: 14px 0 18px; }
.settings-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 24px -20px -20px; padding: 16px 20px; border-top: 1px solid #edf0f3; background: #fafbfc; }
.settings-footer span { font-size: 13px; color: #86909c; }
.settings-footer .changed { color: #b7791f; }
.load-error { margin-bottom: 16px; }
@media (max-width: 720px) {
  .fallback-row { flex-wrap: wrap; }
  .fallback-source, .fallback-targets { width: 100% !important; min-width: 0 !important; flex-basis: 100%; }
  .settings-footer { padding: 12px; }
}

h4 {
  margin: 8px 0 12px;
  font-size: 14px;
  font-weight: 650;
  color: #1c1f23;
}

h4:not(:first-child) {
  margin-top: 20px;
}

.fallback-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}

.fallback-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.fallback-source {
  width: 220px;
}

.fallback-targets {
  flex: 1;
  min-width: 260px;
}

.threshold-label {
  font-size: 13px;
  color: #474d57;
}

.fallback-arrow {
  color: #8f959e;
}

.hint {
  margin: 6px 0 0;
  width: 100%;
  font-size: 13px;
  line-height: 1.5;
  color: #646a73;
}
</style>
