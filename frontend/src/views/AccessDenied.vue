<template>
  <div class="access-denied">
    <el-result
      icon="warning"
      title="No Accessible Pages"
      sub-title="Your role does not currently include permission to view any page."
    >
      <template #extra>
        <el-button type="primary" @click="auth.logout(); router.push('/login')">
          Sign Out
        </el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
</script>

<style scoped>
.access-denied {
  display: grid;
  min-height: 70vh;
  place-items: center;
}
</style>
