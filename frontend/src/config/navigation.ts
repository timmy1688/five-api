export type NavigationName =
  | 'Dashboard'
  | 'Insights'
  | 'Onboarding'
  | 'Channels'
  | 'Models'
  | 'ApiKeys'
  | 'Tenants'
  | 'ModelGroups'
  | 'ModelPrices'
  | 'Logs'
  | 'Audit'
  | 'Security'
  | 'Admins'
  | 'Settings'

export type NavigationIcon =
  | 'dashboard'
  | 'insights'
  | 'onboarding'
  | 'channels'
  | 'models'
  | 'keys'
  | 'teams'
  | 'groups'
  | 'pricing'
  | 'logs'
  | 'audit'
  | 'security'
  | 'admins'
  | 'settings'

export interface NavigationItem {
  path: string
  name: NavigationName
  titleKey: 'nav.overview' | 'nav.insights' | 'nav.reconcile' | 'nav.onboarding' | 'nav.channels' | 'nav.models' | 'nav.keys' | 'nav.tenants' | 'nav.groups' | 'nav.pricing' | 'nav.logs' | 'nav.audit' | 'nav.security' | 'nav.admins' | 'nav.settings'
  tenantAccess?: boolean
  icon: NavigationIcon
}

export interface NavigationGroup {
  id: string
  titleKey?: 'nav.upstream' | 'nav.access' | 'nav.accounts' | 'nav.operations' | 'nav.system'
  items: NavigationItem[]
}

export const navigationGroups: NavigationGroup[] = [
  {
    id: 'overview',
    items: [
      { path: '/', name: 'Dashboard', titleKey: 'nav.overview', icon: 'dashboard' },
      { path: '/insights', name: 'Insights', titleKey: 'nav.insights', icon: 'insights' },
    ],
  },
  {
    id: 'upstream',
    titleKey: 'nav.upstream',
    items: [
      { path: '/channels', name: 'Channels', titleKey: 'nav.channels', icon: 'channels' },
      { path: '/models', name: 'Models', titleKey: 'nav.models', icon: 'models' },
      { path: '/model-prices', name: 'ModelPrices', titleKey: 'nav.pricing', icon: 'pricing' },
    ],
  },
  {
    id: 'access',
    titleKey: 'nav.access',
    items: [
      { path: '/onboarding', name: 'Onboarding', titleKey: 'nav.onboarding', icon: 'onboarding' },
      { path: '/keys', name: 'ApiKeys', tenantAccess: true, titleKey: 'nav.keys', icon: 'keys' },
      { path: '/model-groups', name: 'ModelGroups', titleKey: 'nav.groups', icon: 'groups' },
    ],
  },
  {
    id: 'accounts',
    titleKey: 'nav.accounts',
    items: [
      { path: '/tenants', name: 'Tenants', titleKey: 'nav.tenants', icon: 'teams' },
      { path: '/admins', name: 'Admins', titleKey: 'nav.admins', icon: 'admins' },
    ],
  },
  {
    id: 'operations',
    titleKey: 'nav.operations',
    items: [
      { path: '/logs', name: 'Logs', titleKey: 'nav.logs', icon: 'logs' },
      { path: '/audit', name: 'Audit', titleKey: 'nav.audit', icon: 'audit' },
      { path: '/security', name: 'Security', titleKey: 'nav.security', icon: 'security' },
    ],
  },
  {
    id: 'system',
    titleKey: 'nav.system',
    items: [
      { path: '/settings', name: 'Settings', titleKey: 'nav.settings', icon: 'settings' },
    ],
  },
]

export const navigationItems = navigationGroups.flatMap(group => group.items)

export function firstAllowedPath(isPlatformAdmin: boolean): string {
  return isPlatformAdmin ? '/' : '/keys'
}
