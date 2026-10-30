import client from './client'

export interface ChannelModelPrice {
  model: string
  fixed_price: boolean
  prices: { prompt: number; completion: number; cached: number; cache_write: number; request: number } | null
}

export interface KeyChannel {
  id: number
  name: string
  provider: string
  price_multiplier: number
  healthy: boolean
  models: ChannelModelPrice[]
}

export const keysApi = {
  list: async (page = 1, size = 20) => (await client.get('/keys', { params: { page, size } })).data,
  summary: async () => (await client.get('/keys/summary')).data,
  channels: async (tenantId?: number): Promise<KeyChannel[]> =>
    (await client.get('/keys/channels', { params: tenantId ? { tenant_id: tenantId } : {} })).data,
  create: async (body: any) => (await client.post('/keys', body)).data,
  update: async (id: number, body: any) => (await client.put(`/keys/${id}`, body)).data,
  remove: async (id: number) => (await client.delete(`/keys/${id}`)).data,
  usage: async (id: number) => (await client.get(`/keys/${id}/usage`)).data,
}
