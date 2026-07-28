import { ArcRotateCamera } from '@babylonjs/core/Cameras/arcRotateCamera'
import { Engine } from '@babylonjs/core/Engines/engine'
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight'
import { DirectionalLight } from '@babylonjs/core/Lights/directionalLight'
import { PointLight } from '@babylonjs/core/Lights/pointLight'
import { ShadowGenerator } from '@babylonjs/core/Lights/Shadows/shadowGenerator'
import { LoadAssetContainerAsync } from '@babylonjs/core/Loading/sceneLoader'
import { ImageProcessingConfiguration } from '@babylonjs/core/Materials/imageProcessingConfiguration'
import { Material } from '@babylonjs/core/Materials/material'
import { Color3, Color4 } from '@babylonjs/core/Maths/math.color'
import { Vector3 } from '@babylonjs/core/Maths/math.vector'
import { MeshoptCompression } from '@babylonjs/core/Meshes/Compression/meshoptCompression'
import '@babylonjs/core/Meshes/instancedMesh'
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder'
import { PBRMaterial } from '@babylonjs/core/Materials/PBR/pbrMaterial'
import { HDRCubeTexture } from '@babylonjs/core/Materials/Textures/hdrCubeTexture'
import { Texture } from '@babylonjs/core/Materials/Textures/texture'
import { DefaultRenderingPipeline } from '@babylonjs/core/PostProcesses/RenderPipeline/Pipelines/defaultRenderingPipeline'
import { Scene } from '@babylonjs/core/scene'
import type { AssetContainer } from '@babylonjs/core/assetContainer'
import type { AbstractMesh } from '@babylonjs/core/Meshes/abstractMesh'
import meshoptDecoderSource from '../node_modules/meshoptimizer/meshopt_decoder.cjs?raw'
import { parseAssetCatalog, type AssetCatalog, type CatalogAsset } from './asset-catalog'
import {
  baselineStageText,
  isProjectId,
  parseBaselineManifest,
  type BaselineManifest,
} from './baseline'
import {
  bundleDataUrl,
  deliveryAssetUrl,
  resolveDeliveryConfig,
} from './delivery'
import { parseLayoutManifest, type LayoutManifest } from './layout'
import { parseArtifactManifest, type ArtifactManifest } from './manifest'
import {
  buildRoomViewOptions,
  livingCloseupCameraPreset,
  parseStyleSummaries,
  responsiveRoomCameraRadius,
  roomDetailCameraPreset,
  searchWithStyle,
  type RoomViewOption,
  type StyleSummary,
} from './showroom'
import { parseStylePack, type StylePack } from './style-pack'
import './style.css'

const rootElement = document.querySelector<HTMLElement>('#app')
if (!rootElement) throw new Error('Viewer root is missing')
const root: HTMLElement = rootElement

root.innerHTML = `
  <div class="viewer-shell" data-state="loading">
    <canvas id="scene" aria-label="可交互的 3D 户型"></canvas>
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">◇</span>
        <div><strong>空间预览</strong><span>3D 户型</span></div>
      </div>
      <div class="tool-actions">
        <button class="icon-button" id="clearances" type="button" aria-label="显示门窗动线净空" aria-pressed="false">⌗</button>
        <button class="icon-button" id="fullscreen" type="button" aria-label="全屏浏览">⛶</button>
      </div>
    </header>
    <aside class="model-card" aria-label="模型信息">
      <span class="eyebrow">沉浸式家居</span>
      <h1 id="project-name">全屋设计方案</h1>
      <div class="model-meta">
        <span id="style-name">风格加载中</span><span id="layout-status">空间加载中</span><span id="quality-status">实时画质</span>
      </div>
      <div class="model-stats" id="stats"></div>
    </aside>
    <aside class="style-panel" aria-label="装修风格">
      <span class="eyebrow">装修风格</span>
      <div class="style-heading"><strong>选择装修风格</strong><span id="style-switch-status" role="status" aria-live="polite"></span></div>
      <div class="style-options" id="style-options"></div>
      <p id="style-description">正在读取可用方案…</p>
    </aside>
    <section class="intake-panel" id="intake-panel" aria-labelledby="intake-title" hidden>
      <span class="eyebrow">户型图生成 3D</span>
      <h1 id="intake-title">上传户型图，生成可浏览的 3D 方案</h1>
      <p>当前基准适合边界清晰的直墙户型图。填写图纸外边界实际宽度，系统会自动识别、建模并生成三套可切换风格。</p>
      <form id="baseline-form">
        <label>方案标识<input id="baseline-project" name="project" required maxlength="64" pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}" /></label>
        <label>户型外宽（米）<input id="baseline-width" name="planWidthMeters" required type="number" min="1" max="500" step="0.01" value="10" /></label>
        <label class="file-field">户型图（PNG/JPG）<input id="baseline-file" name="file" required type="file" accept="image/png,image/jpeg" /></label>
        <button type="submit">生成实时 3D 方案</button>
      </form>
      <small>基准会自动接受高可读性的结构建议；门窗、曲墙和房间语义仍会作为限制明确记录。</small>
    </section>
    <div class="status-panel" id="status-panel" role="status" aria-live="polite">
      <div class="spinner" aria-hidden="true"></div>
      <div><strong id="status-title">正在读取模型</strong><span id="status-detail">连接到模型服务…</span></div>
      <div class="progress-track"><span id="progress"></span></div>
    </div>
    <div class="error-panel" id="error-panel" role="alert" hidden>
      <span class="error-mark" aria-hidden="true">!</span>
      <div><strong>暂时无法打开模型</strong><p id="error-message"></p></div>
      <button id="retry" type="button">重新加载</button>
    </div>
    <nav class="view-controls" aria-label="视角控制">
      <button data-view="whole" type="button" class="active">全屋</button>
      <button data-view="top" type="button">鸟瞰</button>
      <span id="room-views"></span>
    </nav>
    <p class="gesture-hint">拖动旋转 · 双指缩放 · 右键平移</p>
  </div>
`

function element<T extends Element>(selector: string): T {
  const found = root.querySelector<T>(selector)
  if (!found) throw new Error(`Viewer element is missing: ${selector}`)
  return found
}

const shell = element<HTMLElement>('.viewer-shell')
const canvas = element<HTMLCanvasElement>('#scene')
const statusPanel = element<HTMLElement>('#status-panel')
const statusTitle = element<HTMLElement>('#status-title')
const statusDetail = element<HTMLElement>('#status-detail')
const progress = element<HTMLElement>('#progress')
const errorPanel = element<HTMLElement>('#error-panel')
const errorMessage = element<HTMLElement>('#error-message')
const projectName = element<HTMLElement>('#project-name')
const stats = element<HTMLElement>('#stats')
const styleName = element<HTMLElement>('#style-name')
const layoutStatus = element<HTMLElement>('#layout-status')
const qualityStatus = element<HTMLElement>('#quality-status')
const styleOptions = element<HTMLElement>('#style-options')
const styleDescription = element<HTMLElement>('#style-description')
const styleSwitchStatus = element<HTMLElement>('#style-switch-status')
const roomViews = element<HTMLElement>('#room-views')
const clearancesButton = element<HTMLButtonElement>('#clearances')
const intakePanel = element<HTMLElement>('#intake-panel')
const baselineForm = element<HTMLFormElement>('#baseline-form')
const baselineProject = element<HTMLInputElement>('#baseline-project')
const baselineWidth = element<HTMLInputElement>('#baseline-width')
const baselineFile = element<HTMLInputElement>('#baseline-file')

