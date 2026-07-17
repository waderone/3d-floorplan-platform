export type Point = [number, number]

export interface WallAnnotation {
  id: string
  start: Point
  end: Point
  thickness: number
}

export interface RoomAnnotation {
  id: string
  roomType: string
  polygon: Point[]
}

export interface OpeningAnnotation {
  id: string
  kind: 'door' | 'window'
  center: Point
  width: number
}

export interface Annotations {
  coordinateSystem: 'plan-bottom-left-x-right-z-up-m'
  walls: WallAnnotation[]
  rooms: RoomAnnotation[]
  openings: OpeningAnnotation[]
}

export interface Calibration {
  planWidthMeters: number
  planBoundsPixels: [number, number, number, number]
  imageWidthPixels: number
  imageHeightPixels: number
}

export interface AnnotationWorkpack {
  workpackId: string
  candidateId: string
  rightsStatus: 'pending' | 'approved' | 'rejected'
  image: {
    file: string
    sha256: string
    widthPixels: number
    heightPixels: number
  }
  calibration: Calibration
  suggestions: Annotations
}

export interface AnnotationSubmission {
  schemaVersion: '1.0'
  workpackId: string
  candidateId: string
  annotationStatus: 'draft' | 'ready-for-review'
  annotations: Annotations
  annotatedBy: string | null
  annotatedAt: string | null
  notes: string
}

export interface AnnotationReview {
  schemaVersion: '1.0'
  workpackId: string
  candidateId: string
  submissionSha256: string
  decision: 'approved' | 'changes-requested'
  reviewedBy: string
  reviewedAt: string
  comment: string | null
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`${label} 格式无效`)
  }
  return value as Record<string, unknown>
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${label} 格式无效`)
  return value
}

function boundedString(value: unknown, label: string, maximum: number): string {
  const parsed = stringValue(value, label)
  if (parsed.length > maximum) throw new Error(`${label} 超出长度限制`)
  return parsed
}

function finiteNumber(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${label} 格式无效`)
  return value
}

function positiveNumber(value: unknown, label: string, maximum = Number.MAX_VALUE): number {
  const parsed = finiteNumber(value, label)
  if (parsed <= 0 || parsed > maximum) throw new Error(`${label} 超出范围`)
  return parsed
}

function point(value: unknown, label: string): Point {
  if (!Array.isArray(value) || value.length !== 2) throw new Error(`${label} 格式无效`)
  return [finiteNumber(value[0], label), finiteNumber(value[1], label)]
}

function wall(value: unknown): WallAnnotation {
  const item = record(value, '墙体')
  const start = point(item.start, '墙体起点')
  const end = point(item.end, '墙体终点')
  if (start[0] === end[0] && start[1] === end[1]) throw new Error('墙体起终点不能相同')
  return {
    id: boundedString(item.id, '墙体 ID', 100),
    start,
    end,
    thickness: positiveNumber(item.thickness, '墙厚', 2),
  }
}

function cross(origin: Point, first: Point, second: Point): number {
  return (first[0] - origin[0]) * (second[1] - origin[1]) -
    (first[1] - origin[1]) * (second[0] - origin[0])
}

function segmentsIntersect(a: Point, b: Point, c: Point, d: Point): boolean {
  return cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0
}

function validatePolygon(polygon: Point[]): void {
  if (polygon.length < 3 || new Set(polygon.map((entry) => entry.join(','))).size < 3) {
    throw new Error('房间至少需要三个不同顶点')
  }
  const edges = polygon.map((entry, index) => [entry, polygon[(index + 1) % polygon.length]] as const)
  edges.forEach((first, firstIndex) => {
    edges.forEach((second, secondIndex) => {
      const adjacent = secondIndex === firstIndex + 1 ||
        (firstIndex === 0 && secondIndex === edges.length - 1)
      if (secondIndex > firstIndex && !adjacent && segmentsIntersect(...first, ...second)) {
        throw new Error('房间多边形不能自相交')
      }
    })
  })
  const doubleArea = edges.reduce(
    (sum, [first, second]) => sum + first[0] * second[1] - second[0] * first[1],
    0,
  )
  if (Math.abs(doubleArea) < 1e-8) throw new Error('房间多边形面积不能为零')
}

