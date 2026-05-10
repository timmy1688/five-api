import client from './client'

export const authApi = {
  login: async (username: string, password: string) => {
    const { data } = await client.post('/admin/login', { username, password })
    return data
  },
  me: async () => {
    const { data } = await client.get('/admin/me')
    return data
  },
  changePassword: async (old_password: string, new_password: string) => {
    const { data } = await client.put('/admin/password', { old_password, new_password })
    return data
  },
}
