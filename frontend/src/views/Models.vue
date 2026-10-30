<template>
  <div class="model-hub">
    <div class="page-header"><div><h3>{{ t('nav.models') }}</h3><p>{{ t('models.subtitle') }}</p></div><div style="display:flex;gap:8px"><el-button @click="settingsOpen = true">{{ t('probe.scheduleTitle') }}</el-button><el-button :loading="loading" @click="load">{{ t('settlements.refresh') }}</el-button></div></div>
    <div class="hub-summary">
      <div><strong>{{ items.length }}</strong><span>{{ t('models.total') }}</span></div>
      <div><strong>{{ items.filter(m => m.has_pricing).length }}</strong><span>{{ t('models.priced') }}</span></div>
      <div><strong>{{ items.filter(m => m.health === 'healthy').length }}</strong><span>{{ t('probe.healthy') }}</span></div>
    </div>
    <p class="schedule-summary" v-if="schedule">{{ t('probe.scheduleSummary', { minutes: schedule.health_interval_seconds / 60, hours: schedule.capability_interval_seconds / 3600 }) }}</p>
    <div class="hub-toolbar"><el-radio-group v-model="viewMode"><el-radio-button value="all">{{ t('common.all') }}</el-radio-button><el-radio-button value="capability">{{ t('probe.capabilityCheck') }}</el-radio-button></el-radio-group>
      <el-input v-model="search" :placeholder="t('models.search')" clearable class="model-search" />
      <el-select v-model="health" class="health-filter"><el-option :label="t('common.all')" value="" /><el-option v-for="state in states" :key="state" :value="state" :label="healthLabel(state)" /></el-select>
      <span class="price-unit">{{ t('models.priceUnit') }}</span>
    </div>
    <el-skeleton v-if="loading && !items.length" :rows="6" animated />
    <div v-else-if="filtered.length" class="model-grid">
      <el-card v-for="model in filtered" :key="model.model" shadow="hover" class="model-card">
        <div class="model-heading">
          <div class="model-brand" :class="{ claude: model.model.includes('claude') }">{{ model.model.includes('claude') ? 'C' : model.model.startsWith('gpt') ? 'G' : 'M' }}</div>
          <div class="model-identity"><el-tooltip :content="model.model"><h4>{{ model.model }}</h4></el-tooltip><span>{{ model.providers.join(' · ') }} · {{ t('models.channelCount', { n: model.channel_count }) }}</span></div>
          <el-tag :type="model.health === 'healthy' ? 'success' : model.health === 'unavailable' ? 'danger' : 'info'" size="small">{{ healthLabel(model.health) }}</el-tag>
        </div>
        <div v-if="model.has_pricing" class="model-prices">
          <div><span>{{ t('logs.input') }}</span><strong>${{ price(model, 'prompt') }}</strong></div>
          <div><span>{{ t('logs.output') }}</span><strong>${{ price(model, 'completion') }}</strong></div>
          <div><span>{{ t('logs.cache') }}</span><strong>${{ price(model, 'cached') }}</strong></div>
        </div>
        <el-alert v-else :title="t('models.priceMissing')" type="warning" :closable="false" show-icon class="missing-price" />
        <ul v-if="model.pricing_varies" class="channel-prices">
          <li v-for="channel in model.channels" :key="channel.id">
            <span class="channel-name">{{ channel.name }}<template v-if="channel.pricing_source === 'channel'"> · {{ t('models.fixedPrice') }}</template><template v-else-if="channel.price_multiplier !== 1"> · ×{{ channel.price_multiplier }}</template></span>
            <span>{{ channel.pricing ? `$${format(channel.pricing.prompt)} / $${format(channel.pricing.completion)}` : '—' }}</span>
          </li>
        </ul>
        <div class="model-meta"><span v-if="requestPrice(model)">{{ t('prices.request') }} ${{ price(model, 'request') }}</span><span v-else>{{ t('models.effectivePrices') }}</span><el-tag v-if="model.pricing_varies" type="info" size="small">{{ t('models.varies') }}</el-tag></div>
        <div class="model-check-status"><span>{{ t('probe.healthCheck') }} · {{ checked(model, 'health') }}</span><span v-if="model.channels.some((c: any) => c.capability_supported)">{{ t('probe.capabilityCheck') }} · {{ checked(model, 'capability') }}</span></div>
        <div class="model-actions"><el-button text type="primary" @click="open(model)">{{ t('probe.healthCheck') }}</el-button><el-button v-if="model.channels.some((c: any) => c.capability_supported)" @click="open(model)">{{ t('probe.capabilityCheck') }}</el-button><el-button v-else @click="open(model)">{{ t('models.details') }}</el-button></div>
      </el-card>
    </div>
    <el-empty v-else :description="t(viewMode === 'capability' ? 'probe.noEligible' : 'models.noResults')"><el-button v-if="viewMode === 'capability'" @click="$router.push('/channels')">{{ t('nav.channels') }}</el-button></el-empty>
    <ModelCheckSettings v-model="settingsOpen" @updated="load" />
    <ModelCheckPanel v-if="selected" v-model="probeOpen" :model="selected" @updated="load" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { modelsApi } from '@/api/models'
