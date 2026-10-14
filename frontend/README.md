# Frontend

这是项目的 Vue 3 + Vite 前端，提供会话、聊天、知识库、来源和 Agent 执行轨迹界面。

本地开发：

```powershell
npm install
npm run dev
```

Vite 会把 `/api` 代理到 `http://localhost:8001`。Docker 模式下由 Nginx 提供静态文件并把 `/api` 转发给 `api:8001`。
