import client from './client'

export interface GatewaySettings {
  log_retention_days: number
  channel_health_threshold: number
  channel_health_check_interval: number
  sticky_session_enabled: boolean
  sticky_session_ttl: number
  routing_strategy: 'weighted' | 'least_busy' | 'latency'
  model_fallbacks?: Record<string, string[]>
  auto_cache_control?: boolean
  budget_downgrade?: { threshold: number; rules: Record<string, string> }
  time_pricing?: TimePriceRule[]
}

export interface TimePriceRule {
  name: string
  models: string[]
  channel_ids: number[]
  start: string
  end: string
  utc_offset: number
  multiplier: number
}

export const settingsApi = {
  get: async (): Promise<GatewaySettings> => {
    const { data } = await client.get('/settings')
    return data
  },
  save: async (body: GatewaySettings): Promise<GatewaySettings> => {
    const { data } = await client.put('/settings', body)
    return data
  },
}
