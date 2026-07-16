# Viewer App

面向最终访客的轻量只读 3D 浏览应用。使用 Babylon.js 直接加载 API 最新的 ready
GLB manifest，不包含 Pascal、React Three Fiber、Three.js 或编辑器状态。

## 本地运行

需要 Node 22.12 或更高版本，以及运行在 `127.0.0.1:8000` 的平台 API：

```bash
npm install
npm run dev
```

访问 `http://localhost:4173/?project=<projectId>&style=warm-minimal`。开发服务器会代理 `/api` 和
`/artifacts`；独立部署时用 `VITE_API_BASE_URL` 指定 API origin。

Viewer 支持 3D/俯视/复位、鼠标与触摸相机、全屏、加载进度、优化状态轮询、错误
重试和手机安全区。它会从 API 读取同一版本化风格包，在 GLB 上应用 PBR 建筑/地面材质、
环境灯光和相机，并读取同一资产目录与 layout manifest，按房间绝对坐标加载客厅、餐厅、
卧室真实 GLB 家具。模型、风格、layout 和目录的 project/revision/version 不一致会明确失败；
单个模型加载失败时使用目录声明的程序化回退并显示统计，layout fallback 则保留建筑预览并
提示缺失的房间语义或尺寸。生产构建运行 `npm run build`。
