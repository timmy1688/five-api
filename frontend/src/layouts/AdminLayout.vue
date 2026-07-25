<template>
  <el-container class="admin-shell">
    <div v-if="mobileMenuOpen" class="sidebar-overlay" @click="mobileMenuOpen = false" />
    <el-aside width="232px" class="sidebar" :class="{ 'mobile-open': mobileMenuOpen }">
      <div class="sidebar-logo">
        <div class="logo-icon">F</div>
        <div class="logo-copy">
          <span class="logo-text">Five API</span>
          <span class="logo-caption">AI GATEWAY</span>
        </div>
      </div>
      <el-menu
        :default-active="route.path"
        router
        style="border-right: none"
        @select="mobileMenuOpen = false"
      >
        <el-menu-item-group
          v-for="group in visibleNavigation"
          :key="group.title"
          :title="group.title"
        >
          <el-menu-item
            v-for="item in group.items"
            :key="item.path"
            :index="item.path"
          >
            <el-icon><component :is="navigationIcons[item.icon]" /></el-icon>
            <span>{{ item.title }}</span>
          </el-menu-item>
        </el-menu-item-group>
      </el-menu>
      <div class="sidebar-status">
        <span class="status-indicator" />
        <div>
          <strong>Gateway online</strong>
          <span>Control plane connected</span>
        </div>
      </div>
    </el-aside>
    <el-container class="content-shell">
      <el-header class="top-header">
        <div class="header-left">
          <el-button class="mobile-menu-button" text circle @click="mobileMenuOpen = true">
            <el-icon><Expand /></el-icon>
          </el-button>
          <div class="page-context">
            <span class="context-kicker">CONTROL PLANE</span>
            <span class="context-title">{{ routeTitle }}</span>
          </div>
        </div>
        <div class="header-right">
          <div class="system-pill">
            <span class="system-dot" />
            Operational
          </div>
          <el-dropdown trigger="click">
            <div class="user-info">
              <div class="user-avatar">{{ (auth.username || 'A')[0].toUpperCase() }}</div>
              <div class="user-copy">
                <span class="user-name">{{ auth.username }}</span>
                <span v-if="auth.roleName" class="user-role">{{ auth.roleName }}</span>
              </div>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="handleLogout">Logout</el-dropdown-item>
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
import { DataBoard, Connection, Key, Document, PriceTag, Menu, FolderOpened, Lock, Expand, User } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const mobileMenuOpen = ref(false)
const navigationIcons: Record<NavigationIcon, unknown> = {
  dashboard: DataBoard,
  channels: Connection,
  models: Menu,
  keys: Key,
  groups: FolderOpened,
  pricing: PriceTag,
  logs: Document,
  admins: User,
  roles: Lock,
}
const visibleNavigation = computed(() => navigationGroups
  .map(group => ({
    ...group,
    items: group.items.filter(item => auth.hasPermission(item.permission)),
  }))
  .filter(group => group.items.length > 0))
const routeTitle = computed(() => String(route.meta.title || 'Five API'))
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
  background: #eef3f9;
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
  flex: 0 0 232px;
  flex-direction: column;
  overflow: hidden;
  background:
    radial-gradient(circle at 22px 70px, rgba(76, 201, 240, 0.1), transparent 180px),
    linear-gradient(180deg, #0a1020 0%, #080d19 100%);
  border-right: 1px solid rgba(148, 163, 184, 0.12);
  box-shadow: 18px 0 48px rgba(8, 15, 30, 0.12);
  transition: transform 0.2s ease;
}

.sidebar::after {
  position: absolute;
  inset: 0 0 auto;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(103, 232, 249, 0.5), transparent);
  content: '';
}

.sidebar-logo {
  height: 76px;
  flex: 0 0 76px;
  display: flex;
  align-items: center;
  padding: 0 18px;
  gap: 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
}

.logo-icon {
  position: relative;
  width: 36px;
  height: 36px;
  background: linear-gradient(145deg, #6978ff 0%, #4cc9f0 100%);
  border: 1px solid rgba(255, 255, 255, 0.32);
  border-radius: 10px;
  box-shadow: 0 0 24px rgba(76, 201, 240, 0.22);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 800;
  font-size: 17px;
}

.logo-icon::after {
  position: absolute;
  right: -3px;
  bottom: -3px;
  width: 8px;
  height: 8px;
  border: 2px solid #0a1020;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 10px rgba(52, 211, 153, 0.7);
  content: '';
}

.logo-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.logo-text {
  font-size: 17px;
  font-weight: 750;
  letter-spacing: -0.01em;
  color: #f8fafc;
}

.logo-caption {
  margin-top: 2px;
  color: #52627a;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.2em;
}

.sidebar-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 12px;
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.52);
}

