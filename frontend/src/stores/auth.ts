import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref('')
  const roleName = ref('')
  const permissions = ref<string[]>([])
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
    try {
      await ensureProfile()
    } catch (error) {
      logout()
      throw error
    }
  }

  async function changePassword(oldPassword: string, newPassword: string) {
    const res = await authApi.changePassword(oldPassword, newPassword)
    setToken(res.access_token)
    mustChangePassword.value = false
  }

  function logout() {
    token.value = ''
    username.value = ''
    roleName.value = ''
    permissions.value = []
    mustChangePassword.value = false
    profileLoaded.value = false
    profileRequest = null
    localStorage.removeItem('token')
  }

  async function fetchMe() {
    const res = await authApi.me()
    username.value = res.username
    roleName.value = res.role_name || ''
    permissions.value = res.permissions || []
    mustChangePassword.value = Boolean(res.must_change_password)
    profileLoaded.value = true
  }

  async function ensureProfile() {
    if (profileLoaded.value) return
    if (!profileRequest) {
      profileRequest = fetchMe().finally(() => {
        profileRequest = null
      })
    }
    await profileRequest
  }

  function hasPermission(perm: string): boolean {
    return permissions.value.includes(perm)
  }

  function hasAnyPermission(...perms: string[]): boolean {
    return perms.some(p => permissions.value.includes(p))
  }

  return {
    token,
    username,
    roleName,
    permissions,
    mustChangePassword,
    profileLoaded,
    login,
    changePassword,
    logout,
    fetchMe,
    ensureProfile,
    hasPermission,
    hasAnyPermission,
  }
})
