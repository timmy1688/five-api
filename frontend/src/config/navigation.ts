export type NavigationName =
  | 'Dashboard'
  | 'Channels'
  | 'Models'
  | 'ApiKeys'
  | 'ModelGroups'
  | 'ModelPrices'
  | 'Logs'
  | 'Audit'
  | 'Security'
  | 'Admins'
  | 'Roles'
  | 'Settings'

export type NavigationIcon =
  | 'dashboard'
  | 'channels'
  | 'models'
  | 'keys'
  | 'groups'
  | 'pricing'
  | 'logs'
  | 'audit'
  | 'security'
  | 'admins'
  | 'roles'
  | 'settings'

export interface NavigationItem {
  path: string
  name: NavigationName
  titleKey: 'nav.overview' | 'nav.channels' | 'nav.models' | 'nav.keys' | 'nav.groups' | 'nav.pricing' | 'nav.logs' | 'nav.audit' | 'nav.security' | 'nav.admins' | 'nav.roles' | 'nav.settings'
  permission: string
  icon: NavigationIcon
}

export interface NavigationGroup {
  id: string
  titleKey?: 'nav.upstream' | 'nav.access' | 'nav.operations' | 'nav.system'
  items: NavigationItem[]
}

export const navigationGroups: NavigationGroup[] = [
  {
    id: 'overview',
    items: [
      { path: '/', name: 'Dashboard', titleKey: 'nav.overview', permission: 'stat:read', icon: 'dashboard' },
    ],
  },
  {
    id: 'upstream',
    titleKey: 'nav.upstream',
    items: [
      { path: '/channels', name: 'Channels', titleKey: 'nav.channels', permission: 'channel:read', icon: 'channels' },
      { path: '/models', name: 'Models', titleKey: 'nav.models', permission: 'channel:read', icon: 'models' },
      { path: '/model-prices', name: 'ModelPrices', titleKey: 'nav.pricing', permission: 'model_price:read', icon: 'pricing' },
    ],
  },
  {
    id: 'access',
    titleKey: 'nav.access',
    items: [
      { path: '/keys', name: 'ApiKeys', titleKey: 'nav.keys', permission: 'key:read', icon: 'keys' },
      { path: '/model-groups', name: 'ModelGroups', titleKey: 'nav.groups', permission: 'model_group:read', icon: 'groups' },
    ],
  },
  {
    id: 'operations',
    titleKey: 'nav.operations',
    items: [
      { path: '/logs', name: 'Logs', titleKey: 'nav.logs', permission: 'log:read', icon: 'logs' },
      { path: '/audit', name: 'Audit', titleKey: 'nav.audit', permission: 'security:read', icon: 'audit' },
      { path: '/security', name: 'Security', titleKey: 'nav.security', permission: 'security:read', icon: 'security' },
    ],
  },
  {
    id: 'system',
    titleKey: 'nav.system',
    items: [
      { path: '/admins', name: 'Admins', titleKey: 'nav.admins', permission: 'user:read', icon: 'admins' },
      { path: '/roles', name: 'Roles', titleKey: 'nav.roles', permission: 'role:read', icon: 'roles' },
      { path: '/settings', name: 'Settings', titleKey: 'nav.settings', permission: 'setting:read', icon: 'settings' },
    ],
  },
]

export const navigationItems = navigationGroups.flatMap(group => group.items)

export function firstAllowedPath(hasPermission: (permission: string) => boolean): string | null {
  return navigationItems.find(item => hasPermission(item.permission))?.path ?? null
}