function metaContent(name: string): string {
  return document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content ?? ''
}

const delivery = resolveDeliveryConfig(
  {
    dataBase: metaContent('showroom-data-base'),
    projectId: metaContent('showroom-project-id'),
    mode: metaContent('showroom-mode'),
    quality: metaContent('showroom-quality'),
  },
  window.location.search,
)
const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const projectId = delivery.projectId
let currentStyleId = delivery.initialStyleId
shell.dataset.presentation = String(delivery.presentationMode)
shell.dataset.quality = delivery.highQualityMode ? 'high' : 'auto'
baselineProject.value = `home-${Date.now().toString(36)}`
const compactDevice = window.matchMedia('(max-width: 700px), (pointer: coarse)').matches
const engine = new Engine(canvas, true, { adaptToDeviceRatio: true, stencil: true })
const renderPixelRatio = delivery.highQualityMode ? 2 : compactDevice ? 1.25 : 1.6
engine.setHardwareScalingLevel(Math.max(1, window.devicePixelRatio / renderPixelRatio))
const meshoptDecoderUrl = URL.createObjectURL(
  new Blob([meshoptDecoderSource], { type: 'text/javascript' }),
)
MeshoptCompression.Configuration = { decoder: { url: meshoptDecoderUrl } }
const scene = new Scene(engine)
scene.useRightHandedSystem = true
scene.clearColor = new Color4(0.91, 0.9, 0.86, 1)
const environmentTexture = new HDRCubeTexture(
  apiUrl('/render-assets/environment/lebombo_1k.hdr'),
  scene,
  delivery.highQualityMode || !compactDevice ? 128 : 64,
  false,
  true,
  false,
  true,
)
environmentTexture.rotationY = (118 * Math.PI) / 180
scene.environmentTexture = environmentTexture
scene.environmentIntensity = 0.72

const camera = new ArcRotateCamera(
  'camera',
  -Math.PI / 4,
  Math.PI / 3,
  12,
  Vector3.Zero(),
  scene,
)
camera.attachControl(canvas, true)
camera.lowerBetaLimit = 0.04
camera.upperBetaLimit = Math.PI / 2.02
camera.wheelPrecision = 45
camera.pinchPrecision = 110
camera.panningSensibility = 180
camera.inertia = 0.78

const skyLight = new HemisphericLight('sky', new Vector3(0.2, 1, 0.1), scene)
skyLight.intensity = 0.72
skyLight.diffuse = new Color3(1, 0.96, 0.88)
skyLight.groundColor = new Color3(0.35, 0.4, 0.46)
const sun = new DirectionalLight('sun', new Vector3(-0.45, -1, 0.35), scene)
sun.intensity = 1.8
sun.diffuse = new Color3(1, 0.9, 0.72)
const shadows = new ShadowGenerator(delivery.highQualityMode || !compactDevice ? 2048 : 1024, sun)
shadows.useBlurExponentialShadowMap = true
shadows.blurKernel = delivery.highQualityMode || !compactDevice ? 28 : 16
shadows.bias = delivery.highQualityMode ? 0.00035 : 0.0005
shadows.normalBias = delivery.highQualityMode ? 0.018 : 0.025
scene.imageProcessingConfiguration.toneMappingEnabled = true
scene.imageProcessingConfiguration.toneMappingType = ImageProcessingConfiguration.TONEMAPPING_ACES
scene.imageProcessingConfiguration.exposure = 1.08
scene.imageProcessingConfiguration.contrast = 1.12
scene.imageProcessingConfiguration.vignetteEnabled = true
scene.imageProcessingConfiguration.vignetteWeight = 1.15
const renderingPipeline = new DefaultRenderingPipeline('showroom-quality', true, scene, [camera])
renderingPipeline.fxaaEnabled = true
renderingPipeline.samples = delivery.highQualityMode || !compactDevice ? 4 : 1
renderingPipeline.bloomEnabled = true
renderingPipeline.bloomThreshold = 0.92
renderingPipeline.bloomWeight = 0.08

let container: AssetContainer | null = null
let styledAssetContainers: AssetContainer[] = []
let styledMeshes: AbstractMesh[] = []
let styledMaterials: PBRMaterial[] = []
let styledTextures: Texture[] = []
let styledLights: PointLight[] = []
let architectureMaterial: PBRMaterial | null = null
let defaultTarget = Vector3.Zero()
let baseRadius = 12
let defaultRadius = 12
let perspectiveAlpha = -Math.PI / 4
let perspectiveBeta = Math.PI / 3
let radiusMultiplier = 1
let currentManifest: ArtifactManifest | null = null
let currentLayout: LayoutManifest | null = null
let currentCatalog: AssetCatalog | null = null
let styleSummaries: StyleSummary[] = []
let roomViewOptions: RoomViewOption[] = []
let switchingStyle = false
let openingClearancesVisible = false
const noHiddenItemIds: ReadonlySet<string> = new Set()
const livingCloseupHiddenItemIds = new Set(['living-television'])

function apiUrl(path: string): string {
  return deliveryAssetUrl(delivery, apiBase, path)
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KiB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
}

function setStatus(title: string, detail: string, percent = 0): void {
  shell.dataset.state = 'loading'
  statusPanel.hidden = false
  errorPanel.hidden = true
  statusTitle.textContent = title
  statusDetail.textContent = detail
  progress.style.width = `${Math.max(0, Math.min(100, percent))}%`
}

function setError(error: unknown): void {
  shell.dataset.state = 'error'
  statusPanel.hidden = true
  errorPanel.hidden = false
  errorMessage.textContent = error instanceof Error ? error.message : '发生未知错误'
}

function showBaselineIntake(): void {
  shell.dataset.state = 'intake'
  intakePanel.hidden = false
  statusPanel.hidden = true
  errorPanel.hidden = true
  document.title = '户型图生成 3D 全屋方案'
}

function baselineProgress(manifest: BaselineManifest): number {
  return { recognition: 20, scene: 44, artifact: 68, layout: 88, ready: 100, failed: 0 }[
    manifest.stage
  ]
}

async function waitForBaseline(project: string): Promise<BaselineManifest> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const response = await fetch(
      apiUrl(`/api/projects/${encodeURIComponent(project)}/baselines/latest`),
      { cache: 'no-store' },
    )
    if (!response.ok) throw new Error(`自动生成状态请求失败（${response.status}）`)
    const manifest = parseBaselineManifest(await response.json())
    setStatus(baselineStageText(manifest.stage), '正在把户型图转换为客户可浏览的实时方案…', baselineProgress(manifest))
    if (manifest.status === 'failed') throw new Error(manifest.error ?? '自动生成未完成')
    if (manifest.status === 'ready') return manifest
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
  }
  throw new Error('自动生成超时，请稍后使用同一方案标识查询')
}

