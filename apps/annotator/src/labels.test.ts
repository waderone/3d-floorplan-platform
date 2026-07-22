import assert from 'node:assert/strict'
import test from 'node:test'

import { ROOM_TYPE_OPTIONS, rightsStatusLabel, roomTypeLabel } from './labels.ts'

test('房型只翻译显示名称并保留英文数据值', () => {
  assert.deepEqual(
    ROOM_TYPE_OPTIONS.map(({ value, label }) => [value, label]),
    [
      ['living', '客厅'],
      ['dining', '餐厅'],
      ['bedroom', '卧室'],
      ['kitchen', '厨房'],
      ['bathroom', '卫生间'],
      ['balcony', '阳台'],
      ['unknown', '未分类'],
    ],
  )
  assert.equal(roomTypeLabel('living'), '客厅')
  assert.equal(roomTypeLabel('custom-room'), '其他类型（保留原值）')
})

test('权利状态使用中文显示名称', () => {
  assert.equal(rightsStatusLabel('pending'), '待审核')
  assert.equal(rightsStatusLabel('approved'), '已批准')
  assert.equal(rightsStatusLabel('rejected'), '已拒绝')
})
