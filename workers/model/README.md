# Model Worker

独立的 GLB 优化边界。FastAPI 只保存源文件和处理状态，再调用本目录的
`process-glb.mjs`；生产环境可在不改变 API manifest 的前提下替换为任务队列。

```bash
npm install
npm run process -- <source.glb> <optimized.glb>
```

命令成功时只向 stdout 输出一行 JSON 指标，诊断信息写入 stderr。输出 GLB 使用
glTF-Transform 的确定性 `optimize` 流程，当前固定版本见 `package-lock.json`。
