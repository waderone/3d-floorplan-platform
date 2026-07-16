import { ArcRotateCamera } from '@babylonjs/core/Cameras/arcRotateCamera'
import { Engine } from '@babylonjs/core/Engines/engine'
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight'
import { DirectionalLight } from '@babylonjs/core/Lights/directionalLight'
import { LoadAssetContainerAsync } from '@babylonjs/core/Loading/sceneLoader'
import { Color3, Color4 } from '@babylonjs/core/Maths/math.color'
import { Vector3 } from '@babylonjs/core/Maths/math.vector'
import { MeshoptCompression } from '@babylonjs/core/Meshes/Compression/meshoptCompression'
import { MeshBuilder } from '@babylonjs/core/Meshes/meshBuilder'
import { PBRMaterial } from '@babylonjs/core/Materials/PBR/pbrMaterial'
import { Scene } from '@babylonjs/core/scene'
import type { AssetContainer } from '@babylonjs/core/assetContainer'
import type { AbstractMesh } from '@babylonjs/core/Meshes/abstractMesh'
import meshoptDecoderSource from '../node_modules/meshoptimizer/meshopt_decoder.cjs?raw'
import { parseAssetCatalog, type AssetCatalog, type CatalogAsset } from './asset-catalog'
import { parseLayoutManifest, type LayoutManifest } from './layout'
import { parseArtifactManifest, type ArtifactManifest } from './manifest'
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
      <button class="icon-button" id="fullscreen" type="button" aria-label="全屏浏览">⛶</button>
    </header>
    <aside class="model-card" aria-label="模型信息">
      <span class="eyebrow">LIVE MODEL</span>
      <h1 id="project-name">3D 户型</h1>
      <div class="model-meta">
        <span id="revision">Revision —</span><span id="size">—</span><span id="style-name">Style —</span><span id="layout-status">布局 —</span>
      </div>
      <div class="model-stats" id="stats"></div>
    </aside>
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
      <button data-view="perspective" type="button" class="active">3D 视角</button>
      <button data-view="top" type="button">俯视</button>
      <button data-view="reset" type="button">复位</button>
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
const revision = element<HTMLElement>('#revision')
const size = element<HTMLElement>('#size')
const stats = element<HTMLElement>('#stats')
const styleName = element<HTMLElement>('#style-name')
const layoutStatus = element<HTMLElement>('#layout-status')

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const projectId = new URLSearchParams(window.location.search).get('project') ?? ''
const styleId = new URLSearchParams(window.location.search).get('style') ?? 'warm-minimal'
const engine = new Engine(canvas, true, { adaptToDeviceRatio: true, stencil: true })
const meshoptDecoderUrl = URL.createObjectURL(
  new Blob([meshoptDecoderSource], { type: 'text/javascript' }),
)
MeshoptCompression.Configuration = { decoder: { url: meshoptDecoderUrl } }
const scene = new Scene(engine)
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

function setReady(
  manifest: ArtifactManifest,
  style: StylePack,
  layout: LayoutManifest,
  assetStats: { models: number; fallbacks: number },
): void {
  shell.dataset.state = 'ready'
  statusPanel.hidden = true
  errorPanel.hidden = true
  projectName.textContent = manifest.projectId
  revision.textContent = `Revision ${manifest.sceneRevision}`
  styleName.textContent = `${style.name} v${style.version}`
  layoutStatus.textContent = layout.furnishedRoomIds.length
    ? layout.unfurnishedRoomIds.length
      ? `已布置 ${layout.furnishedRoomIds.length} · 待处理 ${layout.unfurnishedRoomIds.length}`
      : `已布置 · ${layout.furnishedRoomIds.length} 个房间`
    : layout.fallbackReason === 'no-room-fits'
      ? '房间尺寸不足'
      : layout.fallbackReason === 'no-supported-room'
        ? '暂无支持的房间类型'
        : '待补房间边界'
  if (!manifest.optimized) return
  size.textContent = formatBytes(manifest.optimized.bytes)
  const modelStats = manifest.optimized.statistics
  stats.innerHTML = modelStats
    ? `<span><strong>${modelStats.meshes}</strong> 网格</span><span><strong>${modelStats.materials}</strong> 材质</span><span><strong>${assetStats.models}</strong> 真实家具</span><span><strong>${assetStats.fallbacks}</strong> 回退</span>`
    : ''
  if (manifest.mobileBudgetExceeded) size.textContent += ' · 大模型'
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
  for (const assetContainer of styledAssetContainers) assetContainer.dispose()
  for (const mesh of styledMeshes) mesh.dispose(false, false)
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
  styledMeshes.push(mesh)
}

