import type { StylePlacement } from './style-pack'

export interface LayoutRoom {
  id: string
  name: string
  source: 'zone' | 'slab'
  levelId: string | null
  polygon: Array<[number, number]>
  area: number
  centroid: [number, number]
}

export interface LayoutPlacement extends StylePlacement {
  roomId: string
}

export interface LayoutManifest {
  schemaVersion: '1.0'
  layoutId: string
  pipelineVersion: 'room-aware-layout-v1'
  projectId: string
  sceneRevision: number
  style: { id: string; version: number }
  status: 'ready' | 'fallback'
  fallbackReason: 'no-room-polygon' | 'no-room-fits' | null
  selectedRoomId: string | null
  wallClearance: number
  itemClearance: number
  rooms: LayoutRoom[]
  placements: LayoutPlacement[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function parseVector(value: unknown, length: 2 | 3): number[] {
  if (!Array.isArray(value) || value.length !== length || !value.every(isNumber)) {
    throw new Error('自动布局坐标格式无效')
  }
  return value
}

export function parseLayoutManifest(value: unknown): LayoutManifest {
  if (
    !isRecord(value) ||
    value.schemaVersion !== '1.0' ||
    typeof value.layoutId !== 'string' ||
    !/^[0-9a-f]{64}$/.test(value.layoutId) ||
    value.pipelineVersion !== 'room-aware-layout-v1' ||
    typeof value.projectId !== 'string' ||
    !Number.isInteger(value.sceneRevision) ||
    !isRecord(value.style) ||
    typeof value.style.id !== 'string' ||
    !Number.isInteger(value.style.version) ||
    !(value.status === 'ready' || value.status === 'fallback') ||
    !isNumber(value.wallClearance) ||
    !isNumber(value.itemClearance) ||
    !Array.isArray(value.rooms) ||
    !Array.isArray(value.placements)
  ) {
    throw new Error('自动布局服务返回了无效数据')
  }

  const rooms = value.rooms.map((room): LayoutRoom => {
    if (
      !isRecord(room) ||
      typeof room.id !== 'string' ||
      typeof room.name !== 'string' ||
      !(room.source === 'zone' || room.source === 'slab') ||
      !(room.levelId === null || typeof room.levelId === 'string') ||
      !isNumber(room.area) ||
      !Array.isArray(room.polygon)
    ) {
      throw new Error('自动布局房间格式无效')
    }
    return {
      ...room,
      polygon: room.polygon.map((point) => parseVector(point, 2) as [number, number]),
      centroid: parseVector(room.centroid, 2) as [number, number],
    } as LayoutRoom
  })

  const roomIds = new Set(rooms.map((room) => room.id))
  const placements = value.placements.map((placement): LayoutPlacement => {
    if (
      !isRecord(placement) ||
      typeof placement.id !== 'string' ||
      typeof placement.itemId !== 'string' ||
      typeof placement.roomId !== 'string' ||
      !roomIds.has(placement.roomId) ||
      typeof placement.assetId !== 'string' ||
      !(placement.kind === 'box' || placement.kind === 'cylinder' || placement.kind === 'sphere') ||
      typeof placement.role !== 'string' ||
      !(placement.collisionMode === 'solid' || placement.collisionMode === 'surface') ||
      !isNumber(placement.rotationYDegrees)
    ) {
      throw new Error('自动布局陈设格式无效')
    }
    const size = parseVector(placement.size, 3)
    if (size.some((entry) => entry <= 0)) throw new Error('自动布局陈设尺寸无效')
    return {
      ...placement,
      position: parseVector(placement.position, 3),
      size,
    } as LayoutPlacement
  })

  if (value.status === 'ready' && (typeof value.selectedRoomId !== 'string' || placements.length === 0)) {
    throw new Error('自动布局缺少选定房间或陈设')
  }
  if (value.status === 'fallback' && placements.length !== 0) {
    throw new Error('自动布局回退状态不能包含陈设')
  }
  return { ...value, rooms, placements } as LayoutManifest
}
