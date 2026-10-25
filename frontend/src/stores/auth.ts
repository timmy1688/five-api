import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref('')
  const role = ref<'platform_admin' | 'tenant' | ''>('')
  const roleName = computed(() => role.value)
  const isPlatformAdmin = computed(() => role.value === 'platform_admin')
  const mustChangePassword = ref(false)
  const profileLoaded = ref(false)
  let profileRequest: Promise<void> | null = null

  function setToken(value: string) {
    token.value = value
    localStorage.setItem('token', value)
  }

  async function login(user: string, password: string) {
    const res = await authApi.login(user, password)
    setToken(res.access_token)
    profileLoaded.value = false
    try { await ensureProfile() } catch (error) { logout(); throw error }
  }

  async function changePassword(oldPassword: string, newPassword: string) {
    const res = await authApi.changePassword(oldPassword, newPassword)
    setToken(res.access_token)
    mustChangePassword.value = false
  }

  function logout() {
    token.value = ''
    username.value = ''
    role.value = ''
    mustChangePassword.value = false
    profileLoaded.value = false
    profileRequest = null
    localStorage.removeItem('token')
  }

  async function fetchMe() {
    const res = await authApi.me()
    username.value = res.username
    role.value = res.role
    mustChangePassword.value = Boolean(res.must_change_password)
    profileLoaded.value = true
  }

  async function ensureProfile() {
    if (profileLoaded.value) return
    if (!profileRequest) profileRequest = fetchMe().finally(() => { profileRequest = null })
    await profileRequest
  }

  return { token, username, role, roleName, isPlatformAdmin, mustChangePassword, profileLoaded,
    login, changePassword, logout, fetchMe, ensureProfile }
})