function room(value: unknown): RoomAnnotation {
  const item = record(value, '房间')
  if (!Array.isArray(item.polygon)) throw new Error('房间边界格式无效')
  const polygon = item.polygon.map((entry) => point(entry, '房间顶点'))
  validatePolygon(polygon)
  return {
    id: boundedString(item.id, '房间 ID', 100),
    roomType: boundedString(item.roomType, '房间类型', 50),
    polygon,
  }
}

function opening(value: unknown): OpeningAnnotation {
  const item = record(value, '门窗')
  if (item.kind !== 'door' && item.kind !== 'window') throw new Error('门窗类型格式无效')
  return {
    id: boundedString(item.id, '门窗 ID', 100),
    kind: item.kind,
    center: point(item.center, '门窗中心'),
    width: positiveNumber(item.width, '门窗宽度', 20),
  }
}

function annotations(value: unknown): Annotations {
  const item = record(value, '标注')
  if (item.coordinateSystem !== 'plan-bottom-left-x-right-z-up-m') {
    throw new Error('标注坐标系不受支持')
  }
  if (!Array.isArray(item.walls) || !Array.isArray(item.rooms) || !Array.isArray(item.openings)) {
    throw new Error('标注几何列表格式无效')
  }
  const parsed: Annotations = {
    coordinateSystem: 'plan-bottom-left-x-right-z-up-m',
    walls: item.walls.map(wall),
    rooms: item.rooms.map(room),
    openings: item.openings.map(opening),
  }
  const ids = [...parsed.walls, ...parsed.rooms, ...parsed.openings].map((entry) => entry.id)
  if (new Set(ids).size !== ids.length) throw new Error('标注 ID 必须唯一')
  return parsed
}

function integerBounds(value: unknown): [number, number, number, number] {
  if (!Array.isArray(value) || value.length !== 4 || !value.every(Number.isInteger)) {
    throw new Error('户型像素边界格式无效')
  }
  const bounds = value as [number, number, number, number]
  if (bounds[2] <= bounds[0] || bounds[3] <= bounds[1]) throw new Error('户型像素边界无效')
  return bounds
}

export function parseWorkpack(value: unknown): AnnotationWorkpack {
  const root = record(value, '工作包')
  const candidate = record(root.candidate, '候选')
  const review = record(root.review, '审核记录')
  const curation = record(review.curation, '筛选记录')
  const rights = record(review.rights, '权利记录')
  const image = record(root.image, '图片')
  const suggestions = record(root.suggestions, '识别建议')
  const metrics = record(suggestions.metrics, '识别指标')
  if (rights.status !== 'pending' && rights.status !== 'approved' && rights.status !== 'rejected') {
    throw new Error('权利审核状态无效')
  }
  const widthPixels = positiveNumber(image.widthPixels, '图片宽度')
  const heightPixels = positiveNumber(image.heightPixels, '图片高度')
  if (!Number.isInteger(widthPixels) || !Number.isInteger(heightPixels)) {
    throw new Error('图片尺寸必须为整数')
  }
  const imageSha256 = stringValue(image.sha256, '图片 SHA-256')
  if (!/^[0-9a-f]{64}$/.test(imageSha256)) throw new Error('图片 SHA-256 格式无效')
  const workpackId = stringValue(root.workpackId, '工作包 ID')
  if (!/^[0-9a-f]{64}$/.test(workpackId)) throw new Error('工作包 ID 格式无效')
  const candidateId = stringValue(candidate.candidateId, '候选 ID')
  if (!/^commons-[1-9][0-9]*$/.test(candidateId)) throw new Error('候选 ID 格式无效')
  if (!Array.isArray(suggestions.walls) || !Array.isArray(suggestions.rooms) || !Array.isArray(suggestions.openings)) {
    throw new Error('识别建议列表格式无效')
  }
  return {
    workpackId,
    candidateId,
    rightsStatus: rights.status,
    image: {
      file: stringValue(image.file, '图片文件'),
      sha256: imageSha256,
      widthPixels,
      heightPixels,
    },
    calibration: {
      planWidthMeters: positiveNumber(curation.planWidthMeters, '户型宽度', 500),
      planBoundsPixels: integerBounds(metrics.planBoundsPixels),
      imageWidthPixels: widthPixels,
      imageHeightPixels: heightPixels,
    },
    suggestions: {
      coordinateSystem: 'plan-bottom-left-x-right-z-up-m',
      walls: suggestions.walls.map(wall),
      rooms: suggestions.rooms.map(room),
      openings: suggestions.openings.map(opening),
    },
  }
}

