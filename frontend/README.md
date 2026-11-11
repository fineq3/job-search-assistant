# 招聘信息助手前端

Vue 3 + TypeScript + Vite。布局沿用上游页面，业务交互迁移至 Vue 响应式状态。

在项目根目录运行 `npm.cmd --prefix frontend ci` 安装依赖。

- 开发：`npm.cmd --prefix frontend run dev`。同时启动 8000 端口的 FastAPI，Vite 将 `/api` 代理给后端。
- 检查和构建：`npm.cmd --prefix frontend run build`。包括 TypeScript 检查，生成 `frontend/dist`。
- 演示：构建后启动 FastAPI，直接访问 `http://127.0.0.1:8000/`。无需另开 Vite。

`src/App.vue` 管理上传、问答、来源展开、岗位卡片和清空确认。批量上传逐份请求，单份失败不影响后续文件。刷新页面会重新读取知识库，但聊天历史不会保存。

浏览器调用同源 `/api`，不保存 DeepSeek 密钥。密钥仅在后端 `.env` 中配置。

完整说明见[项目 README](../README.md)。
