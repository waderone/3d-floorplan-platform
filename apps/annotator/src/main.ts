import {
  advanceCorrectionTimer,
  ANNOTATION_IDLE_TIMEOUT_MS,
  clampMeters,
  cloneAnnotations,
  copySuggestions,
  correctionDurationSeconds,
  createAnnotationReview,
  createCorrectionTimer,
  createSubmission,
  emptyAnnotations,
  metersPerPixel,
  metersToPixel,
  nextId,
  parseSubmission,
  parseWorkpack,
  pixelToMeters,
  recordCorrectionActivity,
  setCorrectionTimerForeground,
  sha256Hex,
  type ActiveCorrectionTimer,
  type AnnotationWorkpack,
  type AnnotationSubmission,
  type Annotations,
  type Point,
} from './model.ts'
import { ROOM_TYPE_OPTIONS, rightsStatusLabel, roomTypeLabel } from './labels.ts'
import './style.css'

type Tool = 'select' | 'wall' | 'room' | 'door' | 'window'
type Selection = { kind: 'wall' | 'room' | 'opening'; id: string } | null
type DragTarget =
  | { kind: 'wall'; id: string; part: 'start' | 'end' }
  | { kind: 'room'; id: string; vertex: number }
  | { kind: 'opening'; id: string }

const SVG_NAMESPACE = 'http://www.w3.org/2000/svg'
const DEMO_WORKPACK_ID = 'd'.repeat(64)
const rootElement = document.querySelector<HTMLElement>('#app')
if (!rootElement) throw new Error('找不到标注台根节点')
const root: HTMLElement = rootElement

root.innerHTML = `
  <div class="annotator-shell" data-ready="false">
    <header class="topbar">
      <div class="brand-block">
        <span class="brand-symbol" aria-hidden="true">⌗</span>
        <div><span>数据集工具</span><strong>户型真值标注台</strong></div>
      </div>
      <div class="topbar-status">
        <span class="status-dot"></span>
        <span id="top-status">等待导入工作包</span>
      </div>
      <div class="file-actions">
        <button id="demo-button" class="ghost-button" type="button">载入演示</button>
        <label class="file-button">工作包<input id="workpack-file" type="file" accept="application/json,.json" /></label>
        <label class="file-button">原图<input id="image-file" type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" /></label>
        <label class="file-button secondary">载入标注<input id="draft-file" type="file" accept="application/json,.json" /></label>
      </div>
    </header>

    <div class="workspace">
      <aside class="tool-panel" aria-label="标注工具">
        <span class="panel-label">标注工具</span>
        <div class="tool-grid">
          <button class="tool active" data-tool="select" type="button"><span>↖</span>选择</button>
          <button class="tool" data-tool="wall" type="button"><span>╱</span>墙体</button>
          <button class="tool" data-tool="room" type="button"><span>⬡</span>房间</button>
          <button class="tool" data-tool="door" type="button"><span>◜</span>门</button>
          <button class="tool" data-tool="window" type="button"><span>═</span>窗</button>
        </div>
        <button id="finish-room" class="action-button" type="button" disabled>完成房间</button>
        <button id="cancel-drawing" class="text-button" type="button" disabled>取消当前绘制</button>

        <div class="panel-section compact">
          <label>默认墙厚 <span>米</span><input id="wall-thickness" type="number" min="0.05" max="2" step="0.01" value="0.20" /></label>
          <label>默认门窗宽 <span>米</span><input id="opening-width" type="number" min="0.1" max="20" step="0.05" value="0.90" /></label>
        </div>

        <div class="panel-section">
          <span class="panel-label">参考层</span>
          <label class="switch-row"><input id="show-suggestions" type="checkbox" checked /><span></span>显示机器建议</label>
          <button class="reference-button" data-import="walls" type="button">复制建议墙为待核真值</button>
          <button class="reference-button" data-import="rooms" type="button">复制建议房间为待核真值</button>
          <p class="reference-warning">机器建议仅作参考。复制后仍需逐项检查和修正。</p>
        </div>

        <div class="history-actions">
          <button id="undo" type="button" disabled>↶ 撤销</button>
          <button id="redo" type="button" disabled>↷ 重做</button>
        </div>
      </aside>

      <section class="canvas-stage" aria-label="户型标注画布">
        <div class="empty-state" id="empty-state">
          <span class="empty-mark">⌗</span>
          <h1>导入标注工作包</h1>
          <p>先选择工作包文件，再选择对应原图。文件摘要与像素尺寸验证通过后才能开始。</p>
          <button id="empty-demo-button" type="button">使用内置演示熟悉操作</button>
        </div>
        <div class="canvas-frame" id="canvas-frame" hidden>
          <svg id="annotation-canvas" aria-label="户型图及真值几何">
            <image id="plan-image" />
            <g id="suggestion-layer"></g>
            <g id="truth-layer"></g>
            <g id="draft-layer"></g>
            <g id="handle-layer"></g>
          </svg>
          <div class="canvas-legend">
            <span><i class="legend-suggestion"></i>机器建议</span>
            <span><i class="legend-wall"></i>真值墙体</span>
            <span><i class="legend-room"></i>真值房间</span>
            <span><i class="legend-opening"></i>门窗</span>
          </div>
          <div class="coordinate-readout" id="coordinate-readout">横向 — · 纵向 —</div>
        </div>
        <div class="message-bar" id="message-bar" data-kind="info" role="status" aria-live="polite">
          <span></span><p>工作包、原图和导出草稿只在当前浏览器本地处理。</p>
        </div>
      </section>

      <aside class="inspector-panel">
        <div class="dataset-card">
          <span class="panel-label">工作包</span>
          <strong id="candidate-id">尚未载入</strong>
          <div class="dataset-meta">
            <span id="workpack-id">编号 —</span>
            <span id="rights-status" data-status="pending">权利 —</span>
          </div>
          <div class="counts">
            <div><strong id="wall-count">0</strong><span>墙体</span></div>
            <div><strong id="room-count">0</strong><span>房间</span></div>
            <div><strong id="opening-count">0</strong><span>门窗</span></div>
          </div>
        </div>

        <section class="inspector-section">
          <div class="section-heading"><span class="panel-label">属性编辑</span><button id="delete-selection" type="button" hidden>删除</button></div>
          <div id="selection-inspector" class="selection-empty">选择真值几何后可编辑属性；拖动圆形控制点可修改端点、中心或房间顶点。</div>
        </section>

        <section class="inspector-section export-section">
          <span class="panel-label">标注交接</span>
          <div class="timing-card" id="timing-card" data-state="waiting">
            <div><span>有效编辑时间</span><strong id="timing-value">00:00</strong></div>
            <small id="timing-state">等待首次真值编辑</small>
          </div>
          <label>标注人<input id="annotated-by" type="text" maxlength="100" placeholder="姓名或团队账号" /></label>
          <label>备注<textarea id="annotation-notes" maxlength="2000" rows="3" placeholder="记录尺度疑点、未确认门窗等"></textarea></label>
          <div class="export-buttons">
            <button id="export-draft" class="ghost-button" type="button">导出草稿</button>
            <button id="export-review" class="primary-button" type="button">提交待复核</button>
          </div>
          <p class="handoff-note">“待复核”只表示首轮真值完成，不代表权利批准或正式进入评测集。</p>
        </section>

        <section class="inspector-section review-section">
          <span class="panel-label">第二人复核</span>
          <p id="review-target" class="review-target">载入待复核标注后可进行第二人复核。</p>
          <label>复核人<input id="reviewed-by" type="text" maxlength="100" placeholder="必须与标注人不同" /></label>
          <label>复核说明<textarea id="review-comment" maxlength="1000" rows="3" placeholder="退回时必须说明需要修改的内容"></textarea></label>
          <div class="review-buttons">
            <button id="request-changes" class="ghost-button" type="button" disabled>退回修改</button>
            <button id="approve-review" class="primary-button" type="button" disabled>批准复核</button>
          </div>
          <p class="handoff-note">复核记录绑定原标注文件摘要；内容变化后必须重新复核。</p>
        </section>
      </aside>
    </div>
  </div>
`

