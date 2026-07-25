export type NavigationName =
  | 'Dashboard'
  | 'Channels'
  | 'Models'
  | 'ApiKeys'
  | 'ModelGroups'
  | 'ModelPrices'
  | 'Logs'
  | 'Admins'
  | 'Roles'

export type NavigationIcon =
  | 'dashboard'
  | 'channels'
  | 'models'
  | 'keys'
  | 'groups'
  | 'pricing'
  | 'logs'
  | 'admins'
  | 'roles'

export interface NavigationItem {
  path: string
  name: NavigationName
  title: string
  permission: string
  icon: NavigationIcon
}

export interface NavigationGroup {
  title: string
  items: NavigationItem[]
}

export const navigationGroups: NavigationGroup[] = [
  {
    title: 'WORKSPACE',
    items: [
      { path: '/', name: 'Dashboard', title: 'Overview', permission: 'stat:read', icon: 'dashboard' },
    ],
  },
  {
    title: 'MODEL ACCESS',
    items: [
      { path: '/channels', name: 'Channels', title: 'Channels', permission: 'channel:read', icon: 'channels' },
      { path: '/models', name: 'Models', title: 'Models', permission: 'channel:read', icon: 'models' },
    ],
  },
  {
    title: 'ACCESS & BILLING',
    items: [
      { path: '/keys', name: 'ApiKeys', title: 'API Keys', permission: 'key:read', icon: 'keys' },
      { path: '/model-groups', name: 'ModelGroups', title: 'Model Groups', permission: 'model_group:read', icon: 'groups' },
      { path: '/model-prices', name: 'ModelPrices', title: 'Model Pricing', permission: 'model_price:read', icon: 'pricing' },
    ],
  },
  {
    title: 'OPERATIONS',
    items: [
      { path: '/logs', name: 'Logs', title: 'Request Logs', permission: 'log:read', icon: 'logs' },
    ],
  },
  {
    title: 'ADMINISTRATION',
    items: [
      { path: '/admins', name: 'Admins', title: 'Admins', permission: 'user:read', icon: 'admins' },
      { path: '/roles', name: 'Roles', title: 'Roles & Permissions', permission: 'role:read', icon: 'roles' },
    ],
  },
]

export const navigationItems = navigationGroups.flatMap(group => group.items)

export function firstAllowedPath(hasPermission: (permission: string) => boolean): string | null {
  return navigationItems.find(item => hasPermission(item.permission))?.path ?? null
}
