import client from './client'

export const usersApi = {
  list: async (page = 1, size = 20) => {
    const { data } = await client.get('/admin/users', { params: { page, size } })
    return data
  },
  create: async (body: any) => {
    const { data } = await client.post('/admin/users', body)
    return data
  },
  update: async (id: number, body: any) => {
    const { data } = await client.put(`/admin/users/${id}`, body)
    return data
  },
  remove: async (id: number) => {
    const { data } = await client.delete(`/admin/users/${id}`)
    return data
  },
}
