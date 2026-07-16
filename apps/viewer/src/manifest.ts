export interface GlbStatistics {
  nodes: number
  meshes: number
  materials: number
  primitives: number
}

export interface GlbFileMetadata {
  sha256: string
  bytes: number
  url: string
  statistics: GlbStatistics | null
}

export interface ArtifactManifest {
  artifactId: string
  projectId: string
  sceneRevision: number
  pipelineVersion: string
  status: 'processing' | 'ready' | 'failed'
  source: GlbFileMetadata
  optimized: GlbFileMetadata | null
  mobileBudgetExceeded: boolean
  error: string | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseStatistics(value: unknown): GlbStatistics | null {
  if (value === null) return null
  if (!isRecord(value)) throw new Error('模型指标格式无效')
  for (const key of ['nodes', 'meshes', 'materials', 'primitives']) {
    const count = value[key]
    if (!(Number.isInteger(count) && Number(count) >= 0)) {
      throw new Error('模型指标格式无效')
    }
  }
  return value as unknown as GlbStatistics
}

function parseFile(value: unknown): GlbFileMetadata {
  if (
    !isRecord(value) ||
    typeof value.sha256 !== 'string' ||
    !/^[0-9a-f]{64}$/.test(value.sha256) ||
    !(Number.isInteger(value.bytes) && Number(value.bytes) > 0) ||
    typeof value.url !== 'string' ||
    !/^\/artifacts\/[0-9a-f]{64}\/(?:source|optimized)\.glb$/.test(value.url)
  ) {
    throw new Error('模型文件元数据无效')
  }
  return { ...value, statistics: parseStatistics(value.statistics) } as GlbFileMetadata
}

export function parseArtifactManifest(value: unknown): ArtifactManifest {
  if (
    !isRecord(value) ||
    typeof value.artifactId !== 'string' ||
    !/^[0-9a-f]{64}$/.test(value.artifactId) ||
    typeof value.projectId !== 'string' ||
    !(Number.isInteger(value.sceneRevision) && Number(value.sceneRevision) > 0) ||
    typeof value.pipelineVersion !== 'string' ||
    value.pipelineVersion.length === 0 ||
    !(value.status === 'processing' || value.status === 'ready' || value.status === 'failed') ||
    typeof value.mobileBudgetExceeded !== 'boolean' ||
    !(value.error === null || typeof value.error === 'string')
  ) {
    throw new Error('模型服务返回了无效数据')
  }
  const source = parseFile(value.source)
  const optimized = value.optimized === null ? null : parseFile(value.optimized)
  if (value.status === 'ready' && optimized === null) {
    throw new Error('模型已完成但缺少优化产物')
  }
  return { ...value, source, optimized } as ArtifactManifest
}
