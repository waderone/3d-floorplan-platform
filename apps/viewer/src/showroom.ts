export interface StyleSummary {
  id: string
  version: number
  name: string
  description: string
}

export interface ShowroomRoom {
  id: string
  name: string
  roomType: 'living' | 'dining' | 'bedroom' | 'other'
  polygon: Array<[number, number]>
  area: number
  centroid: [number, number]
}

export interface RoomViewOption {
  id: string
  label: string
  roomId: string
  roomType: 'living' | 'dining' | 'bedroom'
}

export interface RoomCameraPreset {
  target: [number, number, number]
  radius: number
}

const styleIdPattern = /^[a-z0-9][a-z0-9-]{0,63}$/
const roomTypeOrder = ['living', 'dining', 'bedroom'] as const
const roomTypeLabels = { living: '客厅', dining: '餐厅', bedroom: '卧室' } as const

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
    target: [room.centroid[0], 1.05, room.centroid[1]],
    radius: Math.max(4, Math.hypot(width, depth) * 0.9),
  }
}

export function searchWithStyle(search: string, styleId: string): string {
  if (!styleIdPattern.test(styleId)) throw new Error('装修风格 id 无效')
  const parameters = new URLSearchParams(search)
  parameters.set('style', styleId)
  return `?${parameters.toString()}`
}