function element<T extends Element>(selector: string): T {
  const found = root.querySelector<T>(selector)
  if (!found) throw new Error(`找不到标注台元素：${selector}`)
  return found
}

const shell = element<HTMLElement>('.annotator-shell')
const svg = element<SVGSVGElement>('#annotation-canvas')
const planImage = element<SVGImageElement>('#plan-image')
const suggestionLayer = element<SVGGElement>('#suggestion-layer')
const truthLayer = element<SVGGElement>('#truth-layer')
const draftLayer = element<SVGGElement>('#draft-layer')
const handleLayer = element<SVGGElement>('#handle-layer')
const canvasFrame = element<HTMLElement>('#canvas-frame')
const emptyState = element<HTMLElement>('#empty-state')
const messageBar = element<HTMLElement>('#message-bar')
const selectionInspector = element<HTMLElement>('#selection-inspector')
const finishRoomButton = element<HTMLButtonElement>('#finish-room')
const cancelDrawingButton = element<HTMLButtonElement>('#cancel-drawing')
const deleteSelectionButton = element<HTMLButtonElement>('#delete-selection')
const undoButton = element<HTMLButtonElement>('#undo')
const redoButton = element<HTMLButtonElement>('#redo')
const showSuggestionsInput = element<HTMLInputElement>('#show-suggestions')
const annotatedByInput = element<HTMLInputElement>('#annotated-by')
const notesInput = element<HTMLTextAreaElement>('#annotation-notes')
const reviewedByInput = element<HTMLInputElement>('#reviewed-by')
const reviewCommentInput = element<HTMLTextAreaElement>('#review-comment')
const requestChangesButton = element<HTMLButtonElement>('#request-changes')
const approveReviewButton = element<HTMLButtonElement>('#approve-review')
const timingCard = element<HTMLElement>('#timing-card')
const timingValue = element<HTMLElement>('#timing-value')
const timingState = element<HTMLElement>('#timing-state')

let workpack: AnnotationWorkpack | null = null
let imageUrl: string | null = null
let imageVerified = false
let activeTool: Tool = 'select'
let selection: Selection = null
let drawingPoints: Point[] = []
let annotations = emptyAnnotations()
let history = [cloneAnnotations(annotations)]
let historyIndex = 0
let dragTarget: DragTarget | null = null
let dragStart: Annotations | null = null
let correctionTimer: ActiveCorrectionTimer = createCorrectionTimer(0, performance.now())
let reviewTarget: {
  submission: AnnotationSubmission
  sha256: string
  fileName: string
} | null = null

