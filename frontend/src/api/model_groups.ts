import client from './client'

export const modelGroupsApi = {
  list: async (page = 1, size = 20) => {
    const { data } = await client.get('/model-groups', { params: { page, size } })
    return data
  },
  listAll: async () => {
    const { data } = await client.get('/model-groups/all')
    return data
  },
  create: async (body: any) => {
    const { data } = await client.post('/model-groups', body)
    return data
  },
  update: async (id: number, body: any) => {
    const { data } = await client.put(`/model-groups/${id}`, body)
    return data
  },
  remove: async (id: number) => {
    const { data } = await client.delete(`/model-groups/${id}`)
    return data
  },
}
