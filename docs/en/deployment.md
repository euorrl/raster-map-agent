# V2 Deployment

中文版: [V2 部署](../deployment.md)

The actual V2 deployment shape is:

```text
Vercel frontend
  -> calls public backend URL
    -> local machine Docker backend
      -> FastAPI API
      -> Redis
      -> 2 workers
      -> data/<workspace_uuid>/output/
```

The current deployment is not a cloud production GIS platform. It is a demo deployment solution with a local server and a public access entry.

## Local Server

The local machine runs the backend:

```bash
docker compose up --build
```

The backend includes by default:

- `api`: `http://127.0.0.1:8000`;
- `redis`: task queue and job status storage;
- `worker-1`, `worker-2`: workflow execution;
- `data/`: local output result directory.

Local health check:

```text
http://127.0.0.1:8000/health
```

## Intranet Tunnel

To let the Vercel frontend access the local backend, expose local port `8000` as a public URL. The current setup uses an intranet tunnel, such as Cloudflare Tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

A temporary tunnel generates a URL like:

```text
https://xxxx.trycloudflare.com
```

Verify:

```text
https://xxxx.trycloudflare.com/health
```

Expected response:

```json
{"status":"ok"}
```

Temporary tunnel URLs may change after restart. When the address changes, update Vercel `VITE_API_BASE_URL` and redeploy the frontend.

For long-term use, configure a fixed domain and named tunnel, for example:

```text
https://api.example.com
```

This keeps the Vercel environment variable stable. The service is unavailable when the local machine is powered off, but the domain does not need to be reconfigured.

## Vercel Frontend

Vercel deploys only `frontend/`. It does not run Redis, workers, or the raster workflow.

Vercel environment variable:

```env
VITE_API_BASE_URL=https://<backend-public-url>
```

Redeploy:

```bash
cd frontend
vercel --prod
```

After deployment:

1. Open the Vercel page.
2. Click `API Health`.
3. Confirm it returns `{"status":"ok"}`.
4. Test a direct answer first, for example "What can you do?"
5. Then test a small-area raster task.

## CORS

Because the Vercel frontend and public backend URL are not the same domain, the backend needs to allow the Vercel origin:

```env
BACKEND_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://raster-map-agent.vercel.app
```

After modifying CORS, restart the backend:

```bash
docker compose down
docker compose up --build
```

## Deployment Checklist

Local backend:

```text
http://127.0.0.1:8000/health
```

Public backend:

```text
https://<backend-public-url>/health
```

Vercel environment variable:

```text
VITE_API_BASE_URL=https://<backend-public-url>
```

Docker status:

```bash
docker compose ps
```

Worker load:

```bash
docker stats --no-stream raster-map-agent-worker-1 raster-map-agent-worker-2
```

Worker logs:

```bash
docker compose logs -f worker
```

Redis queue:

```bash
docker compose exec -T redis redis-cli LLEN raster_jobs
```

## Known Boundaries

- The public backend is unavailable when the local machine is powered off.
- Temporary intranet tunnel URLs may change.
- Vercel must be redeployed after environment variable changes.
- There is currently no user system or authentication.
- There are currently no production-grade logs, monitoring, or alerts.
- There is currently no multi-machine worker scheduling.
- This is not a production-grade GIS platform.
