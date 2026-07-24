import type { StylePlacement } from './style-pack'

export interface LayoutRoom {
  id: string
  name: string
  roomType: 'living' | 'dining' | 'bedroom' | 'kitchen' | 'bathroom' | 'other'
  source: 'zone' | 'slab'
  levelId: string | null
  polygon: Array<[number, number]>
  area: number
  centroid: [number, number]
}

export interface LayoutPlacement extends StylePlacement {
  roomId: string
}

export interface LayoutOpening {
  id: string
  sourceType: 'door' | 'window'
  openingKind: 'door' | 'window' | 'opening'
  operationType: string
  wallId: string
  levelId: string | null
  roomIds: string[]
  center: [number, number]
  tangent: [number, number]
  width: number
  height: number
  sillHeight: number
  clearanceType: 'swing' | 'approach'
  clearanceDepth: number
  clearancePolygon: Array<[number, number]>
}

export interface LayoutManifest {
  schemaVersion: '3.0'
  layoutId: string
  pipelineVersion: 'multiroom-opening-clearance-layout-v6'
  projectId: string
  sceneRevision: number
  style: { id: string; version: number }
  assetCatalog: { id: string; version: number }
  status: 'ready' | 'partial' | 'fallback'
  fallbackReason: 'no-room-polygon' | 'no-supported-room' | 'no-room-fits' | null
  selectedRoomId: string | null
  furnishedRoomIds: string[]
  unfurnishedRoomIds: string[]
  referencedAssetBytes: number
  mobileAssetBudgetBytes: number
  mobileAssetBudgetExceeded: boolean
  wallClearance: number
  itemClearance: number
  placementSearch: 'bounded-grid-v1'
  openingClearanceValidated: boolean
  ignoredOpeningIds: string[]
  openingBlockedRoomIds: string[]
  rooms: LayoutRoom[]
  openings: LayoutOpening[]
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
    value.schemaVersion !== '3.0' ||
    typeof value.layoutId !== 'string' ||
    !/^[0-9a-f]{64}$/.test(value.layoutId) ||
    value.pipelineVersion !== 'multiroom-opening-clearance-layout-v6' ||
    typeof value.projectId !== 'string' ||
    !Number.isInteger(value.sceneRevision) ||
    !isRecord(value.style) ||
    typeof value.style.id !== 'string' ||
    !Number.isInteger(value.style.version) ||
    !isRecord(value.assetCatalog) ||
    typeof value.assetCatalog.id !== 'string' ||
    !Number.isInteger(value.assetCatalog.version) ||
    !(value.status === 'ready' || value.status === 'partial' || value.status === 'fallback') ||
    !Array.isArray(value.furnishedRoomIds) ||
    !value.furnishedRoomIds.every((entry) => typeof entry === 'string') ||
    !Array.isArray(value.unfurnishedRoomIds) ||
    !value.unfurnishedRoomIds.every((entry) => typeof entry === 'string') ||
    !isNumber(value.referencedAssetBytes) ||
    !isNumber(value.mobileAssetBudgetBytes) ||
    typeof value.mobileAssetBudgetExceeded !== 'boolean' ||
    !isNumber(value.wallClearance) ||
    !isNumber(value.itemClearance) ||
    value.placementSearch !== 'bounded-grid-v1' ||
    typeof value.openingClearanceValidated !== 'boolean' ||
    !Array.isArray(value.ignoredOpeningIds) ||
    !value.ignoredOpeningIds.every((entry) => typeof entry === 'string') ||
    !Array.isArray(value.openingBlockedRoomIds) ||
    !value.openingBlockedRoomIds.every((entry) => typeof entry === 'string') ||
    !Array.isArray(value.rooms) ||
    !Array.isArray(value.openings) ||
    !Array.isArray(value.placements)
  ) {
    throw new Error('自动布局服务返回了无效数据')
  }

  const rooms = value.rooms.map((room): LayoutRoom => {
    if (
      !isRecord(room) ||
      typeof room.id !== 'string' ||
      typeof room.name !== 'string' ||
      !(room.roomType === 'living' ||
        room.roomType === 'dining' ||
        room.roomType === 'bedroom' ||
        room.roomType === 'kitchen' ||
        room.roomType === 'bathroom' ||
        room.roomType === 'other') ||
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
  const openings = value.openings.map((opening): LayoutOpening => {
    if (
      !isRecord(opening) ||
      typeof opening.id !== 'string' ||
      !(opening.sourceType === 'door' || opening.sourceType === 'window') ||
      !(opening.openingKind === 'door' ||
        opening.openingKind === 'window' ||
        opening.openingKind === 'opening') ||
      typeof opening.operationType !== 'string' ||
      opening.operationType.length === 0 ||
      typeof opening.wallId !== 'string' ||
      !(opening.levelId === null || typeof opening.levelId === 'string') ||
      !Array.isArray(opening.roomIds) ||
      !opening.roomIds.every((roomId) => typeof roomId === 'string' && roomIds.has(roomId)) ||
      !isNumber(opening.width) ||
      opening.width <= 0 ||
      !isNumber(opening.height) ||
      opening.height <= 0 ||
      !isNumber(opening.sillHeight) ||
      opening.sillHeight < 0 ||
      !(opening.clearanceType === 'swing' || opening.clearanceType === 'approach') ||
      !isNumber(opening.clearanceDepth) ||
      opening.clearanceDepth <= 0 ||
      !Array.isArray(opening.clearancePolygon) ||
      opening.clearancePolygon.length < 3
    ) {
      throw new Error('自动布局开口格式无效')
    }
    return {
      ...opening,
      center: parseVector(opening.center, 2) as [number, number],
      tangent: parseVector(opening.tangent, 2) as [number, number],
      clearancePolygon: opening.clearancePolygon.map(
        (point) => parseVector(point, 2) as [number, number],
      ),
    } as LayoutOpening
  })
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

  if (
    (value.status === 'ready' || value.status === 'partial') &&
    (typeof value.selectedRoomId !== 'string' || placements.length === 0)
  ) {
    throw new Error('自动布局缺少选定房间或陈设')
  }
  if (value.status === 'fallback' && placements.length !== 0) {
    throw new Error('自动布局回退状态不能包含陈设')
  }
  return { ...value, rooms, openings, placements } as LayoutManifest
}
