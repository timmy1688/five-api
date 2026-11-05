import client from './client'

export const usersApi = {
  list: async (page = 1, size = 20) => {
    const { data } = await client.get('/users', { params: { page, size } })
    return data
  },
  create: async (body: any) => {
    const { data } = await client.post('/users', body)
    return data
  },
  update: async (id: number, body: any) => {
    const { data } = await client.put(`/users/${id}`, body)
    return data
  },
  /** Generates a one-time temporary password and returns it once as `temporary_password`. */
  resetPassword: async (id: number) => {
    const { data } = await client.put(`/users/${id}/password`, {})
    return data
  },
  remove: async (id: number) => {
    const { data } = await client.delete(`/users/${id}`)
    return data
  },
}
