<template>
  <div class="login-container">
    <div class="ambient ambient-one" />
    <div class="ambient ambient-two" />
    <div class="login-card">
      <div class="login-meta">
        <span>CONTROL PLANE</span>
        <span class="login-status"><i /> Operational</span>
      </div>
      <div class="login-brand">
        <div class="brand-icon">F</div>
        <h1>Five API</h1>
        <p>Sign in to manage your AI gateway</p>
      </div>
      <el-form :model="form" @submit.prevent="handleLogin" label-position="top">
        <el-form-item label="Username">
          <el-input v-model="form.username" placeholder="admin" autofocus size="large" />
        </el-form-item>
        <el-form-item label="Password">
          <el-input v-model="form.password" type="password" placeholder="password" show-password size="large" />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" size="large" style="width: 100%; margin-top: 8px">
          Sign In
        </el-button>
      </el-form>
      <div class="login-footer">
        <span>Secure administrator access</span>
        <span>v0.1</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

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
    ElMessage.error('Login failed')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    linear-gradient(rgba(148, 163, 184, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.055) 1px, transparent 1px),
    radial-gradient(circle at 50% 0%, #17243d 0%, #0a1020 46%, #070b14 100%);
  background-size: 36px 36px, 36px 36px, auto;
}

.login-container::before {
  position: absolute;
  top: 0;
  left: 50%;
  width: min(820px, 90vw);
  height: 1px;
  background: linear-gradient(90deg, transparent, #4cc9f0, transparent);
  box-shadow: 0 0 34px 5px rgba(76, 201, 240, 0.2);
  content: '';
  transform: translateX(-50%);
}

.ambient {
  position: absolute;
  border-radius: 50%;
  filter: blur(1px);
  pointer-events: none;
}

.ambient-one {
  top: 14%;
  right: 12%;
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgba(83, 103, 237, 0.16), transparent 68%);
}

.ambient-two {
  bottom: 2%;
  left: 10%;
  width: 360px;
  height: 360px;
  background: radial-gradient(circle, rgba(76, 201, 240, 0.1), transparent 70%);
}

.login-card {
  position: relative;
  z-index: 1;
  width: min(410px, 100%);
  padding: 28px 32px 24px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 16px;
  background: rgba(11, 18, 33, 0.78);
  box-shadow:
    0 30px 90px rgba(0, 0, 0, 0.36),
    0 0 0 1px rgba(255, 255, 255, 0.025) inset;
  backdrop-filter: blur(22px);
}

.login-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 30px;
  color: #53647d;
  font-size: 9px;
  font-weight: 750;
  letter-spacing: 0.14em;
}

.login-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #708097;
  letter-spacing: 0.04em;
}

.login-status i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 9px rgba(52, 211, 153, 0.7);
}

.login-brand {
  text-align: center;
  margin-bottom: 28px;
}

.brand-icon {
  position: relative;
  width: 52px;
  height: 52px;
  background: linear-gradient(145deg, #6978ff, #4cc9f0);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 14px;
  box-shadow: 0 0 30px rgba(76, 201, 240, 0.2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 800;
  font-size: 21px;
  margin-bottom: 16px;
}

.brand-icon::after {
  position: absolute;
  right: -3px;
  bottom: -3px;
  width: 9px;
  height: 9px;
  border: 2px solid #0d1527;
  border-radius: 50%;
  background: #34d399;
  content: '';
}

.login-brand h1 {
  margin: 0;
  color: #f3f7ff;
  font-size: 25px;
  font-weight: 750;
  letter-spacing: -0.03em;
}

.login-brand p {
  margin: 6px 0 0;
  color: #687990;
  font-size: 12px;
}

.login-card :deep(.el-form-item__label) {
  color: #91a0b5;
  font-size: 11px;
  font-weight: 600;
}

.login-card :deep(.el-input__wrapper) {
  min-height: 42px;
  background: rgba(15, 24, 42, 0.78);
  box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.18) inset !important;
}

.login-card :deep(.el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px #6075ee inset,
    0 0 0 3px rgba(83, 103, 237, 0.13) !important;
}

.login-card :deep(.el-input__inner) {
  color: #e5ecf7;
}

.login-card :deep(.el-button) {
  height: 42px;
  margin-top: 10px !important;
}

.login-footer {
  display: flex;
  justify-content: space-between;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.1);
  color: #526079;
  font-size: 9px;
}

@media (max-width: 480px) {
  .login-card {
    padding: 24px 22px 22px;
  }
}
</style>