async function createBaseline(): Promise<void> {
  const project = baselineProject.value.trim()
  const file = baselineFile.files?.[0]
  const width = Number(baselineWidth.value)
  if (!isProjectId(project)) throw new Error('方案标识只能包含字母、数字、短横线或下划线')
  if (!file) throw new Error('请选择 PNG 或 JPG 户型图')
  if (!(Number.isFinite(width) && width >= 1 && width <= 500)) {
    throw new Error('请输入 1～500 米之间的户型外宽')
  }
  intakePanel.hidden = true
  setStatus('正在提交户型图', '创建自动识别与 3D 生成任务…', 6)
  const data = new FormData()
  data.set('file', file)
  data.set('planWidthMeters', String(width))
  const response = await fetch(apiUrl(`/api/projects/${encodeURIComponent(project)}/baselines`), {
    method: 'POST',
    body: data,
  })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    if (
      typeof body === 'object' &&
      body !== null &&
      'detail' in body &&
      typeof body.detail === 'object' &&
      body.detail !== null &&
      'code' in body.detail &&
      body.detail.code === 'baseline_project_exists'
    ) {
      throw new Error('这个方案标识已经存在，请换一个新的标识')
    }
    throw new Error(`户型图提交失败（${response.status}）`)
  }
  parseBaselineManifest(await response.json())
  const ready = await waitForBaseline(project)
  if (!ready.viewerUrl) throw new Error('自动生成完成但缺少客户浏览链接')
  window.location.assign(ready.viewerUrl)
}

function setReady(
  manifest: ArtifactManifest,
  style: StylePack,
  layout: LayoutManifest,
  assetStats: { models: number; fallbacks: number },
): void {
  shell.dataset.state = 'ready'
  statusPanel.hidden = true
  errorPanel.hidden = true
  projectName.textContent = '全屋设计方案'
  document.title = `${style.name} · 3D 全屋方案`
  styleName.textContent = style.name
  styleDescription.textContent = style.description
  layoutStatus.textContent = layout.furnishedRoomIds.length
    ? layout.unfurnishedRoomIds.length
      ? `已布置 ${layout.furnishedRoomIds.length} · 待处理 ${layout.unfurnishedRoomIds.length}`
      : `已布置 · ${layout.furnishedRoomIds.length} 个房间`
    : layout.openingBlockedRoomIds.length
      ? `门窗净空阻断 ${layout.openingBlockedRoomIds.length} 个房间`
      : layout.fallbackReason === 'no-room-fits'
        ? '房间尺寸不足'
        : layout.fallbackReason === 'no-supported-room'
          ? '暂无支持的房间类型'
          : '待补房间边界'
  qualityStatus.textContent = manifest.mobileBudgetExceeded
    ? '轻量降级模式'
    : delivery.highQualityMode
      ? '高端演示画质'
      : compactDevice
        ? '移动优化画质'
        : '实时高画质'
  const furnitureItems = new Set(layout.placements.map((placement) => placement.itemId)).size
  stats.innerHTML = `<span><strong>${layout.rooms.length}</strong> 个空间</span><span><strong>${furnitureItems}</strong> 组家具</span><span><strong>${layout.openings.length}</strong> 个门窗开口</span><span><strong>${assetStats.models}</strong> 真实模型</span>${assetStats.fallbacks ? `<span class="fallback-stat"><strong>${assetStats.fallbacks}</strong> 项回退</span>` : ''}`
  clearancesButton.hidden = layout.openings.length === 0
  renderStyleOptions()
  renderRoomViews(layout)
}

function setStyleSwitching(active: boolean, message = ''): void {
  switchingStyle = active
  shell.dataset.styleState = active ? 'switching' : 'ready'
  styleSwitchStatus.textContent = message
  for (const button of styleOptions.querySelectorAll<HTMLButtonElement>('button')) {
    button.disabled = active
  }
}

function renderStyleOptions(): void {
  styleOptions.replaceChildren()
  for (const summary of styleSummaries) {
    const button = document.createElement('button')
    button.type = 'button'
    button.dataset.styleId = summary.id
    button.className = summary.id === currentStyleId ? 'active' : ''
    button.setAttribute('aria-pressed', String(summary.id === currentStyleId))
    const swatch = document.createElement('span')
    swatch.className = 'style-swatch'
    swatch.setAttribute('aria-hidden', 'true')
    const copy = document.createElement('span')
    const name = document.createElement('strong')
    const description = document.createElement('small')
    name.textContent = summary.name
    description.textContent = summary.description
    copy.append(name, description)
    button.append(swatch, copy)
    button.addEventListener('click', () => void switchStyle(summary.id))
    styleOptions.append(button)
  }
}

function setActiveView(viewId: string): void {
  for (const peer of root.querySelectorAll<HTMLButtonElement>('[data-view]')) {
    const active = peer.dataset.view === viewId
    peer.classList.toggle('active', active)
    peer.setAttribute('aria-pressed', String(active))
  }
}

function setArchitectureOpacity(opacity: number): void {
  if (!architectureMaterial) return
  architectureMaterial.alpha = opacity
  architectureMaterial.transparencyMode = opacity < 1
    ? Material.MATERIAL_ALPHABLEND
    : Material.MATERIAL_OPAQUE
}

function setDoorDetailsVisible(visible: boolean): void {
  for (const mesh of styledMeshes) {
    if (mesh.name.startsWith('door-')) mesh.isVisible = visible
  }
}

function setFurnitureRoomVisibility(
  roomId: string | null,
  hiddenItemIds: ReadonlySet<string> = noHiddenItemIds,
): void {
  const apply = (mesh: AbstractMesh): void => {
    const metadata = mesh.metadata as {
      showroomItemId?: unknown
      showroomRoomId?: unknown
    } | null
    if (typeof metadata?.showroomRoomId !== 'string') return
    const roomVisible = roomId === null || metadata.showroomRoomId === roomId
    const itemVisible =
      typeof metadata.showroomItemId !== 'string' || !hiddenItemIds.has(metadata.showroomItemId)
    mesh.setEnabled(roomVisible && itemVisible)
  }
  for (const mesh of styledMeshes) apply(mesh)
  for (const container of styledAssetContainers) {
    for (const mesh of container.meshes) apply(mesh)
  }
}

function renderRoomViews(layout: LayoutManifest): void {
  roomViewOptions = buildRoomViewOptions(layout.rooms, layout.furnishedRoomIds)
  roomViews.replaceChildren()
  for (const option of roomViewOptions) {
    const button = document.createElement('button')
    button.type = 'button'
    button.dataset.view = option.id
    button.textContent = option.label
    button.addEventListener('click', () => applyView(option.id))
    roomViews.append(button)
    if (option.roomType === 'living' && !roomViews.querySelector('[data-view^="closeup:"]')) {
      const closeup = document.createElement('button')
      closeup.type = 'button'
      closeup.dataset.view = `closeup:${option.roomId}`
      closeup.textContent = '客厅近景'
      closeup.addEventListener('click', () => applyView(closeup.dataset.view ?? option.id))
      roomViews.append(closeup)
    }
  }
}

function preferredDeliveryView(layout: LayoutManifest): string {
  if (!delivery.presentationMode) return 'whole'
  const livingRoom = layout.rooms.find(
    (room) => room.roomType === 'living' && layout.furnishedRoomIds.includes(room.id),
  )
  return livingRoom ? `closeup:${livingRoom.id}` : 'whole'
}