async function loadCatalogModel(
  placement: LayoutManifest['placements'][number],
  asset: CatalogAsset,
  floorTop: number,
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
      styledMaterials.push(material)
      return [role, material]
    }),
  )
  const architecture = materials.architecture
  if (!architecture) throw new Error('风格包缺少建筑材质')
  for (const mesh of model.meshes) {
    if (mesh.getTotalVertices() > 0) mesh.material = architecture
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
  styledMeshes.push(floor)

  const assets = new Map(catalog.assets.map((asset) => [asset.id, asset]))
  let models = 0
  let fallbacks = 0
  await Promise.all(
    layout.placements.map(async (placement) => {
      const asset = assets.get(placement.assetId)
      if (!asset) throw new Error(`自动布局引用了不存在的资产：${placement.assetId}`)
      const loaded = await loadCatalogModel(placement, asset, bounds.minimum.y)
      if (loaded) {
        models += 1
        return
      }
      createFallback(
        placement,
        bounds.minimum.y,
        materials[placement.role] ?? materials[asset.fallback.materialRole] ?? architecture,
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

async function getStylePack(): Promise<StylePack> {
  const response = await fetch(apiUrl(`/api/styles/${encodeURIComponent(styleId)}`), {
    cache: 'no-store',
  })
  if (response.status === 404) throw new Error('指定的装修风格不存在')
  if (!response.ok) throw new Error(`风格服务请求失败（${response.status}）`)
  return parseStylePack(await response.json())
}

async function getLayoutManifest(): Promise<LayoutManifest> {
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
    if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(styleId)) {
      throw new Error('链接包含无效的 style 参数')
    }
    setStatus('正在读取模型', '检查最新发布版本…', 4)
    const [manifest, style, layout, catalog] = await Promise.all([
      waitUntilReady(),
      getStylePack(),
      getLayoutManifest(),
      getAssetCatalog(),
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
    frameModel(layout)
    camera.alpha = perspectiveAlpha
    camera.beta = perspectiveBeta
    setReady(manifest, style, layout, assetStats)
  } catch (error) {
    setError(error)
  }
}

element<HTMLButtonElement>('#retry').addEventListener('click', () => void loadModel())
element<HTMLButtonElement>('#fullscreen').addEventListener('click', async () => {
  if (document.fullscreenElement) await document.exitFullscreen()
  else await shell.requestFullscreen()
})

for (const button of root.querySelectorAll<HTMLButtonElement>('[data-view]')) {
  button.addEventListener('click', () => {
    const view = button.dataset.view
    if (view === 'top') {
      camera.alpha = -Math.PI / 2
      camera.beta = 0.04
    } else {
      camera.alpha = perspectiveAlpha
      camera.beta = perspectiveBeta
    }
    camera.setTarget(defaultTarget)
    camera.radius = defaultRadius
    for (const peer of root.querySelectorAll('[data-view]')) peer.classList.remove('active')
    if (view !== 'reset') button.classList.add('active')
    else element('[data-view="perspective"]').classList.add('active')
  })
}

window.addEventListener('resize', () => {
  const followsDefault = Math.abs(camera.radius - defaultRadius) < 0.05
  engine.resize()
  defaultRadius = radiusForViewport()
  if (followsDefault) camera.radius = defaultRadius
})
engine.runRenderLoop(() => scene.render())
void loadModel()
