export type RoomType = 'living' | 'dining' | 'bedroom' | 'other'
export type PrimitiveKind = 'box' | 'cylinder' | 'sphere'

export interface CatalogAsset {
  id: string
  kind: 'model' | 'procedural'
  roomTypes: RoomType[]
  canonicalSize: [number, number, number]
  materialMode: 'replace' | 'tint' | 'preserve'
  delivery?: { url: string; sha256: string; bytes: number }
  fallback: { kind: PrimitiveKind; materialRole: string }
}

export interface AssetCatalog {
  schemaVersion: '2.0'
  id: string
  version: number
  mobileBudgetBytes: number
  assets: CatalogAsset[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isPositiveVector(value: unknown): value is [number, number, number] {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every((entry) => typeof entry === 'number' && Number.isFinite(entry) && entry > 0)
  )
}

export function parseAssetCatalog(value: unknown): AssetCatalog {
  if (
    !isRecord(value) ||
    value.schemaVersion !== '2.0' ||
    typeof value.id !== 'string' ||
    !Number.isInteger(value.version) ||
    typeof value.mobileBudgetBytes !== 'number' ||
    !Array.isArray(value.assets)
  ) {
    throw new Error('资产目录服务返回了无效数据')
  }
  const ids = new Set<string>()
  const assets = value.assets.map((asset): CatalogAsset => {
    if (
      !isRecord(asset) ||
      typeof asset.id !== 'string' ||
      ids.has(asset.id) ||
      !(asset.kind === 'model' || asset.kind === 'procedural') ||
      !Array.isArray(asset.roomTypes) ||
      !isPositiveVector(asset.canonicalSize) ||
      !(
        asset.materialMode === undefined ||
        asset.materialMode === 'replace' ||
        asset.materialMode === 'tint' ||
        asset.materialMode === 'preserve'
      ) ||
      !isRecord(asset.fallback) ||
      !(asset.fallback.kind === 'box' ||
        asset.fallback.kind === 'cylinder' ||
        asset.fallback.kind === 'sphere') ||
      typeof asset.fallback.materialRole !== 'string'
    ) {
      throw new Error('资产目录条目格式无效')
    }
    ids.add(asset.id)
    if (asset.kind === 'model') {
      if (
        !isRecord(asset.delivery) ||
        typeof asset.delivery.url !== 'string' ||
        !/^\/catalog-assets\/models\/[a-z0-9-]+\.glb$/.test(asset.delivery.url) ||
        typeof asset.delivery.sha256 !== 'string' ||
        !/^[0-9a-f]{64}$/.test(asset.delivery.sha256) ||
        typeof asset.delivery.bytes !== 'number' ||
        asset.delivery.bytes <= 0
      ) {
        throw new Error('真实资产交付元数据无效')
      }
    }
    return { ...asset, materialMode: asset.materialMode ?? 'replace' } as unknown as CatalogAsset
  })
  return { ...value, assets } as unknown as AssetCatalog
}
