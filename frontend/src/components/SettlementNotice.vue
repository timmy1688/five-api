<template>
  <div>
    <el-alert v-if="attention" type="warning" :closable="false" show-icon class="settlement-notice">
      <template #title><div class="notice-row"><span>{{ t('settlements.attention', { n: attention }) }}</span><el-button text type="primary" @click="open = true">{{ t('settlements.inspect') }}</el-button></div></template>
    </el-alert>
    <el-drawer v-model="open" :title="t('settlements.title')" size="min(1080px, 100%)" @closed="load">
      <SettlementStatus v-if="open" :initial-state="counts.uncertain ? 'uncertain' : 'failed'" />
    </el-drawer>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import client from '@/api/client'
import SettlementStatus from '@/components/SettlementStatus.vue'
import { useI18n } from '@/i18n'
const { t } = useI18n()
const counts = ref({ failed: 0, uncertain: 0 }), open = ref(false)
const attention = computed(() => counts.value.failed + counts.value.uncertain)
let timer: ReturnType<typeof setInterval> | undefined
async function load() {
  try { counts.value = (await client.get('/settlements', { params: { size: 1 } })).data.counts }
  catch { /* The existing accounting worker and metrics remain the source of state. */ }
}
onMounted(() => { load(); timer = setInterval(() => { if (document.visibilityState === 'visible') load() }, 30000) })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>
<style scoped>
.settlement-notice { margin-bottom: 16px; }
.notice-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
</style>
