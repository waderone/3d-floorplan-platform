# Viewer App

面向最终访客的轻量只读 3D 浏览应用。使用 Babylon.js 直接加载 API 最新的 ready
GLB manifest，不包含 Pascal、React Three Fiber、Three.js 或编辑器状态。

## 本地运行

需要 Node 22.12 或更高版本，以及运行在 `127.0.0.1:8000` 的平台 API：

```bash
npm install
npm run dev
```

访问 `http://localhost:4173/` 可上传户型图并自动跳转到生成后的实时 3D；已有项目也可直接访问
`http://localhost:4173/?project=<projectId>&style=warm-minimal`。开发服务器会代理 `/api`、
`/artifacts` 和 `/catalog-assets`；独立部署时用 `VITE_API_BASE_URL` 指定 API origin。

Viewer 面向客户提供全屋/鸟瞰和按实际 layout 动态生成的客厅、餐厅、卧室入口，支持鼠标与
触摸相机、全屏、加载进度、优化状态轮询、错误重试和手机安全区。页面从 `/api/styles` 读取
全部可用风格，同一个建筑 GLB 可即时替换 PBR 建筑、地面、真实家具角色材质、陈设和灯光；
切换后 URL 的 `style` 参数同步更新，可直接分享当前方案，不会重新下载建筑模型。

资产目录 v3 为真实模型声明 `replace`、`tint` 或 `preserve`。其中 `tint` 会保留 glTF 内嵌
的 base color、AO/rough/metal 与法线纹理，只将风格角色色作为乘算色；`preserve` 用于玻璃、
金属等不应被整件刷色的灯具和项目原创现代软包床。实例尺寸可由受校验 recipe 覆盖，Viewer
与 Blender 使用同一结果。

layout v3 从 Pascal 权威 Door/Window 派生门扇开启区和窗边接近区。家具只在通过边界、互碰
和开口净空后发布；页面显示门窗数量和阻断状态，并提供默认关闭的 `⌗` 动线检查层。曲墙或
宿主不完整的开口会显式计入 ignored，不由 Viewer 猜测。

实时画质使用 ACES、FXAA、轻量 bloom 和软阴影，桌面使用 4× MSAA/2048 阴影，手机自动降为
1× MSAA/1024 阴影并限制像素倍率。模型、风格、layout 和目录的 project/revision/version
不一致会明确失败；单个真实模型加载失败时使用目录声明的程序化回退并显示统计，layout fallback
则保留建筑预览并提示缺失房间语义或尺寸。

Viewer 与场景/风格契约统一使用米制、右手坐标、Y-up、XZ 地面。Babylon Scene 显式启用
右手坐标，避免 glTF Loader 在左手模式下增加根节点翻转后造成结构与布局家具错位。多个语义
墙节点可以共享同一 glTF mesh，Viewer 显式加载 Babylon `InstancedMesh` 支持模块。

```bash
npm test
npm run build
```
