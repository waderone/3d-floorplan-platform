export type BaselineStatus = 'processing' | 'ready' | 'failed'
export type BaselineStage = 'recognition' | 'scene' | 'artifact' | 'layout' | 'ready' | 'failed'

export interface BaselineManifest {
  schemaVersion: '1.0'
  jobId: string
  pipelineVersion: 'floorplan-to-showroom-baseline-v1'
  projectId: string
  status: BaselineStatus
  stage: BaselineStage
  planWidthMeters: number
  sceneRevision: number | null
  artifactId: string | null
  viewerUrl: string | null
  warnings: string[]
  error: string | null
}

const projectIdPattern = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/
const sha256Pattern = /^[0-9a-f]{64}$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isProjectId(value: string): boolean {
  return projectIdPattern.test(value)
}

export function parseBaselineManifest(value: unknown): BaselineManifest {
  if (
    !isRecord(value) ||
    value.schemaVersion !== '1.0' ||
    typeof value.jobId !== 'string' ||
    !sha256Pattern.test(value.jobId) ||
    value.pipelineVersion !== 'floorplan-to-showroom-baseline-v1' ||
    typeof value.projectId !== 'string' ||
    !isProjectId(value.projectId) ||
    !(value.status === 'processing' || value.status === 'ready' || value.status === 'failed') ||
    !(
      value.stage === 'recognition' ||
      value.stage === 'scene' ||
      value.stage === 'artifact' ||
      value.stage === 'layout' ||
      value.stage === 'ready' ||
      value.stage === 'failed'
    ) ||
    typeof value.planWidthMeters !== 'number' ||
    !Number.isFinite(value.planWidthMeters) ||
    value.planWidthMeters <= 0 ||
    !(value.sceneRevision === null || Number.isInteger(value.sceneRevision)) ||
    !(value.artifactId === null || (typeof value.artifactId === 'string' && sha256Pattern.test(value.artifactId))) ||
    !(value.viewerUrl === null || typeof value.viewerUrl === 'string') ||
    !Array.isArray(value.warnings) ||
    !value.warnings.every((warning) => typeof warning === 'string') ||
    !(value.error === null || typeof value.error === 'string')
  ) {
    throw new Error('自动生成任务返回了无效数据')
  }
  const expectedViewerUrl = `/?project=${encodeURIComponent(value.projectId)}&style=warm-minimal`
  if (value.status === 'ready') {
    if (
      value.stage !== 'ready' ||
      value.sceneRevision === null ||
      value.artifactId === null ||
      value.viewerUrl !== expectedViewerUrl ||
      value.error !== null
    ) {
      throw new Error('自动生成任务完成状态不完整')
    }
  } else if (value.status === 'failed') {
    if (value.stage !== 'failed' || !value.error || value.viewerUrl !== null) {
      throw new Error('自动生成任务失败状态无效')
    }
  }
  return value as unknown as BaselineManifest
}

export function baselineStageText(stage: BaselineStage): string {
  return {
    recognition: '正在识别墙体与房间',
    scene: '正在生成结构化户型',
    artifact: '正在构建 3D 建筑模型',
    layout: '正在布置三套装修风格',
    ready: '3D 方案已经生成',
    failed: '自动生成未完成',
  }[stage]
}
