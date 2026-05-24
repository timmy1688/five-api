import client from './client'

export const logsApi = {
  list: async (params: any) => {
    const { data } = await client.get('/admin/logs', { params })
    return data
  },
  get: async (requestId: string) => {
    const { data } = await client.get(`/admin/logs/${requestId}`)
    return data
  },
  cleanup: async (days?: number) => {
    const { data } = await client.post('/admin/logs/cleanup', null, { params: days ? { days } : {} })
    return data
  },
}
