# Frontend 前端

V2 已加入一个最小可用的 Vue 前端，用于把自然语言请求提交给后端，并展示 job 状态、最终回答、预览图和下载入口。

前端不包含 raster 业务逻辑。它只负责：

- 输入自然语言请求；
- 调用 `POST /jobs` 创建任务；
- 轮询 `GET /jobs/{job_id}`；
- 展示 queued / running / succeeded / failed 状态；
- 展示后端返回的 `message`、`final_answer` 和 `error`；
- 展示 `preview.png`；
- 下载 `metadata.json`、`preview.png` 和 `result.tif`；
- 通过 `API Health` 检查当前配置的后端地址。

## 技术栈

当前前端位于 `frontend/`：

```text
frontend/
  src/
    App.vue
    api.ts
    styles.css
    types.ts
  package.json
  vite.config.ts
```

技术栈：

- Vue 3；
- Vite；
- TypeScript；

## 本地运行

先启动后端：

```bash
docker compose up --build
```

再启动前端：

```bash
cd frontend
npm run dev
```

访问：

```text
http://127.0.0.1:5173
```

本地开发时，前端默认请求 `/api`，由 Vite proxy 转发到：

```text
http://127.0.0.1:8000
```

对应配置：

```env
VITE_API_PROXY_TARGET=http://127.0.0.1:8000
VITE_API_BASE_URL=/api
```

## 线上前端

V2 当前前端部署在 Vercel。线上构建时需要配置：

```env
VITE_API_BASE_URL=https://<backend-public-url>
```

该地址是后端的公网入口。当前项目采用：

```text
本地 Docker 后端 -> 内网穿透公网地址 -> Vercel 前端
```

注意：`VITE_API_BASE_URL` 是构建时变量。修改 Vercel 环境变量后，必须重新部署前端。

```bash
cd frontend
vercel --prod
```

## API Health

前端右上角的 `API Health` 使用与任务请求相同的后端地址：

```text
<VITE_API_BASE_URL>/health
```

如果该按钮不能返回：

```json
{"status":"ok"}
```

则说明前端当前无法访问后端。常见原因包括：

- Vercel 没有重新部署，仍在使用旧的 `VITE_API_BASE_URL`；
- 内网穿透地址已经变化或断开；
- 后端 Docker 服务没有启动；
- 后端 CORS 没有允许当前 Vercel 域名；

## 运行边界

当前前端是 V2 展示层，不包含：

- 用户登录；
- 多会话管理；
- 历史任务列表；
- 任务取消按钮；
- 百分比进度条；
- 地图交互浏览器；
- 生产级错误分析面板。

这些能力可以在后续服务化阶段继续扩展。
