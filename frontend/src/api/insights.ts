import client from './client'

export interface CacheRow {
  requests: number
  prompt_tokens: number
  cached_tokens: number
  cache_write_tokens: number
  hit_rate: number
  cache_savings: number
  cost: number
  date?: string
  model?: string
  api_key_id?: number
  api_key_name?: string
  channel_id?: number
  channel_name?: string
}

export interface CacheStats {
  total: CacheRow
  trend: CacheRow[]
  by_model: CacheRow[]
  by_key: CacheRow[]
  by_channel: CacheRow[]
}

export interface SessionRow {
  session_id: string
  api_key_name: string
  model: string
  requests: number
  cost: number
  prompt_tokens: number
  cached_tokens: number
  cache_write_tokens: number
  completion_tokens: number
  hit_rate: number
  cache_savings: number
  first_at: string
  last_at: string
}

export const insightsApi = {
  cache: async (days = 7): Promise<CacheStats> => {
    const { data } = await client.get('/stats/cache', { params: { days } })
    return data
  },
  sessions: async (days = 7, sort = 'cost'): Promise<{ total: number; items: SessionRow[] }> => {
    const { data } = await client.get('/stats/sessions', { params: { days, sort } })
    return data
  },
  session: async (id: string) => {
    const { data } = await client.get(`/stats/sessions/${id}`)
    return data
  },
}
