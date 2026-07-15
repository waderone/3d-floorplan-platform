# ADR-0001：编辑器底座技术验证

- 状态：技术底座验证通过，待确认正式集成方式
- 日期：2026-07-15

## 背景

项目需要墙体、门窗、房间、楼层、家具、2D/3D 编辑、场景保存和 GLB 导出。直接从零开发这些能力会显著扩大首版风险。

## 当前决定

以 Pascal Editor 作为 Phase 0 候选底座，使用 Git submodule 固定上游版本，仅用于技术验证：

- 上游：https://github.com/pascalorg/editor
- Commit：`a59074774898116c0e7116b424b371e5e3420ea4`
- 许可证：MIT
- 验证目录：`spikes/pascal-editor/upstream`

## 验证标准

1. 固定版本可以完成依赖安装和生产构建或完整类型检查。
2. 现有分层允许产品代码将领域场景、3D Viewer 和编辑体验分开使用。
3. 户型底图、墙体、开口、房间和 GLB 导出已有可复用入口。
4. 修改范围和上游同步成本可控。
5. 商业使用所需版权和许可证声明可以完整保留。

## 约束

- 本次 submodule 不代表最终集成方式。
- 技术验证期间不修改上游源码。
- 验证不通过时删除整个 spike，不影响产品模块。

## 验证结果

锁定版本已在本机完成以下验证：

- `bun install --frozen-lockfile`：成功，按锁文件安装 1374 个依赖包。
- `bun check-types`：成功，Turborepo 任务 10/10 通过。
- `bun run build`：成功，生产构建任务 7/7 通过。
- 核心领域测试：成功，空间检测、对齐吸附和墙体斜接共 20/20 通过。
- 编辑器运行：成功，Next.js 16.2.9 开发服务器就绪，`/api/health` 返回 `status: ok`，首页返回 HTTP 200。
- 运行时注册表：成功加载 43 类核心节点和 1 个发现插件。

构建产生 3 条与内置 SQLite 场景存储动态路径有关的 Next.js 文件追踪警告，不影响产物。产品侧仍按既定架构将业务 API、项目权限和场景持久化迁移到 FastAPI/PostgreSQL。

## 已知缺口

1. 上游 `packages/viewer/src/lib/ktx2-loader.ts` 从 `three/examples/jsm/Addons.js` 桶文件导入 `KTX2Loader`，会连带加载 `TTFLoader` 及其 jsDelivr `opentype.js` 远程模块。涉及 Viewer/Editor 的 Bun 测试在模块加载阶段因此失败；核心领域层 20 条定向测试正常。生产构建和编辑器运行不受影响；正式 fork 时应改为直接导入 `three/examples/jsm/loaders/KTX2Loader.js`，并增加离线测试。
2. 示例应用的 SQLite 场景接口、全局 token、进程内限流和轮询 SSE 只适合单机演示。编辑器组件已有 `onLoad`/`onSave` 扩展点，正式产品应由宿主接入 FastAPI，承载租户、权限、版本和任务编排。
3. Pascal 场景图缺少产品规划中的顶层 `schemaVersion`、`revision` 和 `units`。产品 API 应在外层增加显式场景 envelope 和可测试的数据迁移，不依赖加载时隐式修补。
4. 户型 Guide 已支持位置、旋转、缩放、透明度、标定线及多单位输入，但原始底图只存浏览器 IndexedDB，场景内是 `asset://` 句柄，无法跨设备使用。必须改为 S3/MinIO 预签名上传和稳定 URL；MVP 所需底图裁剪也要补做。
5. GLB 导出已有公共入口并保留节点 extras，但依赖浏览器中的 R3F 场景、`requestAnimationFrame` 和纹理工具。首版渲染 Worker 应先用无头浏览器触发导出，再用 glTF-Transform 优化；后续再评估纯 Node 管线。
6. 内置家具目录和示例应用包含本地及外部 Supabase 资产，但没有足以支撑商业复用的逐项许可清单。正式产品必须使用自有对象存储、可控 CDN 和带来源/作者/许可证的资产台账。
7. 小屏布局、底部面板、安全区和触摸相机手势已存在，但缺少对应自动化测试；平板横屏、低端安卓机和 Safari 仍需真机验收。
8. 当前发布流程没有完整发布内置 nodes，`editor` 包也直接导出源码，单纯 npm 包依赖尚不足以复现完整应用。这是现阶段优先维护私有产品化镜像（逻辑 fork）的直接原因。
9. 本轮只证明底座可以安装、构建和运行；完整的户型标定编辑闭环、跨端资源恢复、GLB 优化及手机性能仍属于后续技术闸门。

## 当前结论

Pascal Editor 满足 Phase 0 的候选底座标准，建议进入下一阶段 PoC。正式集成优先采用固定版本的私有产品化镜像（逻辑 fork），并让产品仓库 submodule 指向该镜像的固定 commit：它既能保留上游分包边界，也允许修复测试依赖、替换资源上传和补充必要导出钩子。FastAPI、S3/MinIO、业务权限和场景 envelope 尽量留在产品宿主，控制镜像改动面。当前 upstream submodule 仅保留为可复现的上游基线。

## 待决策

进入 PoC 前确认以下集成方案：

1. 维护固定版本的私有产品化镜像/逻辑 fork（当前推荐）。
2. 使用已发布的 `@pascal-app/core`、`viewer`、`editor` 包。
3. 仅复用场景 Schema/几何思路，自研编辑器。
