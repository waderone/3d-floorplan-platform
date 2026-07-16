# Style Pack Schema

装修风格是权威场景之外的版本化表现层。Web Viewer 与 Blender Worker 必须消费同一份风格包，不得把风格状态写回户型结构或 GLB artifact identity。

当前目录包含 `warm-minimal@2`、`modern-contrast@1` 和 `nordic-light@1`。材质、灯光和家具几何均由本项目原创定义，不包含第三方贴图或模型；后续外部资产进入风格包前必须补齐 `source`、`license` 和固定版本。

坐标统一为米制、右手坐标系、Y-up、XZ 为地面。风格包中的 `layout.placements` 是以原点为基准的家具外观模板，`itemId` 用于组合多个 primitive，`collisionMode` 区分实体与可重叠的地毯表面。

API 的 room-aware layout pipeline 从权威场景 Zone（或 Slab 回退）选择可容纳模板的房间，校验 `wallClearance` 和 `itemClearance`，再输出带房间引用和绝对坐标的 layout manifest。Viewer 与 Blender 只消费该 manifest 的最终 placements，不自行重新布局。
