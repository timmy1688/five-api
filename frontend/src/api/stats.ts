import client from './client'

export const statsApi = {
  overview: async () => {
    const { data } = await client.get('/admin/stats/overview')
    return data
  },
  usage: async (days = 7) => {
    const { data } = await client.get('/admin/stats/usage', { params: { days } })
    return data
  },
  byModel: async (days = 7) => {
    const { data } = await client.get('/admin/stats/by-model', { params: { days } })
    return data
  },
  byKey: async (days = 7) => {
    const { data } = await client.get('/admin/stats/by-key', { params: { days } })
    return data
  },
}
