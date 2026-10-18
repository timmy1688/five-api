<template>
  <div v-if="rows.length" class="window-usage">
    <span v-for="row in rows" :key="row.window" :class="{ over: row.spent >= row.cap }">
      {{ t(`windows.${row.window}`) }} ${{ row.spent.toFixed(2) }}/${{ row.cap.toFixed(2) }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/i18n'

const props = defineProps<{ limits?: Record<string, number>; spend?: Record<string, number> }>()
const { t } = useI18n()

const rows = computed(() =>
  (['5h', '1d', '7d'] as const)
    .filter(window => props.limits?.[window] !== undefined)
    .map(window => ({ window, cap: props.limits![window], spent: props.spend?.[window] ?? 0 })),
)
</script>

<style scoped>
.window-usage {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 8px;
  margin-top: 2px;
  font-size: 12px;
  color: #64748b;
}

.over {
  color: #f56c6c;
  font-weight: 600;
}
</style>
