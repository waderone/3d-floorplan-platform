# ADR-0004：装修风格与 Blender 效果图技术闸门

- 状态：技术闸门验证通过
- 日期：2026-07-16

## 目标

验证同一份版本化装修风格可以同时驱动独立 Babylon.js Viewer 和 Blender 无界面
Worker，并从已发布的优化 GLB 异步生成可审计 PNG 效果图。

## 决定

1. 风格是权威场景和 GLB 之外的独立表现层。`warm-minimal@1` 统一描述 PBR 材质角色、
   环境灯光、相机、输出规格和程序化陈设，不写回户型结构，也不进入 GLB artifact identity。
2. 首套材质和家具几何全部由本项目原创定义，许可证字段固定为
   `LicenseRef-Project-Authored`。第三方模型或贴图只有在记录固定来源、版本和许可证后才能
   进入后续资产目录。
3. Web Viewer 从 API 读取风格包，在模型加载后应用建筑/地面材质、环境和程序化家具；
   仍不依赖 Pascal、Three.js 或编辑器状态。
4. Blender Worker 消费优化 GLB 和同一风格 JSON。输入坐标为米制、右手、Y-up，Worker
   只在适配层转换为 Blender Z-up；渲染使用 Blender 5.x EEVEE，1280×720、64 samples。
5. FastAPI 为渲染任务保存确定性 identity 和 `processing/ready/failed` manifest。PoC 继续
   使用 BackgroundTasks 验证状态边界，生产实现必须替换为可恢复任务队列。
6. Blender 以 `--background --factory-startup --disable-autoexec --python-exit-code 1`
   启动，不加载 `.blend`，脚本异常必须使任务失败。开发机使用 Blender 5.2.0 LTS 验收；
   生产应使用固定 Blender 5.x 镜像。

## API 契约

- `GET /api/styles`
- `GET /api/styles/{styleId}`
- `POST /api/projects/{projectId}/renders`
- `GET /api/projects/{projectId}/renders/latest?styleId=warm-minimal`

创建渲染必须引用当前场景 revision、ready 的优化 GLB 和已知风格。render identity 包含
project、revision、artifact、style id/version 和 render pipeline version，同一输入重复提交
复用同一结果。ready manifest 记录 PNG SHA-256、字节数、尺寸、引擎、Blender 版本和耗时。

## 验证结果

- FastAPI 自动测试由 26 项增至 37 项并全部通过，覆盖风格契约、未知风格、未就绪模型、
  确定性任务、PNG 访问和渲染失败持久化。
- Viewer TypeScript 与 Vite 生产构建通过；PBR 风格接入后主入口约 gzip 264 KiB。
- Blender 5.2.0 LTS 可直接导入含 `EXT_meshopt_compression` 的 35,420 B 优化 GLB，
  无需回退到包含编辑器辅助网格的 source GLB。
- 真实 HTTP E2E 首先返回 202/processing，随后变为 ready。最终 PNG 为 802,790 B、
  1280×720，EEVEE 记录 1.099 秒，静态 URL、SHA-256 和视觉结果均通过核验。
- 视觉 QA 经三轮修正后，沙发、茶几、地毯、植物、暖白墙面和低饱和木地板构图完整。

## 已知限制

- 程序化家具用于验证架构和色板，不是照片级商业资产；没有纹理、织物细节和真实品牌模型。
- 当前布局是面向默认相机的固定预设。基准场景只有一堵墙，没有房间多边形，不能据此宣称
  已实现房间感知自动布置。
- EEVEE 适合快速效果图闸门；最终营销级静帧仍应增加真实 PBR 资产、HDRI 和 Cycles 档位。
- BackgroundTasks 无进程恢复、分布式锁和重试保证；生产化前必须迁移到 Celery/Redis 或
  等价队列，并把 Blender 固定到容器镜像。
