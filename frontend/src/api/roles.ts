import client from './client'

export const rolesApi = {
  list: async (page = 1, size = 20) => {
    const { data } = await client.get('/roles', { params: { page, size } })
    return data
  },
  listAll: async () => {
    const { data } = await client.get('/roles/all')
    return data
  },
  create: async (body: any) => {
    const { data } = await client.post('/roles', body)
    return data
  },
  update: async (id: number, body: any) => {
    const { data } = await client.put(`/roles/${id}`, body)
    return data
  },
  remove: async (id: number) => {
    const { data } = await client.delete(`/roles/${id}`)
    return data
  },
  permissions: async () => {
    const { data } = await client.get('/roles/permissions')
    return data
  },
}
