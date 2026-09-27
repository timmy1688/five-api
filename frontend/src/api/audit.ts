import client from './client'

export const auditApi = {
  keys: async () => {
    const { data } = await client.get('/audit/keys')
    return data
  },
  requests: async (keyId: number, page = 1) => {
    const { data } = await client.get(`/audit/keys/${keyId}/requests`, { params: { page } })
    return data
  },
  review: async (requestIds: string[]) => {
    const { data } = await client.post('/audit/review', { request_ids: requestIds })
    return data
  },
}
