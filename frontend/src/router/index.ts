import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routePermissions: Record<string, string> = {
  '/channels': 'channel:read',
  '/models': 'channel:read',
  '/keys': 'key:read',
  '/model-groups': 'model_group:read',
  '/model-prices': 'model_price:read',
  '/logs': 'log:read',
  '/admins': 'user:read',
  '/roles': 'role:read',
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue'),
    },
    {
      path: '/',
      component: () => import('@/layouts/AdminLayout.vue'),
      children: [
        { path: '', name: 'Dashboard', component: () => import('@/views/Dashboard.vue') },
        { path: 'channels', name: 'Channels', component: () => import('@/views/Channels.vue') },
        { path: 'models', name: 'Models', component: () => import('@/views/Models.vue') },
        { path: 'keys', name: 'ApiKeys', component: () => import('@/views/ApiKeys.vue') },
        { path: 'model-groups', name: 'ModelGroups', component: () => import('@/views/ModelGroups.vue') },
        { path: 'model-prices', name: 'ModelPrices', component: () => import('@/views/ModelPrices.vue') },
        { path: 'logs', name: 'Logs', component: () => import('@/views/Logs.vue') },
        { path: 'admins', name: 'Admins', component: () => import('@/views/Admins.vue') },
        { path: 'roles', name: 'Roles', component: () => import('@/views/Roles.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name !== 'Login' && !auth.token) {
    return { name: 'Login' }
  }
  if (to.name === 'Login' && auth.token) {
    return { name: 'Dashboard' }
  }
  const requiredPerm = routePermissions[to.path]
  if (requiredPerm && auth.permissions.length > 0 && !auth.hasPermission(requiredPerm)) {
    return { name: 'Dashboard' }
  }
})

export default router
