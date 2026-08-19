# Roadmap

中文版: [路线图](../roadmap.md)

This document records the current stage and future directions.

- V1 has completed the local end-to-end feature loop.
- V2 has completed local service deployment, frontend presentation, and external access through an intranet tunnel.

## V1 Completed

Current V1 includes:

- natural-language planner;
- route decision;
- direct answer route;
- six Sentinel-2 index products;
- product registry;
- tool rules;
- route templates;
- compiler;
- executor;
- single-step tool execution;
- `raster_prepare` validator / adjuster retry loop;
- workspace creation;
- raster preparation;
- index calculation;
- preview rendering;
- metadata export;
- final answer generation;
- terminal logging;
- output cleanup, keeping only `output/` results.

V1 supports these Sentinel-2 indices:

- NDVI;
- SAVI;
- NDWI;
- NDMI;
- NDBI;
- NBR.

V1 output:

```text
data/<uuid>/output/
  metadata.json
  preview.png
  result.tif
```

## V2 Completed

V2 focuses on service deployment, frontend, and deployment presentation without changing the V1 raster workflow, tool chain, algorithms, or architecture.

Current V2 includes:

- FastAPI backend;
- Redis queue;
- 2 workers by default;
- Docker Compose local backend deployment;
- `POST /jobs` to create tasks;
- `GET /jobs/{job_id}` to query status;
- `GET /jobs/{job_id}/metadata` to download metadata;
- `GET /jobs/{job_id}/preview` to download previews;
- `GET /jobs/{job_id}/result` to download GeoTIFF;
- `GET /health` health check;
- job `stage` / `message` status fields;
- worker heartbeat;
- fallback handling for stale running-job heartbeats;
- 30-minute job / workspace lifecycle cleanup;
- Vue / Vite / TypeScript frontend;
- frontend task submission, status polling, answer display, preview display, and result downloads;
- Vercel frontend deployment;
- public access to the local machine backend through an intranet tunnel;
- Vercel frontend calls to the public backend through `VITE_API_BASE_URL`.

Current V2 deployment shape:

```text
Vercel frontend
  -> backend public URL from tunnel
    -> local Docker backend
      -> FastAPI / Redis / workers
```

## V2 Boundaries

Current V2 is still not a production-grade GIS platform. Known boundaries:

- the backend is unavailable when the local machine is powered off;
- temporary intranet tunnel URLs may change;
- Vercel must be redeployed after environment variable changes;
- there is currently no user system or authentication;
- there is currently no task cancellation;
- there is currently no hard task runtime termination;
- there is currently no fine-grained percentage progress;
- there is currently no persisted workflow trace;
- there are currently no production logs, monitoring, or alerts;
- there is currently no multi-machine worker scheduling.

## Future Directions

Future service-oriented work may include:

- fixed domain and named tunnel;
- backend deployment on a stable CPU server;
- more complete job status / progress API;
- task cancellation;
- persisted logs and workflow trace;
- monitoring, alerts, and error tracking;
- user system and authentication;
- multi-machine worker scheduling;
- file retention policy and download permission control.

## V3 / Future Research

V3 or future research can explore a stronger GEE-based replacement toolkit for `raster_prepare`, supporting:

- global scale-aware source selection;
- thematic products such as DEM / population / night lights / land cover;
- simple external interfaces;
- a more complete registry;
- complex remote-sensing data processing across multiple routes.