function frameModel(layout: LayoutManifest): void {
  const visibleMeshes = scene.meshes.filter((mesh) => mesh.isVisible && mesh.getTotalVertices() > 0)
  if (visibleMeshes.length === 0) throw new Error('模型中没有可显示的几何体')
  const bounds = scene.getWorldExtends((mesh) => visibleMeshes.includes(mesh))
  const extent = bounds.max.subtract(bounds.min)
  const furnishedRooms = layout.rooms.filter((room) => layout.furnishedRoomIds.includes(room.id))
  if (furnishedRooms.length > 0) {
    const roomX = furnishedRooms.flatMap((room) => room.polygon.map((point) => point[0]))
    const roomZ = furnishedRooms.flatMap((room) => room.polygon.map((point) => point[1]))
    defaultTarget = new Vector3(
      (Math.min(...roomX) + Math.max(...roomX)) / 2,
      bounds.min.y + Math.max(0.7, extent.y * 0.42),
      (Math.min(...roomZ) + Math.max(...roomZ)) / 2,
    )
    const frameFactor = furnishedRooms.length > 1 ? 1.22 : 0.72
    baseRadius = Math.max(
      4,
      Math.hypot(Math.max(...roomX) - Math.min(...roomX), Math.max(...roomZ) - Math.min(...roomZ)) *
        frameFactor,
    )
  } else {
    defaultTarget = bounds.min.add(extent.scale(0.5))
    baseRadius = Math.max(2, extent.length() * 0.85)
  }
  defaultRadius = radiusForViewport()
  camera.setTarget(defaultTarget)
  camera.radius = defaultRadius
  camera.lowerRadiusLimit = Math.max(0.5, defaultRadius * 0.12)
  camera.upperRadiusLimit = Math.max(30, defaultRadius * 5)
}

function radiusForViewport(): number {
  const aspect = engine.getRenderWidth() / Math.max(1, engine.getRenderHeight())
  return baseRadius * radiusMultiplier * Math.max(1, 0.8 / aspect)
}

function color3(value: string): Color3 {
  return Color3.FromHexString(value)
}

function clearStyle(): void {
  for (const assetContainer of styledAssetContainers) {
    for (const mesh of assetContainer.meshes) shadows.removeShadowCaster(mesh, true)
    assetContainer.dispose()
  }
  for (const mesh of styledMeshes) {
    shadows.removeShadowCaster(mesh, true)
    mesh.dispose(false, false)
  }
  for (const material of styledMaterials) material.dispose()
  for (const texture of styledTextures) texture.dispose()
  for (const light of styledLights) light.dispose()
  styledMeshes = []
  styledMaterials = []
  styledTextures = []
  styledLights = []
  architectureMaterial = null
  styledAssetContainers = []
}

function modelBounds(meshes: AbstractMesh[]): { minimum: Vector3; maximum: Vector3 } {
  const visible = meshes.filter((mesh) => mesh.isVisible && mesh.getTotalVertices() > 0)
  if (visible.length === 0) throw new Error('模型中没有可应用风格的几何体')
  const bounds = scene.getWorldExtends((mesh) => visible.includes(mesh))
  return { minimum: bounds.min, maximum: bounds.max }
}

function addOpeningClearanceGuides(layout: LayoutManifest, floorTop: number): void {
  for (const opening of layout.openings) {
    const points = [...opening.clearancePolygon, opening.clearancePolygon[0]!].map(
      ([x, z]) => new Vector3(x, floorTop + 0.025, z),
    )
    const outline = MeshBuilder.CreateDashedLines(
      `opening-clearance-${opening.id}`,
      { points, dashSize: 0.16, gapSize: 0.08, dashNb: 64 },
      scene,
    )
    outline.color = opening.sourceType === 'door' ? new Color3(0.06, 0.4, 0.23) : new Color3(0.06, 0.3, 0.62)
    outline.isVisible = openingClearancesVisible
    outline.isPickable = false
    styledMeshes.push(outline)
  }
}

function registerDetailMesh(mesh: AbstractMesh, material: PBRMaterial, castsShadow = true): void {
  mesh.material = material
  mesh.receiveShadows = true
  mesh.isPickable = false
  if (castsShadow) shadows.addShadowCaster(mesh, true)
  styledMeshes.push(mesh)
}

function addRoomSurfaceDetails(layout: LayoutManifest, floorTop: number, style: StylePack): void {
  if (style.id !== 'warm-minimal') return
  const kitchenStone = new PBRMaterial('kitchen-stone-floor', scene)
  kitchenStone.albedoColor = Color3.FromHexString('#A7957E')
  kitchenStone.metallic = 0
  kitchenStone.roughness = 0.42
  kitchenStone.environmentIntensity = 0.86
  const bathroomStone = new PBRMaterial('bathroom-limestone-floor', scene)
  bathroomStone.albedoColor = Color3.FromHexString('#C7BBA8')
  bathroomStone.metallic = 0
  bathroomStone.roughness = 0.3
  bathroomStone.environmentIntensity = 0.92
  const grout = new PBRMaterial('bathroom-grout', scene)
  grout.albedoColor = Color3.FromHexString('#8E8375')
  grout.metallic = 0
  grout.roughness = 0.88
  styledMaterials.push(kitchenStone, bathroomStone, grout)

  for (const room of layout.rooms) {
    if (room.roomType !== 'kitchen' && room.roomType !== 'bathroom') continue
    const xValues = room.polygon.map((point) => point[0])
    const zValues = room.polygon.map((point) => point[1])
    const minimumX = Math.min(...xValues) + 0.045
    const maximumX = Math.max(...xValues) - 0.045
    const minimumZ = Math.min(...zValues) + 0.045
    const maximumZ = Math.max(...zValues) - 0.045
    const width = maximumX - minimumX
    const depth = maximumZ - minimumZ
    if (width <= 0.2 || depth <= 0.2) continue
    const surface = MeshBuilder.CreateBox(
      `${room.roomType}-surface-${room.id}`,
      { width, height: 0.025, depth },
      scene,
    )
    surface.position.set(
      (minimumX + maximumX) / 2,
      floorTop + 0.0125,
      (minimumZ + maximumZ) / 2,
    )
    registerDetailMesh(
      surface,
      room.roomType === 'bathroom' ? bathroomStone : kitchenStone,
      false,
    )
    if (room.roomType !== 'bathroom') continue
    const tileSize = 0.58
    for (let x = minimumX + tileSize; x < maximumX - 0.1; x += tileSize) {
      const line = MeshBuilder.CreateBox(
        `bathroom-grout-x-${room.id}-${x.toFixed(2)}`,
        { width: 0.012, height: 0.008, depth },
        scene,
      )
      line.position.set(x, floorTop + 0.029, (minimumZ + maximumZ) / 2)
      registerDetailMesh(line, grout, false)
    }
    for (let z = minimumZ + tileSize; z < maximumZ - 0.1; z += tileSize) {
      const line = MeshBuilder.CreateBox(
        `bathroom-grout-z-${room.id}-${z.toFixed(2)}`,
        { width, height: 0.008, depth: 0.012 },
        scene,
      )
      line.position.set((minimumX + maximumX) / 2, floorTop + 0.029, z)
      registerDetailMesh(line, grout, false)
    }
  }
}

