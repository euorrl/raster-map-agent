# V1 Summary

中文版: [V1 总结](../v1-summary.md)

Raster Map Agent V1 is a locally runnable end-to-end controlled Raster Workflow Agent. It can convert natural-language requests into a Sentinel-2 index product generation workflow and output consistently named user-facing results.

## Implemented V1 Capabilities

Current V1 includes:

- natural-language planner;
- route decision;
- direct answer route;
- six Sentinel-2 index products;
- product registry;
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
- output cleanup, keeping only the `output/` results.

## Supported Products

Real raster preparation currently uses only Sentinel-2.

| Product | Uses |
| --- | --- |
| NDVI | Vegetation greenness, vegetation cover, crop growth |
| SAVI | Sparse vegetation and areas with strong bare-soil background |
| NDWI | Water bodies, water distribution, surface-water extraction |
| NDMI | Vegetation water content, surface moisture, drought stress |
| NDBI | Built-up areas, impervious surfaces, urban expansion |
| NBR | Burn scars, fire impact, vegetation damage |

## Workflow

```text
planner
-> route decision
-> registry if raster task
-> compiler
-> execute_tool loop
-> optional validate_tool / adjust_tool loop
-> final answer
```

Tool calls for the raster route:

```text
workspace.create_workspace
raster_prepare.prepare_raster_inputs
index_calculation.calculate_raster_index
render_preview.render_index_preview
metadata.export_metadata
answer.generate_final_answer
```

Tool call for the direct answer route:

```text
answer.generate_final_answer
```

## Outputs

All index products use the same output structure:

```text
data/
  <uuid>/
    output/
      metadata.json
      preview.png
      result.tif
```

Product type, index name, formula, data source, time range, spatial information, and quality diagnostics are written to `metadata.json`.

## Direct Answer

The direct answer route is used for:

- general knowledge questions;
- system capability questions;
- requests for currently unsupported products.

This route does not run raster tools. For unsupported tasks, the answer explains the current limitation and suggests asking about system capabilities or using one of the currently supported Sentinel-2 index products.

## V1 Limitations

These are V1 boundaries:

- Real raster preparation currently uses only Sentinel-2.
- A Sentinel-2 tile is about 100 km * 100 km.
- The current maximum number of downloadable scenes is 20; this may be lower when local memory is insufficient.
- The current version is suitable for small to medium administrative regions or urban areas. A coverage area below 100,000 square kilometers is recommended.
- Very large AOIs may cause slow downloads, slow processing, or failures.
- Administrative AOIs in coastal areas may include territorial waters. Some remote sea areas may have insufficient satellite data, making coverage and visual results less stable than inland areas.
- Logs are currently printed mainly to the terminal and are not yet persisted as `workflow_trace.json`.
- The current version runs locally and has no web frontend.
- The current version has no FastAPI backend, Redis queue, workers, job lifecycle manager, or user system.
- GEE, automatic multi-source selection, DEM, population, night lights, and land cover products are not currently available.
- This is not a production-grade GIS platform; it is a locally runnable V1 agent.

## Next Steps

V2 focuses on service deployment:

- FastAPI backend;
- Redis queue;
- worker;
- frontend;
- job status API;
- file download API;
- job lifecycle cleanup;
- CPU server deployment.

V3 will explore a GEE-based replacement toolkit for `raster_prepare`.
