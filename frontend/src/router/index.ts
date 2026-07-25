import { createRouter, createWebHistory } from 'vue-router'
import { firstAllowedPath, navigationItems } from '@/config/navigation'
import type { NavigationName } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'

const viewComponents: Record<NavigationName, () => Promise<unknown>> = {
  Dashboard: () => import('@/views/Dashboard.vue'),
  Channels: () => import('@/views/Channels.vue'),
  Models: () => import('@/views/Models.vue'),
  ApiKeys: () => import('@/views/ApiKeys.vue'),
  ModelGroups: () => import('@/views/ModelGroups.vue'),
  ModelPrices: () => import('@/views/ModelPrices.vue'),
  Logs: () => import('@/views/Logs.vue'),
  Admins: () => import('@/views/Admins.vue'),
  Roles: () => import('@/views/Roles.vue'),
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
        ...navigationItems.map(item => ({
          path: item.path === '/' ? '' : item.path.slice(1),
          name: item.name,
          component: viewComponents[item.name],
          meta: {
            title: item.title,
            permission: item.permission,
          },
        })),
        {
          path: 'forbidden',
          name: 'AccessDenied',
          component: () => import('@/views/AccessDenied.vue'),
          meta: { title: 'Access Denied' },
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (!auth.token) {
    if (to.name === 'Login') return
    return { name: 'Login' }
  }

  try {
    await auth.ensureProfile()
  } catch {
    return { name: 'Login' }
  }

  const fallback = firstAllowedPath(auth.hasPermission)
  if (to.name === 'Login') {
    return fallback ?? { name: 'AccessDenied' }
  }

  const requiredPermission = to.meta.permission as string | undefined
  if (requiredPermission && !auth.hasPermission(requiredPermission)) {
    return fallback && fallback !== to.path
      ? fallback
      : { name: 'AccessDenied' }
  }
})

export default router
