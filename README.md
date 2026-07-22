# 3D Floorplan Platform

一个将 2D 住宅户型图转换为可编辑、可风格化并可在手机、平板和电脑浏览的 3D 户型平台。

## 当前状态

项目处于技术验证阶段。编辑器底座、“底图导入→标定→墙体→保存/重载”、
“浏览器 GLB 导出→优化→Babylon.js 多端浏览”、“装修风格→Web 实时预览→Blender
异步效果图”、“房间多边形→规则布局→三套风格同源渲染”、“可审计真实家具→
客餐卧整屋布置→多端同源加载”、“EEVEE 预览→Cycles/Metal 1080p
鸟瞰+客厅+卧室多视角”、“户型图→墙/房间候选→置信度叠加图”，以及“逐项
接受/拒绝→确定性 Wall/Zone 写入→revision 保存”、“可审计样本→墙/房间/门窗指标→
人工修正中位时间”，以及“工作包/原图校验→墙房门窗真值编辑→第二人复核→评测样本晋级”
技术闸门，以及“多来源 CC0 资产→实时 PBR 纹理保留换装→权威门窗净空避让→多端/Blender
同源加载”的首个精细资产切片均已跑通。下一批工作是：

在这些模块之上，当前已经形成第一条可直接演示的产品主线基准：客户在 Viewer 首页上传一张
边界清晰的直墙户型图并填写外宽，系统自动完成识别、权威场景写入、结构 GLB、三套家具布局
和实时 3D 发布，随后可在桌面或手机切换装修风格与房间视角。该基准的已知限制会在上传页和
任务 manifest 中明确显示，不把未支持的门窗、曲墙或房间语义伪装成完整识别能力。下一批工作是：

1. 完成 20～50 张合法真实户型的权利审核、双人标注与正式评测集晋级。
2. 量化当前基线精度和人工修正中位时间，再升级斜墙、门窗、文字干扰和房间语义模型。
3. 在 layout v4 之上实现家具拖拽、约束反馈、布局保存/恢复和任意旋转家具约束。
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
- [真实户型候选收集与人工审核边界](docs/adr/0011-recognition-candidate-intake.md)
- [候选审核与标注工作包](docs/adr/0012-recognition-annotation-workpack.md)
- [独立户型真值标注台](docs/adr/0013-ground-truth-annotation-workbench.md)
- [双人复核与评测样本晋级](docs/adr/0014-double-review-and-sample-promotion.md)
- [前台有效标注时间自动计时](docs/adr/0015-active-annotation-timing.md)
- [真实评测样本生产看板](docs/adr/0016-recognition-sample-production-board.md)
- [客户实时 3D 样板间](docs/adr/0017-customer-realtime-showroom.md)
- [商业级实时资产质量切片](docs/adr/0018-commercial-realtime-assets.md)
- [权威门窗开口与动线净空布局](docs/adr/0019-authoritative-openings-and-circulation.md)
- [户型图到客户实时 3D 的主线基准](docs/adr/0020-floorplan-to-realtime-baseline.md)
- [真实户型主链路可靠性报告](docs/adr/0021-mainline-reliability-evaluation.md)
- [真实样本批次发布与联合评测](docs/adr/0022-recognition-batch-release.md)

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

下一阶段继续以“户型图上传→自动 3D→客户实时看→切换风格”为唯一产品主线，优先用合法真实
样本量化端到端成功率并补齐门窗、斜墙、房间语义和失败复核入口；家具拖拽、约束反馈与版本恢复
作为后续增强，不再先于主链路可靠性建设。

离线可靠性报告已经可以对同一份商业评测 manifest 逐样本运行真实识别、结构场景、GLB 优化和
全部风格布局，并把失败归到明确阶段。当前只有项目自有受控 fixture 完成主线验证，不将其 1/1
结果宣传为真实户型成功率；正式百分比等待 20～50 个 complete 样本晋级后生成。

已晋级样本现在可通过单个批次命令确定性组装为版本化 manifest，并对同一批输入同时产出生产
状态、识别几何和三风格主链路报告。该命令只消费已经通过权利审核、计时标注和第二人复核的
`promoted` 样本，不会自动批准或代签仍待人工处理的候选。
