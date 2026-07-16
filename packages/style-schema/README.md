# Style Pack Schema

装修风格是权威场景之外的版本化表现层。Web Viewer 与 Blender Worker 必须消费同一份风格包，不得把风格状态写回户型结构或 GLB artifact identity。

首个技术闸门只包含 `warm-minimal@1`。其中材质、灯光和家具几何均由本项目原创定义，不包含第三方贴图或模型；后续外部资产进入风格包前必须补齐 `source`、`license` 和固定版本。

坐标统一为米制、右手坐标系、Y-up、XZ 为地面。`layout.placements[].position` 相对模型水平中心和地面顶面，表示物体中心点。
