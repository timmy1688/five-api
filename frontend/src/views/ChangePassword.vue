<template>
  <div class="password-container">
    <div class="password-card">
      <div class="password-toolbar">
        <LangSwitch />
      </div>
      <div class="password-brand">
        <h1>{{ t('password.title') }}</h1>
        <p>{{ auth.mustChangePassword ? t('password.required') : t('password.subtitle') }}</p>
      </div>
      <el-form :model="form" @submit.prevent="handleSubmit" label-position="top">
        <el-form-item :label="t('password.old')">
          <el-input v-model="form.oldPassword" type="password" show-password size="large" autofocus />
        </el-form-item>
        <el-form-item :label="t('password.new')">
          <el-input v-model="form.newPassword" type="password" show-password size="large" :placeholder="t('password.rule')" />
        </el-form-item>
        <el-form-item :label="t('password.confirm')">
          <el-input v-model="form.confirm" type="password" show-password size="large" />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" size="large" class="full">
          {{ t('common.save') }}
        </el-button>
        <el-button v-if="auth.mustChangePassword" text class="full" @click="handleLogout">
          {{ t('common.logout') }}
        </el-button>
        <el-button v-else text class="full" @click="router.push('/')">
          {{ t('common.cancel') }}
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'
import LangSwitch from '@/components/LangSwitch.vue'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = ref({ oldPassword: '', newPassword: '', confirm: '' })

async function handleSubmit() {
  if (form.value.newPassword.length < 8) {
    ElMessage.error(t('password.rule'))
    return
  }
  if (form.value.newPassword !== form.value.confirm) {
    ElMessage.error(t('password.mismatch'))
    return
  }
  loading.value = true
  try {
    await auth.changePassword(form.value.oldPassword, form.value.newPassword)
    ElMessage.success(t('password.changed'))
    router.push('/')
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    ElMessage.error(detail === 'Wrong old password' ? t('password.wrongOld')
      : detail === 'Choose a different password' ? t('password.reused')
        : t('common.saveFailed'))
  } finally {
    loading.value = false
  }
}

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.password-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: #f5f6f7;
}

.password-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.password-card {
  width: min(380px, 100%);
  padding: 16px 28px 24px;
  border: 1px solid #e6e8ea;
  border-radius: 8px;
  background: #fff;
}

.password-brand {
  margin-bottom: 20px;
}

.password-brand h1 {
  margin: 0;
  color: #1c1f23;
  font-size: 20px;
  font-weight: 600;
}

.password-brand p {
  margin: 6px 0 0;
  color: #646a73;
  font-size: 13px;
}

.password-card :deep(.el-form-item__label) {
  color: #1c1f23;
  font-size: 13px;
  font-weight: 500;
}

.full {
  width: 100%;
  margin: 8px 0 0 !important;
}
</style>
