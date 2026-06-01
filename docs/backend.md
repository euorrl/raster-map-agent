# Backend 服务

本文记录 V2 后端服务层的当前实现。V2 没有改变 V1 的 raster workflow、工具链、指数算法和受控执行架构；它是在 V1 workflow 外层增加服务化入口，使前端和外部调用方可以通过 job API 提交任务、查询状态并下载结果。

当前后端仍是本地 / 单机部署形态，不是生产级 GIS 平台。它适合本地演示、课程项目展示和小规模外部访问。

## 组成

V2 后端由三类服务组成：

- `api`：FastAPI 服务，提供 job 创建、状态查询、健康检查和结果文件下载接口；
- `redis`：保存 job 状态，并作为 worker 消费的任务队列；
- `worker`：从 Redis 队列取出 job，调用现有 `app.workflows.workflow.run_workflow()` 执行 raster 或 direct answer 任务。

Docker Compose 默认启动：

- 1 个 API；
- 1 个 Redis；
- 2 个 worker。

## 启动

复制并配置 `.env`：

```env
ZHIPUAI_API_KEY=
ZHIPUAI_MODEL=glm-4.7-flash
ZHIPUAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4

DATA_DIR=./data

JOB_TTL_SECONDS=1800
JOB_RUNNING_TIMEOUT_SECONDS=180

VITE_API_PROXY_TARGET=http://127.0.0.1:8000
VITE_API_BASE_URL=/api
BACKEND_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://raster-map-agent.vercel.app

REDIS_URL=redis://localhost:6379/0
```

使用 Docker Compose 启动：

```bash
docker compose up --build
```

后台启动：

```bash
docker compose up --build -d
```

停止：

```bash
docker compose down
```

## 接口

接口文档：

```text
http://127.0.0.1:8000/docs
```

当前接口：

```text
POST /jobs
GET /jobs/{job_id}
GET /jobs/{job_id}/metadata
GET /jobs/{job_id}/preview
GET /jobs/{job_id}/result
GET /health
```

`POST /jobs` 请求体：

```json
{
  "query": "帮我生成罗马 2024 年 9 月的 NDBI 图"
}
```

返回：

```json
{
  "job_id": "298f44ac24ef4989a678fbecececa4ae",
  "status": "queued"
}
```

`GET /jobs/{job_id}` 返回公开 job 状态：

```json
{
  "job_id": "298f44ac24ef4989a678fbecececa4ae",
  "status": "running",
  "stage": "workflow",
  "message": "任务仍在运行，worker 心跳正常。",
  "final_answer": "",
  "error": ""
}
```

## Job 与 Workspace

当前设计是：

```text
一次用户请求 -> 一个 job_id -> 一次 workflow 执行 -> 一个 workspace
```

Redis job 记录主要保存：

```text
status
query
created_at
updated_at
stage
message
workspace_dir
final_answer
error
```

Direct answer job 没有 raster workspace。Raster job 成功后，workspace 中保留：

```text
data/<workspace_uuid>/output/
  metadata.json
  preview.png
  result.tif
```

外部调用方只需要使用 `job_id`。API 会根据 Redis 中的 `workspace_dir` 找到文件，并通过下载接口返回：

```text
GET /jobs/{job_id}/metadata
GET /jobs/{job_id}/preview
GET /jobs/{job_id}/result
```

## 生命周期

`JOB_TTL_SECONDS` 控制 job 和 workspace 的保留时间，默认：

```env
JOB_TTL_SECONDS=1800
```

也就是 30 分钟。worker 会定期清理超过保留时间的非 running job：

- 删除 Redis 中的 `job:<job_id>`；
- 从 Redis 队列中移除残留的 `job_id`；
- 删除对应的 `data/<workspace_uuid>` workspace。

`JOB_RUNNING_TIMEOUT_SECONDS` 控制 running job 的心跳失联兜底，默认：

```env
JOB_RUNNING_TIMEOUT_SECONDS=180
```

worker 执行任务时会定期写入 `updated_at` 心跳。如果某个 running job 长时间没有心跳，另一个 worker 或重启后的 worker 会把它标记为 failed。该机制用于处理 worker 崩溃、容器重启或任务进程异常退出后的僵尸 running 状态。

它不是硬性任务运行时长限制。如果 worker 进程仍然活着并持续更新心跳，长任务仍会保持 running。

## 后端检查

查看容器状态：

```bash
docker compose ps
```

查看两个 worker 是否都在运行：

```bash
docker compose ps worker
```

查看实时资源负载：

```bash
docker stats raster-map-agent-worker-1 raster-map-agent-worker-2
```

查看一次性资源快照：

```bash
docker stats --no-stream raster-map-agent-worker-1 raster-map-agent-worker-2
```

查看 worker 日志：

```bash
docker compose logs -f worker
```

查看 Redis 队列长度：

```bash
docker compose exec -T redis redis-cli LLEN raster_jobs
```

检查某个 job：

```bash
docker compose exec -T redis redis-cli --raw GET job:<job_id>
```

健康检查：

```text
http://127.0.0.1:8000/health
```

应返回：

```json
{"status":"ok"}
```

## 运行边界

当前 V2 backend 已支持：

- Docker Compose 启动 Redis、API 和 2 个 worker；
- Redis 队列；
- job 创建、查询、状态消息和错误返回；
- worker 心跳；
- running job 心跳失联兜底；
- metadata / preview / result 下载；
- 结果文件完整但 final answer 超时时的可交付兜底；
- 30 分钟 job / workspace 清理；
- 面向 Vercel 前端的 CORS 配置。

当前仍未包含：

- 用户系统和鉴权；
- 任务取消；
- 硬性任务运行超时终止；
- 细粒度进度百分比；
- 持久化 workflow trace；
- 生产日志、监控和告警；
- 多机 worker 调度。
