export interface PbrStyleMaterial {
  baseColor: string
  metallic: number
  roughness: number
}

export interface StylePlacement {
  id: string
  assetId: string
  kind: 'box' | 'cylinder' | 'sphere'
  role: string
  position: [number, number, number]
  size: [number, number, number]
  rotationYDegrees: number
}

export interface StylePack {
  schemaVersion: '1.0'
  id: string
  version: number
  name: string
  description: string
  materials: Record<string, PbrStyleMaterial>
  environment: {
    backgroundColor: string
    ambientColor: string
    ambientIntensity: number
    sunColor: string
    sunIntensity: number
    sunDirection: [number, number, number]
  }
  camera: {
    alphaDegrees: number
    betaDegrees: number
    radiusMultiplier: number
  }
  output: { width: number; height: number; samples: number }
  assets: Array<{
    id: string
    kind: 'procedural'
    source: 'project-authored'
    license: { spdx: 'LicenseRef-Project-Authored'; source: 'project-authored' }
  }>
  layout: { floorPadding: number; placements: StylePlacement[] }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function parseVector(value: unknown, positive = false): [number, number, number] {
  if (
    !Array.isArray(value) ||
    value.length !== 3 ||
    !value.every((entry) => isNumber(entry) && (!positive || entry > 0))
  ) {
    throw new Error('风格包坐标格式无效')
  }
  return value as [number, number, number]
}

function parseMaterial(value: unknown): PbrStyleMaterial {
  if (
    !isRecord(value) ||
    typeof value.baseColor !== 'string' ||
    !/^#[0-9A-Fa-f]{6}$/.test(value.baseColor) ||
    !isNumber(value.metallic) ||
    value.metallic < 0 ||
    value.metallic > 1 ||
    !isNumber(value.roughness) ||
    value.roughness < 0 ||
    value.roughness > 1
  ) {
    throw new Error('风格包材质格式无效')
  }
  return value as unknown as PbrStyleMaterial
}

export function parseStylePack(value: unknown): StylePack {
  if (
    !isRecord(value) ||
    value.schemaVersion !== '1.0' ||
    typeof value.id !== 'string' ||
    !/^[a-z0-9][a-z0-9-]{0,63}$/.test(value.id) ||
    !Number.isInteger(value.version) ||
    Number(value.version) < 1 ||
    typeof value.name !== 'string' ||
    typeof value.description !== 'string' ||
    !isRecord(value.materials) ||
    !isRecord(value.environment) ||
    !isRecord(value.camera) ||
    !isRecord(value.output) ||
    !Array.isArray(value.assets) ||
    !isRecord(value.layout) ||
    !Array.isArray(value.layout.placements)
  ) {
    throw new Error('风格服务返回了无效数据')
  }

  const materials = Object.fromEntries(
    Object.entries(value.materials).map(([role, material]) => [role, parseMaterial(material)]),
  )
  if (!materials.architecture || !materials.floor) {
    throw new Error('风格包缺少建筑或地面材质')
  }
  const assetIds = new Set<string>()
  for (const asset of value.assets) {
    if (
      !isRecord(asset) ||
      typeof asset.id !== 'string' ||
      asset.kind !== 'procedural' ||
      asset.source !== 'project-authored' ||
      !isRecord(asset.license) ||
      asset.license.spdx !== 'LicenseRef-Project-Authored' ||
      asset.license.source !== 'project-authored'
    ) {
      throw new Error('风格包资产许可格式无效')
    }
    assetIds.add(asset.id)
  }

  const placements = value.layout.placements.map((placement): StylePlacement => {
    if (
      !isRecord(placement) ||
      typeof placement.id !== 'string' ||
      typeof placement.assetId !== 'string' ||
      !(placement.kind === 'box' || placement.kind === 'cylinder' || placement.kind === 'sphere') ||
      typeof placement.role !== 'string' ||
      !assetIds.has(placement.assetId) ||
      !materials[placement.role] ||
      !isNumber(placement.rotationYDegrees)
    ) {
      throw new Error('风格包陈设格式无效')
    }
    return {
      ...placement,
      position: parseVector(placement.position),
      size: parseVector(placement.size, true),
    } as StylePlacement
  })

  const environment = value.environment
  const camera = value.camera
  if (
    typeof environment.backgroundColor !== 'string' ||
    typeof environment.ambientColor !== 'string' ||
    !isNumber(environment.ambientIntensity) ||
    typeof environment.sunColor !== 'string' ||
    !isNumber(environment.sunIntensity) ||
    !isNumber(camera.alphaDegrees) ||
    !isNumber(camera.betaDegrees) ||
    !isNumber(camera.radiusMultiplier) ||
    !isNumber(value.layout.floorPadding)
  ) {
    throw new Error('风格包环境格式无效')
  }
  environment.sunDirection = parseVector(environment.sunDirection)
  value.layout.placements = placements
  return { ...value, materials } as unknown as StylePack
}
