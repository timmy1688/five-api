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
    if (name === 'platform_admin') return t('role.superAdmin')
    if (name === 'tenant') return t('role.viewer')
    return name
  }


  return { t, roleLabel, locale }
}
