import client from './client'

export const channelsApi = {
  list: async (page = 1, size = 20) => {
    const { data } = await client.get('/admin/channels', { params: { page, size } })
    return data
  },
  create: async (body: any) => {
    const { data } = await client.post('/admin/channels', body)
    return data
  },
  update: async (id: number, body: any) => {
    const { data } = await client.put(`/admin/channels/${id}`, body)
    return data
  },
  remove: async (id: number) => {
    const { data } = await client.delete(`/admin/channels/${id}`)
    return data
  },
  test: async (id: number) => {
    const { data } = await client.post(`/admin/channels/${id}/test`)
    return data
  },
}
