import { ArcRotateCamera } from '@babylonjs/core/Cameras/arcRotateCamera'
import { Engine } from '@babylonjs/core/Engines/engine'
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight'
import { DirectionalLight } from '@babylonjs/core/Lights/directionalLight'
import { ShadowGenerator } from '@babylonjs/core/Lights/Shadows/shadowGenerator'
import { LoadAssetContainerAsync } from '@babylonjs/core/Loading/sceneLoader'
import { ImageProcessingConfiguration } from '@babylonjs/core/Materials/imageProcessingConfiguration'
import { Color3, Color4 } from '@babylonjs/core/Maths/math.color'
import { Vector3 } from '@babylonjs/core/Maths/math.vector'
import { MeshoptCompression } from '@babylonjs/core/Meshes/Compression/meshoptCompression'
import '@babylonjs/core/Meshes/instancedMesh'
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder'
import { PBRMaterial } from '@babylonjs/core/Materials/PBR/pbrMaterial'
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
import { parseLayoutManifest, type LayoutManifest } from './layout'
import { parseArtifactManifest, type ArtifactManifest } from './manifest'
import {
  buildRoomViewOptions,
  parseStyleSummaries,
  roomCameraPreset,
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
        <div><strong>空间预览</strong><span>3D FLOORPLAN</span></div>
      </div>
      <div class="tool-actions">
        <button class="icon-button" id="clearances" type="button" aria-label="显示门窗动线净空" aria-pressed="false">⌗</button>
        <button class="icon-button" id="fullscreen" type="button" aria-label="全屏浏览">⛶</button>
      </div>
    </header>
    <aside class="model-card" aria-label="模型信息">
      <span class="eyebrow">INTERACTIVE HOME</span>
      <h1 id="project-name">全屋设计方案</h1>
      <div class="model-meta">
        <span id="style-name">风格加载中</span><span id="layout-status">空间加载中</span><span id="quality-status">实时画质</span>
      </div>
      <div class="model-stats" id="stats"></div>
    </aside>
    <aside class="style-panel" aria-label="装修风格">
      <span class="eyebrow">DESIGN STYLES</span>
      <div class="style-heading"><strong>选择装修风格</strong><span id="style-switch-status" role="status" aria-live="polite"></span></div>
      <div class="style-options" id="style-options"></div>
      <p id="style-description">正在读取可用方案…</p>
    </aside>
    <section class="intake-panel" id="intake-panel" aria-labelledby="intake-title" hidden>
      <span class="eyebrow">FLOORPLAN TO 3D</span>
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

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const projectId = new URLSearchParams(window.location.search).get('project') ?? ''
let currentStyleId = new URLSearchParams(window.location.search).get('style') ?? 'warm-minimal'
baselineProject.value = `home-${Date.now().toString(36)}`
const compactDevice = window.matchMedia('(max-width: 700px), (pointer: coarse)').matches
const engine = new Engine(canvas, true, { adaptToDeviceRatio: true, stencil: true })
engine.setHardwareScalingLevel(Math.max(1, window.devicePixelRatio / (compactDevice ? 1.25 : 1.6)))
const meshoptDecoderUrl = URL.createObjectURL(
  new Blob([meshoptDecoderSource], { type: 'text/javascript' }),
)
MeshoptCompression.Configuration = { decoder: { url: meshoptDecoderUrl } }
const scene = new Scene(engine)
scene.useRightHandedSystem = true
scene.clearColor = new Color4(0.91, 0.9, 0.86, 1)

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
skyLight.intensity = 1.25
skyLight.diffuse = new Color3(1, 0.96, 0.88)
skyLight.groundColor = new Color3(0.35, 0.4, 0.46)
const sun = new DirectionalLight('sun', new Vector3(-0.45, -1, 0.35), scene)
sun.intensity = 1.8
sun.diffuse = new Color3(1, 0.9, 0.72)
const shadows = new ShadowGenerator(compactDevice ? 1024 : 2048, sun)
shadows.useBlurExponentialShadowMap = true
shadows.blurKernel = compactDevice ? 16 : 28
scene.imageProcessingConfiguration.toneMappingEnabled = true
scene.imageProcessingConfiguration.toneMappingType = ImageProcessingConfiguration.TONEMAPPING_ACES
scene.imageProcessingConfiguration.exposure = 1.08
scene.imageProcessingConfiguration.contrast = 1.12
scene.imageProcessingConfiguration.vignetteEnabled = true
scene.imageProcessingConfiguration.vignetteWeight = 1.15
const renderingPipeline = new DefaultRenderingPipeline('showroom-quality', true, scene, [camera])
renderingPipeline.fxaaEnabled = true
renderingPipeline.samples = compactDevice ? 1 : 4
renderingPipeline.bloomEnabled = true
renderingPipeline.bloomThreshold = 0.92
renderingPipeline.bloomWeight = 0.08

let container: AssetContainer | null = null
let styledAssetContainers: AssetContainer[] = []
let styledMeshes: AbstractMesh[] = []
let styledMaterials: PBRMaterial[] = []
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

function apiUrl(path: string): string {
  return `${apiBase}${path}`
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
  }
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
  styledMeshes = []
  styledMaterials = []
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
): Promise<boolean> {
  if (asset.kind !== 'model' || !asset.delivery) return false
  try {
    const assetContainer = await LoadAssetContainerAsync(apiUrl(asset.delivery.url), scene)
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
      if (mesh.getTotalVertices() === 0) continue
      if (asset.materialMode === 'replace') mesh.material = material
      mesh.receiveShadows = true
      shadows.addShadowCaster(mesh, true)
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
  const floorWidth = Math.max(6, extent.x + style.layout.floorPadding * 2)
  const floorDepth = Math.max(6, extent.z + style.layout.floorPadding * 2)
  const floorHeight = 0.12
  const floor = MeshBuilder.CreateBox(
    'style-floor',
    { width: floorWidth, height: floorHeight, depth: floorDepth },
    scene,
  )
  floor.position.set(center.x, bounds.minimum.y - floorHeight / 2, center.z)
  floor.material = materials.floor ?? architecture
  floor.receiveShadows = true
  styledMeshes.push(floor)
  addOpeningClearanceGuides(layout, bounds.minimum.y)

  const assets = new Map(catalog.assets.map((asset) => [asset.id, asset]))
  let models = 0
  let fallbacks = 0
  await Promise.all(
    layout.placements.map(async (placement) => {
      const asset = assets.get(placement.assetId)
      if (!asset) throw new Error(`自动布局引用了不存在的资产：${placement.assetId}`)
      const material = materials[placement.role] ?? materials[asset.fallback.materialRole] ?? architecture
      const loaded = await loadCatalogModel(placement, asset, bounds.minimum.y, material)
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

  scene.clearColor = Color4.FromColor3(color3(style.environment.backgroundColor), 1)
  skyLight.diffuse = color3(style.environment.ambientColor)
  skyLight.intensity = style.environment.ambientIntensity * 0.65
  sun.diffuse = color3(style.environment.sunColor)
  sun.intensity = style.environment.sunIntensity * 0.55
  sun.direction = Vector3.FromArray(style.environment.sunDirection)
  perspectiveAlpha = (style.camera.alphaDegrees * Math.PI) / 180
  const betaDegrees =
    layout.furnishedRoomIds.length > 1 ? Math.min(style.camera.betaDegrees, 42) : style.camera.betaDegrees
  perspectiveBeta = (betaDegrees * Math.PI) / 180
  radiusMultiplier = style.camera.radiusMultiplier
  return { models, fallbacks }
}

async function getAssetCatalog(): Promise<AssetCatalog> {
  const response = await fetch(apiUrl('/api/asset-catalog'), { cache: 'no-store' })
  if (!response.ok) throw new Error(`资产目录服务请求失败（${response.status}）`)
  return parseAssetCatalog(await response.json())
}

async function getStyleSummaries(): Promise<StyleSummary[]> {
  const response = await fetch(apiUrl('/api/styles'), { cache: 'no-store' })
  if (!response.ok) throw new Error(`风格目录服务请求失败（${response.status}）`)
  return parseStyleSummaries(await response.json())
}

async function getStylePack(styleId: string): Promise<StylePack> {
  const response = await fetch(apiUrl(`/api/styles/${encodeURIComponent(styleId)}`), {
    cache: 'no-store',
  })
  if (response.status === 404) throw new Error('指定的装修风格不存在')
  if (!response.ok) throw new Error(`风格服务请求失败（${response.status}）`)
  return parseStylePack(await response.json())
}

async function getLayoutManifest(styleId: string): Promise<LayoutManifest> {
  const response = await fetch(
    apiUrl(
      `/api/projects/${encodeURIComponent(projectId)}/layout?styleId=${encodeURIComponent(styleId)}`,
    ),
    { cache: 'no-store' },
  )
  if (response.status === 404) throw new Error('项目场景或装修风格不存在')
  if (!response.ok) throw new Error(`自动布局服务请求失败（${response.status}）`)
  return parseLayoutManifest(await response.json())
}

async function getLatestManifest(): Promise<ArtifactManifest> {
  const response = await fetch(apiUrl(`/api/projects/${encodeURIComponent(projectId)}/artifacts/latest`), {
    cache: 'no-store',
  })
  if (response.status === 404) throw new Error('这个项目还没有发布 3D 模型')
  if (!response.ok) throw new Error(`模型服务请求失败（${response.status}）`)
  return parseArtifactManifest(await response.json())
}

async function waitUntilReady(): Promise<ArtifactManifest> {
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
    setActiveView('whole')
    setReady(manifest, style, layout, assetStats)
  } catch (error) {
    setError(error)
  }
}

function applyView(viewId: string): void {
  if (!currentLayout) return
  if (viewId === 'top') {
    camera.alpha = -Math.PI / 2
    camera.beta = 0.04
    camera.setTarget(defaultTarget)
    camera.radius = defaultRadius
  } else if (viewId === 'whole') {
    camera.alpha = perspectiveAlpha
    camera.beta = perspectiveBeta
    camera.setTarget(defaultTarget)
    camera.radius = defaultRadius
  } else {
    const option = roomViewOptions.find((candidate) => candidate.id === viewId)
    const room = option && currentLayout.rooms.find((candidate) => candidate.id === option.roomId)
    if (!room) return
    const preset = roomCameraPreset(room)
    camera.alpha = perspectiveAlpha
    camera.beta = Math.max(perspectiveBeta, Math.PI * 0.38)
    camera.setTarget(Vector3.FromArray(preset.target))
    const aspect = engine.getRenderWidth() / Math.max(1, engine.getRenderHeight())
    camera.radius = preset.radius * Math.max(1, 0.72 / aspect)
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
    setActiveView('whole')
    window.history.replaceState(null, '', searchWithStyle(window.location.search, currentStyleId))
    setReady(currentManifest, style, layout, assetStats)
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