.sidebar-status div {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.sidebar-status strong {
  color: #cbd5e1;
  font-size: 11px;
  font-weight: 600;
}

.sidebar-status div span {
  margin-top: 2px;
  overflow: hidden;
  color: #52627a;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-indicator,
.system-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 0 4px rgba(52, 211, 153, 0.1), 0 0 12px rgba(52, 211, 153, 0.48);
}

.top-header {
  position: relative;
  z-index: 10;
  display: flex;
  height: 70px;
  flex: 0 0 70px;
  align-items: center;
  justify-content: space-between;
  padding: 0 30px;
  background: rgba(248, 251, 255, 0.84);
  border-bottom: 1px solid rgba(203, 213, 225, 0.7);
  box-shadow: 0 8px 30px rgba(15, 23, 42, 0.035);
  backdrop-filter: blur(18px);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-context {
  display: flex;
  flex-direction: column;
}

.context-kicker {
  margin-bottom: 2px;
  color: #8694a8;
  font-size: 9px;
  font-weight: 750;
  letter-spacing: 0.16em;
}

.context-title {
  color: #162033;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.01em;
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
  gap: 10px;
  min-height: 42px;
  padding: 5px 8px 5px 5px;
  border: 1px solid transparent;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease;
}

.user-info:hover {
  border-color: #dbe5f0;
  background: rgba(255, 255, 255, 0.7);
}

.user-avatar {
  width: 31px;
  height: 31px;
  background: linear-gradient(145deg, #5367ed, #4cc9f0);
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 9px;
  box-shadow: 0 4px 12px rgba(83, 103, 237, 0.16);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 600;
  font-size: 13px;
}

.user-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.user-name {
  max-width: 130px;
  overflow: hidden;
  color: #263247;
  font-size: 12px;
  font-weight: 650;
  text-overflow: ellipsis;
}

.user-role {
  max-width: 130px;
  margin-top: 1px;
  overflow: hidden;
  color: #8a98aa;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.system-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 11px;
  border: 1px solid #dfe8f1;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.65);
  color: #64748b;
  font-size: 10px;
  font-weight: 650;
}

.main-content {
  position: relative;
  min-height: 0;
  padding: 30px 34px 48px;
  overflow-y: auto;
  background:
    linear-gradient(rgba(100, 116, 139, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(100, 116, 139, 0.035) 1px, transparent 1px),
    radial-gradient(circle at 88% 2%, rgba(76, 201, 240, 0.09), transparent 25rem),
    radial-gradient(circle at 12% 100%, rgba(83, 103, 237, 0.06), transparent 30rem),
    #f2f6fb;
  background-attachment: local;
  background-size: 28px 28px, 28px 28px, auto, auto, auto;
  scrollbar-color: #c6d1df transparent;
  scrollbar-width: thin;
}

:deep(.el-menu) {
  min-height: 0;
  flex: 1;
  overflow-x: hidden;
  overflow-y: auto;
  background: transparent;
  padding: 10px 6px 18px;
  scrollbar-color: rgba(100, 116, 139, 0.35) transparent;
  scrollbar-width: thin;
}

:deep(.el-menu-item) {
  position: relative;
  height: 42px;
  line-height: 42px;
  margin: 2px 7px;
  border: 1px solid transparent;
  border-radius: 9px;
  font-size: 13px;
  color: #8190a6;
  transition: color 0.16s ease, background 0.16s ease, border-color 0.16s ease;
}

:deep(.el-menu-item-group__title) {
  padding: 17px 18px 6px !important;
  color: #46556b;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

:deep(.el-menu-item.is-active) {
  border-color: rgba(103, 232, 249, 0.14);
  background: linear-gradient(90deg, rgba(83, 103, 237, 0.19), rgba(76, 201, 240, 0.06)) !important;
  color: #e3e9ff !important;
  font-weight: 600;
}

:deep(.el-menu-item.is-active)::before {
  position: absolute;
  left: -8px;
  width: 2px;
  height: 20px;
  border-radius: 2px;
  background: linear-gradient(#818cf8, #4cc9f0);
  box-shadow: 0 0 12px rgba(76, 201, 240, 0.55);
  content: '';
}

:deep(.el-menu-item .el-icon) {
  font-size: 16px;
}

:deep(.el-menu-item.is-active .el-icon) {
  color: #76d9f5;
}

:deep(.el-menu-item:hover) {
  border-color: rgba(148, 163, 184, 0.09);
  background: rgba(255, 255, 255, 0.035);
  color: #d6deea;
}

@media (max-width: 900px) {
  .sidebar {
    width: 188px !important;
    flex-basis: 188px;
  }

  .main-content {
    padding: 20px 16px 32px;
  }

  .logo-text,
  .logo-caption,
  .user-copy {
    display: none;
  }
}

@media (max-width: 600px) {
  .sidebar {
    width: 72px !important;
    flex-basis: 72px;
  }

  .sidebar-logo {
    justify-content: center;
    padding: 0;
  }

  :deep(.el-menu-item) {
    justify-content: center;
    padding: 0 !important;
  }

  :deep(.el-menu-item span),
  :deep(.el-menu-item-group__title) {
    display: none;
  }

  .sidebar-status {
    justify-content: center;
    padding: 12px 0;
  }

  .sidebar-status div {
    display: none;
  }

  .top-header {
    padding: 0 16px;
  }
}

@media (max-width: 720px) {
  .sidebar {
    position: fixed;
    z-index: 1001;
    top: 0;
    bottom: 0;
    left: 0;
    width: 232px !important;
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

  .logo-copy {
    display: flex;
  }

  .logo-text,
  .logo-caption {
    display: block;
  }

  .mobile-menu-button {
    display: inline-flex;
  }

  .top-header {
    height: 58px;
  }

  :deep(.el-menu-item) {
    justify-content: flex-start;
    padding: 0 20px !important;
  }

  :deep(.el-menu-item span) {
    display: inline;
  }

  .sidebar-status {
    justify-content: flex-start;
    padding: 12px;
  }

  .sidebar-status div {
    display: flex;
  }

  .system-pill {
    display: none;
  }

  .main-content {
    padding: 20px 16px 36px;
  }
}
</style>
