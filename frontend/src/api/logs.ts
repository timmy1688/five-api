import client from './client'

export const logsApi = {
  list: async (params: any) => {
    const { data } = await client.get('/logs', { params })
    return data
  },
  get: async (requestId: string) => {
    const { data } = await client.get(`/logs/${requestId}`)
    return data
  },
  cleanup: async (days?: number) => {
    const { data } = await client.post('/logs/cleanup', null, { params: days ? { days } : {} })
    return data
  },
}
