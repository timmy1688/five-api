import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref('')
  const role = ref('')

  async function login(user: string, password: string) {
    const res = await authApi.login(user, password)
    token.value = res.access_token
    username.value = user
    localStorage.setItem('token', res.access_token)
  }

  function logout() {
    token.value = ''
    username.value = ''
    role.value = ''
    localStorage.removeItem('token')
  }

  async function fetchMe() {
    const res = await authApi.me()
    username.value = res.username
    role.value = res.role || 'admin'
  }

  const isAdmin = () => role.value === 'admin'

  return { token, username, role, login, logout, fetchMe, isAdmin }
})
