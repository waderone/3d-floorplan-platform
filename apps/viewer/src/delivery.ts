export interface DeliveryMetadata {
  dataBase?: string
  projectId?: string
  mode?: string
  quality?: string
}

export interface DeliveryConfig {
  bundled: boolean
  dataBase: string
  projectId: string
  initialStyleId: string
  presentationMode: boolean
  highQualityMode: boolean
}

function normalizedBase(value: string | undefined): string {
  const base = (value ?? '').trim().replace(/\/+$/, '')
  if (base.includes('?') || base.includes('#')) {
    throw new Error('客户预览包数据地址格式无效')
  }
  return base
}

export function resolveDeliveryConfig(
  metadata: DeliveryMetadata,
  search: string,
): DeliveryConfig {
  const parameters = new URLSearchParams(search)
  const dataBase = normalizedBase(metadata.dataBase)
  const requestedMode = parameters.get('mode')
  const requestedQuality = parameters.get('quality')
  return {
    bundled: dataBase.length > 0,
    dataBase,
    projectId: parameters.get('project') ?? metadata.projectId?.trim() ?? '',
    initialStyleId: parameters.get('style') ?? 'warm-minimal',
    presentationMode: requestedMode
      ? requestedMode === 'presentation'
      : metadata.mode === 'presentation',
    highQualityMode: requestedQuality
      ? requestedQuality === 'high'
      : metadata.quality === 'high',
  }
}

export function bundleDataUrl(config: DeliveryConfig, path: string): string {
  if (!config.bundled) throw new Error('当前页面不是客户预览包')
  return `${config.dataBase}/${path.replace(/^\/+/, '')}`
}

export function deliveryAssetUrl(
  config: DeliveryConfig,
  apiBase: string,
  path: string,
): string {
  return config.bundled ? `${config.dataBase}${path}` : `${apiBase}${path}`
}
