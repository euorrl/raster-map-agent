# V2 部署

V2 的实际部署形态是：

```text
Vercel 前端
  -> 调用公网后端地址
    -> 本地电脑 Docker backend
      -> FastAPI API
      -> Redis
      -> 2 个 worker
      -> data/<workspace_uuid>/output/
```

当前部署不是云上生产 GIS 平台。它是一个本地服务端 + 公网访问入口的展示部署方案。

## 本地服务端

本地电脑负责运行后端：

```bash
docker compose up --build
```

后端默认包含：

- `api`：`http://127.0.0.1:8000`；
- `redis`：任务队列和 job 状态；
- `worker-1`、`worker-2`：执行 workflow；
- `data/`：本地输出结果目录。

本地健康检查：

```text
http://127.0.0.1:8000/health
```

## 内网穿透

为了让 Vercel 前端访问本地后端，需要把本地 `8000` 暴露成公网地址。当前使用内网穿透方式，例如 Cloudflare Tunnel：

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

临时 tunnel 会生成类似：

```text
https://xxxx.trycloudflare.com
```

验证：

```text
https://xxxx.trycloudflare.com/health
```

应返回：

```json
{"status":"ok"}
```

临时 tunnel 的地址可能在重启后变化。地址变化后，需要同步更新 Vercel 的 `VITE_API_BASE_URL` 并重新部署前端。

长期使用建议配置固定域名和 named tunnel，例如：

```text
https://api.example.com
```

这样 Vercel 环境变量可以保持不变。电脑关机时服务不可用，但域名不需要重新配置。

## Vercel 前端

Vercel 只部署 `frontend/`。它不运行 Redis、worker 或 raster workflow。

Vercel 环境变量：

```env
VITE_API_BASE_URL=https://<backend-public-url>
```

重新部署：

```bash
cd frontend
vercel --prod
```

部署后检查：

1. 打开 Vercel 页面；
2. 点击 `API Health`；
3. 确认返回 `{"status":"ok"}`；
4. 先测试 direct answer，例如“你能做什么”；
5. 再测试小区域 raster 任务。

## CORS

由于 Vercel 前端和后端公网地址不是同一个域名，后端需要允许 Vercel origin：

```env
BACKEND_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://raster-map-agent.vercel.app
```

修改 CORS 后需要重启后端：

```bash
docker compose down
docker compose up --build
```

## 部署检查清单

本地后端：

```text
http://127.0.0.1:8000/health
```

公网后端：

```text
https://<backend-public-url>/health
```

Vercel 环境变量：

```text
VITE_API_BASE_URL=https://<backend-public-url>
```

Docker 状态：

```bash
docker compose ps
```

worker 负载：

```bash
docker stats --no-stream raster-map-agent-worker-1 raster-map-agent-worker-2
```

worker 日志：

```bash
docker compose logs -f worker
```

Redis 队列：

```bash
docker compose exec -T redis redis-cli LLEN raster_jobs
```

## 已知边界

- 本地电脑关机后，公网后端不可用；
- 临时内网穿透地址可能变化；
- Vercel 修改环境变量后必须重新部署；
- 当前没有用户系统和鉴权；
- 当前没有生产级日志、监控和告警；
- 当前没有多机 worker 调度；
- 当前不是生产级 GIS 平台。
