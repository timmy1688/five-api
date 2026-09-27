import client from './client'

export interface GatewaySettings {
  log_retention_days: number
  channel_health_threshold: number
  channel_health_check_interval: number
  sticky_session_enabled: boolean
  sticky_session_ttl: number
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
