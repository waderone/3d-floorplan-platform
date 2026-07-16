# 3D Floorplan Platform

一个将 2D 住宅户型图转换为可编辑、可风格化并可在手机、平板和电脑浏览的 3D 户型平台。

## 当前状态

项目处于技术验证阶段。编辑器底座、“底图导入→标定→墙体→保存/重载”、
“浏览器 GLB 导出→优化→Babylon.js 多端浏览”、“装修风格→Web 实时预览→Blender
异步效果图”、“房间多边形→规则布局→三套风格同源渲染”、“可审计真实家具→
客餐卧整屋布置→多端同源加载”、“EEVEE 预览→Cycles/Metal 1080p
鸟瞰+客厅+卧室多视角”、“户型图→墙/房间候选→置信度叠加图”，以及“逐项
接受/拒绝→确定性 Wall/Zone 写入→revision 保存”、“可审计样本→墙/房间/门窗指标→
人工修正中位时间”
技术闸门均已跑通。下一批工作是：

1. 建立合法的真实户型评测/训练集，升级斜墙、门窗、文字干扰和房间语义模型。
2. 在建议态增加端点、墙厚与房型语义编辑，并建立人工修正中位时间指标。
3. 门窗动线、通道和任意旋转家具约束，以及更高精度家具资产库。
4. 生产任务队列、对象存储和用户项目系统。

## 初步技术栈

- 编辑器：Pascal Editor、Next.js、React、React Three Fiber、Three.js
- 公共浏览器：Babylon.js
- API：Python、FastAPI
- 数据：PostgreSQL、Redis、S3/MinIO
- 异步任务：Celery
- 模型优化：glTF-Transform
- 高清渲染：Blender Cycles
- 户型识别：PyTorch、OpenCV

## 核心原则

- 带版本号的场景 JSON 是权威数据。
- GLB、效果图和 Blender 文件都是派生结果。
- 自动识别结果必须可以人工校正。
- 实时 3D 和照片级效果图使用独立渲染链路。
- 商业产品优先采用许可证清晰、允许商用的代码和资产。

## 项目文档

- [项目统筹计划](outputs/3D户型项目统筹计划.md)
- [编辑器底座技术决策](docs/adr/0001-editor-foundation.md)
- [户型编辑闭环 PoC](docs/adr/0002-floorplan-editing-poc.md)
- [GLB 移动端交付技术闸门](docs/adr/0003-glb-mobile-delivery.md)
- [装修风格与 Blender 效果图技术闸门](docs/adr/0004-style-render-gate.md)
- [房间感知布局与三风格技术闸门](docs/adr/0005-room-aware-layout.md)
- [可审计真实资产与多房间整屋布置](docs/adr/0006-audited-assets-and-multiroom-layout.md)
- [Cycles 高清多视角效果图](docs/adr/0007-photoreal-render-profiles.md)
- [户型图自动识别与人工复核契约](docs/adr/0008-floorplan-recognition-gate.md)
- [识别建议人工复核与场景写入](docs/adr/0009-recognition-review-ui.md)
- [可商用户型识别评测集与确定性指标](docs/adr/0010-recognition-evaluation-dataset.md)

## 仓库结构

```text
apps/                 Web 应用
packages/             可复用领域包
services/             在线 API 服务
workers/              异步任务 Worker
spikes/               可丢弃的技术验证
outputs/              立项与交付文档
```

## 下一步

下一阶段收集并标注可商用真实户型图，为门窗、斜墙和房间语义模型建立可量化基线；
同时在现有复核面板增加建议态几何/语义编辑，并记录每套户型的人工修正时间。
