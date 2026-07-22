import assert from 'node:assert/strict'
import test from 'node:test'
import {
  advanceCorrectionTimer,
  copySuggestions,
  correctionDurationSeconds,
  createAnnotationReview,
  createCorrectionTimer,
  createSubmission,
  emptyAnnotations,
  metersToPixel,
  parseSubmission,
  parseWorkpack,
  pixelToMeters,
  recordCorrectionActivity,
  setCorrectionTimerForeground,
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
      pipelineVersion: 'opencv-axis-aligned-baseline-v1',
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
    42.5,
    '2026-07-17',
  )

  assert.equal(ready.annotationStatus, 'ready-for-review')
  assert.equal(ready.correctionSession?.durationSeconds, 42.5)
  const wrong = structuredClone(ready) as unknown as Record<string, unknown>
  wrong.workpackId = 'c'.repeat(64)
  assert.throws(() => parseSubmission(wrong, workpack), /其他工作包/)
})

test('rejects malformed identities and values beyond backend limits', () => {
  const malformed = workpackValue()
  malformed.workpackId = 'not-a-hash'
  assert.throws(() => parseWorkpack(malformed), /工作包编号格式无效/)

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

test('creates a bound second-person review and rejects self-review', () => {
  const workpack = parseWorkpack(workpackValue())
  const annotations = copySuggestions(workpack, emptyAnnotations(), ['walls'])
  const submission = createSubmission(
    workpack,
    annotations,
    'ready-for-review',
    'annotator-a',
    '',
    30,
    '2026-07-17',
  )
  const review = createAnnotationReview(
    workpack,
    submission,
    'c'.repeat(64),
    'approved',
    'reviewer-b',
    '',
    '2026-07-17',
  )

  assert.equal(review.submissionSha256, 'c'.repeat(64))
  assert.equal(review.reviewedBy, 'reviewer-b')
  assert.throws(
    () => createAnnotationReview(
      workpack,
      submission,
      'c'.repeat(64),
      'approved',
      'ANNOTATOR-A',
      '',
    ),
    /不能复核自己的标注/,
  )
  assert.throws(
    () => createAnnotationReview(
      workpack,
      submission,
      'c'.repeat(64),
      'changes-requested',
      'reviewer-b',
      ' ',
    ),
    /必须填写原因/,
  )
})

test('tracks only foreground editing time and pauses after inactivity', () => {
  let timer = createCorrectionTimer(12, 0)
  timer = recordCorrectionActivity(timer, 1_000)
  timer = advanceCorrectionTimer(timer, 11_000)
  assert.equal(correctionDurationSeconds(timer, 11_000), 22)

  timer = setCorrectionTimerForeground(timer, false, 16_000)
  timer = advanceCorrectionTimer(timer, 46_000)
  assert.equal(correctionDurationSeconds(timer, 46_000), 27)

  timer = setCorrectionTimerForeground(timer, true, 46_000)
  timer = recordCorrectionActivity(timer, 46_000)
  timer = advanceCorrectionTimer(timer, 86_000)
  assert.equal(correctionDurationSeconds(timer, 86_000), 57)
})

test('restores draft timing and requires time before review handoff', () => {
  const workpack = parseWorkpack(workpackValue())
  const annotations = copySuggestions(workpack, emptyAnnotations(), ['walls'])
  const draft = createSubmission(workpack, annotations, 'draft', '', '', 75.25)
  const restored = parseSubmission(structuredClone(draft), workpack)

  assert.equal(restored.correctionSession?.pipelineVersion, workpack.suggestions.pipelineVersion)
  assert.equal(restored.correctionSession?.durationSeconds, 75.25)
  assert.equal(correctionDurationSeconds(createCorrectionTimer(75.25, 100_000), 200_000), 75.25)
  assert.throws(
    () => createSubmission(workpack, annotations, 'ready-for-review', 'annotator-a', '', 0),
    /必须产生有效编辑时间/,
  )

  const mismatched = structuredClone(draft) as unknown as Record<string, unknown>
  const session = mismatched.correctionSession as Record<string, unknown>
  session.pipelineVersion = 'another-pipeline'
  assert.throws(() => parseSubmission(mismatched, workpack), /算法版本与工作包不一致/)
})
