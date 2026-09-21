# ADR-0003：GLB 移动端交付技术闸门

- 状态：技术闸门验证通过
- 日期：2026-07-16

## 目标

验证已保存的 Pascal 权威场景可以在浏览器生成 GLB，经确定性优化后，由不依赖
编辑器运行时的 Babylon.js 应用在手机、平板和电脑上浏览。

## 决定

1. Pascal 浏览器场景继续负责 GLB 烘焙。产品化镜像只给 editor 层增加可选的
   GLB 结果回调；未提供回调时保留原文件下载行为，不修改 core 或 viewer 状态。
2. FastAPI 接收源 GLB、保存处理状态和产物 manifest，但不在上传请求内同步执行
   优化。PoC 使用同进程后台任务调用独立 Node worker；该边界以后替换为任务队列。
3. 模型 worker 固定 `@gltf-transform/cli@4.5.0`，输出优化 GLB，并记录优化前后
   字节数、节点、网格和材质数量。源文件和优化文件都使用 SHA-256 标识；
   `pipelineVersion` 同时进入 artifact identity，算法升级不会复用旧产物。
4. 公共 Viewer 使用 `@babylonjs/core@9.16.2`、`@babylonjs/loaders@9.16.2`、
   Vite 和 TypeScript，不导入 Pascal、React Three Fiber 或 Three.js。
5. GLB 是场景 revision 的派生产物。新的场景保存不会隐式修改旧产物；再次发布时
   生成新的 artifact version，Viewer 默认读取项目最新的 ready manifest。

## 性能预算

- 源 GLB 上传硬上限：80 MiB。
- 常规单层住宅优化产物目标：不超过 40 MiB。
- 手机首次加载目标：不超过 15 MiB；超过时 Viewer 仍可加载，但 manifest 标记
  `mobileBudgetExceeded: true`，后续需拆分纹理或 LOD。
- 手机建议三角形预算：30–80 万。本闸门先记录几何和文件指标，不自动生成 LOD。

## 基准场景

`services/api/tests/fixtures/glb-baseline-scene.json` 来自上一阶段浏览器保存并重载成功
的 `chrome-e2e` 场景，保留 site → building → level → wall 层级，移除 Guide 和图片
资产，从而保证 GLB 验证完全离线。

## 验收

- 编辑器按钮可对当前已保存场景发起发布，并显示生成、处理、成功或失败状态。
- API 拒绝非法 GLB、超限文件和不存在的场景；manifest 可以恢复处理结果。
- worker 对基准 GLB 生成优化产物和可核验指标。
- Viewer 具备加载进度、错误重试、轨道相机和响应式信息面板。
- 自动测试、生产构建和至少一次浏览器多宽度验证通过。

## 非目标

本阶段不实现生产对象存储、分布式任务队列、家具风格包、AI 识别、Blender 高清
渲染或多模型 LOD。

## 验证结果

- Pascal 平台宿主从 revision 1 的真实墙体场景生成并上传 GLB，发布状态从
  `generating`、`uploading`、`processing` 到 `ready`。
- v3 worker 剪除无 Pascal identity 的编辑器环境网格；源 GLB 51,216 B，优化产物
  35,420 B（约减少 30.8%），节点 8→1、网格 4→1、材质 5→2、primitive 7→2。
- API 自动测试 26 项通过，model worker 测试 2 项通过；Pascal 改动 Biome 通过，
  全仓类型任务 10/10 通过；Viewer TypeScript 与 Vite 生产构建通过。
- Babylon.js Viewer 在 1024×768 与 390×844 下均加载 ready，控制台无错误或警告，
  信息卡、顶栏和控制条无越界，3D/俯视/复位交互通过。

## 已知限制

- Vite 仍提示 Babylon 主 chunk 超过 500 KiB；当前主入口约 gzip 178 KiB，glTF loader
  延迟 chunk 约 gzip 42 KiB，属于非阻断优化项。
- 基准只有一堵墙，证明的是交付链路而非最终装修美术质量；家具、纹理风格和完整多房间
  模型仍需后续风格包阶段验证。
- BackgroundTasks 不提供进程恢复；生产实现必须迁移到 Celery/Redis 或等价队列。
