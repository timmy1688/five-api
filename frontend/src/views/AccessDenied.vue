<template>
  <div class="access-denied">
    <el-result
      icon="warning"
      :title="t('denied.title')"
      :sub-title="t('denied.subtitle')"
    >
      <template #extra>
        <el-button type="primary" @click="auth.logout(); router.push('/login')">
          {{ t('denied.signOut') }}
        </el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()
</script>

<style scoped>
.access-denied {
  display: grid;
  min-height: 70vh;
  place-items: center;
}
</style>