export function parseSubmission(value: unknown, workpack: AnnotationWorkpack): AnnotationSubmission {
  const root = record(value, '标注文件')
  if (root.schemaVersion !== '1.0') throw new Error('标注文件版本不受支持')
  if (root.workpackId !== workpack.workpackId) throw new Error('标注文件属于其他工作包')
  if (root.candidateId !== workpack.candidateId) throw new Error('标注文件属于其他候选')
  if (root.annotationStatus !== 'draft' && root.annotationStatus !== 'ready-for-review') {
    throw new Error('标注状态无效')
  }
  const annotatedBy = root.annotatedBy === null ? null : boundedString(root.annotatedBy, '标注人', 100)
  const annotatedAt = root.annotatedAt === null ? null : stringValue(root.annotatedAt, '标注日期')
  const notes = typeof root.notes === 'string' ? root.notes : ''
  if (notes.length > 2000) throw new Error('备注超出长度限制')
  const parsed: AnnotationSubmission = {
    schemaVersion: '1.0',
    workpackId: workpack.workpackId,
    candidateId: workpack.candidateId,
    annotationStatus: root.annotationStatus,
    annotations: annotations(root.annotations),
    annotatedBy,
    annotatedAt,
    notes,
  }
  const points = parsed.annotations.walls.flatMap((entry) => [entry.start, entry.end])
  points.push(...parsed.annotations.rooms.flatMap((entry) => entry.polygon))
  points.push(...parsed.annotations.openings.map((entry) => entry.center))
  const scale = metersPerPixel(workpack.calibration)
  const planHeight = (
    workpack.calibration.planBoundsPixels[3] - workpack.calibration.planBoundsPixels[1]
  ) * scale
  const epsilon = 1e-6
  if (points.some(([x, z]) => (
    x < -epsilon || x > workpack.calibration.planWidthMeters + epsilon ||
    z < -epsilon || z > planHeight + epsilon
  ))) {
    throw new Error('标注几何超出已标定户型边界')
  }
  if (parsed.annotationStatus === 'ready-for-review') {
    if (parsed.annotations.walls.length === 0) throw new Error('待复核标注至少需要一面墙')
    if (!parsed.annotatedBy || !/^\d{4}-\d{2}-\d{2}$/.test(parsed.annotatedAt ?? '')) {
      throw new Error('待复核标注必须填写标注人和日期')
    }
  }
  return parsed
}

export function emptyAnnotations(): Annotations {
  return {
    coordinateSystem: 'plan-bottom-left-x-right-z-up-m',
    walls: [],
    rooms: [],
    openings: [],
  }
}

export function cloneAnnotations(value: Annotations): Annotations {
  return structuredClone(value)
}

export function metersPerPixel(calibration: Calibration): number {
  return calibration.planWidthMeters /
    (calibration.planBoundsPixels[2] - calibration.planBoundsPixels[0])
}

export function pixelToMeters(value: Point, calibration: Calibration): Point {
  const [minimumX, , , maximumY] = calibration.planBoundsPixels
  const scale = metersPerPixel(calibration)
  return [
    Number(((value[0] - minimumX) * scale).toFixed(3)),
    Number(((maximumY - value[1]) * scale).toFixed(3)),
  ]
}

