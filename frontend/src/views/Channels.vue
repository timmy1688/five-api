<template>
  <div>
    <div class="page-header">
      <div>
        <h3>Channels</h3>
        <p>Manage upstream LLM provider connections</p>
      </div>
      <el-button v-if="auth.hasPermission('channel:write')" type="primary" @click="openCreate">Add Channel</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="channels" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="Name" min-width="120" show-overflow-tooltip />
        <el-table-column prop="provider" label="Provider" width="100">
          <template #default="{ row }">
            <el-tag size="small" round>{{ row.provider }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Health" width="72" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="healthMap[row.id]" :content="healthMap[row.id].healthy ? 'Healthy' : `Unhealthy (${healthMap[row.id].fail_count} failures)`">
              <span :style="{ color: healthMap[row.id].healthy ? '#10b981' : '#ef4444', fontSize: '18px', cursor: 'pointer' }">&#9679;</span>
            </el-tooltip>
            <span v-else style="color: #c0c4cc; font-size: 18px">&#9679;</span>
          </template>
        </el-table-column>
        <el-table-column label="Models" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="m in row.models" :key="m" size="small" style="margin: 2px">{{ m }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="Priority" width="80" align="center" />
        <el-table-column prop="weight" label="Weight" width="72" align="center" />
        <el-table-column label="Enabled" width="76" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_enabled" :disabled="!auth.hasPermission('channel:write')" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column v-if="auth.hasPermission('channel:write')" label="Actions" width="230" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">Edit</el-button>
            <el-button text type="success" size="small" @click="testChannel(row)">Test</el-button>
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

    <el-dialog v-model="dialogVisible" :title="editingId ? 'Edit Channel' : 'Add Channel'" width="640px" top="5vh">
      <el-form :model="form" label-width="130px" class="channel-form" style="padding: 0 8px">
        <el-form-item label="Name">
          <el-input v-model="form.name" placeholder="e.g. OpenAI Official" />
          <div class="form-hint">给渠道起个名字，方便在日志和列表中识别</div>
        </el-form-item>

        <el-form-item label="Provider">
          <el-select v-model="form.provider" style="width: 100%">
            <el-option label="OpenAI" value="openai">
              <span>OpenAI</span>
              <span class="option-hint">OpenAI 协议：官方 / 第三方中转 / Gemini / Qwen 等兼容端点</span>
            </el-option>
            <el-option label="Anthropic" value="anthropic">
              <span>Anthropic</span>
              <span class="option-hint">Anthropic 协议，使用 /v1/messages 接口</span>
            </el-option>
          </el-select>
          <div class="form-hint">选择上游端点的线协议：OpenAI 兼容端点（含 Gemini/Qwen 中转）选 OpenAI，Claude 系列选 Anthropic</div>
        </el-form-item>

        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" :placeholder="baseUrlPlaceholder" />
          <div class="form-hint">上游 API 地址，不含 /v1 后缀。如使用第三方中转填其域名即可</div>
        </el-form-item>

        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password placeholder="上游平台提供的 API Key" />
          <div class="form-hint">上游提供商的密钥，编辑时留空表示不修改</div>
        </el-form-item>

        <el-divider content-position="left" style="margin: 20px 0 16px">模型配置</el-divider>

        <el-form-item label="Models">
          <div style="display: flex; gap: 8px; width: 100%">
            <el-select v-model="form.models" multiple filterable allow-create style="flex: 1" placeholder="输入模型名后按 Enter 添加">
            </el-select>
            <el-button @click="fetchModels" :loading="fetchingModels" :disabled="!form.base_url || !form.api_key">Fetch</el-button>
          </div>
          <div class="form-hint">此渠道支持的模型列表。点击 Fetch 从上游自动拉取，或手动输入模型名按回车添加</div>
        </el-form-item>

        <el-form-item label="Model Mapping">
          <div class="form-hint" style="margin-bottom: 8px">
            模型别名映射：左侧填客户端请求的名称，右侧填实际发送给上游的名称。<br/>
            例如客户端请求 <code>gpt-4</code>，实际转发为 <code>gpt-4o</code>
          </div>
          <div v-for="(val, key, idx) in form.model_mapping" :key="idx" style="display: flex; gap: 8px; margin-bottom: 4px">
            <el-input :model-value="key" disabled style="width: 45%" />
            <span class="mapping-arrow">&rarr;</span>
            <el-input :model-value="val" disabled style="width: 45%" />
            <el-button text type="danger" @click="removeMapping(key as string)">X</el-button>
          </div>
          <div style="display: flex; gap: 8px; align-items: center">
            <el-input v-model="newMappingKey" placeholder="客户端模型名" style="width: 45%" />
            <span class="mapping-arrow">&rarr;</span>
            <el-input v-model="newMappingVal" placeholder="上游实际模型名" style="width: 45%" />
            <el-button text type="primary" @click="addMapping">+</el-button>
          </div>
        </el-form-item>

        <el-divider content-position="left" style="margin: 20px 0 16px">路由与计费</el-divider>

        <el-form-item label="Priority">
          <el-input-number v-model="form.priority" :min="0" />
          <div class="form-hint">多个渠道支持同一模型时，优先选择数值更高的渠道</div>
        </el-form-item>

        <el-form-item label="Weight">
          <el-input-number v-model="form.weight" :min="1" />
          <div class="form-hint">同 Priority 的渠道之间按权重随机分配流量。如 A=3, B=1 则 A 分到 75% 请求</div>
        </el-form-item>

        <el-form-item label="Timeout (s)">
          <el-input-number v-model="form.timeout" :min="10" :max="600" />
          <div class="form-hint">上游请求超时时间（秒）</div>
        </el-form-item>

        <el-form-item label="Custom Pricing">
          <div class="form-hint" style="margin-bottom: 8px">
            为此渠道单独设置模型价格（$/1M tokens），覆盖全局定价表。留空则使用全局价格。<br/>
            P = Prompt 输入价格，C = Completion 输出价格，Ca = 缓存命中价格
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
            <el-input v-model="newPricingModel" placeholder="模型名" style="width: 24%" />
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

const auth = useAuthStore()

const channels = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
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
  priority: 0, weight: 1, timeout: 120,
})
const form = ref(emptyForm())

async function load() {
  loading.value = true
  try {
    const res = await channelsApi.list(page.value)
    channels.value = res.items
    total.value = res.total
    loadHealth()
  } catch {
    ElMessage.error('Failed to load channels')
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
  } catch {
    ElMessage.error('Recover failed')
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
  } catch {
    ElMessage.error('Failed to fetch models')
  } finally {
    fetchingModels.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row: any) {
  editingId.value = row.id
  form.value = { ...row, models: [...row.models], model_mapping: { ...row.model_mapping }, model_pricing: { ...row.model_pricing } }
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
  } catch {
    ElMessage.error('Save failed')
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await channelsApi.remove(id)
    ElMessage.success('Deleted')
    await load()
  } catch {
    ElMessage.error('Delete failed')
  }
}

async function toggleEnabled(row: any) {
  try {
    await channelsApi.update(row.id, { is_enabled: row.is_enabled })
  } catch {
    row.is_enabled = !row.is_enabled
    ElMessage.error('Update failed')
  }
}

async function testChannel(row: any) {
  try {
    const res = await channelsApi.test(row.id)
    if (res.success) ElMessage.success(`Test passed (${res.status_code})`)
    else ElMessage.error(`Test failed: ${res.error || res.status_code}`)
  } catch {
    ElMessage.error('Test request failed')
  }
}

onMounted(load)
</script>

<style scoped>
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
</style>
