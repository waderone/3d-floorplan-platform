import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildRoomViewOptions,
  parseStyleSummaries,
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
  assert.deepEqual(preset.target, [8, 1.05, 2])
  assert.ok(Math.abs(preset.radius - 5.091168824543143) < 1e-12)
  assert.equal(
    searchWithStyle('?project=customer-home&style=warm-minimal', 'modern-contrast'),
    '?project=customer-home&style=modern-contrast',
  )
  assert.throws(() => searchWithStyle('?project=customer-home', '../invalid'), /风格 id/)
})
