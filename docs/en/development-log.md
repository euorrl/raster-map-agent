# Development Log

中文版: [开发日志](../development-log.md)

This document records the project's evolution from the engineering skeleton to V1 closure. The current code has reached the V1 completion and documentation alignment stage.

## Stage 1: Engineering Skeleton

Completed:

- Python project structure;
- `app/`, `docs/`, `scripts/`, `tests/`, `data/`;
- basic tests, linting, and MkDocs configuration;
- local `data/` as a runtime artifact directory excluded from git.

## Stage 2: AgentState and Workflow Skeleton

Completed:

- `AgentState`;
- workflow runner;
- node boundaries for planner / registry / executor and related components;
- linear fallback runner when LangGraph is unavailable.

The focus was validating whether state can flow stably between nodes and whether workflow order can be tested.

## Stage 3: Registry and Product Capabilities

Completed:

- Sentinel-2 data source configuration;
- Landsat registry-only configuration;
- 6 index product configurations: NDVI, SAVI, NDWI, NDMI, NDBI, NBR;
- band roles, index formulas, and render configs.

Real `raster_prepare` currently uses only Sentinel-2.

## Stage 4: Real Raster Prepare Toolchain

Completed:

- AOI parsing;
- STAC scene plan;
- coverage-aware greedy scene selection;
- Sentinel-2 asset download;
- mosaic;
- AOI clip;
- coverage diagnostics;
- intermediate directory cleanup.

If scene coverage does not meet the requirement, `raster_prepare` short-circuits before download and returns diagnostics.

## Stage 5: Workspace

Completed:

- `workspace.create_workspace`;
- create `data/<uuid>/` for each task;
- share `workspace_dir` across later tools.

Final user-facing results are kept consistently in:

```text
data/<uuid>/output/
  metadata.json
  preview.png
  result.tif
```

## Stage 6: Index Calculation

Completed:

- `index_calculation.calculate_raster_index`;
- restricted AST execution for index formulas;
- nodata mask;
- band alignment;
- output `output/result.tif`;
- delete `clipped_raster/` after consuming clipped bands.

## Stage 7: Preview Rendering

Completed:

- `render_preview.render_index_preview`;
- registry-driven colormap;
- transparent nodata;
- optional colorbar;
- output `output/preview.png`.

## Stage 8: Metadata Export

Completed:

- `metadata.export_metadata`;
- extract concise product information from workflow state snapshots;
- read final GeoTIFF profile;
- output `output/metadata.json`;
- metadata is no longer a full `AgentState` dump.

## Stage 9: Planner and Direct Answer

Completed:

- natural-language planner;
- route decision;
- `raster_product_generate`;
- `direct_answer`;
- system capability answers;
- unsupported product requests no longer force raster workflow execution.

Current `direct_answer` is used for general questions, system capability questions, and unsupported product requests.

## Stage 10: Compiler / Executor

Completed:

- `ToolCall` schema;
- compiler generates tool calls from plan, registry, and workflow template;
- executor executes tool calls one step at a time;
- `$state...` reference resolution;
- dependency checks;
- write-back to workspace, tool_results, and final_answer;
- `runtime.current_tool_index` controls execution progress.

Current raster route toolchain:

```text
workspace.create_workspace
raster_prepare.prepare_raster_inputs
index_calculation.calculate_raster_index
render_preview.render_index_preview
metadata.export_metadata
answer.generate_final_answer
```

## Stage 11: Validator / Adjuster

Completed:

- `raster_prepare` validator;
- `raster_prepare` adjuster;
- retry runtime records;
- maximum retry count of 5;
- adjuster modifies tool call params, not `state.plan`.

The current validator mainly checks coverage, required bands, diagnostics, and band paths.

## Stage 12: Nodes Design and LangGraph Nodes Graph

Completed:

- general minimal node design;
- general LangGraph nodes graph construction;
- nodes graph construction without LangGraph.

## Stage 13: V1 Closure

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
- output cleanup, keeping only output results.

Current stage:

- V1 is complete.
- Documentation is aligned.

## Stage 14: Minimal Backend Service Layer

Current backend includes:

- FastAPI backend;
- Redis queue;
- worker;
- Docker Compose startup;
- 2 workers by default;
- `POST /jobs` to create tasks;
- `GET /jobs/{job_id}` to query status;
- `GET /jobs/{job_id}/metadata` to download metadata;
- `GET /jobs/{job_id}/preview` to download preview;
- `GET /jobs/{job_id}/result` to download GeoTIFF;
- `GET /health` health check;
- job creation timestamp;
- 30-minute job / workspace lifecycle cleanup;
- deliverable fallback when result files are complete but final answer times out.

The current backend remains minimal and does not include a user system, authentication, task cancellation, fine-grained percentage progress, persisted workflow trace, production logs, or monitoring.

## Stage 15: V2 Frontend and Local Deployment Demo

Current V2 has completed the frontend and deployment demo loop:

- Vue / Vite / TypeScript frontend;
- natural-language request input;
- `POST /jobs` to create tasks;
- `GET /jobs/{job_id}` to poll task status;
- display queued / running / succeeded / failed status;
- display backend `message`, `final_answer`, and `error`;
- display `preview.png`;
- download `metadata.json`, `preview.png`, and `result.tif`;
- `API Health` uses the configured backend address;
- Vercel frontend deployment;
- public access to the local Docker backend through an intranet tunnel;
- backend CORS allows the Vercel frontend;
- Vercel configures the public backend URL through `VITE_API_BASE_URL`;
- the V2 frontend and local deployment demo loop is complete.

Current deployment shape:

```text
Vercel frontend
  -> intranet tunnel public URL
    -> local machine Docker backend
      -> FastAPI / Redis / workers
```

This stage keeps the V1 workflow unchanged and only adds service, frontend, and deployment entries around it.

V3 / future research may explore a GEE-based replacement toolkit for `raster_prepare`, enabling global scale-aware source selection and more thematic products.
