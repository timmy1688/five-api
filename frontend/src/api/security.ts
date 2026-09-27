import client from './client'

export const securityApi = {
  get: async () => {
    const { data } = await client.get('/security')
    return data
  },
  setEnabled: async (enabled: boolean) => {
    const { data } = await client.put('/security', { enabled })
    return data
  },
  setSecretScan: async (enabled: boolean) => {
    const { data } = await client.put('/security/secret-scan', { enabled })
    return data
  },
  setInferenceAudit: async (enabled: boolean) => {
    const { data } = await client.put('/security/inference-audit', { enabled })
    return data
  },
  setAiAudit: async (payload: { enabled: boolean; model: string; fail_closed: boolean }) => {
    const { data } = await client.put('/security/ai-audit', payload)
    return data
  },
  createKeyword: async (keyword: string, direction: string) => {
    const { data } = await client.post('/security/keywords', { keyword, direction })
    return data
  },
  updateKeyword: async (id: number, payload: { direction?: string; is_enabled?: boolean }) => {
    const { data } = await client.put(`/security/keywords/${id}`, payload)
    return data
  },
  removeKeyword: async (id: number) => {
    await client.delete(`/security/keywords/${id}`)
  },
}
