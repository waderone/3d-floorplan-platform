import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { Document, NodeIO } from '@gltf-transform/core'

async function createTriangleGlb(path) {
  const document = new Document()
  const buffer = document.createBuffer()
  const positions = document
    .createAccessor('positions')
    .setType('VEC3')
    .setArray(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]))
    .setBuffer(buffer)
  const indices = document
    .createAccessor('indices')
    .setType('SCALAR')
    .setArray(new Uint16Array([0, 1, 2]))
    .setBuffer(buffer)
  const material = document.createMaterial('wall')
  const primitive = document
    .createPrimitive()
    .setAttribute('POSITION', positions)
    .setIndices(indices)
    .setMaterial(material)
  const mesh = document.createMesh('wall').addPrimitive(primitive)
  const node = document
    .createNode('wall')
    .setMesh(mesh)
    .setExtras({ pascalId: 'wall-test', kind: 'wall' })
  const helper = document.createNode('ground-helper').setMesh(mesh).setScale([1000, 1, 1000])
  const site = document
    .createNode('site')
    .setExtras({ pascalId: 'site-test', kind: 'site' })
    .addChild(node)
    .addChild(helper)
  document.createScene('floorplan').addChild(site)
  await new NodeIO().write(path, document)
}

test('optimizes a GLB and reports verifiable metrics', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'floorplan-glb-'))
  try {
    const source = join(directory, 'source.glb')
    const optimized = join(directory, 'optimized.glb')
    await createTriangleGlb(source)

    const result = spawnSync(process.execPath, ['process-glb.mjs', source, optimized], {
      cwd: new URL('..', import.meta.url),
      encoding: 'utf8',
    })

    assert.equal(result.status, 0, result.stderr)
    const report = JSON.parse(result.stdout)
    assert.equal(report.source.nodes, 3)
    assert.equal(report.source.meshes, 1)
    assert.equal(report.source.materials, 1)
    assert.equal(report.optimized.meshes, 1)
    assert.equal(report.optimized.nodes, 1)
    assert.match(report.source.sha256, /^[0-9a-f]{64}$/)
    assert.match(report.optimized.sha256, /^[0-9a-f]{64}$/)
    assert.ok(report.optimized.bytes > 0)
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test('fails explicitly when the source GLB is missing', () => {
  const result = spawnSync(
    process.execPath,
    ['process-glb.mjs', '/missing/source.glb', '/missing/output.glb'],
    { cwd: new URL('..', import.meta.url), encoding: 'utf8' },
  )

  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /ENOENT/)
})
