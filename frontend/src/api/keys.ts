import client from './client'

export const keysApi = {
  list: async (page = 1, size = 20) => {
    const { data } = await client.get('/keys', { params: { page, size } })
    return data
  },
  create: async (body: any) => {
    const { data } = await client.post('/keys', body)
    return data
  },
  update: async (id: number, body: any) => {
    const { data } = await client.put(`/keys/${id}`, body)
    return data
  },
  remove: async (id: number) => {
    const { data } = await client.delete(`/keys/${id}`)
    return data
  },
  resetQuota: async (id: number) => {
    const { data } = await client.post(`/keys/${id}/reset-quota`)
    return data
  },
}
