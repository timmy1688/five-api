import client from './client'

export const keysApi = {
  list: async (page = 1, size = 20) => (await client.get('/keys', { params: { page, size } })).data,
  summary: async () => (await client.get('/keys/summary')).data,
  create: async (body: any) => (await client.post('/keys', body)).data,
  update: async (id: number, body: any) => (await client.put(`/keys/${id}`, body)).data,
  remove: async (id: number) => (await client.delete(`/keys/${id}`)).data,
  usage: async (id: number) => (await client.get(`/keys/${id}/usage`)).data,
}
