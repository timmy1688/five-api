<template>
  <el-container class="admin-shell">
    <div v-if="mobileMenuOpen" class="sidebar-overlay" @click="mobileMenuOpen = false" />
    <el-aside width="200px" class="sidebar" :class="{ 'mobile-open': mobileMenuOpen }">
      <div class="sidebar-logo">
        <span class="logo-text">Five API</span>
      </div>
      <el-menu
        :default-active="route.path"
        router
        style="border-right: none"
        @select="mobileMenuOpen = false"
      >
        <template v-for="group in visibleNavigation" :key="group.id">
          <el-menu-item-group v-if="group.titleKey" :title="t(group.titleKey)">
            <el-menu-item
              v-for="item in group.items"
              :key="item.path"
              :index="item.path"
            >
              <el-icon><component :is="navigationIcons[item.icon]" /></el-icon>
              <span>{{ t(item.titleKey) }}</span>
            </el-menu-item>
          </el-menu-item-group>
          <el-menu-item
            v-for="item in group.titleKey ? [] : group.items"
            :key="item.path"
            :index="item.path"
          >
            <el-icon><component :is="navigationIcons[item.icon]" /></el-icon>
            <span>{{ t(item.titleKey) }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>
    <el-container class="content-shell">
      <el-header class="top-header">
        <div class="header-left">
          <el-button class="mobile-menu-button" text circle @click="mobileMenuOpen = true">
            <el-icon><Expand /></el-icon>
          </el-button>
        </div>
        <div class="header-right">
          <LangSwitch />
          <el-dropdown trigger="click">
            <div class="user-info">
              <div class="user-avatar">{{ (auth.username || 'A')[0].toUpperCase() }}</div>
              <div class="user-copy">
                <span class="user-name">{{ auth.username }}</span>
                <span v-if="auth.roleName" class="user-role">{{ roleLabel(auth.roleName) }}</span>
              </div>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="handleLogout">{{ t('common.logout') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { navigationGroups } from '@/config/navigation'
import type { NavigationIcon } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'
import LangSwitch from '@/components/LangSwitch.vue'
import { DataBoard, Connection, Key, Document, PriceTag, Menu, FolderOpened, Lock, Expand, User, Warning, Memo, Setting } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t, roleLabel } = useI18n()
const mobileMenuOpen = ref(false)
const navigationIcons: Record<NavigationIcon, unknown> = {
  dashboard: DataBoard,
  channels: Connection,
  models: Menu,
  keys: Key,
  groups: FolderOpened,
  pricing: PriceTag,
  logs: Document,
  audit: Memo,
  security: Warning,
  admins: User,
  roles: Lock,
  settings: Setting,
}
const visibleNavigation = computed(() => navigationGroups
  .map(group => ({
    ...group,
    items: group.items.filter(item => auth.hasPermission(item.permission)),
  }))
  .filter(group => group.items.length > 0))
const mobileMedia = window.matchMedia('(max-width: 720px)')
const syncViewport = () => {
  if (!mobileMedia.matches) mobileMenuOpen.value = false
}

onMounted(() => {
  mobileMedia.addEventListener('change', syncViewport)
})

onUnmounted(() => mobileMedia.removeEventListener('change', syncViewport))

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.admin-shell {
  height: 100vh;
  overflow: hidden;
  background: #f5f6f7;
}

.content-shell {
  height: 100vh;
  min-width: 0;
  overflow: hidden;
}

.sidebar {
  position: relative;
  z-index: 20;
  display: flex;
  height: 100vh;
  flex: 0 0 200px;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  border-right: 1px solid #e6e8ea;
  transition: transform 0.2s ease;
}

.sidebar-logo {
  height: 48px;
  flex: 0 0 48px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  border-bottom: 1px solid #e6e8ea;
}

.logo-text {
  font-size: 15px;
  font-weight: 650;
  color: #1c1f23;
}

.top-header {
  display: flex;
  height: 48px;
  flex: 0 0 48px;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  background: #fff;
  border-bottom: 1px solid #e6e8ea;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.context-title {
  color: #1c1f23;
  font-size: 14px;
  font-weight: 600;
}

.mobile-menu-button {
  display: none;
}

.sidebar-overlay {
  display: none;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 4px;
  border-radius: 6px;
  cursor: pointer;
}

.user-info:hover {
  background: #f5f6f7;
}

.user-avatar {
  width: 24px;
  height: 24px;
  background: #1677ff;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 600;
  font-size: 12px;
}

.user-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.user-name {
  max-width: 120px;
  overflow: hidden;
  color: #1c1f23;
  font-size: 13px;
  text-overflow: ellipsis;
}

.user-role {
  max-width: 120px;
  overflow: hidden;
  color: #8a9099;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.main-content {
  min-height: 0;
  padding: 16px;
  overflow-y: auto;
  background: #f5f6f7;
  scrollbar-color: #d0d3d6 transparent;
  scrollbar-width: thin;
}

:deep(.el-menu) {
  min-height: 0;
  flex: 1;
  overflow-x: hidden;
  overflow-y: auto;
  background: #fff;
  border-right: none;
  padding: 8px;
}

:deep(.el-menu-item) {
  height: 36px;
  line-height: 36px;
  margin: 2px 0;
  border-radius: 6px;
  font-size: 14px;
  color: #1c1f23;
}

:deep(.el-menu-item-group__title) {
  padding: 12px 8px 4px !important;
  color: #8a9099;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0;
}

:deep(.el-menu-item.is-active) {
  background: #e8f3ff !important;
  color: #1677ff !important;
}

:deep(.el-menu-item .el-icon) {
  font-size: 16px;
  color: #646a73;
}

:deep(.el-menu-item.is-active .el-icon) {
  color: #1677ff;
}

:deep(.el-menu-item:hover) {
  background: #f5f6f7;
  color: #1c1f23;
}

@media (max-width: 900px) {
  .sidebar {
    width: 180px !important;
    flex-basis: 180px;
  }

  .user-copy {
    display: none;
  }
}

@media (max-width: 720px) {
  .sidebar {
    position: fixed;
    z-index: 1001;
    top: 0;
    bottom: 0;
    left: 0;
    width: 200px !important;
    height: 100dvh;
    transform: translateX(-100%);
    box-shadow: 16px 0 40px rgba(15, 23, 42, 0.24);
  }

  .sidebar.mobile-open {
    transform: translateX(0);
  }

  .sidebar-overlay {
    display: block;
    position: fixed;
    z-index: 1000;
    inset: 0;
    background: rgba(15, 23, 42, 0.42);
    backdrop-filter: blur(2px);
  }

  .sidebar-logo {
    justify-content: flex-start;
    padding: 0 20px;
  }

  .logo-text {
    display: block;
  }

  .mobile-menu-button {
    display: inline-flex;
  }

  .top-header {
    height: 48px;
  }

  :deep(.el-menu-item) {
    justify-content: flex-start;
    padding: 0 20px !important;
  }

  :deep(.el-menu-item span) {
    display: inline;
  }

  .main-content {
    padding: 12px;
  }
}
</style>
