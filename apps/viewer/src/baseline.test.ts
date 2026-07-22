import assert from 'node:assert/strict'
import test from 'node:test'
import { baselineStageText, isProjectId, parseBaselineManifest } from './baseline.ts'

function manifest() {
  return {
    schemaVersion: '1.0',
    jobId: 'a'.repeat(64),
    pipelineVersion: 'floorplan-to-showroom-baseline-v1',
    projectId: 'customer-home',
    status: 'ready',
    stage: 'ready',
    planWidthMeters: 10,
    sceneRevision: 2,
    artifactId: 'b'.repeat(64),
    viewerUrl: '/?project=customer-home&style=warm-minimal',
    warnings: ['baseline_auto_accept_without_human_review'],
    error: null,
  }
}

test('parses a ready floorplan-to-showroom baseline', () => {
  const parsed = parseBaselineManifest(manifest())

  assert.equal(parsed.projectId, 'customer-home')
  assert.equal(parsed.sceneRevision, 2)
  assert.equal(baselineStageText('artifact'), '正在构建 3D 建筑模型')
})

test('rejects a ready manifest that redirects to another project', () => {
  const value = manifest()
  value.viewerUrl = '/?project=other-home&style=warm-minimal'

  assert.throws(() => parseBaselineManifest(value), /完成状态不完整/)
})

test('validates project ids and explicit failures', () => {
  assert.equal(isProjectId('home-2026_01'), true)
  assert.equal(isProjectId('../home'), false)
  const value = manifest()
  value.status = 'failed'
  value.stage = 'failed'
  value.sceneRevision = null
  value.artifactId = null
  value.viewerUrl = null
  value.error = 'no walls detected'
  assert.equal(parseBaselineManifest(value).status, 'failed')
})
