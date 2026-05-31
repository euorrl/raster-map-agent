# Backend 服务

当前项目包含一个最小可用的后端服务层，用于把本地 workflow 包装成可提交、可排队、可查询、可下载结果的 job。

该后端仍是本地 / 单机部署形态，不是生产级 GIS 平台。它的目标是为后续前端和服务器部署提供稳定的接口边界。

## 组成

后端由三类服务组成：

- `api`：FastAPI 服务，提供 job 创建、状态查询和文件下载接口；
- `redis`：保存 job 状态，并作为 worker 消费的任务队列；
- `worker`：从 Redis 队列取出 job，调用现有 workflow 执行 raster 或 direct answer 任务。

Docker Compose 默认启动 1 个 API、1 个 Redis 和 2 个 worker。

## 启动

复制并配置 `.env`：

```env
ZHIPUAI_API_KEY=
ZHIPUAI_MODEL=glm-4.7-flash
ZHIPUAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
DATA_DIR=./data
JOB_TTL_SECONDS=1800
```

启动：

```bash
docker compose up --build
```

后台启动：

```bash
docker compose up --build -d
```

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f
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

`POST /jobs` 的请求体：

```json
{
  "query": "帮我生成罗马2024年9月的NDBI图"
}
```

返回：

```json
{
  "job_id": "298f44ac24ef4989a678fbecececa4ae",
  "status": "queued"
}
```

前端或调用方使用 `job_id` 查询状态和下载文件。外部调用方不需要直接访问 workspace 路径。

## Job 与 Workspace

当前设计是：

```text
一次用户请求 -> 一个 job_id -> 一个 workflow 执行 -> 一个 workspace
```

Redis job 记录保存：

```text
status
query
created_at
workspace_dir
final_answer
error
```

Direct answer job 可能没有 raster workspace。Raster job 成功后，workspace 中保留：

```text
data/<workspace_uuid>/output/
  metadata.json
  preview.png
  result.tif
```

API 通过 Redis 中的 `workspace_dir` 找到文件，并通过以下接口返回：

```text
GET /jobs/{job_id}/metadata
GET /jobs/{job_id}/preview
GET /jobs/{job_id}/result
```

## 生命周期

`JOB_TTL_SECONDS` 控制 job 保留时间，默认：

```env
JOB_TTL_SECONDS=1800
```

也就是 30 分钟。worker 会定期清理超过保留时间的 job：

- 删除 Redis 中的 `job:<job_id>`；
- 从 Redis 队列中移除残留的 `job_id`；
- 删除对应的 `data/<workspace_uuid>` workspace。

正在 `running` 的 job 不会被清理，避免任务执行时删除正在写入的文件。

## 运行边界

当前 backend 已支持：

- Docker Compose 启动 Redis、API 和 worker；
- Redis 队列；
- 2 个 worker 并发消费任务；
- job 状态查询；
- metadata / preview / result 下载；
- 结果文件完整但 final answer 超时时的可交付兜底；
- 30 分钟 job / workspace 清理。

当前尚未包含：

- Web 前端；
- 用户系统和鉴权；
- 任务取消；
- 细粒度进度百分比；
- 持久化 workflow trace；
- 生产日志、监控和告警；
- 多机 worker 调度。
