# 3D Floorplan Platform

一个将 2D 住宅户型图转换为可编辑、可风格化并可在手机、平板和电脑浏览的 3D 户型平台。

## 当前状态

项目处于立项与技术验证阶段。第一阶段先完成技术闸门：

1. 户型底图导入与尺寸标定。
2. 墙体、门窗和房间编辑。
3. 权威场景 JSON 的保存与恢复。
4. GLB 导出、压缩和移动端浏览。
5. Blender 高清效果图渲染。

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

## 下一步

执行五天技术闸门，验证编辑器底座、场景模型、GLB 移动端交付以及 Blender 渲染全链路，再决定正式 MVP 实施。
