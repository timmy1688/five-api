<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.settings') }}</h3>
        <p>{{ t('settings.subtitle') }}</p>
      </div>
      <el-button
        v-if="canWrite"
        type="primary"
        :loading="saving"
        @click="save"
      >
        {{ t('common.save') }}
      </el-button>
    </div>

    <el-card v-loading="loading" shadow="never">
      <el-form label-position="top" :disabled="!canWrite">
        <h4>{{ t('settings.logs') }}</h4>
        <el-form-item :label="t('settings.logRetention')">
          <el-input-number v-model="form.log_retention_days" :min="0" :max="3650" :step="1" />
          <p class="hint">{{ t('settings.logRetentionHint') }}</p>
        </el-form-item>

        <h4>{{ t('settings.routing') }}</h4>
        <el-form-item :label="t('settings.sticky')">
          <el-switch v-model="form.sticky_session_enabled" />
          <p class="hint">{{ t('settings.stickyHint') }}</p>
        </el-form-item>
        <el-form-item :label="t('settings.stickyTtl')">
          <el-input-number v-model="form.sticky_session_ttl" :min="60" :max="86400" :step="60" />
        </el-form-item>

        <h4>{{ t('settings.health') }}</h4>
        <el-form-item :label="t('settings.healthThreshold')">
          <el-input-number v-model="form.channel_health_threshold" :min="1" :max="100" :step="1" />
        </el-form-item>
        <el-form-item :label="t('settings.healthInterval')">
          <el-input-number v-model="form.channel_health_check_interval" :min="10" :max="86400" :step="10" />
          <p class="hint">{{ t('settings.healthHint') }}</p>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { settingsApi, type GatewaySettings } from '@/api/settings'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t } = useI18n()
const auth = useAuthStore()
const canWrite = computed(() => auth.hasPermission('setting:write'))
const loading = ref(false)
const saving = ref(false)
const form = reactive<GatewaySettings>({
  log_retention_days: 90,
  channel_health_threshold: 3,
  channel_health_check_interval: 60,
  sticky_session_enabled: true,
  sticky_session_ttl: 900,
})

function apply(data: GatewaySettings) {
  form.log_retention_days = data.log_retention_days
  form.channel_health_threshold = data.channel_health_threshold
  form.channel_health_check_interval = data.channel_health_check_interval
  form.sticky_session_enabled = data.sticky_session_enabled
  form.sticky_session_ttl = data.sticky_session_ttl
}

async function load() {
  loading.value = true
  try {
    apply(await settingsApi.get())
  } catch {
    ElMessage.error(t('settings.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    apply(await settingsApi.save({ ...form }))
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
h4 {
  margin: 8px 0 12px;
  font-size: 14px;
  font-weight: 650;
  color: #1c1f23;
}

h4:not(:first-child) {
  margin-top: 20px;
}

.hint {
  margin: 6px 0 0;
  width: 100%;
  font-size: 13px;
  line-height: 1.5;
  color: #646a73;
}
</style>
