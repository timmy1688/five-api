import client from './client'

export const modelsApi = {
  list: async () => {
    const { data } = await client.get('/models')
    return data
  },
}
