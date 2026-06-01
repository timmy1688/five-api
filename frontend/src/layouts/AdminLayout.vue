<template>
  <el-container style="height: 100vh">
    <el-aside width="220px" style="background: #fff; border-right: 1px solid #f1f5f9">
      <div class="sidebar-logo">
        <div class="logo-icon">F</div>
        <span class="logo-text">Five API</span>
      </div>
      <el-menu
        :default-active="route.path"
        router
        style="border-right: none"
      >
        <el-menu-item v-if="auth.hasPermission('stat:read')" index="/">
          <el-icon><DataBoard /></el-icon>
          <span>Dashboard</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('channel:read')" index="/channels">
          <el-icon><Connection /></el-icon>
          <span>Channels</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('channel:read')" index="/models">
          <el-icon><Menu /></el-icon>
          <span>Models</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('key:read')" index="/keys">
          <el-icon><Key /></el-icon>
          <span>API Keys</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('model_group:read')" index="/model-groups">
          <el-icon><FolderOpened /></el-icon>
          <span>Model Groups</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('model_price:read')" index="/model-prices">
          <el-icon><PriceTag /></el-icon>
          <span>Pricing</span>
        </el-menu-item>
        <el-menu-item v-if="auth.hasPermission('log:read')" index="/logs">
          <el-icon><Document /></el-icon>
          <span>Logs</span>
        </el-menu-item>
        <el-sub-menu v-if="auth.hasAnyPermission('user:read', 'role:read')" index="permission">
          <template #title>
            <el-icon><Lock /></el-icon>
            <span>Permissions</span>
          </template>
          <el-menu-item v-if="auth.hasPermission('user:read')" index="/admins">
            <span>Authorization</span>
          </el-menu-item>
          <el-menu-item v-if="auth.hasPermission('role:read')" index="/roles">
            <span>Roles</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="top-header">
        <div class="header-left" />
        <div class="header-right">
          <el-dropdown trigger="click">
            <div class="user-info">
              <div class="user-avatar">{{ (auth.username || 'A')[0].toUpperCase() }}</div>
              <span class="user-name">{{ auth.username }}</span>
              <el-tag v-if="auth.roleName" size="small" round style="margin-left: 6px">{{ auth.roleName }}</el-tag>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="handleLogout">Logout</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main style="background: #f8fafc; padding: 28px">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { DataBoard, Connection, Key, Document, PriceTag, Menu, FolderOpened, Lock } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

onMounted(() => {
  auth.fetchMe().catch(() => {})
})

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.sidebar-logo {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 12px;
  border-bottom: 1px solid #f1f5f9;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 800;
  font-size: 16px;
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.top-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #f1f5f9;
  height: 64px;
  padding: 0 28px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.user-avatar {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 600;
  font-size: 13px;
}

.user-name {
  font-size: 14px;
  font-weight: 500;
  color: #334155;
}

:deep(.el-menu-item) {
  height: 44px;
  line-height: 44px;
  margin: 2px 8px;
  border-radius: 8px;
  font-size: 14px;
  color: #64748b;
}

:deep(.el-menu-item.is-active) {
  background: #eef2ff !important;
  color: #6366f1 !important;
  font-weight: 600;
}

:deep(.el-menu-item:hover) {
  background: #f8fafc;
}

:deep(.el-sub-menu__title) {
  height: 44px;
  line-height: 44px;
  margin: 2px 8px;
  border-radius: 8px;
  font-size: 14px;
  color: #64748b;
}

:deep(.el-sub-menu__title:hover) {
  background: #f8fafc;
}

:deep(.el-sub-menu .el-menu-item) {
  padding-left: 52px !important;
  min-width: auto;
}
</style>
