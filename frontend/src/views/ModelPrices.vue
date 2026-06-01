<template>
  <div>
    <div class="page-header">
      <div>
        <h3>Model Pricing</h3>
        <p>Configure per-model token pricing for cost tracking</p>
      </div>
      <div v-if="auth.hasPermission('model_price:write')" style="display: flex; gap: 8px">
        <el-button @click="syncDefaults" :loading="syncing">Sync Defaults</el-button>
        <el-button type="primary" @click="openCreate">Add Price</el-button>
      </div>
    </div>

    <el-card v-if="unpricedModels.length > 0" shadow="never" style="margin-bottom: 16px">
      <template #header>
        <div style="display: flex; align-items: center; gap: 8px; padding: 0 4px">
          <el-icon color="#f59e0b" :size="18"><WarningFilled /></el-icon>
          <span style="font-weight: 600; font-size: 14px">未设置价格的模型（{{ unpricedModels.length }}）</span>
          <span style="font-size: 12px; color: #94a3b8">以下模型已在渠道中配置但尚未设置价格，请求将无法计费</span>
        </div>
      </template>
      <div class="unpriced-list" style="padding: 4px 20px 16px">
        <div v-for="item in unpricedModels" :key="item.model" class="unpriced-item">
          <div class="unpriced-model">
            <el-tag size="small" type="warning">{{ item.model }}</el-tag>
            <span class="unpriced-channels">
              <span v-for="ch in item.channels" :key="ch" class="channel-tag">{{ ch }}</span>
            </span>
          </div>
          <el-button v-if="auth.hasPermission('model_price:write')" text type="primary" size="small" @click="quickAdd(item.model)">添加价格</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="model" label="Model" min-width="180" show-overflow-tooltip />
        <el-table-column label="Input ($/1M)" width="120" align="right">
          <template #default="{ row }"><span style="font-weight: 500">{{ row.prompt_price }}</span></template>
        </el-table-column>
        <el-table-column label="Output ($/1M)" width="120" align="right">
          <template #default="{ row }"><span style="font-weight: 500">{{ row.completion_price }}</span></template>
        </el-table-column>
        <el-table-column label="Cached ($/1M)" width="120" align="right">
          <template #default="{ row }">
            <span :style="{ fontWeight: 500, color: row.cached_price > 0 ? '#f59e0b' : '#cbd5e1' }">
              {{ row.cached_price }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="Active" width="76" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_active" :disabled="!auth.hasPermission('model_price:write')" @change="toggleActive(row)" />
          </template>
        </el-table-column>
        <el-table-column v-if="auth.hasPermission('model_price:write')" label="Actions" width="140" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEdit(row)">Edit</el-button>
            <el-popconfirm title="Delete this price?" @confirm="handleDelete(row.id)">
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
        :page-size="50"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="(p: number) => { page = p; load() }"
      />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editingId ? 'Edit Price' : 'Add Price'" width="500px">
      <el-form :model="form" label-width="170px">
        <el-form-item label="Model">
          <el-input v-model="form.model" placeholder="gpt-4o" :disabled="!!editingId" />
        </el-form-item>
        <el-form-item label="Input ($/1M tokens)">
          <el-input-number v-model="form.prompt_price" :min="0" :precision="4" :step="0.1" style="width: 100%" />
          <div class="form-hint">输入 token 单价（每百万 token 美元价格）</div>
        </el-form-item>
        <el-form-item label="Output ($/1M tokens)">
          <el-input-number v-model="form.completion_price" :min="0" :precision="4" :step="0.1" style="width: 100%" />
          <div class="form-hint">输出 token 单价</div>
        </el-form-item>
        <el-form-item label="Cached ($/1M tokens)">
          <el-input-number v-model="form.cached_price" :min="0" :precision="4" :step="0.1" style="width: 100%" />
          <div class="form-hint">缓存命中 token 单价，通常远低于 Prompt 价格（Anthropic ~10%，OpenAI ~50%）</div>
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
import { ref, onMounted } from 'vue'
import { modelPricesApi } from '@/api/model_prices'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { WarningFilled } from '@element-plus/icons-vue'

const auth = useAuthStore()

const items = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const dialogVisible = ref(false)
const saving = ref(false)
const syncing = ref(false)
const editingId = ref<number | null>(null)
const unpricedModels = ref<{ model: string; channels: string[] }[]>([])

const emptyForm = () => ({ model: '', prompt_price: 0, completion_price: 0, cached_price: 0 })
const form = ref(emptyForm())

async function load() {
  loading.value = true
  try {
    const res = await modelPricesApi.list(page.value)
    items.value = res.items
    total.value = res.total
  } catch {
    ElMessage.error('Failed to load model prices')
  } finally {
    loading.value = false
  }
}

async function loadUnpriced() {
  try {
    unpricedModels.value = await modelPricesApi.unpriced()
  } catch {
    // silent
  }
}

function quickAdd(model: string) {
  editingId.value = null
  form.value = { ...emptyForm(), model }
  dialogVisible.value = true
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row: any) {
  editingId.value = row.id
  form.value = { model: row.model, prompt_price: row.prompt_price, completion_price: row.completion_price, cached_price: row.cached_price }
  dialogVisible.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editingId.value) {
      await modelPricesApi.update(editingId.value, form.value)
    } else {
      await modelPricesApi.create(form.value)
    }
    dialogVisible.value = false
    ElMessage.success('Saved')
    await load()
    await loadUnpriced()
  } catch {
    ElMessage.error('Save failed')
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  try {
    await modelPricesApi.remove(id)
    ElMessage.success('Deleted')
    await load()
    await loadUnpriced()
  } catch {
    ElMessage.error('Delete failed')
  }
}

async function toggleActive(row: any) {
  try {
    await modelPricesApi.update(row.id, { is_active: row.is_active })
  } catch {
    row.is_active = !row.is_active
    ElMessage.error('Update failed')
  }
}

async function syncDefaults() {
  syncing.value = true
  try {
    const res = await modelPricesApi.syncDefaults()
    ElMessage.success(`${res.created} new model prices imported`)
    await load()
    await loadUnpriced()
  } catch {
    ElMessage.error('Sync failed')
  } finally {
    syncing.value = false
  }
}

onMounted(() => { load(); loadUnpriced() })
</script>

<style scoped>
.form-hint {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
  margin-top: 4px;
}

.unpriced-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.unpriced-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid #f1f5f9;
}

.unpriced-item:last-child {
  border-bottom: none;
}

.unpriced-model {
  display: flex;
  align-items: center;
  gap: 12px;
}

.unpriced-channels {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.channel-tag {
  font-size: 11px;
  color: #94a3b8;
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 3px;
}
</style>
