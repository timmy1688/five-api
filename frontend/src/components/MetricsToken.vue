<template>
  <el-card v-loading="loading" shadow="never" class="metrics-card">
    <h4>{{ t('metrics.title') }}</h4>
    <p class="hint">{{ t('metrics.subtitle') }}</p>
    <div class="token-row">
      <el-input :model-value="token" readonly type="password" show-password class="token-input" />
      <el-button @click="copy">{{ t('keys.copy') }}</el-button>
      <el-button v-if="canWrite" :loading="resetting" @click="reset">{{ t('metrics.reset') }}</el-button>
    </div>
    <pre class="example">{{ example }}</pre>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { metricsTokenApi } from '@/api/settings'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t } = useI18n()
const auth = useAuthStore()
const canWrite = computed(() => auth.hasPermission('setting:write'))
const token = ref('')
const loading = ref(false)
const resetting = ref(false)

const example = computed(() => [
  'scrape_configs:',
  '  - job_name: five-api',
  '    authorization: { credentials: "<token>" }',
  '    static_configs:',
  `      - targets: ["${location.host}"]`,
].join('\n'))

async function load() {
  loading.value = true
  try {
    token.value = await metricsTokenApi.get()
  } catch {
    ElMessage.error(t('settings.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(token.value)
    ElMessage.success(t('common.copied'))
  } catch {
    ElMessage.error(t('common.copyFailed'))
  }
}

async function reset() {
  try {
    await ElMessageBox.confirm(t('metrics.resetConfirm'), t('metrics.reset'), {
      confirmButtonText: t('metrics.reset'),
      cancelButtonText: t('common.cancel'),
      type: 'warning',
    })
  } catch {
    return
  }
  resetting.value = true
  try {
    token.value = await metricsTokenApi.reset()
    ElMessage.success(t('common.saved'))
  } catch {
    ElMessage.error(t('common.saveFailed'))
  } finally {
    resetting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.metrics-card {
  margin-top: 12px;
}

h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
  color: #1c1f23;
}

.hint {
  margin: 6px 0 12px;
  font-size: 13px;
  line-height: 1.5;
  color: #646a73;
}

.token-row {
  display: flex;
  gap: 8px;
  max-width: 640px;
}

.token-input {
  flex: 1;
}

.example {
  margin: 12px 0 0;
  padding: 10px 12px;
  max-width: 640px;
  font-size: 12px;
  line-height: 1.6;
  background: #f5f6f7;
  border-radius: 6px;
  color: #1c1f23;
  overflow-x: auto;
}
</style>