function addArchitecturalDetails(
  layout: LayoutManifest,
  floorTop: number,
  materials: Record<string, PBRMaterial>,
  style: StylePack,
): void {
  const architecture = materials.architecture
  const wood = materials.wood ?? architecture
  const metal = materials.metal ?? wood
  const fabric = materials.fabric ?? architecture
  if (!architecture) return

  const seenEdges = new Set<string>()
  for (const room of layout.rooms) {
    for (let index = 0; index < room.polygon.length; index += 1) {
      const start = room.polygon[index]!
      const end = room.polygon[(index + 1) % room.polygon.length]!
      const ordered = [start, end].sort((a, b) => a[0] - b[0] || a[1] - b[1])
      const key = ordered.map((point) => point.map((entry) => entry.toFixed(3)).join(',')).join('|')
      if (seenEdges.has(key)) continue
      seenEdges.add(key)
      const dx = end[0] - start[0]
      const dz = end[1] - start[1]
      const length = Math.hypot(dx, dz)
      if (length < 0.18) continue
      const baseboard = MeshBuilder.CreateBox(
        `baseboard-${room.id}-${index}`,
        { width: length, height: 0.11, depth: 0.035 },
        scene,
      )
      baseboard.position.set((start[0] + end[0]) / 2, floorTop + 0.055, (start[1] + end[1]) / 2)
      baseboard.rotation.y = -Math.atan2(dz, dx)
      registerDetailMesh(baseboard, architecture)
    }
  }

  for (const opening of layout.openings) {
    const [tx, tz] = opening.tangent
    const tangentLength = Math.hypot(tx, tz)
    if (tangentLength < 1e-6) continue
    const tangent = [tx / tangentLength, tz / tangentLength] as const
    const normal = [-tangent[1], tangent[0]] as const
    const angle = -Math.atan2(tangent[1], tangent[0])
    const frameHeight = opening.sillHeight + opening.height
    for (const side of [-1, 1]) {
      const post = MeshBuilder.CreateBox(
        `door-frame-${opening.id}-${side}`,
        { width: 0.09, height: opening.height + 0.1, depth: 0.16 },
        scene,
      )
      post.position.set(
        opening.center[0] + tangent[0] * (opening.width / 2 + 0.035) * side,
        floorTop + opening.sillHeight + opening.height / 2,
        opening.center[1] + tangent[1] * (opening.width / 2 + 0.035) * side,
      )
      post.rotation.y = angle
      registerDetailMesh(post, wood)
    }
    const header = MeshBuilder.CreateBox(
      `door-header-${opening.id}`,
      { width: opening.width + 0.16, height: 0.09, depth: 0.16 },
      scene,
    )
    header.position.set(opening.center[0], floorTop + frameHeight + 0.045, opening.center[1])
    header.rotation.y = angle
    registerDetailMesh(header, wood)

    if (opening.sourceType === 'window') {
      const relatedRoom = layout.rooms.find((room) => opening.roomIds.includes(room.id))
      const towardRoom = relatedRoom
        ? [relatedRoom.centroid[0] - opening.center[0], relatedRoom.centroid[1] - opening.center[1]]
        : normal
      const normalSign = normal[0] * towardRoom[0] + normal[1] * towardRoom[1] >= 0 ? 1 : -1
      const inward = [normal[0] * normalSign, normal[1] * normalSign] as const
      const curtainHeight = Math.min(2.45, Math.max(1.6, frameHeight + 0.18))
      const panelWidth = Math.max(0.24, opening.width * 0.3)
      const foldWidth = panelWidth / 4
      for (const side of [-1, 1]) {
        const panelCenter = side * (opening.width / 2 - panelWidth / 2)
        for (let fold = 0; fold < 4; fold += 1) {
          const along = panelCenter + (fold - 1.5) * foldWidth
          const wave = fold % 2 === 0 ? 0.025 : -0.018
          const curtainFold = MeshBuilder.CreateBox(
            `curtain-${opening.id}-${side}-${fold}`,
            { width: foldWidth * 0.9, height: curtainHeight, depth: 0.075 },
            scene,
          )
          curtainFold.position.set(
            opening.center[0] + tangent[0] * along + inward[0] * (0.11 + wave),
            floorTop + curtainHeight / 2 + 0.04,
            opening.center[1] + tangent[1] * along + inward[1] * (0.11 + wave),
          )
          curtainFold.rotation.y = angle
          registerDetailMesh(curtainFold, fabric)
        }
      }
      const rod = MeshBuilder.CreateBox(
        `curtain-rod-${opening.id}`,
        { width: opening.width + 0.5, height: 0.035, depth: 0.045 },
        scene,
      )
      rod.position.set(
        opening.center[0] + inward[0] * 0.08,
        floorTop + curtainHeight + 0.08,
        opening.center[1] + inward[1] * 0.08,
      )
      rod.rotation.y = angle
      registerDetailMesh(rod, metal)
    }

    if (opening.sourceType !== 'door' || opening.openingKind === 'opening') continue
    const leafWidth = Math.max(0.45, opening.width - 0.1)
    const openAngle = Math.PI / 7
    const leafDirection = [
      tangent[0] * Math.cos(openAngle) + normal[0] * Math.sin(openAngle),
      tangent[1] * Math.cos(openAngle) + normal[1] * Math.sin(openAngle),
    ] as const
    const hinge = [
      opening.center[0] - tangent[0] * leafWidth / 2,
      opening.center[1] - tangent[1] * leafWidth / 2,
    ] as const
    const leaf = MeshBuilder.CreateBox(
      `door-leaf-${opening.id}`,
      { width: leafWidth, height: opening.height - 0.08, depth: 0.045 },
      scene,
    )
    leaf.position.set(
      hinge[0] + leafDirection[0] * leafWidth / 2,
      floorTop + opening.height / 2,
      hinge[1] + leafDirection[1] * leafWidth / 2,
    )
    leaf.rotation.y = -Math.atan2(leafDirection[1], leafDirection[0])
    registerDetailMesh(leaf, wood)
    const handle = MeshBuilder.CreateSphere(
      `door-handle-${opening.id}`,
      { diameter: 0.055, segments: 16 },
      scene,
    )
    handle.position.set(
      hinge[0] + leafDirection[0] * (leafWidth - 0.11) + normal[0] * 0.035,
      floorTop + 1.0,
      hinge[1] + leafDirection[1] * (leafWidth - 0.11) + normal[1] * 0.035,
    )
    registerDetailMesh(handle, metal)
  }

  const warmLight = Color3.FromHexString(style.id === 'warm-minimal' ? '#FFD1A0' : '#FFE4C7')
  for (const room of layout.rooms.filter((candidate) => layout.furnishedRoomIds.includes(candidate.id))) {
    const light = new PointLight(
      `room-light-${room.id}`,
      new Vector3(room.centroid[0], floorTop + 2.3, room.centroid[1]),
      scene,
    )
    light.diffuse = warmLight
    const livingFocus = style.id === 'warm-minimal' && room.roomType === 'living'
    const detailedRoom = style.id === 'warm-minimal' &&
      (room.roomType === 'bedroom' || room.roomType === 'kitchen' || room.roomType === 'bathroom')
    light.intensity = livingFocus
      ? (compactDevice ? 0.82 : 1.05)
      : detailedRoom
        ? (compactDevice ? 0.58 : 0.76)
        : (compactDevice ? 0.42 : 0.56)
    light.range = Math.max(3.2, Math.sqrt(room.area) * (livingFocus ? 1.35 : 1.55))
    styledLights.push(light)

    let focalItemId: string | undefined
    if (room.roomType === 'bedroom') focalItemId = 'bedroom-nightstand-west'
    else if (room.roomType === 'kitchen') focalItemId = 'kitchen-suite'
    else if (room.roomType === 'bathroom') focalItemId = 'bathroom-suite'
    const focal = focalItemId
      ? layout.placements.find(
          (placement) => placement.roomId === room.id && placement.itemId === focalItemId,
        )
      : undefined
    if (!focal || style.id !== 'warm-minimal') continue
    const accentLight = new PointLight(
      `room-accent-light-${room.id}`,
      new Vector3(
        focal.position[0],
        floorTop + (room.roomType === 'bedroom' ? 1.15 : 1.55),
        focal.position[2] - 0.08,
      ),
      scene,
    )
    accentLight.diffuse = room.roomType === 'bathroom'
      ? Color3.FromHexString('#FFF0D7')
      : Color3.FromHexString('#FFB86A')
    accentLight.intensity = compactDevice ? 0.26 : 0.38
    accentLight.range = room.roomType === 'bedroom' ? 2.2 : 2.6
    styledLights.push(accentLight)
  }
}

