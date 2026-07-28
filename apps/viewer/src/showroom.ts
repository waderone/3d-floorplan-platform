export interface StyleSummary {
  id: string
  version: number
  name: string
  description: string
}

export interface ShowroomRoom {
  id: string
  name: string
  roomType: 'living' | 'dining' | 'bedroom' | 'kitchen' | 'bathroom' | 'other'
  polygon: Array<[number, number]>
  area: number
  centroid: [number, number]
}

export interface RoomViewOption {
  id: string
  label: string
  roomId: string
  roomType: 'living' | 'dining' | 'bedroom' | 'kitchen' | 'bathroom'
}

export interface RoomCameraPreset {
  target: [number, number, number]
  radius: number
}

export interface LivingCameraPlacement {
  itemId: string
  position: [number, number, number]
}

export interface RoomCameraPlacement extends LivingCameraPlacement {
  rotationYDegrees: number
}

export interface LivingCloseupCameraPreset extends RoomCameraPreset {
  alpha: number
  beta: number
}

const styleIdPattern = /^[a-z0-9][a-z0-9-]{0,63}$/
const roomTypeOrder = ['living', 'dining', 'bedroom', 'kitchen', 'bathroom'] as const
const roomTypeLabels = {
  living: '客厅',
  dining: '餐厅',
  bedroom: '卧室',
  kitchen: '厨房',
  bathroom: '卫生间',
} as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseStyleSummaries(value: unknown): StyleSummary[] {
  if (!Array.isArray(value) || value.length === 0) throw new Error('风格目录为空或格式无效')
  const ids = new Set<string>()
  return value.map((entry): StyleSummary => {
    if (
      !isRecord(entry) ||
      typeof entry.id !== 'string' ||
      !styleIdPattern.test(entry.id) ||
      ids.has(entry.id) ||
      !Number.isInteger(entry.version) ||
      Number(entry.version) < 1 ||
      typeof entry.name !== 'string' ||
      entry.name.length === 0 ||
      typeof entry.description !== 'string' ||
      entry.description.length === 0
    ) {
      throw new Error('风格目录条目格式无效')
    }
    ids.add(entry.id)
    return entry as unknown as StyleSummary
  })
}

export function buildRoomViewOptions(
  rooms: ShowroomRoom[],
  furnishedRoomIds: string[],
): RoomViewOption[] {
  const furnished = new Set(furnishedRoomIds)
  return roomTypeOrder.flatMap((roomType) => {
    const typedRooms = rooms
      .filter((candidate) => candidate.roomType === roomType && furnished.has(candidate.id))
      .sort((first, second) => second.area - first.area || first.id.localeCompare(second.id))
    return typedRooms.map((room) => ({
      id: `room:${room.id}`,
      label: room.name || roomTypeLabels[roomType],
      roomId: room.id,
      roomType,
    }))
  })
}

export function roomCameraPreset(room: ShowroomRoom): RoomCameraPreset {
  const xValues = room.polygon.map((point) => point[0])
  const zValues = room.polygon.map((point) => point[1])
  const width = Math.max(...xValues) - Math.min(...xValues)
  const depth = Math.max(...zValues) - Math.min(...zValues)
  return {
    target: [room.centroid[0], 0.95, room.centroid[1]],
    radius: Math.max(3.2, Math.hypot(width, depth) * 0.67),
  }
}

export function roomDetailCameraPreset(
  room: ShowroomRoom,
  placements: RoomCameraPlacement[],
): LivingCloseupCameraPreset {
  let focalItemId: string | undefined
  if (room.roomType === 'bedroom') focalItemId = 'bedroom-bed'
  else if (room.roomType === 'kitchen') focalItemId = 'kitchen-suite'
  else if (room.roomType === 'bathroom') focalItemId = 'bathroom-suite'
  const focal = focalItemId
    ? placements.find((placement) => placement.itemId === focalItemId)
    : undefined
  const rotation = ((focal?.rotationYDegrees ?? 0) * Math.PI) / 180
  const frontX = Math.sin(rotation)
  const frontZ = Math.cos(rotation)
  const roomPreset = roomCameraPreset(room)
  const radiusByType = {
    bedroom: Math.min(4.1, Math.max(3.8, roomPreset.radius)),
    kitchen: Math.min(3.25, Math.max(2.9, roomPreset.radius * 0.9)),
    bathroom: Math.min(2.9, Math.max(2.55, roomPreset.radius * 0.82)),
  } as const
  return {
    target: [
      focal?.position[0] ?? roomPreset.target[0],
      room.roomType === 'bedroom' ? 0.82 : room.roomType === 'bathroom' ? 1.08 : 0.98,
      (focal?.position[2] ?? roomPreset.target[2]) + (room.roomType === 'bedroom' ? 0.18 : 0),
    ],
    radius: radiusByType[room.roomType as keyof typeof radiusByType] ?? roomPreset.radius,
    alpha: room.roomType === 'bedroom' || room.roomType === 'bathroom'
      ? Math.atan2(frontZ, -frontX)
      : Math.atan2(-frontZ, frontX),
    beta: room.roomType === 'bathroom'
      ? Math.PI * 0.493
      : room.roomType === 'bedroom'
        ? Math.PI * 0.49
        : Math.PI * 0.475,
  }
}

export function responsiveRoomCameraRadius(radius: number, aspect: number): number {
  return radius * Math.min(2.25, Math.max(1, 0.92 / Math.max(0.01, aspect)))
}

export function livingCloseupCameraPreset(
  placements: LivingCameraPlacement[],
): LivingCloseupCameraPreset | null {
  const sofa = placements.find((placement) => placement.itemId === 'living-sofa')
  const table = placements.find((placement) => placement.itemId === 'living-coffee-table')
  const focal = placements.find((placement) => placement.itemId === 'living-sideboard')
  if (!sofa || !table || !focal) return null
  const forwardX = focal.position[0] - sofa.position[0]
  const forwardZ = focal.position[2] - sofa.position[2]
  const forwardLength = Math.hypot(forwardX, forwardZ)
  if (forwardLength < 0.4) return null
  const unitX = forwardX / forwardLength
  const unitZ = forwardZ / forwardLength
  const lateralX = -unitZ
  const lateralZ = unitX
  const targetX = table.position[0] * 0.65 + sofa.position[0] * 0.35
  const targetZ = table.position[2] * 0.65 + sofa.position[2] * 0.35
  const offsetX = unitX * 0.9 + lateralX * 2.8
  const offsetZ = unitZ * 0.9 + lateralZ * 2.8
  return {
    target: [targetX, 0.82, targetZ],
    radius: Math.hypot(offsetX, offsetZ),
    // Babylon negates the X component of ArcRotateCamera in right-handed scenes.
    alpha: Math.atan2(offsetZ, -offsetX),
    beta: Math.PI * 0.42,
  }
}

export function searchWithStyle(search: string, styleId: string): string {
  if (!styleIdPattern.test(styleId)) throw new Error('装修风格 id 无效')
  const parameters = new URLSearchParams(search)
  parameters.set('style', styleId)
  return `?${parameters.toString()}`
}
