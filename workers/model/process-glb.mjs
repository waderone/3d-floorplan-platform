import { createHash } from 'node:crypto'
import { readFile, stat, unlink } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { NodeIO } from '@gltf-transform/core'
import { ALL_EXTENSIONS } from '@gltf-transform/extensions'
import { MeshoptDecoder } from 'meshoptimizer'

const [, , sourcePath, outputPath] = process.argv

if (!(sourcePath && outputPath)) {
  process.stderr.write('Usage: node process-glb.mjs <source.glb> <optimized.glb>\n')
  process.exit(2)
}

const cliPath = fileURLToPath(new URL('./node_modules/.bin/gltf-transform', import.meta.url))
const STRUCTURAL_KINDS = new Set(['site', 'building', 'level'])

async function sha256(path) {
  return createHash('sha256').update(await readFile(path)).digest('hex')
}

async function inspectGlb(path) {
  await MeshoptDecoder.ready
  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
    'meshopt.decoder': MeshoptDecoder,
  })
  const document = await io.read(path)
  const root = document.getRoot()
  return {
    sha256: await sha256(path),
    bytes: (await stat(path)).size,
    nodes: root.listNodes().length,
    meshes: root.listMeshes().length,
    materials: root.listMaterials().length,
    primitives: root.listMeshes().reduce((total, mesh) => total + mesh.listPrimitives().length, 0),
  }
}

async function prepareAuthoritativeScene(source, prepared) {
  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
  const document = await io.read(source)
  let identityCount = 0

  function pruneNode(node) {
    const extras = node.getExtras()
    if (typeof extras.pascalId === 'string') {
      identityCount += 1
      if (!STRUCTURAL_KINDS.has(extras.kind)) return true
    }

    let keepsIdentityDescendant = false
    for (const child of [...node.listChildren()]) {
      if (pruneNode(child)) keepsIdentityDescendant = true
      else child.dispose()
    }
    const isIdentity = typeof extras.pascalId === 'string'
    if (keepsIdentityDescendant && !isIdentity && node.getMesh()) node.setMesh(null)
    return isIdentity || keepsIdentityDescendant
  }

  for (const scene of document.getRoot().listScenes()) {
    for (const child of [...scene.listChildren()]) {
      if (!pruneNode(child)) child.dispose()
    }
  }
  if (identityCount === 0) throw new Error('GLB contains no Pascal identity nodes')
  await io.write(prepared, document)
}

async function main() {
  const source = await inspectGlb(sourcePath)
  const preparedPath = `${outputPath}.prepared.glb`
  try {
    await prepareAuthoritativeScene(sourcePath, preparedPath)
    const optimized = spawnSync(
      process.execPath,
      [
        cliPath,
        'optimize',
        preparedPath,
        outputPath,
        '--compress',
        'meshopt',
        '--texture-size',
        '2048',
      ],
      { encoding: 'utf8' },
    )
    if (optimized.status !== 0) {
      throw new Error(
        optimized.stderr.trim() || optimized.stdout.trim() || 'GLB optimization failed',
      )
    }
  } finally {
    await unlink(preparedPath).catch(() => undefined)
  }
  const result = await inspectGlb(outputPath)
  process.stdout.write(`${JSON.stringify({ source, optimized: result })}\n`)
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`)
  process.exitCode = 1
})
