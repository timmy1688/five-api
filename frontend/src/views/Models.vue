<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.models') }}</h3>
        <p>{{ t('models.subtitle') }}</p>
      </div>
      <el-input
        v-model="search"
        :placeholder="t('models.search')"
        clearable
        style="width: 260px"
        @input="onSearch"
      />
    </div>

    <el-row :gutter="12" style="margin-bottom: 16px">
      <el-col :xs="12" :md="6">
        <el-card shadow="never" class="summary-card">
          <div class="summary-value">{{ items.length }}</div>
          <div class="summary-label">{{ t('models.total') }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6">
        <el-card shadow="never" class="summary-card">
          <div class="summary-value">{{ pricedCount }}</div>
          <div class="summary-label">{{ t('models.priced') }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6">
        <el-card shadow="never" class="summary-card">
          <div class="summary-value" :style="{ color: unpricedCount > 0 ? '#f59e0b' : '#10b981' }">{{ unpricedCount }}</div>
          <div class="summary-label">{{ t('models.unpriced') }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6">
        <el-card shadow="never" class="summary-card">
          <div class="summary-value">{{ providerSet.size }}</div>
          <div class="summary-label">{{ t('models.providers') }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <el-table :data="filtered" v-loading="loading" stripe>
        <el-table-column prop="model" :label="t('common.model')" min-width="220" show-overflow-tooltip sortable />
        <el-table-column :label="t('models.providers')" width="180">
          <template #default="{ row }">
            <el-tag v-for="p in row.providers" :key="p" size="small" round style="margin: 2px">{{ p }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="channel_count" :label="t('models.channels')" width="100" align="center" sortable />
        <el-table-column :label="t('models.channelNames')" min-width="200">
          <template #default="{ row }">
            <el-tooltip
              v-for="ch in row.channels"
              :key="ch.id"
              :content="channelPriceLabel(ch)"
              placement="top"
            >
              <el-tag size="small" type="info" style="margin: 2px">{{ ch.name }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column :label="t('models.input')" width="120" align="right" sortable :sort-method="sortByPrompt">
          <template #default="{ row }">
            <el-tag v-if="row.pricing_varies" size="small">{{ t('models.varies') }}</el-tag>
            <span v-else-if="row.pricing" style="font-weight: 500">{{ row.pricing.prompt }}</span>
            <el-tag v-else size="small" type="warning">{{ t('models.na') }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('models.output')" width="120" align="right" sortable :sort-method="sortByCompletion">
          <template #default="{ row }">
            <el-tag v-if="row.pricing_varies" size="small">{{ t('models.varies') }}</el-tag>
            <span v-else-if="row.pricing" style="font-weight: 500">{{ row.pricing.completion }}</span>
            <el-tag v-else size="small" type="warning">{{ t('models.na') }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('models.cached')" width="140" align="right">
          <template #default="{ row }">
            <el-tag v-if="row.pricing_varies" size="small">{{ t('models.varies') }}</el-tag>
            <span v-else-if="row.pricing" :style="{ fontWeight: 500, color: row.pricing.cached > 0 ? '#f59e0b' : '#cbd5e1' }">{{ row.pricing.cached }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { modelsApi } from '@/api/models'
import { useI18n } from '@/i18n'

const { t } = useI18n()
import { ElMessage } from 'element-plus'

const items = ref<any[]>([])
const loading = ref(false)
const search = ref('')
const filtered = ref<any[]>([])

const pricedCount = computed(() => items.value.filter(m => m.has_pricing).length)
const unpricedCount = computed(() => items.value.filter(m => !m.has_pricing).length)
const providerSet = computed(() => {
  const s = new Set<string>()
  items.value.forEach(m => m.providers.forEach((p: string) => s.add(p)))
  return s
})

function onSearch() {
  const q = search.value.toLowerCase()
  filtered.value = q ? items.value.filter(m => m.model.toLowerCase().includes(q)) : items.value
}

function sortByPrompt(a: any, b: any) {
  return (a.pricing?.prompt ?? -1) - (b.pricing?.prompt ?? -1)
}

function sortByCompletion(a: any, b: any) {
  return (a.pricing?.completion ?? -1) - (b.pricing?.completion ?? -1)
}

function channelPriceLabel(channel: any) {
  if (!channel.pricing) return `${channel.name}: unpriced`
  const p = channel.pricing
  return `${channel.name}: $${p.prompt} input / $${p.completion} output / $${p.cached} cache read (${channel.pricing_source})`
}

async function load() {
  loading.value = true
  try {
    const res = await modelsApi.list()
    items.value = res.items
    filtered.value = res.items
  } catch {
    ElMessage.error(t('models.loadFailed'))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.summary-card :deep(.el-card__body) {
  text-align: center;
  padding: 16px;
}

.summary-card {
  margin-bottom: 12px;
}

.summary-value {
  font-size: 28px;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.summary-label {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}
</style>
