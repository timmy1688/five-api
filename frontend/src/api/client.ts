import axios from 'axios'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

const client = axios.create({ baseURL: '/api' })

client.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      const auth = useAuthStore()
      auth.logout()
      router.push('/login')
    } else if (err.response?.status === 403 && err.response.data?.detail === 'Password change required') {
      useAuthStore().mustChangePassword = true
      router.push('/password')
    }
    return Promise.reject(err)
  }
)

export default client
