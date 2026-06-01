import client from './client'

export const authApi = {
  login: async (username: string, password: string) => {
    const { data } = await client.post('/login', { username, password })
    return data
  },
  me: async () => {
    const { data } = await client.get('/me')
    return data
  },
  changePassword: async (old_password: string, new_password: string) => {
    const { data } = await client.put('/password', { old_password, new_password })
    return data
  },
}
