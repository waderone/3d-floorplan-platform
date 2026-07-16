# Editor App

面向设计人员的户型校正与 3D 编辑应用。

当前 PoC 采用 `spikes/pascal-editor/upstream` 中的私人 Pascal 产品化镜像，
产品入口是 `/poc/{projectId}`。该入口复用原生 Guide 标定和墙体工具，并通过
`onLoad`/`onSave` 接入本仓库 FastAPI；已保存且完成比例标定的底图还可进入
“识别→叠加预览→逐项接受/拒绝→Wall/Zone 写入→自动保存”流程。

## 本地运行

先按 [API 说明](../../services/api/README.md) 启动 8000 端口，然后启动编辑器：

```bash
git submodule update --init --depth 1
cd spikes/pascal-editor/upstream
bun install --frozen-lockfile
cd apps/editor
PORT=3002 PLATFORM_API_URL=http://127.0.0.1:8000 bun run dev
```

访问 `http://localhost:3002/poc/demo`。本地浏览器统一使用 `localhost`，避免
Next.js 开发模式拒绝来自 `127.0.0.1` 的 HMR 请求。

如需 React Scan 和 Agentation 开发工具，额外设置
`NEXT_PUBLIC_EDITOR_DEVTOOLS=true`；默认关闭，避免覆盖层拦截 2D 画布操作。

## 当前边界

- JPG/PNG 上传、场景和资产均使用本地 PoC 存储；
- 场景支持 revision 乐观并发，但界面冲突策略目前只提示错误；
- 识别结果必须匹配当前 project、scene revision 与底图 asset；识别期间发生保存时，旧结果
  只允许查看，不允许应用；
- 已接受建议写入当前 Level，并保留 recognition metadata；拒绝和未决项不写入，重复建议
  不复制或覆盖已修改节点；
- 非 404 加载失败会锁定编辑、上传和保存；同一页面的保存请求按 revision 串行；
- 硬刷新或关闭页面时，浏览器对排队 keepalive 请求的送达仍是尽力而为；
- 当前识别基线不支持门窗、房型语义、斜墙和复杂噪声图；精确修正需在应用后使用 Pascal
  原生工具；
- 尚未接入登录、PostgreSQL、MinIO、生产对象存储和任务队列。
