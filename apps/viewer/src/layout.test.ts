import assert from 'node:assert/strict'
import test from 'node:test'
import { parseLayoutManifest } from './layout.ts'

function manifest() {
  return {
    schemaVersion: '3.0',
    layoutId: 'a'.repeat(64),
    pipelineVersion: 'multiroom-opening-clearance-layout-v6',
    projectId: 'layout-demo',
    sceneRevision: 1,
    style: { id: 'warm-minimal', version: 2 },
    assetCatalog: { id: 'starter-furniture', version: 4 },
    status: 'fallback',
    fallbackReason: 'no-room-fits',
    selectedRoomId: null,
    furnishedRoomIds: [],
    unfurnishedRoomIds: ['zone-living'],
    referencedAssetBytes: 0,
    mobileAssetBudgetBytes: 5_242_880,
    mobileAssetBudgetExceeded: false,
    wallClearance: 0.25,
    itemClearance: 0.2,
    placementSearch: 'bounded-grid-v1',
    openingClearanceValidated: true,
    ignoredOpeningIds: [],
    openingBlockedRoomIds: ['zone-living'],
    rooms: [
      {
        id: 'zone-living',
        name: '客厅',
        roomType: 'living',
        source: 'zone',
        levelId: 'level-main',
        polygon: [[0, 0], [5, 0], [5, 5], [0, 5]],
        area: 25,
        centroid: [2.5, 2.5],
      },
    ],
    openings: [
      {
        id: 'door-main',
        sourceType: 'door',
        openingKind: 'door',
        operationType: 'hinged',
        wallId: 'wall-main',
        levelId: 'level-main',
        roomIds: ['zone-living'],
        center: [2.5, 0],
        tangent: [1, 0],
        width: 0.9,
        height: 2.1,
        sillHeight: 0,
        clearanceType: 'swing',
        clearanceDepth: 0.9,
        clearancePolygon: [[1.95, -0.9], [3.05, -0.9], [3.05, 0.9], [1.95, 0.9]],
      },
    ],
    placements: [],
  }
}

test('parses layout v6 authoritative openings and clearance diagnostics', () => {
  const parsed = parseLayoutManifest(manifest())

  assert.equal(parsed.openings[0]?.id, 'door-main')
  assert.deepEqual(parsed.openings[0]?.roomIds, ['zone-living'])
  assert.deepEqual(parsed.openingBlockedRoomIds, ['zone-living'])
})

test('rejects opening references outside the layout rooms', () => {
  const value = manifest()
  value.openings[0]!.roomIds = ['zone-missing']

  assert.throws(() => parseLayoutManifest(value), /开口格式/)
})

test('rejects legacy layout contracts without silently guessing openings', () => {
  const value = manifest()
  value.schemaVersion = '2.0'

  assert.throws(() => parseLayoutManifest(value), /无效数据/)
})
