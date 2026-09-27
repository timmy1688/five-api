<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.security') }}</h3>
        <p>{{ t('security.subtitle') }}</p>
      </div>
    </div>

    <el-card v-loading="loading" shadow="never" class="setting-card">
      <div class="setting-row">
        <div>
          <div class="setting-title">{{ t('security.keywordTitle') }}</div>
          <p class="setting-desc">{{ t('security.keywordDesc') }}</p>
        </div>
        <el-switch
          v-model="enabled"
          :disabled="!auth.hasPermission('security:write') || saving"
          @change="saveEnabled"
        />
      </div>
    </el-card>

    <el-card shadow="never" class="setting-card" style="margin-top: 12px">
      <div class="setting-row">
        <div>
          <div class="setting-title">{{ t('security.secretTitle') }}</div>
          <p class="setting-desc">{{ t('security.secretDesc') }}</p>
        </div>
        <el-switch
          v-model="secretScan"
          :disabled="!auth.hasPermission('security:write') || savingSecrets"
          @change="saveSecretScan"
        />
      </div>
    </el-card>

    <el-card shadow="never" class="setting-card" style="margin-top: 12px">
      <div class="setting-row">
        <div>
          <div class="setting-title">{{ t('security.auditTitle') }}</div>
          <p class="setting-desc">{{ t('security.auditDesc') }}</p>
        </div>
        <el-switch
          v-model="inferenceAudit"
          :disabled="!auth.hasPermission('security:write') || savingAudit"
          @change="saveInferenceAudit"
        />
      </div>
    </el-card>

    <el-card shadow="never" class="setting-card" style="margin-top: 12px">
      <div class="setting-row">
        <div>
          <div class="setting-title">{{ t('security.aiTitle') }}</div>
          <p class="setting-desc">
            {{ t('security.aiDesc', {
              system: limits.system_chars,
              user: limits.user_chars,
              minutes: limits.cache_seconds / 60,
              min: limits.min_chars,
            }) }}
          </p>
        </div>
        <el-switch
          v-model="ai.enabled"
          :disabled="!auth.hasPermission('security:write') || savingAi"
          @change="saveAi"
        />
      </div>
      <div class="add-row">
        <el-input
          v-model="ai.model"
          :placeholder="t('security.aiModel')"
          maxlength="64"
          style="max-width: 420px"
          :disabled="!auth.hasPermission('security:write')"
        />
        <el-button
          v-if="auth.hasPermission('security:write')"
          :loading="savingAi"
          @click="saveAi"
        >
          {{ t('common.save') }}
        </el-button>
      </div>
    </el-card>

    <el-card shadow="never" style="margin-top: 12px">
      <div v-if="auth.hasPermission('security:write')" class="add-row">
        <el-input v-model="draft" :placeholder="t('security.keywordPlaceholder')" maxlength="64" style="max-width: 360px" />
        <el-button type="primary" :disabled="draft.trim().length < 2" @click="addKeyword">{{ t('common.add') }}</el-button>
      </div>

      <el-table :data="keywords" style="width: 100%">
        <el-table-column prop="keyword" :label="t('security.keyword')" min-width="180" />
        <el-table-column :label="t('common.enabled')" width="110" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="row.is_enabled"
              :disabled="!auth.hasPermission('security:write')"
              @change="(value: boolean) => toggleKeyword(row, value)"
            />
          </template>
        </el-table-column>
        <el-table-column v-if="auth.hasPermission('security:write')" label="" width="100" align="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="removeKeyword(row)">{{ t('common.delete') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { securityApi } from '@/api/security'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t } = useI18n()

const auth = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const savingSecrets = ref(false)
const savingAudit = ref(false)
const savingAi = ref(false)
const enabled = ref(false)
const secretScan = ref(false)
const inferenceAudit = ref(false)
const keywords = ref<any[]>([])
const draft = ref('')
const limits = ref({
  system_chars: 400,
  user_chars: 1200,
  min_chars: 24,
  cache_seconds: 600,
})
const ai = ref({ enabled: false, model: '', fail_closed: false })
const savedAi = ref({ enabled: false, model: '', fail_closed: false })

