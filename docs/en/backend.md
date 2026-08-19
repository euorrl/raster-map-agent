# Backend Service

中文版: [Backend 服务](../backend.md)

This document records the current V2 backend service layer. V2 does not change the V1 raster workflow, tool chain, index algorithms, or controlled execution architecture. It adds a service entry around the V1 workflow so the frontend and external callers can submit tasks, query status, and download results through the job API.

The current backend is still a local / single-machine deployment, not a production-grade GIS platform. It is suitable for local demos, course project presentations, and small-scale external access.

## Components

The V2 backend consists of three service types:

- `api`: FastAPI service that provides job creation, status query, health check, and result file download endpoints;
- `redis`: stores job status and acts as the task queue consumed by workers;
- `worker`: pulls jobs from the Redis queue and calls the existing `app.workflows.workflow.run_workflow()` to execute raster or direct answer tasks.

Docker Compose starts by default:

- 1 API service;
- 1 Redis service;
- 2 workers.

## Startup

Copy and configure `.env`:

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

Start with Docker Compose:

```bash
docker compose up --build
```

Start in the background:

```bash
docker compose up --build -d
```

Stop:

```bash
docker compose down
```

## API

API documentation:

```text
http://127.0.0.1:8000/docs
```

Current endpoints:

```text
POST /jobs
GET /jobs/{job_id}
GET /jobs/{job_id}/metadata
GET /jobs/{job_id}/preview
GET /jobs/{job_id}/result
GET /health
```

`POST /jobs` request body:

```json
{
  "query": "Generate an NDBI map for Rome in September 2024"
}
```

Response:

```json
{
  "job_id": "298f44ac24ef4989a678fbecececa4ae",
  "status": "queued"
}
```

`GET /jobs/{job_id}` returns public job status:

```json
{
  "job_id": "298f44ac24ef4989a678fbecececa4ae",
  "status": "running",
  "stage": "workflow",
  "message": "The task is still running and the worker heartbeat is healthy.",
  "final_answer": "",
  "error": ""
}
```

## Job and Workspace

The current design is:

```text
one user request -> one job_id -> one workflow execution -> one workspace
```

Redis job records mainly store:

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

Direct answer jobs do not have a raster workspace. After a raster job succeeds, the workspace keeps:

```text
data/<workspace_uuid>/output/
  metadata.json
  preview.png
  result.tif
```

External callers only need to use `job_id`. The API finds files through `workspace_dir` stored in Redis and returns them through:

```text
GET /jobs/{job_id}/metadata
GET /jobs/{job_id}/preview
GET /jobs/{job_id}/result
```

## Lifecycle

`JOB_TTL_SECONDS` controls how long jobs and workspaces are retained. Default:

```env
JOB_TTL_SECONDS=1800
```

This means 30 minutes. Workers periodically clean up non-running jobs that exceed the retention time:

- delete `job:<job_id>` from Redis;
- remove residual `job_id` entries from the Redis queue;
- delete the corresponding `data/<workspace_uuid>` workspace.

`JOB_RUNNING_TIMEOUT_SECONDS` controls fallback handling for running jobs with stale heartbeats. Default:

```env
JOB_RUNNING_TIMEOUT_SECONDS=180
```

Workers periodically write an `updated_at` heartbeat while executing tasks. If a running job has no heartbeat for a long time, another worker or a restarted worker marks it as failed. This mechanism handles zombie running states after worker crashes, container restarts, or abnormal task process exits.

It is not a hard task runtime limit. If the worker process is still alive and continues updating heartbeats, long tasks remain running.

## Backend Checks

View container status:

```bash
docker compose ps
```

Check whether both workers are running:

```bash
docker compose ps worker
```

View real-time resource load:

```bash
docker stats raster-map-agent-worker-1 raster-map-agent-worker-2
```

View a one-time resource snapshot:

```bash
docker stats --no-stream raster-map-agent-worker-1 raster-map-agent-worker-2
```

View worker logs:

```bash
docker compose logs -f worker
```

View Redis queue length:

```bash
docker compose exec -T redis redis-cli LLEN raster_jobs
```

Inspect a job:

```bash
docker compose exec -T redis redis-cli --raw GET job:<job_id>
```

Health check:

```text
http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## Runtime Boundaries

The current V2 backend supports:

- Docker Compose startup for Redis, API, and 2 workers;
- Redis queue;
- job creation, query, status messages, and error responses;
- worker heartbeat;
- fallback handling for stale running-job heartbeats;
- metadata / preview / result downloads;
- deliverable fallback when result files are complete but final answer times out;
- 30-minute job / workspace cleanup;
- CORS configuration for the Vercel frontend.

It still does not include:

- user system and authentication;
- task cancellation;
- hard task runtime termination;
- fine-grained percentage progress;
- persisted workflow trace;
- production logs, monitoring, and alerts;
- multi-machine worker scheduling.
