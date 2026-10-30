import client from './client'

export const modelsApi = {
  checkSettings: async () => (await client.get('/models/check-settings')).data,
  saveCheckSettings: async (body: any) => (await client.put('/models/check-settings', body)).data,
  probe: async (channel_id: number, model: string, kind: 'health' | 'capability') =>
    (await client.post('/models/probe', { channel_id, model, kind }, { timeout: 70000 })).data,
  probes: async (channel_id: number, model: string, page = 1, kind: '' | 'health' | 'capability' = '') =>
    (await client.get('/models/probes', { params: { channel_id, model, page, size: 10, ...(kind ? { kind } : {}) } })).data,
  list: async () => {
    const { data } = await client.get('/models')
    return data
  },
}
