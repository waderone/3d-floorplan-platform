# ADR-0007：Cycles 高清多视角效果图

- 状态：技术闸门验证通过
- 日期：2026-07-16

## 目标

保留秒级 Web/EEVEE 预览，同时建立可审计、可以逐步替换高精度资产的 Cycles
高清管线，并为同一整屋 layout 输出鸟瞰、客厅和卧室三张稳定效果图。

## 决定

1. `packages/render-assets/catalog.json` 是渲染档位、相机、HDRI/PBR 文件和许可元数据的
   版本化契约。API 启动时校验本地许可声明、文件字节数与 SHA-256；运行时不调用
   Poly Haven API。
2. `preview@1` 继续使用 EEVEE、1280×720、单鸟瞰图，并作为 API 默认值。
   `quality@1` 使用 Cycles、Metal 优先、1920×1080、64 samples、adaptive threshold 0.06、
   OpenImageDenoise 和 AgX。
3. 高清档的 HDRI 只参与照明/反射，camera ray 使用中性背景，避免把无关环境假装成
   户型外部场景。木地板使用 diffuse/OpenGL normal/roughness；墙面、布料和地毯使用微表面细节。
4. Apple Silicon 先刷新 Cycles 设备并只启用 Metal GPU；不可用时改用 CPU，manifest 必须记录
   实际 `device`，不用“请求了 GPU”代替真实结果。
5. Render identity 包含 profile id/version。latest 索引按风格和 profile 隔离；ready manifest
   新增 `profile`、`device`、`views[]`，并保留 `output == views[0].output` 供旧客户兼容。
6. 室内相机由房间 polygon 计算机位，由档位冻结镜头和方位角。未能可靠锚定到
   真实模型的程序化抱枕不进入交付，避免悬浮软装换取虚假的细节数。

## 资产与许可

首批高清资产为 Poly Haven `lebombo` 1K HDR 和 `wood_floor` 1K diffuse/normal/roughness。
两个资产页声明 CC0，仓库保留精确下载 URL、作者、字节数、SHA-256 和本地
`CC0-1.0` 声明。Poly Haven 实时 API 的商业条款与资产 CC0 不是一件事；本实现不依赖该 API。

## 真实验证

- Blender 5.2.0 LTS 在 Apple M4 `METAL:Apple M4 (GPU - 10 cores)` 上完整输出三张
  1920×1080 PNG，总耗时 35.139 秒；鸟瞰/客厅/卧室分别为 8.459/13.104/13.409 秒。
- 三张图约 1.88–1.93 MiB，每个 URL 的 PNG 头、字节数与 SHA-256 均通过二次下载校验。
- 任务经历 `processing → ready`，记录 13 个 placement、8 个真实模型、0 回退。
- FastAPI 54 项自动测试通过，覆盖默认预览、高清任务身份、三视角、未知档位、
  素材引用和文件篡改。

## 已知限制

- Cycles、PBR、HDRI 与更好的构图已解决管线上限，但当前 Kenney 家具仍是低多边形。
  达到商业样板间级别还需替换高精度家具、增加门窗与装饰并建立人工视觉评分基线。
- 当前 BackgroundTasks 不具备持久化、重试、优先级和 GPU 调度；生产必须迁移到任务队列与固定镜像。
- 高清档目前是同步三视角批处理，未实现视角级重试、中间预览或分布式合并。
