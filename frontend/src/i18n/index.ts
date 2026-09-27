import { useLocaleStore } from '@/stores/locale'
import { en, zh, type MessageKey } from './messages'

const catalogs = { en, zh }

export function useI18n() {
  const locale = useLocaleStore()

  function t(key: MessageKey, params?: Record<string, string | number>) {
    let text: string = catalogs[locale.current][key] ?? en[key]
    if (params) {
      for (const [name, value] of Object.entries(params)) {
        text = text.split(`{${name}}`).join(String(value))
      }
    }
    return text
  }

  function roleLabel(name: string) {
    if (name === 'Super Admin') return t('role.superAdmin')
    if (name === 'Viewer') return t('role.viewer')
    return name
  }

  function permissionLabel(permission: string) {
    const [resource, action] = permission.split(':')
    const resourceKey = `perm.${resource}` as MessageKey
    const actionKey = `perm.${action}` as MessageKey
    const resourceText = resourceKey in en ? t(resourceKey) : resource
    const actionText = actionKey in en ? t(actionKey) : action
    return action ? `${resourceText} · ${actionText}` : resourceText
  }

  return { t, roleLabel, permissionLabel, locale }
}