export function metersToPixel(value: Point, calibration: Calibration): Point {
  const [minimumX, , , maximumY] = calibration.planBoundsPixels
  const scale = metersPerPixel(calibration)
  return [value[0] / scale + minimumX, maximumY - value[1] / scale]
}

export function clampMeters(value: Point, calibration: Calibration): Point {
  const scale = metersPerPixel(calibration)
  const planHeight = (calibration.planBoundsPixels[3] - calibration.planBoundsPixels[1]) * scale
  return [
    Math.min(calibration.planWidthMeters, Math.max(0, value[0])),
    Math.min(planHeight, Math.max(0, value[1])),
  ]
}

export function copySuggestions(
  workpack: AnnotationWorkpack,
  current: Annotations,
  kinds: Array<'walls' | 'rooms' | 'openings'>,
): Annotations {
  const next = cloneAnnotations(current)
  const ids = new Set([...next.walls, ...next.rooms, ...next.openings].map((entry) => entry.id))
  for (const kind of kinds) {
    for (const suggestion of workpack.suggestions[kind]) {
      const copied = structuredClone(suggestion)
      copied.id = `truth-${suggestion.id}`
      if (ids.has(copied.id)) continue
      ids.add(copied.id)
      if (kind === 'walls') next.walls.push(copied as WallAnnotation)
      if (kind === 'rooms') next.rooms.push(copied as RoomAnnotation)
      if (kind === 'openings') next.openings.push(copied as OpeningAnnotation)
    }
  }
  return next
}

export function nextId(prefix: 'wall' | 'room' | 'door' | 'window', value: Annotations): string {
  const ids = new Set([...value.walls, ...value.rooms, ...value.openings].map((entry) => entry.id))
  let index = 1
  while (ids.has(`${prefix}-${index}`)) index += 1
  return `${prefix}-${index}`
}

export function createSubmission(
  workpack: AnnotationWorkpack,
  value: Annotations,
  status: 'draft' | 'ready-for-review',
  annotatedBy: string,
  notes: string,
  date = new Date().toISOString().slice(0, 10),
): AnnotationSubmission {
  return parseSubmission(
    {
      schemaVersion: '1.0',
      workpackId: workpack.workpackId,
      candidateId: workpack.candidateId,
      annotationStatus: status,
      annotations: value,
      annotatedBy: annotatedBy.trim() || null,
      annotatedAt: annotatedBy.trim() ? date : null,
      notes,
    },
    workpack,
  )
}

export function createAnnotationReview(
  workpack: AnnotationWorkpack,
  submission: AnnotationSubmission,
  submissionSha256: string,
  decision: 'approved' | 'changes-requested',
  reviewedBy: string,
  comment: string,
  date = new Date().toISOString().slice(0, 10),
): AnnotationReview {
  if (submission.annotationStatus !== 'ready-for-review') {
    throw new Error('只有待复核标注可以生成复核记录')
  }
  if (submission.workpackId !== workpack.workpackId || submission.candidateId !== workpack.candidateId) {
    throw new Error('待复核标注与当前工作包不匹配')
  }
  if (!/^[0-9a-f]{64}$/.test(submissionSha256)) throw new Error('标注文件 SHA-256 格式无效')
  const reviewer = reviewedBy.trim()
  if (!reviewer || reviewer.length > 100) throw new Error('请填写有效的复核人')
  if (reviewer.toLowerCase() === (submission.annotatedBy ?? '').trim().toLowerCase()) {
    throw new Error('标注人不能复核自己的标注')
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error('复核日期格式无效')
  const normalizedComment = comment.trim()
  if (normalizedComment.length > 1000) throw new Error('复核说明超出长度限制')
  if (decision === 'changes-requested' && !normalizedComment) throw new Error('退回修改必须填写原因')
  return {
    schemaVersion: '1.0',
    workpackId: workpack.workpackId,
    candidateId: workpack.candidateId,
    submissionSha256,
    decision,
    reviewedBy: reviewer,
    reviewedAt: date,
    comment: normalizedComment || null,
  }
}

export async function sha256Hex(content: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', content)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}
