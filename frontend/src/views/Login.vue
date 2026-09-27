<template>
  <div class="login-container">
    <div class="login-card">
      <div class="login-toolbar">
        <LangSwitch />
      </div>
      <div class="login-brand">
        <h1>Five API</h1>
        <p>{{ t('login.subtitle') }}</p>
      </div>
      <el-form :model="form" @submit.prevent="handleLogin" label-position="top">
        <el-form-item :label="t('login.username')">
          <el-input v-model="form.username" placeholder="admin" autofocus size="large" />
        </el-form-item>
        <el-form-item :label="t('login.password')">
          <el-input v-model="form.password" type="password" :placeholder="t('login.passwordPlaceholder')" show-password size="large" />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" size="large" style="width: 100%; margin-top: 8px">
          {{ t('login.submit') }}
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { useI18n } from '@/i18n'
import LangSwitch from '@/components/LangSwitch.vue'

const { t } = useI18n()

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = ref({ username: '', password: '' })

async function handleLogin() {
  loading.value = true
  try {
    await auth.login(form.value.username, form.value.password)
    router.push('/')
  } catch {
    ElMessage.error(t('login.failed'))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: #f5f6f7;
}

.login-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.login-card {
  width: min(380px, 100%);
  padding: 16px 28px 24px;
  border: 1px solid #e6e8ea;
  border-radius: 8px;
  background: #fff;
}

.login-brand {
  margin-bottom: 20px;
}

.login-brand h1 {
  margin: 0;
  color: #1c1f23;
  font-size: 20px;
  font-weight: 600;
}

.login-brand p {
  margin: 6px 0 0;
  color: #646a73;
  font-size: 13px;
}

.login-card :deep(.el-form-item__label) {
  color: #1c1f23;
  font-size: 13px;
  font-weight: 500;
}

.login-card :deep(.el-button) {
  height: 36px;
  margin-top: 4px !important;
}

@media (max-width: 480px) {
  .login-card {
    padding: 24px 22px 22px;
  }
}
</style>