import ModelCheckPanel from '@/components/ModelCheckPanel.vue'
import ModelCheckSettings from '@/components/ModelCheckSettings.vue'
import { useI18n } from '@/i18n'
const { t } = useI18n()
const items = ref<any[]>([]), selected = ref<any>(null), loading = ref(false), probeOpen = ref(false)
const search = ref(''), health = ref(''), viewMode = ref('all'), settingsOpen = ref(false), schedule = ref<any>(null)
const states = ['healthy', 'unavailable', 'unknown'] as const
const healthLabel = (state: typeof states[number]) => t(`probe.${state}`)
const filtered = computed(() => items.value.filter(model => model.model.toLowerCase().includes(search.value.toLowerCase()) && (!health.value || model.health === health.value) && (viewMode.value !== 'capability' || model.channels.some((c: any) => c.capability_supported))))
function format(value: number) { return Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 }) }
function price(model: any, name: string) {
  const values: number[] = model.channels.filter((c: any) => c.pricing).map((c: any) => Number(c.pricing[name] || 0))
  if (!values.length) return '—'
  const low = Math.min(...values), high = Math.max(...values)
  return low === high ? format(low) : format(low) + '–' + format(high)
}
function checked(model: any, kind: string) {
  const last = model.channels.map((c: any) => c[kind]).filter(Boolean).sort((a: any, b: any) => Date.parse(b.created_at) - Date.parse(a.created_at))[0]
  return last ? new Date(last.created_at).toLocaleString() : t('probe.unknown')
}
function requestPrice(model: any) { return model.channels.some((c: any) => c.pricing?.request > 0) }
function open(model: any) { selected.value = model; probeOpen.value = true }
async function load() {
  loading.value = true
  try {
    const [catalog, monitor] = await Promise.all([modelsApi.list(), modelsApi.checkSettings()])
    items.value = catalog.items; schedule.value = monitor.config
    if (selected.value) selected.value = items.value.find(model => model.model === selected.value.model) || selected.value
  } catch { ElMessage.error(t('models.loadFailed')) } finally { loading.value = false }
}
onMounted(load)
</script>

<style scoped>
.schedule-summary { color: #86909c; font-size: 12px; margin: -4px 0 16px; }
.model-check-status { display: flex; flex-direction: column; gap: 8px; font-size: 12px; color: #86909c; margin-top: 14px; }
.model-hub { max-width: 1440px; margin: 0 auto; }
.hub-summary { display: flex; gap: 48px; background: #fff; border: 1px solid #e6e9ef; border-radius: 10px; padding: 20px 24px; margin-bottom: 20px; }
.hub-summary div { display: flex; align-items: baseline; gap: 10px; }
.hub-summary strong { font-size: 26px; font-weight: 600; color: #1c1f23; }
.hub-summary span, .price-unit, .model-meta { color: #86909c; font-size: 12px; }
.hub-toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 18px; flex-wrap: wrap; }
.model-search { width: 280px; } .health-filter { width: 150px; } .price-unit { margin-left: auto; }
.model-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 16px; }
.model-card { border-radius: 10px; } .model-card :deep(.el-card__body) { padding: 20px; }
.model-heading { display: flex; align-items: center; gap: 12px; min-width: 0; }
.model-brand { flex-shrink: 0; display: grid; place-items: center; width: 38px; height: 38px; background: #e8f5ef; color: #247653; border-radius: 10px; font-size: 18px; font-weight: 600; }
.model-brand.claude { background: #fff0e7; color: #b87853; }
.model-identity { flex: 1; min-width: 0; }
h4 { margin: 0 0 6px; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-identity span { font-size: 12px; color: #86909c; }
.model-prices { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 24px 0 14px; }
.model-prices span { display: block; margin-bottom: 8px; color: #86909c; font-size: 12px; }
.model-prices strong { font-size: 16px; font-weight: 600; color: #1c1f23; }
.model-meta { display: flex; align-items: center; justify-content: space-between; min-height: 24px; }
.model-actions { display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #edf0f3; padding-top: 14px; margin-top: 18px; }
.missing-price { margin: 20px 0 14px; }
.channel-prices { list-style: none; margin: 0 0 12px; padding: 8px 10px; background: #f7f8fa; border-radius: 6px; font-size: 12px; }
.channel-prices li { display: flex; justify-content: space-between; gap: 8px; padding: 2px 0; color: #4e5969; }
.channel-prices .channel-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #86909c; }
@media (max-width: 600px) { .hub-summary { gap: 20px; padding: 16px; flex-wrap: wrap; } .hub-summary div { gap: 6px; } .hub-summary strong { font-size: 22px; } .model-search { width: 100%; } .price-unit { margin-left: 0; } .model-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