function setOpeningClearancesVisible(visible: boolean): void {
  openingClearancesVisible = visible
  for (const mesh of styledMeshes) {
    if (mesh.name.startsWith('opening-clearance-')) mesh.isVisible = visible
  }
  clearancesButton.setAttribute('aria-pressed', String(visible))
  clearancesButton.classList.toggle('active', visible)
}

function createFallback(
  placement: LayoutManifest['placements'][number],
  floorTop: number,
  material: PBRMaterial,
): void {
  const [width, height, depth] = placement.size
  let mesh: AbstractMesh
  if (placement.kind === 'box') {
    mesh = MeshBuilder.CreateBox(`style-${placement.id}`, { width, height, depth }, scene)
  } else if (placement.kind === 'cylinder') {
    mesh = MeshBuilder.CreateCylinder(
      `style-${placement.id}`,
      { height, diameter: Math.max(width, depth), tessellation: 48 },
      scene,
    )
  } else {
    mesh = MeshBuilder.CreateSphere(`style-${placement.id}`, { segments: 32, diameter: 1 }, scene)
    mesh.scaling.set(width, height, depth)
  }
  mesh.position.set(placement.position[0], floorTop + placement.position[1], placement.position[2])
  mesh.rotation.y = (placement.rotationYDegrees * Math.PI) / 180
  mesh.metadata = {
    ...(mesh.metadata ?? {}),
    showroomItemId: placement.itemId,
    showroomRoomId: placement.roomId,
  }
  mesh.material = material
  mesh.receiveShadows = true
  shadows.addShadowCaster(mesh, true)
  styledMeshes.push(mesh)
}

async function loadCatalogModel(
  placement: LayoutManifest['placements'][number],
  asset: CatalogAsset,
  floorTop: number,
  material: PBRMaterial,
  highQualityTextures = false,
): Promise<boolean> {
  if (asset.kind !== 'model' || !asset.delivery) return false
  try {
    const modelUrl = new URL(apiUrl(asset.delivery.url), window.location.origin)
    modelUrl.searchParams.set('sha256', asset.delivery.sha256)
    const assetContainer = await LoadAssetContainerAsync(modelUrl.toString(), scene)
    const roots = assetContainer.meshes.filter((mesh) => mesh.parent === null)
    if (roots.length === 0) throw new Error(`资产 ${asset.id} 没有根节点`)
    const scale = placement.size.map((value, index) => value / asset.canonicalSize[index])
    for (const rootMesh of roots) {
      rootMesh.scaling.set(scale[0], scale[1], scale[2])
      rootMesh.position.set(
        placement.position[0],
        floorTop + placement.position[1] - placement.size[1] / 2,
        placement.position[2],
      )
      rootMesh.rotation.y = (placement.rotationYDegrees * Math.PI) / 180
    }
    for (const mesh of assetContainer.meshes) {
      mesh.metadata = {
        ...(mesh.metadata ?? {}),
        showroomItemId: placement.itemId,
        showroomRoomId: placement.roomId,
      }
      if (mesh.getTotalVertices() === 0) continue
      if (asset.materialMode === 'replace') mesh.material = material
      mesh.receiveShadows = true
      shadows.addShadowCaster(mesh, true)
    }
    for (const importedMaterial of assetContainer.materials) {
      if (!(importedMaterial instanceof PBRMaterial)) continue
      importedMaterial.environmentIntensity = 0.92
      if (highQualityTextures) {
        for (const texture of importedMaterial.getActiveTextures()) {
          if (texture instanceof Texture) texture.anisotropicFilteringLevel = 16
        }
      }
      if (
        asset.id === 'project-warm-minimal-bathroom' &&
        importedMaterial.name.includes('silvered-mirror')
      ) {
        importedMaterial.albedoColor = Color3.FromHexString('#71858A')
        importedMaterial.emissiveColor = Color3.FromHexString('#162226')
        importedMaterial.metallic = 0.18
        importedMaterial.roughness = 0.16
        importedMaterial.environmentIntensity = 1.2
      }
    }
    if (asset.materialMode === 'tint') {
      for (const importedMaterial of assetContainer.materials) {
        if (importedMaterial instanceof PBRMaterial) {
          importedMaterial.albedoColor = importedMaterial.albedoColor.multiply(material.albedoColor)
          importedMaterial.environmentIntensity = material.environmentIntensity
        }
      }
    }
    assetContainer.addAllToScene()
    styledAssetContainers.push(assetContainer)
    return true
  } catch (error) {
    console.warn(`真实资产 ${asset.id} 加载失败，使用程序化回退`, error)
    return false
  }
}