function setMessage(message: string, kind: 'info' | 'success' | 'warning' | 'error' = 'info'): void {
  messageBar.dataset.kind = kind
  const paragraph = messageBar.querySelector('p')
  if (paragraph) paragraph.textContent = message
}

function isReady(): boolean {
  return workpack !== null && imageVerified && imageUrl !== null
}

function timerForeground(): boolean {
  return document.visibilityState === 'visible' && document.hasFocus()
}

function resetCorrectionTimer(durationSeconds = 0): void {
  const now = performance.now()
  correctionTimer = {
    ...createCorrectionTimer(durationSeconds, now),
    foreground: timerForeground(),
  }
  renderTiming(now)
}

function markEditingActivity(): void {
  correctionTimer = recordCorrectionActivity(correctionTimer, performance.now())
  renderTiming()
}

function currentCorrectionDuration(): number {
  return correctionDurationSeconds(correctionTimer, performance.now())
}

function formatDuration(seconds: number): string {
  const wholeSeconds = Math.floor(seconds)
  const minutes = Math.floor(wholeSeconds / 60)
  const remainder = wholeSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
}

function renderTiming(now = performance.now()): void {
  const duration = correctionDurationSeconds(correctionTimer, now)
  const hasActivity = correctionTimer.lastActivityMilliseconds !== null
  const active = hasActivity && correctionTimer.foreground &&
    now - (correctionTimer.lastActivityMilliseconds ?? now) < ANNOTATION_IDLE_TIMEOUT_MS
  const state = !hasActivity
    ? 'waiting'
    : !correctionTimer.foreground
      ? 'paused'
      : active
        ? 'active'
        : 'idle'
  timingCard.dataset.state = state
  timingValue.textContent = formatDuration(duration)
  timingState.textContent = state === 'waiting'
    ? (duration > 0 ? '已恢复累计时间，等待继续编辑' : '等待首次真值编辑')
    : state === 'active'
      ? '正在累计前台有效时间'
      : state === 'paused'
        ? '页面失焦，计时已暂停'
        : '连续 30 秒无操作，计时已暂停'
}

function resetHistory(value: Annotations): void {
  annotations = cloneAnnotations(value)
  history = [cloneAnnotations(value)]
  historyIndex = 0
  selection = null
  drawingPoints = []
}

function validateAndCommit(next: Annotations, message?: string): boolean {
  if (!workpack) return false
  try {
    createSubmission(
      workpack,
      next,
      'draft',
      annotatedByInput.value,
      notesInput.value,
      currentCorrectionDuration(),
    )
    annotations = cloneAnnotations(next)
    history = history.slice(0, historyIndex + 1)
    history.push(cloneAnnotations(next))
    historyIndex += 1
    reviewTarget = null
    markEditingActivity()
    if (message) setMessage(message, 'success')
    render()
    return true
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '标注几何无效', 'error')
    return false
  }
}

function svgNode<K extends keyof SVGElementTagNameMap>(
  name: K,
  attributes: Record<string, string | number>,
): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG_NAMESPACE, name)
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)))
  return node
}

function selectShape(event: PointerEvent, next: Selection): void {
  if (activeTool !== 'select') return
  event.stopPropagation()
  selection = next
  render()
}

function appendWall(
  layer: SVGGElement,
  wall: Annotations['walls'][number],
  className: string,
  selectable: boolean,
): void {
  if (!workpack) return
  const start = metersToPixel(wall.start, workpack.calibration)
  const end = metersToPixel(wall.end, workpack.calibration)
  const width = Math.max(2, wall.thickness / metersPerPixel(workpack.calibration))
  const hit = svgNode('line', {
    x1: start[0], y1: start[1], x2: end[0], y2: end[1],
    class: `${className} wall-hit`, 'stroke-width': Math.max(14, width),
  })
  const line = svgNode('line', {
    x1: start[0], y1: start[1], x2: end[0], y2: end[1],
    class: className, 'stroke-width': width,
  })
  if (selectable) {
    const listener = (event: PointerEvent) => selectShape(event, { kind: 'wall', id: wall.id })
    hit.addEventListener('pointerdown', listener)
    line.addEventListener('pointerdown', listener)
  }
  layer.append(hit, line)
}

function appendRoom(
  layer: SVGGElement,
  room: Annotations['rooms'][number],
  className: string,
  selectable: boolean,
): void {
  if (!workpack) return
  const calibration = workpack.calibration
  const points = room.polygon
    .map((entry) => metersToPixel(entry, calibration))
    .map((entry) => entry.join(','))
    .join(' ')
  const polygon = svgNode('polygon', { points, class: className })
  if (selectable) {
    polygon.addEventListener('pointerdown', (event) => {
      selectShape(event, { kind: 'room', id: room.id })
    })
  }
  layer.append(polygon)
}

