import { createRouter, createWebHistory } from 'vue-router'
import { firstAllowedPath, navigationItems } from '@/config/navigation'
import type { NavigationName } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'

const viewComponents: Record<NavigationName, () => Promise<unknown>> = {
  Dashboard: () => import('@/views/Dashboard.vue'),
  Insights: () => import('@/views/Insights.vue'),
  Onboarding: () => import('@/views/Onboarding.vue'),
  Channels: () => import('@/views/Channels.vue'),
  Models: () => import('@/views/Models.vue'),
  ApiKeys: () => import('@/views/ApiKeys.vue'),
  Tenants: () => import('@/views/Tenants.vue'),
  ModelGroups: () => import('@/views/ModelGroups.vue'),
  ModelPrices: () => import('@/views/ModelPrices.vue'),
  Logs: () => import('@/views/Logs.vue'),
  Audit: () => import('@/views/Audit.vue'),
  Security: () => import('@/views/Security.vue'),
  Admins: () => import('@/views/Admins.vue'),
  Settings: () => import('@/views/Settings.vue'),
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
      path: '/password',
      name: 'ChangePassword',
      component: () => import('@/views/ChangePassword.vue'),
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
            titleKey: item.titleKey,
            tenantAccess: item.tenantAccess,
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

  if (auth.mustChangePassword) {
    return to.name === 'ChangePassword' ? undefined : { name: 'ChangePassword' }
  }
  if (to.name === 'ChangePassword') return

  const fallback = firstAllowedPath(auth.isPlatformAdmin)
  if (to.name === 'Login') {
    return fallback ?? { name: 'AccessDenied' }
  }

  if (!auth.isPlatformAdmin && !to.meta.tenantAccess) return '/keys'

})

export default router
