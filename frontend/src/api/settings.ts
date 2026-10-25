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
  save: async (body: Partial<GatewaySettings>): Promise<GatewaySettings> => {
    const { data } = await client.put('/settings', body)
    return data
  },
}

export const metricsTokenApi = {
  get: async (): Promise<string> => (await client.get('/settings/metrics-token')).data.token,
  reset: async (): Promise<string> => (await client.post('/settings/metrics-token/reset')).data.token,
}

export type WebhookType = 'feishu' | 'dingtalk' | 'wecom' | 'generic'

export interface AlertWebhook {
  id?: string
  name: string
  type: WebhookType
  url: string
  secret?: string
  has_secret?: boolean
  clear_secret?: boolean
}

export interface AlertSettings {
  enabled: boolean
  webhooks: AlertWebhook[]
  events: Record<'budget' | 'channel' | 'errors', boolean>
  budget_threshold: number
  error_threshold: number
  error_min_requests: number
}

export const alertsApi = {
  get: async (): Promise<AlertSettings> => (await client.get('/settings/alerts')).data,
  save: async (body: AlertSettings): Promise<AlertSettings> => (await client.put('/settings/alerts', body)).data,
  test: async (id = ''): Promise<{ items: { name: string; ok: boolean; error: string }[] }> =>
    (await client.post('/settings/alerts/test', { id })).data,
}
