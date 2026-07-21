# Viewer App

面向最终访客的轻量只读 3D 浏览应用。使用 Babylon.js 直接加载 API 最新的 ready
GLB manifest，不包含 Pascal、React Three Fiber、Three.js 或编辑器状态。

## 本地运行

需要 Node 22.12 或更高版本，以及运行在 `127.0.0.1:8000` 的平台 API：

```bash
npm install
npm run dev
```

访问 `http://localhost:4173/?project=<projectId>&style=warm-minimal`。开发服务器会代理 `/api`、
`/artifacts` 和 `/catalog-assets`；独立部署时用 `VITE_API_BASE_URL` 指定 API origin。

Viewer 面向客户提供全屋/鸟瞰和按实际 layout 动态生成的客厅、餐厅、卧室入口，支持鼠标与
触摸相机、全屏、加载进度、优化状态轮询、错误重试和手机安全区。页面从 `/api/styles` 读取
全部可用风格，同一个建筑 GLB 可即时替换 PBR 建筑、地面、真实家具角色材质、陈设和灯光；
切换后 URL 的 `style` 参数同步更新，可直接分享当前方案，不会重新下载建筑模型。

实时画质使用 ACES、FXAA、轻量 bloom 和软阴影，桌面使用 4× MSAA/2048 阴影，手机自动降为
1× MSAA/1024 阴影并限制像素倍率。模型、风格、layout 和目录的 project/revision/version
不一致会明确失败；单个真实模型加载失败时使用目录声明的程序化回退并显示统计，layout fallback
则保留建筑预览并提示缺失房间语义或尺寸。

```bash
npm test
npm run build
```
