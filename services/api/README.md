# API Service

项目、场景版本、资产和任务 API。

计划采用 FastAPI。GPU 识别、模型导出和 Blender 渲染必须通过任务队列执行，不在 HTTP 请求进程中运行。