async function load() {
  loading.value = true
  try {
    const data = await securityApi.get()
    enabled.value = !!data.enabled
    secretScan.value = !!data.secret_scan_enabled
    inferenceAudit.value = !!data.inference_audit_enabled
    keywords.value = data.keywords || []
    if (data.ai_audit) {
      const next = {
        enabled: !!data.ai_audit.enabled,
        model: data.ai_audit.model || '',
        fail_closed: !!data.ai_audit.fail_closed,
      }
      ai.value = next
      savedAi.value = { ...next }
      limits.value = {
        system_chars: data.ai_audit.system_chars,
        user_chars: data.ai_audit.user_chars,
        min_chars: data.ai_audit.min_chars,
        cache_seconds: data.ai_audit.cache_seconds,
      }
    }
  } catch {
    ElMessage.error(t('security.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function saveEnabled(value: boolean) {
  saving.value = true
  try {
    const data = await securityApi.setEnabled(value)
    enabled.value = !!data.enabled
    ElMessage.success(enabled.value ? t('security.keywordOn') : t('security.keywordOff'))
  } catch {
    enabled.value = !value
    ElMessage.error(t('security.updateFailed'))
  } finally {
    saving.value = false
  }
}

async function saveSecretScan(value: boolean) {
  savingSecrets.value = true
  try {
    const data = await securityApi.setSecretScan(value)
    secretScan.value = !!data.enabled
    ElMessage.success(secretScan.value ? t('security.secretOn') : t('security.secretOff'))
  } catch {
    secretScan.value = !value
    ElMessage.error(t('security.secretFailed'))
  } finally {
    savingSecrets.value = false
  }
}

async function saveInferenceAudit(value: boolean) {
  savingAudit.value = true
  try {
    const data = await securityApi.setInferenceAudit(value)
    inferenceAudit.value = !!data.enabled
    ElMessage.success(inferenceAudit.value ? t('security.auditOn') : t('security.auditOff'))
  } catch {
    inferenceAudit.value = !value
    ElMessage.error(t('security.auditFailed'))
  } finally {
    savingAudit.value = false
  }
}

async function saveAi() {
  savingAi.value = true
  try {
    const data = await securityApi.setAiAudit({
      enabled: ai.value.enabled,
      model: ai.value.model.trim(),
      fail_closed: ai.value.fail_closed,
    })
    const next = {
      enabled: !!data.enabled,
      model: data.model || '',
      fail_closed: !!data.fail_closed,
    }
    ai.value = next
    savedAi.value = { ...next }
    if (next.enabled && !next.model) {
      ElMessage.warning(t('security.aiIdle'))
    } else {
      ElMessage.success(t('security.aiSaved'))
    }
  } catch {
    ai.value = { ...savedAi.value }
    ElMessage.error(t('security.aiFailed'))
  } finally {
    savingAi.value = false
  }
}

async function addKeyword() {
  try {
    await securityApi.createKeyword(draft.value.trim(), 'request')
    draft.value = ''
    await load()
  } catch {
    ElMessage.error(t('security.addFailed'))
  }
}

async function toggleKeyword(row: any, value: boolean) {
  const previous = row.is_enabled
  row.is_enabled = value
  try {
    await securityApi.updateKeyword(row.id, { is_enabled: value })
  } catch {
    row.is_enabled = previous
    ElMessage.error(t('security.keywordUpdateFailed'))
  }
}

async function removeKeyword(row: any) {
  try {
    await securityApi.removeKeyword(row.id)
    keywords.value = keywords.value.filter(item => item.id !== row.id)
  } catch {
    ElMessage.error(t('security.keywordDeleteFailed'))
  }
}

onMounted(load)
</script>

<style scoped>
.setting-card :deep(.el-card__body) {
  padding: 8px;
}

.setting-row,
.add-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 4px 4px 8px;
}

.add-row {
  justify-content: flex-start;
  padding-bottom: 8px;
}

.setting-title {
  font-size: 16px;
  font-weight: 650;
  color: #1d2129;
}

.setting-desc {
  margin: 6px 0 0;
  max-width: 720px;
  font-size: 14px;
  line-height: 1.6;
  color: #4e5969;
}
</style>
