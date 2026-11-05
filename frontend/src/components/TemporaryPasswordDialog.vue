<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="480px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    @update:model-value="emit('update:modelValue', $event)"
    @closed="emit('closed')"
  >
    <el-alert type="warning" :closable="false" :title="t('tempPassword.once')" style="margin-bottom: 16px" />
    <p v-if="username" class="account-line">
      <span>{{ t('login.username') }}</span><strong>{{ username }}</strong>
    </p>
    <el-input ref="field" :model-value="password" readonly class="password-field" @focus="selectAll">
      <template #append><el-button @click="copy">{{ t('keys.copy') }}</el-button></template>
    </el-input>
    <p class="hint">{{ hint }}</p>
    <template #footer>
      <el-button type="primary" @click="emit('update:modelValue', false)">{{ t('tempPassword.saved') }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from '@/i18n'

/** Shows a server-generated temporary password once; the page clears it when the dialog closes. */
defineProps<{
  modelValue: boolean
  title: string
  username?: string
  password: string
  hint: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean], closed: [] }>()
const { t } = useI18n()
const field = ref<{ select: () => void, input?: HTMLInputElement } | null>(null)

function selectAll() {
  field.value?.select()
}

async function copy(): Promise<void> {
  const input = field.value?.input
  try {
    // The clipboard API needs HTTPS or localhost; the console is often opened over plain HTTP.
    await navigator.clipboard.writeText(input?.value ?? '')
    ElMessage.success(t('common.copied'))
    return
  } catch {
    input?.select()
  }
  if (document.execCommand('copy')) ElMessage.success(t('common.copied'))
  else ElMessage.error(t('keys.copyManual'))
}
</script>

<style scoped>
.account-line {
  display: flex;
  gap: 12px;
  align-items: baseline;
  margin: 0 0 8px;
  color: #646a73;
  font-size: 13px;
}

.account-line strong {
  color: #1c1f23;
  font-size: 14px;
}

.password-field :deep(input) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 16px;
  letter-spacing: 0.5px;
}

.hint {
  margin: 12px 0 0;
  color: #646a73;
  font-size: 13px;
  line-height: 1.6;
}
</style>
