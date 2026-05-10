import client from './client'

export const modelPricesApi = {
  list: async (page = 1, size = 50) => {
    const { data } = await client.get('/admin/model-prices', { params: { page, size } })
    return data
  },
  create: async (body: { model: string; prompt_price: number; completion_price: number; cached_price: number; currency?: string }) => {
    const { data } = await client.post('/admin/model-prices', body)
    return data
  },
  update: async (id: number, body: Record<string, any>) => {
    const { data } = await client.put(`/admin/model-prices/${id}`, body)
    return data
  },
  remove: async (id: number) => {
    const { data } = await client.delete(`/admin/model-prices/${id}`)
    return data
  },
  syncDefaults: async () => {
    const { data } = await client.post('/admin/model-prices/sync-defaults')
    return data
  },
  unpriced: async () => {
    const { data } = await client.get('/admin/model-prices/unpriced')
    return data
  },
}