function appendOpening(
  layer: SVGGElement,
  opening: Annotations['openings'][number],
  className: string,
  selectable: boolean,
): void {
  if (!workpack) return
  const center = metersToPixel(opening.center, workpack.calibration)
  const radius = Math.max(7, opening.width / metersPerPixel(workpack.calibration) / 2)
  const circle = svgNode('circle', {
    cx: center[0], cy: center[1], r: radius, class: className,
  })
  const label = svgNode('text', {
    x: center[0], y: center[1] + 4, class: `${className}-label`, 'text-anchor': 'middle',
  })
  label.textContent = opening.kind === 'door' ? '门' : '窗'
  if (selectable) {
    const listener = (event: PointerEvent) => selectShape(event, { kind: 'opening', id: opening.id })
    circle.addEventListener('pointerdown', listener)
    label.addEventListener('pointerdown', listener)
  }
  layer.append(circle, label)
}

function appendHandle(point: Point, target: DragTarget): void {
  if (!workpack) return
  const pixel = metersToPixel(point, workpack.calibration)
  const handle = svgNode('circle', {
    cx: pixel[0], cy: pixel[1], r: 7, class: 'edit-handle',
  })
  handle.addEventListener('pointerdown', (event) => {
    if (activeTool !== 'select') return
    event.preventDefault()
    event.stopPropagation()
    dragTarget = target
    dragStart = cloneAnnotations(annotations)
    annotations = cloneAnnotations(annotations)
    markEditingActivity()
    svg.setPointerCapture(event.pointerId)
  })
  handleLayer.append(handle)
}

function renderCanvas(): void {
  suggestionLayer.replaceChildren()
  truthLayer.replaceChildren()
  draftLayer.replaceChildren()
  handleLayer.replaceChildren()
  if (!workpack) return
  const activeWorkpack = workpack

  suggestionLayer.style.display = showSuggestionsInput.checked ? '' : 'none'
  workpack.suggestions.rooms.forEach((item) => appendRoom(suggestionLayer, item, 'suggestion-room', false))
  workpack.suggestions.walls.forEach((item) => appendWall(suggestionLayer, item, 'suggestion-wall', false))
  workpack.suggestions.openings.forEach((item) => appendOpening(suggestionLayer, item, 'suggestion-opening', false))
  annotations.rooms.forEach((item) => {
    appendRoom(truthLayer, item, selection?.kind === 'room' && selection.id === item.id ? 'truth-room selected' : 'truth-room', true)
  })
  annotations.walls.forEach((item) => {
    appendWall(truthLayer, item, selection?.kind === 'wall' && selection.id === item.id ? 'truth-wall selected' : 'truth-wall', true)
  })
  annotations.openings.forEach((item) => {
    appendOpening(truthLayer, item, selection?.kind === 'opening' && selection.id === item.id ? 'truth-opening selected' : 'truth-opening', true)
  })

  if (drawingPoints.length > 0) {
    const pixels = drawingPoints.map((entry) => metersToPixel(entry, activeWorkpack.calibration))
    if (activeTool === 'wall' && pixels[0]) {
      draftLayer.append(svgNode('circle', { cx: pixels[0][0], cy: pixels[0][1], r: 7, class: 'draft-point' }))
    }
    if (activeTool === 'room') {
      draftLayer.append(svgNode('polyline', {
        points: pixels.map((entry) => entry.join(',')).join(' '), class: 'draft-room',
      }))
      pixels.forEach((entry) => draftLayer.append(svgNode('circle', {
        cx: entry[0], cy: entry[1], r: 6, class: 'draft-point',
      })))
    }
  }

  if (selection?.kind === 'wall') {
    const selectedId = selection.id
    const item = annotations.walls.find((entry) => entry.id === selectedId)
    if (item) {
      appendHandle(item.start, { kind: 'wall', id: item.id, part: 'start' })
      appendHandle(item.end, { kind: 'wall', id: item.id, part: 'end' })
    }
  }
  if (selection?.kind === 'room') {
    const selectedId = selection.id
    const item = annotations.rooms.find((entry) => entry.id === selectedId)
    item?.polygon.forEach((entry, vertex) => appendHandle(entry, { kind: 'room', id: item.id, vertex }))
  }
  if (selection?.kind === 'opening') {
    const selectedId = selection.id
    const item = annotations.openings.find((entry) => entry.id === selectedId)
    if (item) appendHandle(item.center, { kind: 'opening', id: item.id })
  }
}