async function applyStyle(
  style: StylePack,
  layout: LayoutManifest,
  catalog: AssetCatalog,
  model: AssetContainer,
): Promise<{ models: number; fallbacks: number }> {
  clearStyle()
  const warmMinimal = style.id === 'warm-minimal'
  const materials = Object.fromEntries(
    Object.entries(style.materials).map(([role, value]) => {
      const material = new PBRMaterial(`style-${role}`, scene)
      material.albedoColor = color3(value.baseColor)
      material.metallic = value.metallic
      material.roughness = value.roughness
      material.environmentIntensity = 0.8
      styledMaterials.push(material)
      return [role, material]
    }),
  )
  const architecture = materials.architecture
  if (!architecture) throw new Error('风格包缺少建筑材质')
  const accent = materials.accent
  if (style.id === 'warm-minimal' && accent) {
    const rugAlbedo = new Texture(
      apiUrl('/render-assets/materials/natural-rug/curly_teddy_natural_diff_1k.jpg'),
      scene,
    )
    const rugNormal = new Texture(
      apiUrl('/render-assets/materials/natural-rug/curly_teddy_natural_nor_gl_1k.jpg'),
      scene,
    )
    const rugRoughness = new Texture(
      apiUrl('/render-assets/materials/natural-rug/curly_teddy_natural_rough_1k.jpg'),
      scene,
    )
    for (const texture of [rugAlbedo, rugNormal, rugRoughness]) {
      texture.uScale = 10
      texture.vScale = 8
      texture.anisotropicFilteringLevel = 16
      styledTextures.push(texture)
    }
    rugNormal.level = 0.55
    rugRoughness.gammaSpace = false
    accent.albedoColor = Color3.White()
    accent.albedoTexture = rugAlbedo
    accent.bumpTexture = rugNormal
    accent.metallicTexture = rugRoughness
    accent.metallic = 0
    accent.roughness = 1
    accent.useRoughnessFromMetallicTextureAlpha = false
    accent.useRoughnessFromMetallicTextureGreen = true
    accent.useMetallnessFromMetallicTextureBlue = false
  }
  architectureMaterial = architecture
  for (const mesh of model.meshes) {
    if (mesh.getTotalVertices() > 0) {
      mesh.material = architecture
      mesh.receiveShadows = true
      shadows.addShadowCaster(mesh, true)
    }
  }

  const bounds = modelBounds(model.meshes)
  const extent = bounds.maximum.subtract(bounds.minimum)
  const center = bounds.minimum.add(extent.scale(0.5))
  const floorEdge = Math.min(0.12, style.layout.floorPadding)
  const floorWidth = Math.max(6, extent.x + floorEdge * 2)
  const floorDepth = Math.max(6, extent.z + floorEdge * 2)
  const floorHeight = 0.12
  const floor = MeshBuilder.CreateBox(
    'style-floor',
    { width: floorWidth, height: floorHeight, depth: floorDepth },
    scene,
  )
  floor.position.set(center.x, bounds.minimum.y - floorHeight / 2, center.z)
  const floorMaterial = materials.floor ?? architecture
  if (style.id === 'warm-minimal') {
    const albedo = new Texture(
      apiUrl('/render-assets/materials/wood-floor/wood_floor_diff_1k.jpg'),
      scene,
    )
    const normal = new Texture(
      apiUrl('/render-assets/materials/wood-floor/wood_floor_nor_gl_1k.jpg'),
      scene,
    )
    const roughness = new Texture(
      apiUrl('/render-assets/materials/wood-floor/wood_floor_rough_1k.jpg'),
      scene,
    )
    for (const texture of [albedo, normal, roughness]) {
      texture.uScale = floorWidth / 1.7
      texture.vScale = floorDepth / 1.7
      texture.anisotropicFilteringLevel = 16
      styledTextures.push(texture)
    }
    normal.level = 0.42
    roughness.gammaSpace = false
    floorMaterial.albedoTexture = albedo
    floorMaterial.bumpTexture = normal
    floorMaterial.metallicTexture = roughness
    floorMaterial.metallic = 0
    floorMaterial.roughness = 1
    floorMaterial.useRoughnessFromMetallicTextureAlpha = false
    floorMaterial.useRoughnessFromMetallicTextureGreen = true
    floorMaterial.useMetallnessFromMetallicTextureBlue = false
  }
  floor.material = floorMaterial
  floor.receiveShadows = true
  styledMeshes.push(floor)
  addRoomSurfaceDetails(layout, bounds.minimum.y, style)
  addArchitecturalDetails(layout, bounds.minimum.y, materials, style)
  addOpeningClearanceGuides(layout, bounds.minimum.y)

  const assets = new Map(catalog.assets.map((asset) => [asset.id, asset]))
  const livingRoomIds = new Set(
    layout.rooms.filter((room) => room.roomType === 'living').map((room) => room.id),
  )
  let models = 0
  let fallbacks = 0
  await Promise.all(
    layout.placements.map(async (placement) => {
      const asset = assets.get(placement.assetId)
      if (!asset) throw new Error(`自动布局引用了不存在的资产：${placement.assetId}`)
      const material = materials[placement.role] ?? materials[asset.fallback.materialRole] ?? architecture
      const loaded = await loadCatalogModel(
        placement,
        asset,
        bounds.minimum.y,
        material,
        warmMinimal && livingRoomIds.has(placement.roomId),
      )
      if (loaded) {
        models += 1
        return
      }
      createFallback(
        placement,
        bounds.minimum.y,
        material,
      )
      if (asset.kind === 'model') fallbacks += 1
    }),
  )

  scene.clearColor = warmMinimal
    ? new Color4(0.84, 0.81, 0.76, 1)
    : Color4.FromColor3(color3(style.environment.backgroundColor), 1)
  scene.environmentIntensity = warmMinimal ? 0.5 : 0.72
  skyLight.diffuse = color3(style.environment.ambientColor)
  skyLight.intensity = warmMinimal ? 0.42 : style.environment.ambientIntensity * 0.65
  skyLight.groundColor = warmMinimal
    ? Color3.FromHexString('#49392F')
    : new Color3(0.35, 0.4, 0.46)
  sun.diffuse = warmMinimal
    ? Color3.FromHexString('#FFD2A0')
    : color3(style.environment.sunColor)
  sun.intensity = warmMinimal ? 1.12 : style.environment.sunIntensity * 0.55
  sun.direction = Vector3.FromArray(style.environment.sunDirection)
  scene.imageProcessingConfiguration.exposure = warmMinimal ? 0.96 : 1.08
  scene.imageProcessingConfiguration.contrast = warmMinimal ? 1.22 : 1.12
  renderingPipeline.bloomThreshold = warmMinimal ? 0.8 : 0.92
  renderingPipeline.bloomWeight = warmMinimal ? 0.12 : 0.08
  perspectiveAlpha = (style.camera.alphaDegrees * Math.PI) / 180
  const betaDegrees =
    layout.furnishedRoomIds.length > 1 ? Math.min(style.camera.betaDegrees, 42) : style.camera.betaDegrees
  perspectiveBeta = (betaDegrees * Math.PI) / 180
  radiusMultiplier = style.camera.radiusMultiplier
  return { models, fallbacks }
}

async function getAssetCatalog(): Promise<AssetCatalog> {
  const response = await fetch(
    delivery.bundled ? bundleDataUrl(delivery, 'catalog.json') : apiUrl('/api/asset-catalog'),
    { cache: 'no-store' },
  )
  if (!response.ok) throw new Error(`资产目录服务请求失败（${response.status}）`)
  return parseAssetCatalog(await response.json())
}

async function getStyleSummaries(): Promise<StyleSummary[]> {
  const response = await fetch(
    delivery.bundled ? bundleDataUrl(delivery, 'styles/index.json') : apiUrl('/api/styles'),
    { cache: 'no-store' },
  )
  if (!response.ok) throw new Error(`风格目录服务请求失败（${response.status}）`)
  return parseStyleSummaries(await response.json())
}

async function getStylePack(styleId: string): Promise<StylePack> {
  const response = await fetch(
    delivery.bundled
      ? bundleDataUrl(delivery, `styles/${encodeURIComponent(styleId)}.json`)
      : apiUrl(`/api/styles/${encodeURIComponent(styleId)}`),
    { cache: 'no-store' },
  )
  if (response.status === 404) throw new Error('指定的装修风格不存在')
  if (!response.ok) throw new Error(`风格服务请求失败（${response.status}）`)
  return parseStylePack(await response.json())
}

async function getLayoutManifest(styleId: string): Promise<LayoutManifest> {
  const response = await fetch(
    delivery.bundled
      ? bundleDataUrl(delivery, `layouts/${encodeURIComponent(styleId)}.json`)
      : apiUrl(
          `/api/projects/${encodeURIComponent(projectId)}/layout?styleId=${encodeURIComponent(styleId)}`,
        ),
    { cache: 'no-store' },
  )
  if (response.status === 404) throw new Error('项目场景或装修风格不存在')
  if (!response.ok) throw new Error(`自动布局服务请求失败（${response.status}）`)
  return parseLayoutManifest(await response.json())
}

async function getLatestManifest(): Promise<ArtifactManifest> {
  const response = await fetch(
    delivery.bundled
      ? bundleDataUrl(delivery, 'manifest.json')
      : apiUrl(`/api/projects/${encodeURIComponent(projectId)}/artifacts/latest`),
    { cache: 'no-store' },
  )
  if (response.status === 404) throw new Error('这个项目还没有发布 3D 模型')
  if (!response.ok) throw new Error(`模型服务请求失败（${response.status}）`)
  return parseArtifactManifest(await response.json())
}

async function waitUntilReady(): Promise<ArtifactManifest> {
  if (delivery.bundled) {
    const manifest = await getLatestManifest()
    if (manifest.status !== 'ready') throw new Error('客户预览包缺少可用的优化模型')
    return manifest
  }
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const manifest = await getLatestManifest()
    if (manifest.status === 'failed') throw new Error(manifest.error ?? '模型优化失败')
    if (manifest.status === 'ready') return manifest
    setStatus('正在优化模型', `已发布 Revision ${manifest.sceneRevision}，请稍候…`, 12)
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
  }
  throw new Error('模型仍在处理中，请稍后重新加载')
}

