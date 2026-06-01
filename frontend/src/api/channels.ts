import client from './client'

export const channelsApi = {
  list: async (page = 1, size = 20) => {
    const { data } = await client.get('/channels', { params: { page, size } })
    return data
  },
  create: async (body: any) => {
    const { data } = await client.post('/channels', body)
    return data
  },
  update: async (id: number, body: any) => {
    const { data } = await client.put(`/channels/${id}`, body)
    return data
  },
  remove: async (id: number) => {
    const { data } = await client.delete(`/channels/${id}`)
    return data
  },
  test: async (id: number) => {
    const { data } = await client.post(`/channels/${id}/test`)
    return data
  },
  healthStatus: async () => {
    const { data } = await client.get('/channels/health/status')
    return data
  },
  recover: async (id: number) => {
    const { data } = await client.post(`/channels/${id}/recover`)
    return data
  },
  fetchModels: async (id: number) => {
    const { data } = await client.post(`/channels/${id}/fetch-models`)
    return data
  },
  fetchModelsPreview: async (body: { provider: string; base_url: string; api_key: string }) => {
    const { data } = await client.post('/channels/fetch-models-preview', body)
    return data
  },
}
