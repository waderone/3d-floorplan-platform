import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildRoomViewOptions,
  livingCloseupCameraPreset,
  parseStyleSummaries,
  roomDetailCameraPreset,
  responsiveRoomCameraRadius,
  roomCameraPreset,
  searchWithStyle,
  type ShowroomRoom,
} from './showroom.ts'

const rooms: ShowroomRoom[] = [
  {
    id: 'living-large',
    name: '客餐厅',
    roomType: 'living',
    polygon: [[0, 0], [6, 0], [6, 4], [0, 4]],
    area: 24,
    centroid: [3, 2],
  },
  {
    id: 'living-small',
    name: '起居室',
    roomType: 'living',
    polygon: [[0, 0], [3, 0], [3, 3], [0, 3]],
    area: 9,
    centroid: [1.5, 1.5],
  },
  {
    id: 'bedroom',
    name: '主卧',
    roomType: 'bedroom',
    polygon: [[6, 0], [10, 0], [10, 4], [6, 4]],
    area: 16,
    centroid: [8, 2],
  },
  {
    id: 'storage',
    name: '储物间',
    roomType: 'other',
    polygon: [[0, 4], [2, 4], [2, 6], [0, 6]],
    area: 4,
    centroid: [1, 5],
  },
  {
    id: 'kitchen',
    name: '厨房',
    roomType: 'kitchen',
    polygon: [[2, 4], [5, 4], [5, 6], [2, 6]],
    area: 6,
    centroid: [3.5, 5],
  },
  {
    id: 'bathroom',
    name: '卫生间',
    roomType: 'bathroom',
    polygon: [[5, 4], [7, 4], [7, 6], [5, 6]],
    area: 4,
    centroid: [6, 5],
  },
]

test('parses a unique non-empty style catalog', () => {
  const parsed = parseStyleSummaries([
    { id: 'warm-minimal', version: 2, name: '暖木极简', description: '柔和暖木风格' },
    { id: 'nordic-light', version: 1, name: '北欧浅色', description: '明亮北欧风格' },
  ])
  assert.deepEqual(parsed.map((style) => style.id), ['warm-minimal', 'nordic-light'])
  assert.throws(() => parseStyleSummaries([]), /风格目录/)
  assert.throws(
    () => parseStyleSummaries([
      { id: 'warm-minimal', version: 1, name: 'A', description: 'A' },
      { id: 'warm-minimal', version: 2, name: 'B', description: 'B' },
    ]),
    /风格目录条目/,
  )
})

test('portrait room cameras pull back enough to keep furniture visible', () => {
  assert.equal(responsiveRoomCameraRadius(3, 16 / 9), 3)
  assert.ok(responsiveRoomCameraRadius(3, 390 / 844) > 5.9)
  assert.equal(responsiveRoomCameraRadius(3, 0.1), 6.75)
})

test('builds one view for every furnished customer room', () => {
  assert.deepEqual(
    buildRoomViewOptions(rooms, ['living-small', 'living-large', 'bedroom', 'kitchen', 'bathroom']),
    [
      { id: 'room:living-large', label: '客餐厅', roomId: 'living-large', roomType: 'living' },
      { id: 'room:living-small', label: '起居室', roomId: 'living-small', roomType: 'living' },
      { id: 'room:bedroom', label: '主卧', roomId: 'bedroom', roomType: 'bedroom' },
      { id: 'room:kitchen', label: '厨房', roomId: 'kitchen', roomType: 'kitchen' },
      { id: 'room:bathroom', label: '卫生间', roomId: 'bathroom', roomType: 'bathroom' },
    ],
  )
})

test('frames a room and preserves the project parameter in share URLs', () => {
  const preset = roomCameraPreset(rooms[2])
  assert.deepEqual(preset.target, [8, 0.95, 2])
  assert.ok(Math.abs(preset.radius - 3.790092347159895) < 1e-12)
  assert.equal(
    searchWithStyle('?project=customer-home&style=warm-minimal', 'modern-contrast'),
    '?project=customer-home&style=modern-contrast',
  )
  assert.throws(() => searchWithStyle('?project=customer-home', '../invalid'), /风格 id/)
})

test('builds an eye-level living-room camera from the sofa and focal wall axis', () => {
  const preset = livingCloseupCameraPreset([
    { itemId: 'living-sofa', position: [4.95, 0.45, 7.86] },
    { itemId: 'living-coffee-table', position: [4.8, 0.195, 6.41] },
    { itemId: 'living-sideboard', position: [4.8, 0.34, 4.96] },
  ])
  assert.ok(preset)
  assert.deepEqual(preset.target, [4.8525, 0.82, 6.9175])
  assert.ok(Math.abs(preset.radius - Math.hypot(0.9, 2.8)) < 1e-12)
  assert.ok(preset.alpha < -Math.PI / 2 && preset.alpha > -Math.PI)
  assert.equal(preset.beta, Math.PI * 0.42)
  assert.equal(livingCloseupCameraPreset([]), null)
})

test('builds front-facing detail cameras for bedroom kitchen and bathroom fixtures', () => {
  const bedroom = roomDetailCameraPreset(rooms[2], [
    { itemId: 'bedroom-bed', position: [8, 0.63, 2], rotationYDegrees: 0 },
  ])
  assert.deepEqual(bedroom.target, [8, 0.82, 2.18])
  assert.equal(bedroom.alpha, Math.PI / 2)
  assert.equal(bedroom.beta, Math.PI * 0.49)
  assert.ok(bedroom.radius >= 3.8 && bedroom.radius <= 4.1)

  const kitchen = roomDetailCameraPreset(rooms[4], [
    { itemId: 'kitchen-suite', position: [3.5, 1, 5], rotationYDegrees: 90 },
  ])
  assert.ok(Math.abs(kitchen.alpha) < 1e-12)
  assert.ok(kitchen.radius >= 2.9 && kitchen.radius <= 3.25)

  const bathroom = roomDetailCameraPreset(rooms[5], [
    { itemId: 'bathroom-suite', position: [6, 0.86, 5], rotationYDegrees: 0 },
  ])
  assert.equal(bathroom.alpha, Math.PI / 2)
  assert.deepEqual(bathroom.target, [6, 1.08, 5])
  assert.equal(bathroom.beta, Math.PI * 0.493)
  assert.ok(bathroom.radius >= 2.55 && bathroom.radius <= 2.9)
})