async function loadModel(): Promise<void> {
  try {
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(projectId)) {
      throw new Error('链接缺少有效的 project 参数')
    }
    if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(currentStyleId)) {
      throw new Error('链接包含无效的 style 参数')
    }
    setStatus('正在读取模型', '检查最新发布版本…', 4)
    const [manifest, style, layout, catalog, summaries] = await Promise.all([
      waitUntilReady(),
      getStylePack(currentStyleId),
      getLayoutManifest(currentStyleId),
      getAssetCatalog(),
      getStyleSummaries(),
    ])
    if (!manifest.optimized) throw new Error('模型产物尚未准备完成')
    if (
      layout.projectId !== manifest.projectId ||
      layout.sceneRevision !== manifest.sceneRevision ||
      layout.style.id !== style.id ||
      layout.style.version !== style.version
      || layout.assetCatalog.id !== catalog.id
      || layout.assetCatalog.version !== catalog.version
    ) {
      throw new Error('模型、风格与自动布局版本不一致')
    }
    await Promise.all([
      import('@babylonjs/loaders/glTF/2.0/glTFLoader'),
      import('@babylonjs/loaders/glTF/2.0/Extensions/EXT_meshopt_compression'),
      import('@babylonjs/loaders/glTF/2.0/Extensions/KHR_mesh_quantization'),
      import('@babylonjs/loaders/glTF/2.0/Extensions/KHR_texture_transform'),
    ])
    clearStyle()
    container?.dispose()
    container = await LoadAssetContainerAsync(apiUrl(manifest.optimized.url), scene, {
      onProgress: (event) => {
        const percent = event.lengthComputable ? (event.loaded / event.total) * 100 : 36
        setStatus('正在加载空间', `${formatBytes(event.loaded)} 已接收`, percent)
      },
    })
    container.addAllToScene()
    const assetStats = await applyStyle(style, layout, catalog, container)
    currentManifest = manifest
    currentLayout = layout
    currentCatalog = catalog
    styleSummaries = summaries
    frameModel(layout)
    camera.alpha = perspectiveAlpha
    camera.beta = perspectiveBeta
    setReady(manifest, style, layout, assetStats)
    applyView(preferredDeliveryView(layout))
  } catch (error) {
    setError(error)
  }
}

function applyView(viewId: string): void {
  if (!currentLayout) return
  if (viewId === 'top') {
    setArchitectureOpacity(1)
    setDoorDetailsVisible(true)
    setFurnitureRoomVisibility(null)
    camera.alpha = -Math.PI / 2
    camera.beta = 0.04
    camera.setTarget(defaultTarget)
    camera.radius = defaultRadius
  } else if (viewId === 'whole') {
    setArchitectureOpacity(1)
    setDoorDetailsVisible(true)
    setFurnitureRoomVisibility(null)
    camera.alpha = perspectiveAlpha
    camera.beta = perspectiveBeta
    camera.setTarget(defaultTarget)
    camera.radius = defaultRadius
  } else {
    const closeupRoomId = viewId.startsWith('closeup:') ? viewId.slice('closeup:'.length) : null
    if (closeupRoomId) {
      const room = currentLayout.rooms.find((candidate) => candidate.id === closeupRoomId)
      const preset = livingCloseupCameraPreset(
        currentLayout.placements.filter((placement) => placement.roomId === closeupRoomId),
      )
      if (!room || room.roomType !== 'living' || !preset) return
      setArchitectureOpacity(delivery.presentationMode ? 0.04 : 0.2)
      setDoorDetailsVisible(false)
      setFurnitureRoomVisibility(closeupRoomId, livingCloseupHiddenItemIds)
      camera.alpha = preset.alpha
      camera.beta = preset.beta
      camera.setTarget(Vector3.FromArray(preset.target))
      const aspect = engine.getRenderWidth() / Math.max(1, engine.getRenderHeight())
      camera.radius = preset.radius * Math.max(1, 0.72 / aspect)
      setActiveView(viewId)
      return
    }
    const option = roomViewOptions.find((candidate) => candidate.id === viewId)
    const room = option && currentLayout.rooms.find((candidate) => candidate.id === option.roomId)
    if (!room) return
    setArchitectureOpacity(option.roomType === 'bathroom' ? 0.12 : 0.2)
    setDoorDetailsVisible(false)
    setFurnitureRoomVisibility(room.id)
    const preset = roomDetailCameraPreset(
      room,
      currentLayout.placements.filter((placement) => placement.roomId === room.id),
    )
    camera.alpha = preset.alpha
    camera.beta = preset.beta
    camera.setTarget(Vector3.FromArray(preset.target))
    const aspect = engine.getRenderWidth() / Math.max(1, engine.getRenderHeight())
    camera.radius = responsiveRoomCameraRadius(preset.radius, aspect)
  }
  setActiveView(viewId)
}

async function switchStyle(styleId: string): Promise<void> {
  if (
    switchingStyle ||
    styleId === currentStyleId ||
    !currentManifest ||
    !currentCatalog ||
    !container
  ) {
    return
  }
  setStyleSwitching(true, '正在切换…')
  try {
    const [style, layout] = await Promise.all([
      getStylePack(styleId),
      getLayoutManifest(styleId),
    ])
    if (
      layout.projectId !== currentManifest.projectId ||
      layout.sceneRevision !== currentManifest.sceneRevision ||
      layout.style.id !== style.id ||
      layout.style.version !== style.version ||
      layout.assetCatalog.id !== currentCatalog.id ||
      layout.assetCatalog.version !== currentCatalog.version
    ) {
      throw new Error('新风格与当前户型版本不一致')
    }
    const assetStats = await applyStyle(style, layout, currentCatalog, container)
    currentStyleId = style.id
    currentLayout = layout
    frameModel(layout)
    camera.alpha = perspectiveAlpha
    camera.beta = perspectiveBeta
    window.history.replaceState(null, '', searchWithStyle(window.location.search, currentStyleId))
    setReady(currentManifest, style, layout, assetStats)
    applyView(preferredDeliveryView(layout))
    setStyleSwitching(false, '已切换')
    window.setTimeout(() => {
      if (!switchingStyle) styleSwitchStatus.textContent = ''
    }, 1400)
  } catch (error) {
    setStyleSwitching(false)
    setError(error)
  }
}

element<HTMLButtonElement>('#retry').addEventListener('click', () => {
  if (projectId) void loadModel()
  else showBaselineIntake()
})
baselineForm.addEventListener('submit', (event) => {
  event.preventDefault()
  void createBaseline().catch(setError)
})
element<HTMLButtonElement>('#fullscreen').addEventListener('click', async () => {
  if (document.fullscreenElement) await document.exitFullscreen()
  else await shell.requestFullscreen()
})
clearancesButton.addEventListener('click', () => {
  setOpeningClearancesVisible(!openingClearancesVisible)
})

for (const button of root.querySelectorAll<HTMLButtonElement>('.view-controls > [data-view]')) {
  button.addEventListener('click', () => applyView(button.dataset.view ?? 'whole'))
}

window.addEventListener('resize', () => {
  const followsDefault = Math.abs(camera.radius - defaultRadius) < 0.05
  engine.resize()
  defaultRadius = radiusForViewport()
  if (followsDefault) camera.radius = defaultRadius
})
engine.runRenderLoop(() => scene.render())
if (projectId) void loadModel()
else showBaselineIntake()