function numberInput(label: string, field: string, value: number, step = '0.01'): string {
  return `<label>${label}<input data-field="${field}" type="number" step="${step}" value="${value.toFixed(3)}" /></label>`
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function renderInspector(): void {
  deleteSelectionButton.hidden = selection === null
  if (!selection) {
    selectionInspector.className = 'selection-empty'
    selectionInspector.textContent = '选择真值几何后可编辑属性；拖动圆形控制点可修改端点、中心或房间顶点。'
    return
  }
  selectionInspector.className = 'selection-form'
  const selectedId = selection.id
  if (selection.kind === 'wall') {
    const item = annotations.walls.find((entry) => entry.id === selectedId)
    if (!item) return
    const itemNumber = annotations.walls.findIndex((entry) => entry.id === selectedId) + 1
    selectionInspector.innerHTML = `
      <strong>墙体 ${itemNumber}</strong><span>几何对象</span>
      <div class="field-grid">
        ${numberInput('起点横向坐标', 'start-0', item.start[0])}
        ${numberInput('起点纵向坐标', 'start-1', item.start[1])}
        ${numberInput('终点横向坐标', 'end-0', item.end[0])}
        ${numberInput('终点纵向坐标', 'end-1', item.end[1])}
      </div>
      ${numberInput('墙厚（米）', 'thickness', item.thickness)}
    `
  } else if (selection.kind === 'room') {
    const item = annotations.rooms.find((entry) => entry.id === selectedId)
    if (!item) return
    const itemNumber = annotations.rooms.findIndex((entry) => entry.id === selectedId) + 1
    selectionInspector.innerHTML = `
      <strong>房间 ${itemNumber}</strong><span>${item.polygon.length} 个顶点</span>
      <label>房间类型
        <select data-field="roomType">
          ${ROOM_TYPE_OPTIONS.map((option) => `<option value="${option.value}" ${item.roomType === option.value ? 'selected' : ''}>${option.label}</option>`).join('')}
          ${ROOM_TYPE_OPTIONS.some((option) => option.value === item.roomType) ? '' : `<option value="${escapeHtml(item.roomType)}" selected>${roomTypeLabel(item.roomType)}</option>`}
        </select>
      </label>
      <p>拖动画布上的控制点编辑房间边界。</p>
    `
  } else {
    const item = annotations.openings.find((entry) => entry.id === selectedId)
    if (!item) return
    const itemNumber = annotations.openings.findIndex((entry) => entry.id === selectedId) + 1
    selectionInspector.innerHTML = `
      <strong>${item.kind === 'door' ? '门' : '窗'} ${itemNumber}</strong><span>几何对象</span>
      <label>类型<select data-field="kind"><option value="door" ${item.kind === 'door' ? 'selected' : ''}>门</option><option value="window" ${item.kind === 'window' ? 'selected' : ''}>窗</option></select></label>
      <div class="field-grid">
        ${numberInput('中心横向坐标', 'center-0', item.center[0])}
        ${numberInput('中心纵向坐标', 'center-1', item.center[1])}
      </div>
      ${numberInput('净宽（米）', 'width', item.width)}
    `
  }
  selectionInspector.querySelectorAll<HTMLInputElement | HTMLSelectElement>('[data-field]').forEach((input) => {
    input.addEventListener('change', () => updateSelectedField(input.dataset.field ?? '', input.value))
  })
}

function updateSelectedField(field: string, rawValue: string): void {
  if (!selection) return
  const next = cloneAnnotations(annotations)
  if (selection.kind === 'wall') {
    const item = next.walls.find((entry) => entry.id === selection?.id)
    const value = Number(rawValue)
    if (!item || !Number.isFinite(value)) return
    if (field === 'thickness') item.thickness = value
    if (field === 'start-0') item.start[0] = value
    if (field === 'start-1') item.start[1] = value
    if (field === 'end-0') item.end[0] = value
    if (field === 'end-1') item.end[1] = value
  } else if (selection.kind === 'room') {
    const item = next.rooms.find((entry) => entry.id === selection?.id)
    if (!item || field !== 'roomType') return
    item.roomType = rawValue.trim()
  } else {
    const item = next.openings.find((entry) => entry.id === selection?.id)
    if (!item) return
    if (field === 'kind' && (rawValue === 'door' || rawValue === 'window')) item.kind = rawValue
    const value = Number(rawValue)
    if (field !== 'kind' && !Number.isFinite(value)) return
    if (field === 'width') item.width = value
    if (field === 'center-0') item.center[0] = value
    if (field === 'center-1') item.center[1] = value
  }
  validateAndCommit(next, '属性已更新')
}

function render(): void {
  const ready = isReady()
  const candidateName = workpack?.workpackId === DEMO_WORKPACK_ID ? '内置演示' : workpack?.candidateId
  shell.dataset.ready = String(ready)
  canvasFrame.hidden = !ready
  emptyState.hidden = ready
  element<HTMLElement>('#top-status').textContent = ready
    ? `${candidateName} · 图片已校验`
    : workpack
      ? '工作包已载入 · 等待对应原图'
      : '等待导入工作包'
  element<HTMLElement>('#candidate-id').textContent = candidateName ?? '尚未载入'
  element<HTMLElement>('#workpack-id').textContent = workpack
    ? `编号 ${workpack.workpackId === DEMO_WORKPACK_ID ? '演示' : `${workpack.workpackId.slice(0, 8)}…`}`
    : '编号 —'
  const rights = element<HTMLElement>('#rights-status')
  rights.dataset.status = workpack?.rightsStatus ?? 'pending'
  rights.textContent = workpack ? `权利 ${rightsStatusLabel(workpack.rightsStatus)}` : '权利 —'
  element<HTMLElement>('#wall-count').textContent = String(annotations.walls.length)
  element<HTMLElement>('#room-count').textContent = String(annotations.rooms.length)
  element<HTMLElement>('#opening-count').textContent = String(annotations.openings.length)
  root.querySelectorAll<HTMLButtonElement>('[data-tool]').forEach((button) => {
    button.classList.toggle('active', button.dataset.tool === activeTool)
    button.disabled = !ready
  })
  root.querySelectorAll<HTMLButtonElement>('[data-import]').forEach((button) => {
    button.disabled = !ready
  })
  finishRoomButton.disabled = !(ready && activeTool === 'room' && drawingPoints.length >= 3)
  cancelDrawingButton.disabled = drawingPoints.length === 0
  undoButton.disabled = historyIndex === 0
  redoButton.disabled = historyIndex >= history.length - 1
  const canReview = reviewTarget !== null && ready
  requestChangesButton.disabled = !canReview
  approveReviewButton.disabled = !canReview
  element<HTMLElement>('#review-target').textContent = reviewTarget
    ? `${reviewTarget.fileName} · 标注人 ${reviewTarget.submission.annotatedBy ?? '未知'} · 摘要 ${reviewTarget.sha256.slice(0, 8)}…`
    : '载入待复核标注后可进行第二人复核。'
  element<HTMLButtonElement>('#export-draft').disabled = !ready
  element<HTMLButtonElement>('#export-review').disabled = !ready
  if (ready) renderCanvas()
  renderInspector()
}

function activateTool(tool: Tool): void {
  activeTool = tool
  drawingPoints = []
  selection = null
  setMessage(
    tool === 'select' ? '选择几何并拖动控制点进行修改。' :
      tool === 'wall' ? '依次点击墙体起点和终点。' :
        tool === 'room' ? '依次点击房间顶点，完成后按 Enter 或“完成房间”。' :
          `点击${tool === 'door' ? '门' : '窗'}中心位置。`,
  )
  render()
}

function eventPoint(event: PointerEvent): Point | null {
  if (!workpack) return null
  const matrix = svg.getScreenCTM()
  if (!matrix) return null
  const pixel = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
  return clampMeters(pixelToMeters([pixel.x, pixel.y], workpack.calibration), workpack.calibration)
}

function handleCanvasPointer(event: PointerEvent): void {
  if (!isReady() || dragTarget) return
  const value = eventPoint(event)
  if (!value) return
  if (activeTool === 'select') {
    selection = null
    render()
    return
  }
  markEditingActivity()
  if (activeTool === 'wall') {
    drawingPoints.push(value)
    if (drawingPoints.length === 2) {
      const next = cloneAnnotations(annotations)
      next.walls.push({
        id: nextId('wall', next),
        start: drawingPoints[0] as Point,
        end: drawingPoints[1] as Point,
        thickness: Number(element<HTMLInputElement>('#wall-thickness').value),
      })
      drawingPoints = []
      validateAndCommit(next, '墙体已添加')
    } else render()
  } else if (activeTool === 'room') {
    drawingPoints.push(value)
    render()
  } else {
    const next = cloneAnnotations(annotations)
    const kind = activeTool
    next.openings.push({
      id: nextId(kind, next),
      kind,
      center: value,
      width: Number(element<HTMLInputElement>('#opening-width').value),
    })
    validateAndCommit(next, `${kind === 'door' ? '门' : '窗'}已添加`)
  }
}

function finishRoom(): void {
  if (drawingPoints.length < 3) return
  const next = cloneAnnotations(annotations)
  next.rooms.push({ id: nextId('room', next), roomType: 'unknown', polygon: [...drawingPoints] })
  if (validateAndCommit(next, '房间已添加，请在属性面板确认房型语义')) drawingPoints = []
}

function mutateDrag(value: Point): void {
  if (!dragTarget) return
  if (dragTarget.kind === 'wall') {
    const item = annotations.walls.find((entry) => entry.id === dragTarget?.id)
    if (item) item[dragTarget.part] = value
  } else if (dragTarget.kind === 'room') {
    const item = annotations.rooms.find((entry) => entry.id === dragTarget?.id)
    if (item) item.polygon[dragTarget.vertex] = value
  } else {
    const item = annotations.openings.find((entry) => entry.id === dragTarget?.id)
    if (item) item.center = value
  }
}

function completeDrag(): void {
  if (!dragTarget || !dragStart) return
  const next = cloneAnnotations(annotations)
  annotations = dragStart
  dragTarget = null
  dragStart = null
  validateAndCommit(next, '几何位置已更新')
}

function removeSelection(): void {
  if (!selection) return
  const next = cloneAnnotations(annotations)
  if (selection.kind === 'wall') next.walls = next.walls.filter((entry) => entry.id !== selection?.id)
  if (selection.kind === 'room') next.rooms = next.rooms.filter((entry) => entry.id !== selection?.id)
  if (selection.kind === 'opening') next.openings = next.openings.filter((entry) => entry.id !== selection?.id)
  selection = null
  validateAndCommit(next, '标注已删除')
}

async function verifyAndLoadImage(blob: Blob, filename: string): Promise<void> {
  if (!workpack) throw new Error('请先载入工作包')
  const content = await blob.arrayBuffer()
  const digest = await sha256Hex(content)
  if (digest !== workpack.image.sha256) throw new Error('原图文件摘要与工作包不一致')
  const nextUrl = URL.createObjectURL(blob)
  const probe = new Image()
  probe.src = nextUrl
  await probe.decode()
  if (probe.naturalWidth !== workpack.image.widthPixels || probe.naturalHeight !== workpack.image.heightPixels) {
    URL.revokeObjectURL(nextUrl)
    throw new Error('原图像素尺寸与工作包不一致')
  }
  if (imageUrl) URL.revokeObjectURL(imageUrl)
  imageUrl = nextUrl
  imageVerified = true
  svg.setAttribute('viewBox', `0 0 ${probe.naturalWidth} ${probe.naturalHeight}`)
  planImage.setAttribute('href', nextUrl)
  planImage.setAttribute('width', String(probe.naturalWidth))
  planImage.setAttribute('height', String(probe.naturalHeight))
  setMessage(`${filename} 已通过文件摘要与像素尺寸校验`, 'success')
  render()
}

async function loadWorkpackFile(file: File): Promise<void> {
  const parsed = parseWorkpack(JSON.parse(await file.text()) as unknown)
  workpack = parsed
  imageVerified = false
  if (imageUrl) URL.revokeObjectURL(imageUrl)
  imageUrl = null
  reviewTarget = null
  resetHistory(emptyAnnotations())
  resetCorrectionTimer()
  setMessage(`工作包 ${parsed.workpackId.slice(0, 8)}… 已载入，请选择 ${parsed.image.file}`, 'success')
  render()
}

function downloadSubmission(status: 'draft' | 'ready-for-review'): void {
  if (!workpack) return
  try {
    const submission = createSubmission(
      workpack,
      annotations,
      status,
      annotatedByInput.value,
      notesInput.value,
      currentCorrectionDuration(),
    )
    const blob = new Blob([`${JSON.stringify(submission, null, 2)}\n`], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${workpack.candidateId}-${status}.json`
    link.click()
    URL.revokeObjectURL(url)
    setMessage(status === 'draft' ? '草稿已导出' : '待复核标注已导出', 'success')
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '导出失败', 'error')
  }
}

function downloadReview(decision: 'approved' | 'changes-requested'): void {
  if (!workpack || !reviewTarget || !isReady()) return
  try {
    const review = createAnnotationReview(
      workpack,
      reviewTarget.submission,
      reviewTarget.sha256,
      decision,
      reviewedByInput.value,
      reviewCommentInput.value,
    )
    const blob = new Blob([`${JSON.stringify(review, null, 2)}\n`], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${workpack.candidateId}-review-${decision}.json`
    link.click()
    URL.revokeObjectURL(url)
    setMessage(decision === 'approved' ? '复核通过记录已导出' : '退回修改记录已导出', 'success')
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '复核记录导出失败', 'error')
  }
}

async function loadDemo(): Promise<void> {
  const svgText = `<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700" viewBox="0 0 1000 700"><rect width="1000" height="700" fill="#f8f5ec"/><g fill="none" stroke="#26312e" stroke-width="18"><rect x="80" y="60" width="840" height="580"/><path d="M500 60V270M500 380V640M80 350H300M390 350H700M790 350H920"/></g><g fill="#837c6d" font-family="sans-serif" font-size="30" text-anchor="middle"><text x="285" y="200">客厅</text><text x="715" y="200">卧室</text><text x="285" y="520">厨房</text><text x="715" y="520">卧室</text></g></svg>`
  const blob = new Blob([svgText], { type: 'image/svg+xml' })
  const digest = await sha256Hex(await blob.arrayBuffer())
  workpack = {
    workpackId: DEMO_WORKPACK_ID,
    candidateId: 'commons-1',
    rightsStatus: 'pending',
    image: { file: 'demo-floorplan.svg', sha256: digest, widthPixels: 1000, heightPixels: 700 },
    calibration: {
      planWidthMeters: 10.668,
      planBoundsPixels: [80, 60, 920, 640],
      imageWidthPixels: 1000,
      imageHeightPixels: 700,
    },
    suggestions: {
      pipelineVersion: 'opencv-axis-aligned-baseline-v1',
      coordinateSystem: 'plan-bottom-left-x-right-z-up-m',
      walls: [
        { id: 'wall-suggestion-top', start: [0, 7.366], end: [10.668, 7.366], thickness: 0.23 },
        { id: 'wall-suggestion-bottom', start: [0, 0], end: [10.668, 0], thickness: 0.23 },
        { id: 'wall-suggestion-left', start: [0, 0], end: [0, 7.366], thickness: 0.23 },
        { id: 'wall-suggestion-right', start: [10.668, 0], end: [10.668, 7.366], thickness: 0.23 },
        { id: 'wall-suggestion-middle', start: [5.334, 0], end: [5.334, 7.366], thickness: 0.2 },
      ],
      rooms: [
        { id: 'room-suggestion-living', roomType: 'unknown', polygon: [[0.2, 3.8], [5.1, 3.8], [5.1, 7.1], [0.2, 7.1]] },
      ],
      openings: [],
    },
  }
  reviewTarget = null
  resetHistory(emptyAnnotations())
  resetCorrectionTimer()
  await verifyAndLoadImage(blob, '内置演示户型')
  setMessage('演示数据已载入：灰色虚线为机器建议，彩色几何才是真值', 'success')
}

root.querySelectorAll<HTMLButtonElement>('[data-tool]').forEach((button) => {
  button.addEventListener('click', () => activateTool(button.dataset.tool as Tool))
})
root.querySelectorAll<HTMLButtonElement>('[data-import]').forEach((button) => {
  button.addEventListener('click', () => {
    if (!workpack) return
    const kind = button.dataset.import as 'walls' | 'rooms'
    validateAndCommit(copySuggestions(workpack, annotations, [kind]), '建议已复制为待核真值，请逐项修正')
  })
})

element<HTMLInputElement>('#workpack-file').addEventListener('change', async (event) => {
  const file = (event.currentTarget as HTMLInputElement).files?.[0]
  if (!file) return
  reviewTarget = null
  render()
  try { await loadWorkpackFile(file) } catch (error) {
    setMessage(error instanceof Error ? error.message : '工作包载入失败', 'error')
  }
})
element<HTMLInputElement>('#image-file').addEventListener('change', async (event) => {
  const file = (event.currentTarget as HTMLInputElement).files?.[0]
  if (!file) return
  imageVerified = false
  render()
  try { await verifyAndLoadImage(file, file.name) } catch (error) {
    setMessage(error instanceof Error ? error.message : '原图载入失败', 'error')
  }
})
element<HTMLInputElement>('#draft-file').addEventListener('change', async (event) => {
  const file = (event.currentTarget as HTMLInputElement).files?.[0]
  if (!file || !workpack) return
  reviewTarget = null
  render()
  try {
    const content = await file.arrayBuffer()
    const submission = parseSubmission(
      JSON.parse(new TextDecoder().decode(content)) as unknown,
      workpack,
    )
    resetHistory(submission.annotations)
    resetCorrectionTimer(submission.correctionSession?.durationSeconds ?? 0)
    annotatedByInput.value = submission.annotatedBy ?? ''
    notesInput.value = submission.notes
    reviewTarget = submission.annotationStatus === 'ready-for-review'
      ? { submission, sha256: await sha256Hex(content), fileName: file.name }
      : null
    setMessage(
      reviewTarget ? `${file.name} 已载入，可由第二人复核` : `${file.name} 草稿已载入`,
      'success',
    )
    render()
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '草稿载入失败', 'error')
  }
})

