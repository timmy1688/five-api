import client from './client'

export const teamsApi = {
  list: async (page = 1, size = 20) => {
    const { data } = await client.get('/teams', { params: { page, size } })
    return data
  },
  listAll: async () => {
    const { data } = await client.get('/teams/all')
    return data
  },
  create: async (body: any) => {
    const { data } = await client.post('/teams', body)
    return data
  },
  update: async (id: number, body: any) => {
    const { data } = await client.put(`/teams/${id}`, body)
    return data
  },
  remove: async (id: number) => {
    const { data } = await client.delete(`/teams/${id}`)
    return data
  },
  resetQuota: async (id: number) => {
    const { data } = await client.post(`/teams/${id}/reset-quota`)
    return data
  },
}
