<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.channels') }}</h3>
        <p>{{ t('channels.subtitle') }}</p>
      </div>
      <el-button v-if="auth.isPlatformAdmin" type="primary" @click="openCreate">{{ t('channels.add') }}</el-button>
    </div>

    <div class="channel-summary">
      <div class="summary-item"><span>{{ t('channels.total') }}</span><strong>{{ total }}</strong></div>
      <div class="summary-item"><span>{{ t('common.enabled') }}</span><strong>{{ enabledCount }}</strong></div>
      <div class="summary-item"><span>{{ t('channels.healthy') }}</span><strong class="success-text">{{ healthyCount }}</strong></div>
      <div class="summary-item"><span>{{ t('channels.models') }}</span><strong>{{ modelCount }}</strong></div>
    </div>

    <el-card shadow="never">
      <el-table :data="channels" v-loading="loading" stripe>
        <el-table-column prop="id" :label="t('common.id')" width="60" />
        <el-table-column prop="name" :label="t('common.name')" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="channel-name">
              <strong>{{ row.name }}</strong>
              <span>{{ compactUrl(row.base_url) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="provider" :label="t('channels.protocol')" width="155">
          <template #default="{ row }">
            <el-tag size="small" round>{{ providerLabel(row.provider) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('channels.health')" width="110">
          <template #default="{ row }">
            <div class="health-cell" :class="{ unknown: !healthMap[row.id], unhealthy: healthMap[row.id] && !healthMap[row.id].healthy }">
              <span class="health-dot" />
              <span>{{ !healthMap[row.id] ? t('channels.unknown') : healthMap[row.id].healthy ? t('channels.healthy') : t('channels.unhealthy') }}</span>
            </div>
            <div v-if="row.key_count > 1" class="key-pool">
              {{ t('channels.keyPool', { ready: row.key_count - (healthMap[row.id]?.keys_cooling || 0), total: row.key_count }) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('channels.models')" min-width="200">
          <template #default="{ row }">
            <div class="model-tags">
              <el-tag v-for="m in row.models.slice(0, 3)" :key="m" size="small">{{ m }}</el-tag>
              <el-tag v-if="row.models.length > 3" size="small" type="info">+{{ row.models.length - 3 }}</el-tag>
              <span v-if="!row.models.length" class="muted-text">{{ t('channels.notConfigured') }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('channels.priceColumn')" width="130">
          <template #default="{ row }">
            <span :class="{ 'muted-text': Number(row.price_multiplier) === 1 }">×{{ Number(row.price_multiplier) }}</span>
            <el-tag v-if="Object.keys(row.price_overrides || {}).length" size="small" type="warning" effect="plain" class="fixed-tag">
              {{ t('channels.fixedCount', { n: Object.keys(row.price_overrides).length }) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="priority" :label="t('channels.priority')" width="80" align="center" />
        <el-table-column prop="weight" :label="t('channels.weight')" width="72" align="center" />
        <el-table-column :label="t('common.enabled')" width="76" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_enabled" :disabled="!auth.isPlatformAdmin" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column v-if="auth.isPlatformAdmin" :label="t('common.actions')" width="220" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-button text type="success" size="small" :loading="testingId === row.id" @click="testChannel(row)">{{ t('channels.test') }}</el-button>
            <el-button v-if="healthMap[row.id] && !healthMap[row.id].healthy" text type="warning" size="small" @click="recoverChannel(row)">{{ t('channels.recover') }}</el-button>
            <el-popconfirm :title="t('channels.deleteConfirm')" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button text type="danger" size="small">{{ t('common.delete') }}</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="total > 0"
        style="margin-top: 16px; justify-content: flex-end"
        :current-page="page"
        :page-size="20"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="(p: number) => { page = p; load() }"
      />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editingId ? t('channels.edit') : t('channels.add')" width="820px" top="5vh" class="channel-dialog">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="channel-form">
        <section class="form-section">
          <header class="section-head">
            <h4>{{ t('channels.sectionBasic') }}</h4>
          </header>
          <div class="form-grid">
            <el-form-item :label="t('common.name')" prop="name">
              <el-input v-model="form.name" :placeholder="t('channels.namePlaceholder')" />
            </el-form-item>
            <el-form-item :label="t('channels.provider')">
              <el-select v-model="form.provider" style="width: 100%">
                <el-option :label="t('channels.openai')" value="openai">
                  <span>{{ t('channels.openai') }}</span>
                  <span class="option-hint">{{ t('channels.openaiHint') }}</span>
                </el-option>
                <el-option :label="t('channels.anthropic')" value="anthropic">
                  <span>{{ t('channels.anthropic') }}</span>
                  <span class="option-hint">{{ t('channels.anthropicHint') }}</span>
                </el-option>
              </el-select>
              <div class="form-hint">{{ form.provider === 'openai' ? t('channels.openaiModeHint') : t('channels.anthropicModeHint') }}</div>
            </el-form-item>
            <el-form-item :label="t('channels.baseUrl')" prop="base_url" class="span-2">
              <el-input v-model="form.base_url" :placeholder="baseUrlPlaceholder" />
              <div class="form-hint">{{ t('channels.baseUrlHint') }}</div>
            </el-form-item>
            <el-form-item :label="t('channels.apiKey')" class="span-2">
              <el-input
                v-model="form.api_key"
                type="textarea"
                :autosize="{ minRows: 2, maxRows: 6 }"
                class="secret-textarea"
                :placeholder="editingId ? t('channels.apiKeyKeep') : t('channels.apiKeyOptional')"
              />
              <div class="form-hint">{{ t('channels.apiKeyHint') }}</div>
            </el-form-item>
          </div>
        </section>

        <section class="form-section">
          <header class="section-head">
            <h4>{{ t('channels.sectionModels') }}</h4>
          </header>
          <el-form-item :label="t('channels.models')">
            <div class="inline-row">
              <el-select
                v-model="form.models"
                multiple
                filterable
                allow-create
                default-first-option
                collapse-tags
                :max-collapse-tags="8"
                :placeholder="t('channels.modelsPlaceholder')"
                class="grow"
              />
              <el-button :icon="Download" :loading="fetchingModels" :disabled="!form.base_url" @click="fetchModels">{{ t('channels.fetch') }}</el-button>
            </div>
            <div class="form-hint">{{ t('channels.modelsHint') }}</div>
          </el-form-item>

          <el-form-item :label="t('channels.mapping')">
            <div class="row-table">
              <div v-if="mappingRows.length" class="row-table-head mapping-cols">
                <span>{{ t('channels.publicModel') }}</span>
                <span />
                <span>{{ t('channels.upstreamModel') }}</span>
                <span />
              </div>
              <div v-for="(row, index) in mappingRows" :key="index" class="row-table-row mapping-cols">
                <el-input v-model="row.from" placeholder="my-model" />
                <el-icon class="row-arrow"><Right /></el-icon>
                <el-input v-model="row.to" placeholder="local-model" />
                <el-button text type="danger" :icon="Delete" :aria-label="t('common.delete')" @click="mappingRows.splice(index, 1)" />
              </div>
              <el-button text type="primary" :icon="Plus" class="row-add" @click="mappingRows.push({ from: '', to: '' })">{{ t('channels.addMapping') }}</el-button>
            </div>
            <div class="form-hint">{{ t('channels.mappingHint') }}</div>
          </el-form-item>
        </section>

        <section class="form-section">
          <header class="section-head">
            <h4>{{ t('channels.routing') }}</h4>
          </header>
          <div class="routing-grid">
            <el-form-item :label="t('channels.priority')">
              <el-input-number v-model="form.priority" :min="0" controls-position="right" class="full" />
              <div class="form-hint">{{ t('channels.priorityHint') }}</div>
            </el-form-item>
            <el-form-item :label="t('channels.weight')">
              <el-input-number v-model="form.weight" :min="1" controls-position="right" class="full" />
              <div class="form-hint">{{ t('channels.weightHint') }}</div>
            </el-form-item>
            <el-form-item :label="t('channels.timeout')">
              <el-input-number v-model="form.timeout" :min="10" :max="600" controls-position="right" class="full" />
              <div class="form-hint">{{ t('channels.timeoutHint') }}</div>
            </el-form-item>
            <el-form-item :label="t('channels.retries')">
              <el-input-number v-model="form.max_retries" :min="0" :max="5" controls-position="right" class="full" />
              <div class="form-hint">{{ t('channels.retriesHint') }}</div>
            </el-form-item>
          </div>
        </section>

        <section class="form-section">
          <header class="section-head">
            <h4>{{ t('channels.pricing') }}</h4>
            <p>{{ t('channels.pricingSectionDesc') }}</p>
          </header>
          <div>
            <el-form-item :label="t('channels.priceMultiplier')">
              <el-input-number v-model="form.price_multiplier" :min="0" :max="100" :step="0.1" controls-position="right" style="width: 180px" />
              <div class="form-hint">{{ t('channels.priceMultiplierHint') }}</div>
            </el-form-item>
            <el-form-item :label="t('channels.pricingTable')">
              <div class="row-table">
                <div v-if="pricingRows.length" class="row-table-head pricing-cols">
                  <span>{{ t('common.model') }}</span>
                  <span>{{ t('channels.priceInput') }}</span>
                  <span>{{ t('channels.priceOutput') }}</span>
                  <span>{{ t('channels.priceCacheRead') }}</span>
                  <span>{{ t('channels.priceCacheWrite') }}</span>
                  <span>{{ t('channels.priceRequest') }}</span>
                  <span />
                </div>
                <div v-for="(row, index) in pricingRows" :key="index" class="row-table-row pricing-cols">
                  <el-select v-model="row.model" filterable allow-create default-first-option :placeholder="t('common.model')">
                    <el-option v-for="model in pricingModelOptions" :key="model" :label="model" :value="model" />
                  </el-select>
                  <el-input-number v-model="row.prompt" :min="0" :controls="false" />
                  <el-input-number v-model="row.completion" :min="0" :controls="false" />
                  <el-input-number v-model="row.cached" :min="0" :controls="false" />
                  <el-input-number v-model="row.cache_write" :min="0" :controls="false" :value-on-clear="null" :placeholder="t('channels.sameAsInput')" />
                  <el-input-number v-model="row.request" :min="0" :controls="false" :value-on-clear="null" placeholder="-" />
                  <el-button text type="danger" :icon="Delete" :aria-label="t('common.delete')" @click="pricingRows.splice(index, 1)" />
                </div>
                <el-button text type="primary" :icon="Plus" class="row-add" @click="addPricingRow">{{ t('channels.addPricing') }}</el-button>
              </div>
              <div class="form-hint">{{ t('channels.pricingHint') }}</div>
            </el-form-item>
          </div>
        </section>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { channelsApi } from '@/api/channels'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const { t } = useI18n()
import { ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'
import { Delete, Download, Plus, Right } from '@element-plus/icons-vue'

type ChannelPrice = { prompt: number; completion: number; cached?: number; cache_write?: number; request?: number }
type MappingRow = { from: string; to: string }
type PricingRow = { model: string; prompt: number; completion: number; cached: number; cache_write: number | null; request: number | null }

const auth = useAuthStore()

const channels = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const dialogVisible = ref(false)
const saving = ref(false)
const testingId = ref<number | null>(null)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const mappingRows = ref<MappingRow[]>([])
const pricingRows = ref<PricingRow[]>([])
const healthMap = ref<Record<number, { healthy: boolean; fail_count: number; disabled_at: number | null; keys_total?: number; keys_cooling?: number }>>({})
const fetchingModels = ref(false)
const providerUrlExamples: Record<string, string> = {
  openai: 'https://api.openai.com',
  anthropic: 'https://api.anthropic.com',
}

const baseUrlPlaceholder = computed(() => providerUrlExamples[form.value.provider] || 'https://api.example.com')

const emptyForm = () => ({
  name: '', provider: 'openai', base_url: '', api_key: '',
  models: [] as string[], model_mapping: {} as Record<string, string>,
  price_overrides: {} as Record<string, ChannelPrice>,
  priority: 0, weight: 1, timeout: 120, max_retries: 1, price_multiplier: 1,
})
const form = ref(emptyForm())
const enabledCount = computed(() => channels.value.filter(channel => channel.is_enabled).length)
const pricingModelOptions = computed(() => [
  ...new Set([...form.value.models, ...mappingRows.value.map(row => row.to.trim()).filter(Boolean)]),
])
const healthyCount = computed(() => channels.value.filter(channel => healthMap.value[channel.id]?.healthy).length)
const modelCount = computed(() => new Set(channels.value.flatMap(channel => channel.models)).size)
const rules = computed(() => ({
  name: [{ required: true, message: t('channels.nameRequired'), trigger: 'blur' }],
  base_url: [
    { required: true, message: t('channels.urlRequired'), trigger: 'blur' },
    { pattern: /^https?:\/\/.+/i, message: t('channels.urlInvalid'), trigger: 'blur' },
  ],
}))

function providerLabel(provider: string) {
  return provider === 'openai' ? t('channels.openai') : t('channels.anthropic')
}

function compactUrl(value: string) {
  try {
    const url = new URL(value)
    return `${url.host}${url.pathname === '/' ? '' : url.pathname}`
  } catch {
    return value
  }
}

function apiError(error: any, fallback: string) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

function loadRows(mapping: Record<string, string>, pricing: Record<string, ChannelPrice>) {
  mappingRows.value = Object.entries(mapping).map(([from, to]) => ({ from, to }))
  pricingRows.value = Object.entries(pricing).map(([model, price]) => ({
    model,
    prompt: price.prompt,
    completion: price.completion,
    cached: price.cached ?? 0,
    cache_write: price.cache_write ?? null,
    request: price.request ?? null,
  }))
}

function addPricingRow() {
  pricingRows.value.push({ model: '', prompt: 0, completion: 0, cached: 0, cache_write: null, request: null })
}

/** Converts editable rows back to API objects; returns an error message for incomplete rows. */
function collectRows(): string | null {
  const mapping: Record<string, string> = {}
  for (const row of mappingRows.value) {
    const from = row.from.trim()
    const to = row.to.trim()
    if (!from && !to) continue
    if (!from || !to) return t('channels.mappingIncomplete')
    if (from in mapping) return t('channels.duplicateModel', { model: from })
    mapping[from] = to
  }
  const pricing: Record<string, ChannelPrice> = {}
  for (const row of pricingRows.value) {
    const model = row.model.trim()
    if (!model) return t('channels.pricingModelRequired')
    if (model in pricing) return t('channels.duplicateModel', { model })
    const price: ChannelPrice = { prompt: row.prompt ?? 0, completion: row.completion ?? 0, cached: row.cached ?? 0 }
    if (row.cache_write != null) price.cache_write = row.cache_write
    if (row.request != null) price.request = row.request
    pricing[model] = price
  }
  form.value.model_mapping = mapping
  form.value.price_overrides = pricing
  return null
}

async function load() {
  loading.value = true
  try {
    const res = await channelsApi.list(page.value)
    channels.value = res.items
    total.value = res.total
    await loadHealth()
  } catch (error) {
    ElMessage.error(apiError(error, t('channels.loadFailed')))
  } finally {
    loading.value = false
  }
}

async function loadHealth() {
  try {
    healthMap.value = await channelsApi.healthStatus()
  } catch { /* ignore */ }
}

async function recoverChannel(row: any) {
  try {
    await channelsApi.recover(row.id)
    ElMessage.success(t('channels.recovered'))
    await loadHealth()
  } catch (error) {
    ElMessage.error(apiError(error, t('channels.recoverFailed')))
  }
}

async function fetchModels() {
  fetchingModels.value = true
  try {
    let res
    if (editingId.value) {
      res = await channelsApi.fetchModels(editingId.value)
    } else {
      res = await channelsApi.fetchModelsPreview({
        provider: form.value.provider,
        base_url: form.value.base_url,
        api_key: form.value.api_key,
      })
    }
    const existing = new Set(form.value.models)
    let added = 0
    for (const m of res.models) {
      if (!existing.has(m)) {
        form.value.models.push(m)
        added++
      }
    }
    ElMessage.success(t('channels.fetched', { count: res.models.length, added }))
  } catch (error) {
    ElMessage.error(apiError(error, t('channels.fetchFailed')))
  } finally {
    fetchingModels.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  loadRows({}, {})
  dialogVisible.value = true
}

function openEdit(row: any) {
  editingId.value = row.id
  form.value = {
    ...row,
    api_key: '',
    models: [...row.models],
    model_mapping: { ...row.model_mapping },
    price_overrides: { ...row.price_overrides },
  }
  loadRows(form.value.model_mapping, form.value.price_overrides)
  dialogVisible.value = true
}

async function handleSave() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  const rowError = collectRows()
  if (rowError) {
    ElMessage.warning(rowError)
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      await channelsApi.update(editingId.value, form.value)
    } else {
      await channelsApi.create(form.value)
    }
    dialogVisible.value = false
    ElMessage.success(t('common.saved'))
    await load()
  } catch (error) {
    ElMessage.error(apiError(error, t('common.saveFailed')))
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await channelsApi.remove(id)
    ElMessage.success(t('common.deleted'))
    await load()
  } catch (error) {
    ElMessage.error(apiError(error, t('common.deleteFailed')))
  }
}

async function toggleEnabled(row: any) {
  try {
    await channelsApi.update(row.id, { is_enabled: row.is_enabled })
  } catch (error) {
    row.is_enabled = !row.is_enabled
    ElMessage.error(apiError(error, t('common.updateFailed')))
  }
}

async function testChannel(row: any) {
  testingId.value = row.id
  try {
    const res = await channelsApi.test(row.id)
    if (res.success) ElMessage.success(t('channels.testPassed', { code: res.status_code }))
    else ElMessage.error(t('channels.testFailed', { error: res.error || res.status_code }))
  } catch (error) {
    ElMessage.error(apiError(error, t('channels.testRequestFailed')))
  } finally {
    testingId.value = null
  }
}

onMounted(load)
</script>

<style scoped>
.channel-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.summary-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 70px;
  padding: 16px 18px;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
}

.summary-item span {
  color: #64748b;
  font-size: 13px;
}

.summary-item strong {
  color: #0f172a;
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}

.summary-item .success-text {
  color: #059669;
}

.channel-name {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.channel-name strong {
  overflow: hidden;
  color: #1e293b;
  text-overflow: ellipsis;
}

.channel-name span {
  overflow: hidden;
  color: #94a3b8;
  font-size: 12px;
  text-overflow: ellipsis;
}

.secret-textarea :deep(textarea) {
  font-family: var(--el-font-family-mono, monospace);
  -webkit-text-security: disc;
}

.secret-textarea :deep(textarea:focus) {
  -webkit-text-security: none;
}

.key-pool {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.health-cell {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #059669;
  font-size: 12px;
  font-weight: 600;
}

.health-cell.unknown {
  color: #94a3b8;
}

.health-cell.unhealthy {
  color: #dc2626;
}

.health-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 12%, transparent);
}

.model-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.muted-text {
  color: #94a3b8;
  font-size: 12px;
}

.channel-form {
  max-height: calc(90vh - 160px);
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 6px;
}

.form-section {
  padding: 16px 18px 2px;
  margin-bottom: 14px;
  border: 1px solid #e8edf5;
  border-radius: 10px;
  background: #fff;
}

.form-section:last-child {
  margin-bottom: 0;
}

.section-head {
  position: relative;
  margin-bottom: 14px;
}

.section-head h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: #1e293b;
  font-size: 14px;
  font-weight: 600;
}

.section-head p {
  margin: 4px 0 0;
  padding-right: 28px;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.5;
}

.fixed-tag {
  margin-left: 6px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 16px;
}

.form-grid .span-2 {
  grid-column: span 2;
}

.routing-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  column-gap: 14px;
}

.channel-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.channel-form :deep(.el-form-item__label) {
  color: #475569;
  font-weight: 500;
}

.full {
  width: 100%;
}

.inline-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.grow {
  flex: 1;
  min-width: 0;
}

.row-table {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.row-table-head {
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.4;
}

.row-table-head,
.row-table-row {
  display: grid;
  align-items: center;
  gap: 8px;
}

.mapping-cols {
  grid-template-columns: minmax(0, 1fr) 16px minmax(0, 1fr) 32px;
}

.pricing-cols {
  grid-template-columns: minmax(0, 1.8fr) repeat(5, minmax(0, 1fr)) 32px;
}

.pricing-cols :deep(.el-input-number) {
  width: 100%;
}

.row-arrow {
  color: #94a3b8;
}

.row-add {
  align-self: flex-start;
  padding-left: 0;
}

.form-hint {
  width: 100%;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
  margin-top: 4px;
}

.form-hint code {
  background: #f1f5f9;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12px;
  color: #6366f1;
}

.option-hint {
  float: right;
  font-size: 12px;
  color: #94a3b8;
}

@media (max-width: 720px) {
  .channel-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .form-grid,
  .routing-grid {
    grid-template-columns: 1fr;
  }

  .form-grid .span-2 {
    grid-column: auto;
  }

  .pricing-cols {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .row-table-head.pricing-cols {
    display: none;
  }

  .summary-item {
    min-height: 60px;
    padding: 12px 14px;
  }
}
</style>
