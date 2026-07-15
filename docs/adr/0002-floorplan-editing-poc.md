# ADR-0002：户型编辑闭环 PoC

- 状态：混合闭环验证通过；真实文件选择待人工复核
- 日期：2026-07-15

## 目标

验证用户能否在浏览器完成最小户型编辑闭环：上传 JPG/PNG 底图、按已知尺寸
标定、绘制墙体、保存场景并在整页重载后恢复。

## 决定

1. 使用私人仓库 `waderone/3d-floorplan-editor` 维护 Pascal 产品化镜像；主仓库
   以 submodule 固定具体 commit，并保留原始 `pascalorg/editor` upstream。
2. 在镜像增加薄路由 `/poc/{projectId}`，只负责平台 API 适配，不改 Pascal Core
   场景模型、Guide 标定算法或墙体工具。
3. FastAPI 使用外层场景 envelope：`schemaVersion`、`revision`、`units`、
   `scene` 和 `assets`。PoC 以单进程本地 JSON/文件存储实现，HTTP 契约可替换为
   PostgreSQL 与 S3/MinIO。
4. 图片使用 SHA-256 内容寻址。编辑器通过 Next 同源代理保存
   `/platform-assets/<sha>.<ext>`，避免局域网设备把 `127.0.0.1` 指向自身。
5. 场景更新使用 `expectedRevision` 乐观并发；不在本阶段引入实时协作或合并算法。
6. 产品宿主只把 404 解释为新项目；其他加载或场景应用错误统一锁定编辑与保存。
   同一项目的保存请求串行执行，资产按调用时快照，旧响应不得回写新状态。

## 已完成验证

- API 自动测试 18 项通过，覆盖 JPG/PNG 检查、20 MiB 上限、稳定 URL、路径逃逸、
  节点/资产边界校验、同源代理资产往返、首次创建、更新和 revision 冲突。
- Pascal 全仓类型检查通过，生产构建通过。
- 前端增加运行时 envelope 校验、加载失败写入锁、项目切换隔离和串行保存队列；
  修改文件通过 Biome，Pascal 全仓 10 项类型检查通过。
- API 上传与 Next 资产回读已验证；浏览器随后加载包含同一 HTTP Guide 的
  revision 1 场景，原生 Set Scale 输入 5 m 后自动保存为 revision 2。
- 2D 画布创建一条 Wall 后自动保存为 revision 3。
- API 读取同时包含 Guide `scaleReference.realLengthMeters = 5` 与 Wall 节点；整页
  reload 后恢复 5 个节点、1 个底图引用和 revision 3。

## 限制

- 本地文件和 JSON 只保证单个 Uvicorn 进程内的并发语义。
- CORS 在 PoC 中允许任意 origin，且没有鉴权；生产前必须收紧。
- 图片目前只校验 Content-Type 和文件头，场景 JSON 尚无独立请求体上限；生产前需
  增加完整图片解码、像素/场景配额和流式存储。
- 页面内保存已串行，但硬刷新或关闭页面时，排队的 keepalive 请求能否启动仍取决于
  浏览器；生产写入协议需增加可恢复草稿或幂等客户端序号。
- Pascal 现有防误清空规则会阻止从“Guide + 最后一堵墙”删除到只剩结构节点的自动
  保存，下一编辑能力阶段需要专项修正并补回归测试。
- 浏览器自动选择文件需要 Chrome 扩展允许访问 file URL，因此本轮未自动触发
  原生文件选择控件；提交前仍需人工选择一张 JPG/PNG 复核完整单页路径。API
  上传、资产回读、前端上传逻辑的类型/生产构建已分别验证。
- 尚未验证手机真机、GLB 导出/压缩、公共 Viewer、AI 户型识别和 Blender 渲染。

## 下一技术闸门

以保存后的权威场景为输入，验证 GLB 导出、glTF-Transform 优化、Babylon.js
移动端浏览和性能预算；通过后再开始装修风格包与离线高清渲染。
