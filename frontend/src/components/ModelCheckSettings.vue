<template>
  <el-dialog v-model="visible" :title="t('probe.scheduleTitle')" width="min(520px, 95%)">
    <el-form label-position="top" v-loading="loading">
      <div class="schedule-switch"><strong>{{ t('probe.healthCheck') }}</strong><el-switch v-model="form.health_enabled" /></div>
      <el-form-item :label="t('probe.healthInterval')"><el-input-number v-model="minutes" :min="1" :max="1440" :disabled="!form.health_enabled" /></el-form-item>
      <div class="schedule-switch"><strong>{{ t('probe.capabilityCheck') }}</strong><el-switch v-model="form.capability_enabled" /></div>
      <el-form-item :label="t('probe.capabilityInterval')"><el-input-number v-model="hours" :min="1" :max="168" :disabled="!form.capability_enabled" /></el-form-item>
      <el-alert :title="t('probe.scheduleHint')" type="info" :closable="false" show-icon />
    </el-form>
    <template #footer><el-button @click="visible = false">{{ t('common.cancel') }}</el-button><el-button type="primary" :loading="saving" :disabled="loading" @click="save">{{ t('common.save') }}</el-button></template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { modelsApi } from '@/api/models'
import { useI18n } from '@/i18n'
const visible = defineModel<boolean>({ default: false })
const emit = defineEmits<{ updated: [] }>()
const { t } = useI18n()
const loading = ref(false), saving = ref(false)
const form = reactive({ health_enabled: true, health_interval_seconds: 900, capability_enabled: true, capability_interval_seconds: 86400 })
const minutes = computed({ get: () => form.health_interval_seconds / 60, set: value => { form.health_interval_seconds = value * 60 } })
const hours = computed({ get: () => form.capability_interval_seconds / 3600, set: value => { form.capability_interval_seconds = value * 3600 } })
watch(visible, async value => {
  if (!value) return
  loading.value = true
  try { Object.assign(form, (await modelsApi.checkSettings()).config) }
  catch { ElMessage.error(t('settings.loadFailed')) } finally { loading.value = false }
})
async function save() {
  saving.value = true
  try { await modelsApi.saveCheckSettings(form); visible.value = false; emit('updated'); ElMessage.success(t('common.saved')) }
  catch { ElMessage.error(t('common.saveFailed')) } finally { saving.value = false }
}
</script>
<style scoped>
.schedule-switch { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-top: 8px; }
.schedule-switch strong { font-size: 14px; }
</style>
