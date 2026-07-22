export const ROOM_TYPE_OPTIONS = [
  { value: 'living', label: '客厅' },
  { value: 'dining', label: '餐厅' },
  { value: 'bedroom', label: '卧室' },
  { value: 'kitchen', label: '厨房' },
  { value: 'bathroom', label: '卫生间' },
  { value: 'balcony', label: '阳台' },
  { value: 'unknown', label: '未分类' },
] as const

const ROOM_TYPE_LABELS = new Map<string, string>(
  ROOM_TYPE_OPTIONS.map((option) => [option.value, option.label]),
)

const RIGHTS_STATUS_LABELS = {
  pending: '待审核',
  approved: '已批准',
  rejected: '已拒绝',
} as const

export function roomTypeLabel(value: string): string {
  return ROOM_TYPE_LABELS.get(value) ?? '其他类型（保留原值）'
}

export function rightsStatusLabel(status: keyof typeof RIGHTS_STATUS_LABELS): string {
  return RIGHTS_STATUS_LABELS[status]
}
