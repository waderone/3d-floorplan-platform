# API Service

户型编辑闭环的最小 FastAPI PoC，当前仅提供：

- JPG/PNG 资产上传和稳定的 `/assets/...` 访问地址；
- 按项目保存、读取场景 JSON；
- 基于 `expectedRevision` 的乐观并发控制；
- 场景图节点引用和资产元数据的最小边界校验；
- GLB 上传、异步优化状态、版本化 manifest 和静态产物访问；
- 版本化装修风格目录和 Blender 异步效果图状态；
- Zone/Slab 房间提取、确定性家具布局和明确回退状态；
- 健康检查。

数据默认保存在当前目录的 `data/` 中，也可通过
`FLOORPLAN_DATA_DIR` 指定其他目录。数据库、鉴权、任务队列不在本 PoC 范围。
本地 JSON 的并发控制仅保证单个 API 进程内有效；本阶段不要启用多个 Uvicorn worker。
GLB 优化使用同进程 `BackgroundTasks` 调用独立 Node worker，仅用于技术闸门；生产环境
必须替换为任务队列，但保留相同 manifest 状态契约。
效果图同样以 BackgroundTasks 调用 Blender 5.x，使用 `FLOORPLAN_BLENDER_BIN` 指定
可执行文件。开发机已用 Blender 5.2.0 LTS 验证；生产必须使用固定镜像和任务队列。
为便于本地编辑器和移动设备联调，PoC 暂时允许任意 CORS origin，且不使用
cookie 或认证信息；生产部署前必须改为明确的前端域名白名单。

## 本地运行

需要 Python 3.11 或更高版本。模型 worker 需要 Node 22.12 或更高版本，并先安装：

```bash
cd workers/model
npm install
```

随后启动 API：

```bash
cd services/api
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Node 不在 PATH 时用 `FLOORPLAN_NODE_BIN=/absolute/path/to/node` 指定运行时。
Blender 不在 PATH 时用 `FLOORPLAN_BLENDER_BIN=/absolute/path/to/blender` 指定运行时。

健康检查：`GET http://127.0.0.1:8000/health`。API 交互文档：
`http://127.0.0.1:8000/docs`。

## 接口约定

### 上传户型图

`POST /api/assets`，multipart 字段名为 `file`。服务会同时检查
Content-Type 和文件头，仅接受 `image/jpeg` 和 `image/png`，单文件上限为
20 MiB。返回示例：

```json
{
  "assetId": "<sha256>",
  "url": "/assets/<sha256>.png",
  "mediaType": "image/png",
  "size": 12345
}
```

内容相同的文件总是得到相同 URL，原始文件名不用于落盘路径。

### 场景读写

- `GET /api/projects/{project_id}/scene`
- `PUT /api/projects/{project_id}/scene`

`project_id` 只允许 1–64 位字母、数字、`_` 和 `-`，且首位必须是字母或数字。
PUT 请求示例：

```json
{
  "schemaVersion": "1.0",
  "revision": 0,
  "expectedRevision": null,
  "units": "m",
  "scene": {
    "nodes": {},
    "rootNodeIds": [],
    "collections": {},
    "materials": {}
  },
  "assets": []
}
```

并发规则：

- 首次创建必须使用 `revision: 0` 和 `expectedRevision: null`；成功返回
  HTTP 201，已保存的 revision 为 1。
- 更新时，`revision` 和 `expectedRevision` 都必须等于服务器当前
  revision；成功返回 HTTP 200，revision 加一。
- 旧版本、已存在项目的重复创建，以及不一致的 revision 都返回
  HTTP 409，`detail.currentRevision` 告知当前版本；项目尚未创建时该值为 `null`。
- GET 未找到场景时返回 HTTP 404。

API 会校验节点必须是对象、字典键与 `node.id` 一致、节点包含 `type`、所有
`rootNodeIds` 均存在，并限制资产为本服务生成的 SHA-256 JPG/PNG 路径。节点内部
的 Wall、Guide 等具体字段仍以锁定版本的 Pascal Schema 为权威，避免后端复制一套
会漂移的编辑器类型。

当前图片只做 Content-Type 与文件头校验，场景 JSON 也尚未设置独立请求体上限；
生产化前需增加完整图片解码、像素上限、场景配额和流式落盘。

### 发布 GLB

- `POST /api/projects/{project_id}/artifacts/glb`
- `GET /api/projects/{project_id}/artifacts/latest`

POST 使用 multipart，字段为 `file`（`model/gltf-binary`）和 `sceneRevision`。源文件
硬上限 80 MiB，必须是长度一致的 GLB 2.0，且 revision 必须等于当前已保存场景。
接口返回 HTTP 202 与 `processing` manifest；后台完成后 latest 变为 `ready` 或
`failed`。ready manifest 记录 `pipelineVersion`、源/优化 SHA-256、字节数、节点、
网格、材质、primitive 和 15 MiB 手机预算标记。优化文件通过 `/artifacts/...` 访问。

### 风格与效果图

- `GET /api/styles`
- `GET /api/styles/{style_id}`
- `GET /api/projects/{project_id}/layout?styleId=warm-minimal`
- `POST /api/projects/{project_id}/renders`
- `GET /api/projects/{project_id}/renders/latest?styleId=warm-minimal`

POST JSON 示例：

```json
{
  "sceneRevision": 1,
  "styleId": "warm-minimal"
}
```

场景 revision 必须与 ready 的最新 GLB 一致。接口返回 HTTP 202 和 processing manifest；
后台完成后 latest 变为 ready 或 failed。ready 记录风格 id/version、PNG SHA-256、字节数、
1280×720 尺寸、Blender 版本、引擎、耗时和 `layoutId`，图片通过
`/renders/.../image.png` 访问。

layout 接口优先读取 Zone polygon，缺少 Zone 时读取 Slab polygon。可放置时返回 `ready`、
选定房间、全部候选房间和带 `roomId` 的绝对坐标；缺少闭合房间或尺寸不足时返回
`fallback` 与 `no-room-polygon`/`no-room-fits`，placements 为空。三套风格只使用本项目
原创程序化材质和家具。

## 测试

```bash
cd services/api
source .venv/bin/activate
python -m pytest
```

浏览器 GLB 导出、模型优化和 Blender 渲染将来必须通过正式任务编排执行。当前
BackgroundTasks 只验证可替换边界，不具备进程恢复、分布式锁或重试保证。
