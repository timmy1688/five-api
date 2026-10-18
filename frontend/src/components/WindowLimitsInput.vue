<template>
  <div class="window-inputs">
    <div v-for="w in WINDOWS" :key="w" class="window-input">
      <span class="window-label">{{ t(`windows.${w}`) }}</span>
      <el-input-number
        :model-value="modelValue[w] ?? undefined"
        :min="0"
        :precision="2"
        :step="1"
        :value-on-clear="null"
        :placeholder="t('common.unlimited')"
        controls-position="right"
        @update:model-value="(v: number | null | undefined) => update(w, v)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from '@/i18n'

export type WindowLimits = Record<string, number>

const WINDOWS = ['5h', '1d', '7d'] as const
const props = defineProps<{ modelValue: WindowLimits }>()
const emit = defineEmits<{ 'update:modelValue': [value: WindowLimits] }>()
const { t } = useI18n()

function update(window: string, value: number | null | undefined) {
  const next = { ...props.modelValue }
  if (value === null || value === undefined) delete next[window]
  else next[window] = value
  emit('update:modelValue', next)
}
</script>

<style scoped>
.window-inputs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}

.window-input {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.window-input :deep(.el-input-number) {
  width: 100%;
}

.window-label {
  font-size: 12px;
  line-height: 18px;
  color: #646a73;
}
</style>
