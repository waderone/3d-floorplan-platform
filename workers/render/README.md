# Render Worker

消费已发布的优化 GLB、版本化装修风格包、API 固化的 layout manifest、
可审计资产目录与渲染档位，通过 Blender 5.x 无界面模式生成 PNG 效果图。
GLB 是权威场景的派生产物；Worker 不写回场景 JSON，也不自行重新计算家具位置。

本地技术闸门：

```bash
blender --background --factory-startup --disable-autoexec \
  --python-exit-code 1 --python render_scene.py -- \
  --input /path/model.glb \
  --style ../../packages/style-schema/styles/warm-minimal-v1.json \
  --layout /path/layout.json \
  --catalog ../../packages/asset-catalog/catalog.json \
  --render-config ../../packages/render-assets/catalog.json \
  --profile quality \
  --output-directory /tmp/floorplan-render \
  --report /tmp/floorplan-report.json
```

API 通过 `FLOORPLAN_BLENDER_BIN` 指定 Blender 可执行文件。当前本机验收版本为 Blender 5.2.0 LTS；生产环境应使用固定 Blender 5.x 镜像和独立任务队列。

家具模型来自独立 CC0 资产目录，程序化配件用于显式回退；高清档位的
HDRI/PBR 文件也由目录字节数和 SHA-256 校验。Worker 不读取 `.blend`，并使用
`--disable-autoexec` 禁止不可信文件自动执行脚本。报告会记录 profile 版本、实际设备、
总耗时与每个视角耗时；Metal 不可用时会明确记录 `CPU:fallback`。
