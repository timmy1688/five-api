import client from './client'

export const statsApi = {
  overview: async () => {
    const { data } = await client.get('/stats/overview')
    return data
  },
  usage: async (days = 7) => {
    const { data } = await client.get('/stats/usage', { params: { days } })
    return data
  },
  byModel: async (days = 7) => {
    const { data } = await client.get('/stats/by-model', { params: { days } })
    return data
  },
  byKey: async (days = 7) => {
    const { data } = await client.get('/stats/by-key', { params: { days } })
    return data
  },
  byChannel: async (days = 7) => {
    const { data } = await client.get('/stats/by-channel', { params: { days } })
    return data
  },
  errorRate: async (days = 7) => {
    const { data } = await client.get('/stats/error-rate', { params: { days } })
    return data
  },
  latency: async (days = 7) => {
    const { data } = await client.get('/stats/latency', { params: { days } })
    return data
  },
  throughput: async (days = 7) => {
    const { data } = await client.get('/stats/throughput', { params: { days } })
    return data
  },
}
