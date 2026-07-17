import assert from 'node:assert/strict'
import test from 'node:test'
import {
  copySuggestions,
  createSubmission,
  emptyAnnotations,
  metersToPixel,
  parseSubmission,
  parseWorkpack,
  pixelToMeters,
} from './model.ts'

function workpackValue(): Record<string, unknown> {
  return {
    workpackId: 'a'.repeat(64),
    candidate: { candidateId: 'commons-1' },
    review: {
      curation: { planWidthMeters: 10 },
      rights: { status: 'pending' },
    },
    image: {
      file: 'commons-1.png',
      sha256: 'b'.repeat(64),
      widthPixels: 1200,
      heightPixels: 800,
    },
    suggestions: {
      metrics: { planBoundsPixels: [100, 100, 1100, 700] },
      walls: [
        {
          id: 'wall-suggestion-1',
          start: [0, 0],
          end: [10, 0],
          thickness: 0.2,
          confidence: 0.8,
        },
      ],
      rooms: [
        {
          id: 'room-suggestion-1',
          roomType: 'unknown',
          polygon: [[0, 0], [10, 0], [10, 6], [0, 6]],
          confidence: 0.7,
        },
      ],
      openings: [],
    },
  }
}

test('parses workpack without promoting suggestions to truth', () => {
  const workpack = parseWorkpack(workpackValue())

  assert.equal(workpack.rightsStatus, 'pending')
  assert.equal(workpack.suggestions.walls.length, 1)
  assert.equal(emptyAnnotations().walls.length, 0)
})

test('pixel and meter coordinates round trip through plan bounds', () => {
  const calibration = parseWorkpack(workpackValue()).calibration
  const meters = pixelToMeters([600, 400], calibration)

  assert.deepEqual(meters, [5, 3])
  assert.deepEqual(metersToPixel(meters, calibration), [600, 400])
})

test('copies suggestions explicitly and does not duplicate them', () => {
  const workpack = parseWorkpack(workpackValue())
  const first = copySuggestions(workpack, emptyAnnotations(), ['walls', 'rooms'])
  const repeated = copySuggestions(workpack, first, ['walls', 'rooms'])

  assert.deepEqual(first, repeated)
  assert.equal(first.walls[0]?.id, 'truth-wall-suggestion-1')
  assert.equal(first.rooms[0]?.roomType, 'unknown')
})

test('validates workpack identity and review-ready requirements', () => {
  const workpack = parseWorkpack(workpackValue())
  const annotations = copySuggestions(workpack, emptyAnnotations(), ['walls'])
  const ready = createSubmission(
    workpack,
    annotations,
    'ready-for-review',
    'test-curator',
    '',
    '2026-07-17',
  )

  assert.equal(ready.annotationStatus, 'ready-for-review')
  const wrong = structuredClone(ready) as unknown as Record<string, unknown>
  wrong.workpackId = 'c'.repeat(64)
  assert.throws(() => parseSubmission(wrong, workpack), /其他工作包/)
})

test('rejects malformed identities and values beyond backend limits', () => {
  const malformed = workpackValue()
  malformed.workpackId = 'not-a-hash'
  assert.throws(() => parseWorkpack(malformed), /工作包 ID 格式无效/)

  const workpack = parseWorkpack(workpackValue())
  const draft = createSubmission(workpack, emptyAnnotations(), 'draft', '', '')
  const oversized = structuredClone(draft) as unknown as Record<string, unknown>
  oversized.notes = 'x'.repeat(2001)
  assert.throws(() => parseSubmission(oversized, workpack), /备注超出长度限制/)

  const outside = copySuggestions(workpack, emptyAnnotations(), ['walls'])
  outside.walls[0]!.end = [10.001, 0]
  assert.throws(
    () => createSubmission(workpack, outside, 'draft', '', ''),
    /超出已标定户型边界/,
  )
})
