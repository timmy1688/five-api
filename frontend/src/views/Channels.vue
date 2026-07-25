<template>
  <div>
    <div class="page-header">
      <div>
        <h3>Channels</h3>
        <p>Connect official APIs, proxy services, and self-hosted models</p>
      </div>
      <el-button v-if="auth.hasPermission('channel:write')" type="primary" @click="openCreate">Add Channel</el-button>
    </div>

    <div class="channel-summary">
      <div class="summary-item"><span>Total</span><strong>{{ total }}</strong></div>
      <div class="summary-item"><span>Enabled</span><strong>{{ enabledCount }}</strong></div>
      <div class="summary-item"><span>Healthy</span><strong class="success-text">{{ healthyCount }}</strong></div>
      <div class="summary-item"><span>Models</span><strong>{{ modelCount }}</strong></div>
    </div>

    <el-card shadow="never">
      <el-table :data="channels" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="Name" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="channel-name">
              <strong>{{ row.name }}</strong>
              <span>{{ compactUrl(row.base_url) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="provider" label="Protocol" width="155">
          <template #default="{ row }">
            <el-tag size="small" round>{{ providerLabel(row.provider) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Health" width="110">
          <template #default="{ row }">
            <div class="health-cell" :class="{ unknown: !healthMap[row.id], unhealthy: healthMap[row.id] && !healthMap[row.id].healthy }">
              <span class="health-dot" />
              <span>{{ !healthMap[row.id] ? 'Unknown' : healthMap[row.id].healthy ? 'Healthy' : 'Unhealthy' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Models" min-width="200">
          <template #default="{ row }">
            <div class="model-tags">
              <el-tag v-for="m in row.models.slice(0, 3)" :key="m" size="small">{{ m }}</el-tag>
              <el-tag v-if="row.models.length > 3" size="small" type="info">+{{ row.models.length - 3 }}</el-tag>
              <span v-if="!row.models.length" class="muted-text">Not configured</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="Priority" width="80" align="center" />
        <el-table-column prop="weight" label="Weight" width="72" align="center" />
        <el-table-column label="Enabled" width="76" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_enabled" :disabled="!auth.hasPermission('channel:write')" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column v-if="auth.hasPermission('channel:write')" label="Actions" width="220" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">Edit</el-button>
            <el-button text type="success" size="small" :loading="testingId === row.id" @click="testChannel(row)">Test</el-button>
            <el-button v-if="healthMap[row.id] && !healthMap[row.id].healthy" text type="warning" size="small" @click="recoverChannel(row)">Recover</el-button>
            <el-popconfirm title="Delete this channel?" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button text type="danger" size="small">Delete</el-button>
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

    <el-dialog v-model="dialogVisible" :title="editingId ? 'Edit channel' : 'Add channel'" width="760px" top="4vh">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="channel-form">
        <el-alert
          v-if="form.provider === 'openai'"
          class="provider-alert"
          title="OpenAI-compatible mode"
          description="Supports OpenAI, DeepSeek, vLLM, Ollama, and compatible gateways. For vLLM, use a URL such as http://127.0.0.1:8000/v1; API Key can be empty."
          type="info"
          :closable="false"
          show-icon
        />

        <div class="form-grid">
        <el-form-item label="Name" prop="name">
          <el-input v-model="form.name" placeholder="e.g. OpenAI Official" />
          <div class="form-hint">A short name shown in routing logs</div>
        </el-form-item>

        <el-form-item label="Provider">
          <el-select v-model="form.provider" style="width: 100%">
            <el-option label="OpenAI Compatible" value="openai">
              <span>OpenAI Compatible</span>
              <span class="option-hint">OpenAI / vLLM / proxy</span>
            </el-option>
            <el-option label="Anthropic" value="anthropic">
              <span>Anthropic</span>
              <span class="option-hint">Native /v1/messages</span>
            </el-option>
          </el-select>
          <div class="form-hint">The wire protocol implemented by the upstream</div>
        </el-form-item>

        <el-form-item label="Base URL" prop="base_url">
          <el-input v-model="form.base_url" :placeholder="baseUrlPlaceholder" />
          <div class="form-hint">Server root and URLs ending in /v1 are both supported</div>
        </el-form-item>

        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password :placeholder="editingId ? 'Leave empty to keep the current key' : 'Optional for self-hosted services'" />
          <div class="form-hint">Optional for local vLLM; encrypted at rest when provided</div>
        </el-form-item>
        </div>

        <el-divider content-position="left">Models</el-divider>

        <el-form-item label="Models">
          <div style="display: flex; gap: 8px; width: 100%">
            <el-select v-model="form.models" multiple filterable allow-create style="flex: 1" placeholder="Enter a model name and press Enter">
            </el-select>
            <el-button @click="fetchModels" :loading="fetchingModels" :disabled="!form.base_url">Fetch</el-button>
          </div>
          <div class="form-hint">Fetch from /models, or type a model name and press Enter</div>
        </el-form-item>

        <el-form-item label="Model Mapping">
          <div class="form-hint" style="margin-bottom: 8px">
            Map a public model alias to the model name expected upstream.<br/>
            Example: client requests <code>my-model</code>, upstream receives <code>local-model</code>.
          </div>
          <div v-for="(val, key, idx) in form.model_mapping" :key="idx" style="display: flex; gap: 8px; margin-bottom: 4px">
            <el-input :model-value="key" disabled style="width: 45%" />
            <span class="mapping-arrow">&rarr;</span>
            <el-input :model-value="val" disabled style="width: 45%" />
            <el-button text type="danger" @click="removeMapping(key as string)">X</el-button>
          </div>
          <div style="display: flex; gap: 8px; align-items: center">
            <el-input v-model="newMappingKey" placeholder="Public model" style="width: 45%" />
            <span class="mapping-arrow">&rarr;</span>
            <el-input v-model="newMappingVal" placeholder="Upstream model" style="width: 45%" />
            <el-button text type="primary" @click="addMapping">+</el-button>
          </div>
        </el-form-item>

        <el-divider content-position="left">Routing and billing</el-divider>

        <div class="routing-grid">
        <el-form-item label="Priority">
          <el-input-number v-model="form.priority" :min="0" />
          <div class="form-hint">Higher values are selected first</div>
        </el-form-item>

        <el-form-item label="Weight">
          <el-input-number v-model="form.weight" :min="1" />
          <div class="form-hint">Traffic share within the same priority</div>
        </el-form-item>

        <el-form-item label="Timeout (s)">
          <el-input-number v-model="form.timeout" :min="10" :max="600" />
          <div class="form-hint">Upstream request timeout</div>
        </el-form-item>

        <el-form-item label="Retries">
          <el-input-number v-model="form.max_retries" :min="0" :max="5" />
          <div class="form-hint">Retries before switching channels</div>
        </el-form-item>
        </div>

        <el-form-item label="Custom Pricing">
          <div class="form-hint" style="margin-bottom: 8px">
            Optional channel price per 1M tokens; overrides global pricing.<br/>
            P = input, C = output, Ca = cached input.
          </div>
          <div v-for="(val, key) in form.model_pricing" :key="key" style="display: flex; gap: 6px; margin-bottom: 4px; align-items: center">
            <el-input :model-value="key" disabled style="width: 24%" />
            <span class="pricing-label">P:</span>
            <el-input-number :model-value="val.prompt" disabled :controls="false" style="width: 20%" />
            <span class="pricing-label">C:</span>
            <el-input-number :model-value="val.completion" disabled :controls="false" style="width: 20%" />
            <span class="pricing-label">Ca:</span>
            <el-input-number :model-value="val.cached" disabled :controls="false" style="width: 20%" />
            <el-button text type="danger" @click="removePricing(key as string)">X</el-button>
          </div>
          <div style="display: flex; gap: 6px; align-items: center">
            <el-input v-model="newPricingModel" placeholder="Model" style="width: 24%" />
            <span class="pricing-label">P:</span>
            <el-input-number v-model="newPricingPrompt" :min="0" :precision="4" :controls="false" placeholder="2.5" style="width: 20%" />
            <span class="pricing-label">C:</span>
            <el-input-number v-model="newPricingCompletion" :min="0" :precision="4" :controls="false" placeholder="10.0" style="width: 20%" />
            <span class="pricing-label">Ca:</span>
            <el-input-number v-model="newPricingCached" :min="0" :precision="4" :controls="false" placeholder="0.3" style="width: 20%" />
            <el-button text type="primary" @click="addPricing">+</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">Save</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { channelsApi } from '@/api/channels'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import type { FormInstance } from 'element-plus'

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
const newMappingKey = ref('')
const newMappingVal = ref('')
const newPricingModel = ref('')
const newPricingPrompt = ref(0)
const newPricingCompletion = ref(0)
const newPricingCached = ref(0)
const healthMap = ref<Record<number, { healthy: boolean; fail_count: number; disabled_at: number | null }>>({})
const fetchingModels = ref(false)
const providerUrlExamples: Record<string, string> = {
  openai: 'https://api.openai.com',
  anthropic: 'https://api.anthropic.com',
}

const baseUrlPlaceholder = computed(() => providerUrlExamples[form.value.provider] || 'https://api.example.com')

const emptyForm = () => ({
  name: '', provider: 'openai', base_url: '', api_key: '',
  models: [] as string[], model_mapping: {} as Record<string, string>,
  model_pricing: {} as Record<string, { prompt: number; completion: number; cached: number }>,
  priority: 0, weight: 1, timeout: 120, max_retries: 1,
})
const form = ref(emptyForm())
const enabledCount = computed(() => channels.value.filter(channel => channel.is_enabled).length)
const healthyCount = computed(() => channels.value.filter(channel => healthMap.value[channel.id]?.healthy).length)
const modelCount = computed(() => new Set(channels.value.flatMap(channel => channel.models)).size)
const rules = {
  name: [{ required: true, message: 'Enter a channel name', trigger: 'blur' }],
  base_url: [
    { required: true, message: 'Enter the upstream Base URL', trigger: 'blur' },
    { pattern: /^https?:\/\/.+/i, message: 'Use a full http:// or https:// URL', trigger: 'blur' },
  ],
}

function providerLabel(provider: string) {
  return provider === 'openai' ? 'OpenAI Compatible' : 'Anthropic'
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

function resetDrafts() {
  newMappingKey.value = ''
  newMappingVal.value = ''
  newPricingModel.value = ''
  newPricingPrompt.value = 0
  newPricingCompletion.value = 0
  newPricingCached.value = 0
}

async function load() {
  loading.value = true
  try {
    const res = await channelsApi.list(page.value)
    channels.value = res.items
    total.value = res.total
    await loadHealth()
  } catch (error) {
    ElMessage.error(apiError(error, 'Failed to load channels'))
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
    ElMessage.success('Channel recovered')
    await loadHealth()
  } catch (error) {
    ElMessage.error(apiError(error, 'Recover failed'))
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
    ElMessage.success(`Fetched ${res.models.length} models, ${added} new added`)
  } catch (error) {
    ElMessage.error(apiError(error, 'Failed to fetch models'))
  } finally {
    fetchingModels.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  resetDrafts()
  dialogVisible.value = true
}

function openEdit(row: any) {
  editingId.value = row.id
  resetDrafts()
  form.value = {
    ...row,
    api_key: '',
    models: [...row.models],
    model_mapping: { ...row.model_mapping },
    model_pricing: { ...row.model_pricing },
  }
  dialogVisible.value = true
}

function addMapping() {
  if (newMappingKey.value && newMappingVal.value) {
    form.value.model_mapping[newMappingKey.value] = newMappingVal.value
    newMappingKey.value = ''
    newMappingVal.value = ''
  }
}

function removeMapping(key: string) {
  delete form.value.model_mapping[key]
}

function addPricing() {
  if (newPricingModel.value) {
    form.value.model_pricing[newPricingModel.value] = { prompt: newPricingPrompt.value, completion: newPricingCompletion.value, cached: newPricingCached.value }
    newPricingModel.value = ''
    newPricingPrompt.value = 0
    newPricingCompletion.value = 0
    newPricingCached.value = 0
  }
}

function removePricing(key: string) {
  delete form.value.model_pricing[key]
}

async function handleSave() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    if (editingId.value) {
      await channelsApi.update(editingId.value, form.value)
    } else {
      await channelsApi.create(form.value)
    }
    dialogVisible.value = false
    ElMessage.success('Saved')
    await load()
  } catch (error) {
    ElMessage.error(apiError(error, 'Save failed'))
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await channelsApi.remove(id)
    ElMessage.success('Deleted')
    await load()
  } catch (error) {
    ElMessage.error(apiError(error, 'Delete failed'))
  }
}

async function toggleEnabled(row: any) {
  try {
    await channelsApi.update(row.id, { is_enabled: row.is_enabled })
  } catch (error) {
    row.is_enabled = !row.is_enabled
    ElMessage.error(apiError(error, 'Update failed'))
  }
}

async function testChannel(row: any) {
  testingId.value = row.id
  try {
    const res = await channelsApi.test(row.id)
    if (res.success) ElMessage.success(`Test passed (${res.status_code})`)
    else ElMessage.error(`Test failed: ${res.error || res.status_code}`)
  } catch (error) {
    ElMessage.error(apiError(error, 'Test request failed'))
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

.provider-alert {
  margin-bottom: 20px;
}

.form-grid,
.routing-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 18px;
}

.channel-form {
  max-height: calc(88vh - 170px);
  overflow-x: hidden;
  overflow-y: auto;
  padding: 2px 8px 8px 2px;
}

.form-hint {
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

.mapping-arrow {
  color: #94a3b8;
  font-size: 14px;
  line-height: 32px;
  flex-shrink: 0;
}

.pricing-label {
  font-size: 12px;
  white-space: nowrap;
  color: #64748b;
  font-weight: 500;
}

.channel-form :deep(.el-divider__text) {
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
}

.channel-form :deep(.el-divider) {
  margin: 22px 0 18px;
}

.channel-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

@media (max-width: 720px) {
  .channel-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .form-grid,
  .routing-grid {
    grid-template-columns: 1fr;
  }

  .summary-item {
    min-height: 60px;
    padding: 12px 14px;
  }
}
</style>
