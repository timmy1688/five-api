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
  audit: async (requestId: string) => {
    const { data } = await client.get(`/logs/${requestId}/audit`)
    return data
  },
}
