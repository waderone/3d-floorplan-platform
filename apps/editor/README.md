# Editor App

面向设计人员的户型校正与 3D 编辑应用。

公开仓库在 `spikes/pascal-editor/upstream` 固定未经修改的 Pascal Editor 官方公开版本，
用于复现编辑器底座的安装、构建和领域能力验证。此前产品化镜像中的 `/poc/{projectId}`
FastAPI 集成补丁不属于当前公开基线，因此下面的命令启动的是 Pascal 上游应用，而不是已经
接通本仓库 API 的产品入口。识别复核与真值编辑的公开实现位于 `apps/annotator`。

## 本地运行

初始化并启动公开上游编辑器：

```bash
git submodule update --init --depth 1
cd spikes/pascal-editor/upstream
bun install --frozen-lockfile
bun run dev
```

具体端口和应用入口以 Pascal 上游终端输出为准。

## 当前边界

- 当前公开基线尚未把 Pascal 上游 UI 与本仓库 FastAPI 接通；
- JPG/PNG 上传、场景和资产的公开 API 均使用本地 PoC 存储；
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
