<template>
  <div>
    <div class="page-header">
      <div>
        <h3>{{ t('nav.onboarding') }}</h3>
        <p>{{ t('onboard.subtitle') }}</p>
      </div>
      <el-button v-if="auth.isPlatformAdmin" type="primary" @click="router.push('/keys')">{{ t('onboard.createKey') }}</el-button>
    </div>

    <el-card shadow="never" class="block">
      <el-form label-position="top" class="params">
        <el-form-item :label="t('onboard.baseUrl')">
          <el-input v-model="baseUrl" />
        </el-form-item>
        <el-form-item :label="t('onboard.key')">
          <el-input v-model="apiKey" :placeholder="KEY_PLACEHOLDER" type="password" show-password />
          <div class="hint">{{ t('onboard.keyHint') }}</div>
        </el-form-item>
        <el-form-item :label="t('onboard.model')">
          <el-select v-model="model" filterable allow-create default-first-option style="width: 100%">
            <el-option v-for="m in models" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="block">
      <el-tabs v-model="tab">
        <el-tab-pane v-for="item in snippets" :key="item.id" :label="item.label" :name="item.id">
          <p class="intro">{{ item.intro }}</p>
          <div v-for="(block, index) in item.blocks" :key="index" class="snippet">
            <div class="snippet-head">
              <span>{{ block.title }}</span>
              <el-button size="small" text type="primary" @click="copy(block.code)">{{ t('onboard.copy') }}</el-button>
            </div>
            <pre><code>{{ block.code }}</code></pre>
          </div>
          <p v-if="item.note" class="hint">{{ item.note }}</p>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { modelsApi } from '@/api/models'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const KEY_PLACEHOLDER = 'sk-your-five-api-key'
const { t } = useI18n()
const auth = useAuthStore()
const router = useRouter()
const baseUrl = ref(window.location.origin)
const apiKey = ref('')
const model = ref('')
const models = ref<string[]>([])
const tab = ref('claude')

const key = computed(() => apiKey.value.trim() || KEY_PLACEHOLDER)
const base = computed(() => baseUrl.value.trim().replace(/\/+$/, ''))
const modelName = computed(() => model.value || 'claude-sonnet-4-6')

const snippets = computed(() => [
  {
    id: 'claude',
    label: 'Claude Code',
    intro: t('onboard.claudeIntro'),
    blocks: [
      {
        title: '~/.claude/settings.json',
        code: JSON.stringify({
          env: {
            ANTHROPIC_BASE_URL: base.value,
            ANTHROPIC_AUTH_TOKEN: key.value,
            ANTHROPIC_MODEL: modelName.value,
            ANTHROPIC_SMALL_FAST_MODEL: modelName.value,
          },
        }, null, 2),
      },
      {
        title: t('onboard.shellVariant'),
        code: `export ANTHROPIC_BASE_URL=${base.value}\nexport ANTHROPIC_AUTH_TOKEN=${key.value}\nexport ANTHROPIC_MODEL=${modelName.value}\nclaude`,
      },
    ],
    note: t('onboard.claudeNote'),
  },
  {
    id: 'codex',
    label: 'Codex CLI',
    intro: t('onboard.codexIntro'),
    blocks: [
      {
        title: '~/.codex/config.toml',
        code: `model = "${modelName.value}"\nmodel_provider = "five"\n\n[model_providers.five]\nname = "Five API"\nbase_url = "${base.value}/v1"\nenv_key = "FIVE_API_KEY"\nwire_api = "responses"`,
      },
      { title: 'shell', code: `export FIVE_API_KEY=${key.value}\ncodex` },
    ],
    note: t('onboard.codexNote'),
  },
  {
    id: 'cursor',
    label: 'Cursor',
    intro: t('onboard.cursorIntro'),
    blocks: [
      {
        title: t('onboard.cursorSteps'),
        code: `OpenAI API Key:          ${key.value}\nOverride OpenAI Base URL: ${base.value}/v1\nModel:                   ${modelName.value}`,
      },
    ],
    note: t('onboard.cursorNote'),
  },
  {
    id: 'openai',
    label: 'OpenAI SDK',
    intro: t('onboard.openaiIntro'),
    blocks: [
      {
        title: 'Python',
        code: `from openai import OpenAI\n\nclient = OpenAI(api_key="${key.value}", base_url="${base.value}/v1")\nresp = client.chat.completions.create(\n    model="${modelName.value}",\n    messages=[{"role": "user", "content": "Hello"}],\n)\nprint(resp.choices[0].message.content)`,
      },
      {
        title: 'Node.js',
        code: `import OpenAI from 'openai'\n\nconst client = new OpenAI({ apiKey: '${key.value}', baseURL: '${base.value}/v1' })\nconst resp = await client.chat.completions.create({\n  model: '${modelName.value}',\n  messages: [{ role: 'user', content: 'Hello' }],\n})\nconsole.log(resp.choices[0].message.content)`,
      },
    ],
    note: '',
  },
  {
    id: 'anthropic',
    label: 'Anthropic SDK',
    intro: t('onboard.anthropicIntro'),
    blocks: [
      {
        title: 'Python',
        code: `import anthropic\n\nclient = anthropic.Anthropic(api_key="${key.value}", base_url="${base.value}")\nmsg = client.messages.create(\n    model="${modelName.value}",\n    max_tokens=1024,\n    messages=[{"role": "user", "content": "Hello"}],\n)\nprint(msg.content[0].text)`,
      },
    ],
    note: '',
  },
  {
    id: 'curl',
    label: 'curl',
    intro: t('onboard.curlIntro'),
    blocks: [
      {
        title: 'OpenAI',
        code: `curl ${base.value}/v1/chat/completions \\\n  -H "Authorization: Bearer ${key.value}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${modelName.value}", "messages": [{"role": "user", "content": "Hello"}]}'`,
      },
      {
        title: 'Anthropic',
        code: `curl ${base.value}/v1/messages \\\n  -H "x-api-key: ${key.value}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${modelName.value}", "max_tokens": 256, "messages": [{"role": "user", "content": "Hello"}]}'`,
      },
      { title: t('onboard.checkKey'), code: `curl ${base.value}/v1/me -H "Authorization: Bearer ${key.value}"` },
    ],
    note: '',
  },
])

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(t('onboard.copied'))
  } catch {
    ElMessage.error(t('onboard.copyFailed'))
  }
}

onMounted(async () => {
  if (!auth.isPlatformAdmin) return
  try {
    const data = await modelsApi.list()
    models.value = (data.items || []).map((item: { model: string }) => item.model)
    model.value = models.value[0] ?? ''
  } catch {
    models.value = []
  }
})
</script>

<style scoped>
.block {
  margin-bottom: 12px;
}

.params {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0 16px;
}

@media (max-width: 900px) {
  .params {
    grid-template-columns: 1fr;
  }
}

.intro {
  margin: 0 0 12px;
  font-size: 13px;
  color: #474d57;
}

.snippet {
  margin-bottom: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
}

.snippet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 4px 12px;
  font-size: 12px;
  color: #646a73;
  background: #f7f8fa;
  border-bottom: 1px solid #e5e7eb;
}

pre {
  margin: 0;
  padding: 12px;
  overflow-x: auto;
  font-size: 12.5px;
  line-height: 1.6;
  background: #fbfbfc;
}

.hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: #8f959e;
}
</style>
