import { defineStore } from 'pinia'
import { ref } from 'vue'

export type LocaleCode = 'en' | 'zh'

function initialLocale(): LocaleCode {
  const saved = localStorage.getItem('locale')
  if (saved === 'en' || saved === 'zh') return saved
  return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en'
}

export const useLocaleStore = defineStore('locale', () => {
  const current = ref<LocaleCode>(initialLocale())

  function apply(code: LocaleCode) {
    current.value = code
    localStorage.setItem('locale', code)
    document.documentElement.lang = code === 'zh' ? 'zh-CN' : 'en'
  }

  apply(current.value)

  return { current, setLocale: apply }
})
