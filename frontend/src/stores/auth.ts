import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref('')
  const roleName = ref('')
  const permissions = ref<string[]>([])

  async function login(user: string, password: string) {
    const res = await authApi.login(user, password)
    token.value = res.access_token
    username.value = user
    localStorage.setItem('token', res.access_token)
  }

  function logout() {
    token.value = ''
    username.value = ''
    roleName.value = ''
    permissions.value = []
    localStorage.removeItem('token')
  }

  async function fetchMe() {
    const res = await authApi.me()
    username.value = res.username
    roleName.value = res.role_name || ''
    permissions.value = res.permissions || []
  }

  function hasPermission(perm: string): boolean {
    return permissions.value.includes(perm)
  }

  function hasAnyPermission(...perms: string[]): boolean {
    return perms.some(p => permissions.value.includes(p))
  }

  return { token, username, roleName, permissions, login, logout, fetchMe, hasPermission, hasAnyPermission }
})
