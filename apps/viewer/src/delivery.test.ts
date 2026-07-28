import assert from 'node:assert/strict'
import test from 'node:test'
import {
  bundleDataUrl,
  deliveryAssetUrl,
  resolveDeliveryConfig,
} from './delivery.ts'

test('uses API mode when delivery metadata is empty', () => {
  const config = resolveDeliveryConfig({}, '?project=customer-home&style=nordic-light')
  assert.equal(config.bundled, false)
  assert.equal(config.projectId, 'customer-home')
  assert.equal(config.initialStyleId, 'nordic-light')
  assert.equal(config.presentationMode, false)
  assert.equal(config.highQualityMode, false)
  assert.equal(
    deliveryAssetUrl(config, 'https://api.example.test', '/catalog-assets/models/sofa.glb'),
    'https://api.example.test/catalog-assets/models/sofa.glb',
  )
})

test('uses packaged data and allows explicit URL overrides', () => {
  const config = resolveDeliveryConfig(
    {
      dataBase: './showroom-data/',
      projectId: 'packaged-home',
      mode: 'presentation',
      quality: 'high',
    },
    '?style=modern-contrast&mode=full&quality=auto',
  )
  assert.equal(config.bundled, true)
  assert.equal(config.projectId, 'packaged-home')
  assert.equal(config.initialStyleId, 'modern-contrast')
  assert.equal(config.presentationMode, false)
  assert.equal(config.highQualityMode, false)
  assert.equal(bundleDataUrl(config, '/styles/index.json'), './showroom-data/styles/index.json')
  assert.equal(
    deliveryAssetUrl(config, '', '/render-assets/environment/room.hdr'),
    './showroom-data/render-assets/environment/room.hdr',
  )
})

test('defaults packaged presentation and high quality from metadata', () => {
  const config = resolveDeliveryConfig(
    {
      dataBase: './showroom-data',
      projectId: 'packaged-home',
      mode: 'presentation',
      quality: 'high',
    },
    '',
  )
  assert.equal(config.presentationMode, true)
  assert.equal(config.highQualityMode, true)
  assert.throws(
    () => resolveDeliveryConfig({ dataBase: './showroom-data?bad=1' }, ''),
    /数据地址/,
  )
})