svg.addEventListener('pointerdown', handleCanvasPointer)
svg.addEventListener('pointermove', (event) => {
  const value = eventPoint(event)
  if (value) element<HTMLElement>('#coordinate-readout').textContent = `横向 ${value[0].toFixed(2)} · 纵向 ${value[1].toFixed(2)} 米`
  if (!dragTarget || !value) return
  mutateDrag(value)
  renderCanvas()
  renderInspector()
})
svg.addEventListener('pointerup', completeDrag)
svg.addEventListener('pointercancel', completeDrag)
showSuggestionsInput.addEventListener('change', renderCanvas)
finishRoomButton.addEventListener('click', finishRoom)
cancelDrawingButton.addEventListener('click', () => { drawingPoints = []; render() })
deleteSelectionButton.addEventListener('click', removeSelection)
element<HTMLButtonElement>('#export-draft').addEventListener('click', () => downloadSubmission('draft'))
element<HTMLButtonElement>('#export-review').addEventListener('click', () => downloadSubmission('ready-for-review'))
requestChangesButton.addEventListener('click', () => downloadReview('changes-requested'))
approveReviewButton.addEventListener('click', () => downloadReview('approved'))
element<HTMLButtonElement>('#demo-button').addEventListener('click', () => void loadDemo())
element<HTMLButtonElement>('#empty-demo-button').addEventListener('click', () => void loadDemo())
undoButton.addEventListener('click', () => {
  if (historyIndex === 0) return
  historyIndex -= 1
  annotations = cloneAnnotations(history[historyIndex] as Annotations)
  reviewTarget = null
  selection = null
  markEditingActivity()
  render()
})
redoButton.addEventListener('click', () => {
  if (historyIndex >= history.length - 1) return
  historyIndex += 1
  annotations = cloneAnnotations(history[historyIndex] as Annotations)
  reviewTarget = null
  selection = null
  markEditingActivity()
  render()
})

window.addEventListener('blur', () => {
  correctionTimer = setCorrectionTimerForeground(correctionTimer, false, performance.now())
  renderTiming()
})
window.addEventListener('focus', () => {
  correctionTimer = setCorrectionTimerForeground(correctionTimer, timerForeground(), performance.now())
  renderTiming()
})
document.addEventListener('visibilitychange', () => {
  correctionTimer = setCorrectionTimerForeground(correctionTimer, timerForeground(), performance.now())
  renderTiming()
})
window.setInterval(() => {
  correctionTimer = advanceCorrectionTimer(correctionTimer, performance.now())
  renderTiming()
}, 1000)

window.addEventListener('keydown', (event) => {
  const target = event.target as HTMLElement | null
  if (target?.matches('input, textarea, select')) return
  if (event.key === 'Enter' && activeTool === 'room') finishRoom()
  if (event.key === 'Escape') { drawingPoints = []; activateTool('select') }
  if ((event.key === 'Backspace' || event.key === 'Delete') && selection) removeSelection()
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    if (event.shiftKey) redoButton.click()
    else undoButton.click()
  }
})

if (new URLSearchParams(window.location.search).get('demo') === '1') void loadDemo()
resetCorrectionTimer()
render()
