import client from './client'

export const tenantsApi = {
  list: async (page = 1, size = 20) => (await client.get('/tenants', { params: { page, size } })).data,
  listAll: async () => (await client.get('/tenants/all')).data,
  create: async (body: any) => (await client.post('/tenants', body)).data,
  update: async (id: number, body: any) => (await client.put(`/tenants/${id}`, body)).data,
  quota: async (id: number, body: any) => (await client.put(`/tenants/${id}/quota`, body)).data,
  password: async (id: number, password: string) => (await client.put(`/tenants/${id}/password`, { password })).data,
}
