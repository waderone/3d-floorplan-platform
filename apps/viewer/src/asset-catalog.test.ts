import assert from 'node:assert/strict'
import test from 'node:test'
import { parseAssetCatalog } from './asset-catalog.ts'

function catalogWith(asset: Record<string, unknown>): Record<string, unknown> {
  return {
    schemaVersion: '2.0',
    id: 'catalog',
    version: 2,
    mobileBudgetBytes: 1024,
    assets: [asset],
  }
}

const baseAsset = {
  id: 'sofa',
  kind: 'model',
  roomTypes: ['living'],
  canonicalSize: [2, 1, 1],
  delivery: {
    url: '/catalog-assets/models/sofa.glb',
    sha256: 'a'.repeat(64),
    bytes: 512,
  },
  fallback: { kind: 'box', materialRole: 'fabric' },
}

test('defaults legacy model material handling to replacement', () => {
  const parsed = parseAssetCatalog(catalogWith(baseAsset))
  assert.equal(parsed.assets[0].materialMode, 'replace')
})

test('accepts texture-preserving material modes and rejects unknown modes', () => {
  const parsed = parseAssetCatalog(catalogWith({ ...baseAsset, materialMode: 'tint' }))
  assert.equal(parsed.assets[0].materialMode, 'tint')
  assert.throws(
    () => parseAssetCatalog(catalogWith({ ...baseAsset, materialMode: 'flatten' })),
    /资产目录条目格式无效/,
  )
})
