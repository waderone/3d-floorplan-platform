import { ArcRotateCamera } from '@babylonjs/core/Cameras/arcRotateCamera'
import { Engine } from '@babylonjs/core/Engines/engine'
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight'
import { DirectionalLight } from '@babylonjs/core/Lights/directionalLight'
import { LoadAssetContainerAsync } from '@babylonjs/core/Loading/sceneLoader'
import { Color3, Color4 } from '@babylonjs/core/Maths/math.color'
import { Vector3 } from '@babylonjs/core/Maths/math.vector'
import { MeshoptCompression } from '@babylonjs/core/Meshes/Compression/meshoptCompression'
import { Scene } from '@babylonjs/core/scene'
import type { AssetContainer } from '@babylonjs/core/assetContainer'
import meshoptDecoderSource from '../node_modules/meshoptimizer/meshopt_decoder.cjs?raw'
import { parseArtifactManifest, type ArtifactManifest } from './manifest'
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
        <span id="revision">Revision —</span><span id="size">—</span>
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

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const projectId = new URLSearchParams(window.location.search).get('project') ?? ''
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
let defaultTarget = Vector3.Zero()
let baseRadius = 12
let defaultRadius = 12

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

function setReady(manifest: ArtifactManifest): void {
  shell.dataset.state = 'ready'
  statusPanel.hidden = true
  errorPanel.hidden = true
  projectName.textContent = manifest.projectId
  revision.textContent = `Revision ${manifest.sceneRevision}`
  if (!manifest.optimized) return
  size.textContent = formatBytes(manifest.optimized.bytes)
  const modelStats = manifest.optimized.statistics
  stats.innerHTML = modelStats
    ? `<span><strong>${modelStats.meshes}</strong> 网格</span><span><strong>${modelStats.materials}</strong> 材质</span>`
    : ''
  if (manifest.mobileBudgetExceeded) size.textContent += ' · 大模型'
}

function frameModel(): void {
  const visibleMeshes = scene.meshes.filter((mesh) => mesh.isVisible && mesh.getTotalVertices() > 0)
  if (visibleMeshes.length === 0) throw new Error('模型中没有可显示的几何体')
  const bounds = scene.getWorldExtends((mesh) => visibleMeshes.includes(mesh))
  const extent = bounds.max.subtract(bounds.min)
  defaultTarget = bounds.min.add(extent.scale(0.5))
  baseRadius = Math.max(2, extent.length() * 0.85)
  defaultRadius = radiusForViewport()
  camera.setTarget(defaultTarget)
  camera.radius = defaultRadius
  camera.lowerRadiusLimit = Math.max(0.5, defaultRadius * 0.12)
  camera.upperRadiusLimit = Math.max(30, defaultRadius * 5)
}

function radiusForViewport(): number {
  const aspect = engine.getRenderWidth() / Math.max(1, engine.getRenderHeight())
  return baseRadius * Math.max(1, 0.8 / aspect)
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
    setStatus('正在读取模型', '检查最新发布版本…', 4)
    const manifest = await waitUntilReady()
    if (!manifest.optimized) throw new Error('模型产物尚未准备完成')
    await Promise.all([
      import('@babylonjs/loaders/glTF/2.0/glTFLoader'),
      import('@babylonjs/loaders/glTF/2.0/Extensions/EXT_meshopt_compression'),
      import('@babylonjs/loaders/glTF/2.0/Extensions/KHR_mesh_quantization'),
      import('@babylonjs/loaders/glTF/2.0/Extensions/KHR_texture_transform'),
    ])
    container?.dispose()
    container = await LoadAssetContainerAsync(apiUrl(manifest.optimized.url), scene, {
      onProgress: (event) => {
        const percent = event.lengthComputable ? (event.loaded / event.total) * 100 : 36
        setStatus('正在加载空间', `${formatBytes(event.loaded)} 已接收`, percent)
      },
    })
    container.addAllToScene()
    frameModel()
    setReady(manifest)
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
      camera.alpha = -Math.PI / 4
      camera.beta = Math.PI / 3
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
