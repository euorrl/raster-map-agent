# Raster Toolchain

中文版: [栅格工具链](../raster-toolchain.md)

This document describes the inputs, outputs, and boundaries of the current V1 real raster toolchain. The real V1 execution pipeline is based on Sentinel-2.

## Overall Flow

In the raster route, the compiler generates the following controlled tool chain:

```text
workspace.create_workspace
-> raster_prepare.prepare_raster_inputs
-> index_calculation.calculate_raster_index
-> render_preview.render_index_preview
-> metadata.export_metadata
-> answer.generate_final_answer
```

The executor executes one tool call at a time. After each tool finishes, if the tool call has a rule, the workflow enters validator / adjuster. Currently, only `raster_prepare` has a tool rule.

## Workspace

Each time the agent generates a raster product, the workflow first calls:

```python
workspace.create_workspace
```

It creates a UUID workspace under `data/`. Processing may produce:

- AOI files;
- downloaded rasters;
- mosaic rasters;
- clipped rasters;
- output results.

V1 currently uses a local workspace lifecycle. The workflow cleans up intermediate files and directories. Final user-facing results keep only:

```text
data/
  <uuid>/
    output/
      metadata.json
      preview.png
      result.tif
```

V2 plans to further introduce a job lifecycle manager. A deployed version can retain output for a period, such as 30 minutes, and then automatically delete the entire job workspace.

## Raster Prepare

`raster_prepare.prepare_raster_inputs` is the data preparation entry. It is responsible for:

1. parsing the AOI;
2. querying STAC;
3. selecting Sentinel-2 scenes that cover the AOI;
4. downloading required bands;
5. mosaicking;
6. clipping to the AOI;
7. returning band paths and diagnostics;
8. deleting AOI, downloaded imagery, and mosaic intermediate directories.

Typical input from a compiler-generated tool call:

```python
{
  "aoi_query": "Chengdu, Sichuan, China",
  "index_name": "NDVI",
  "data_source": "sentinel2",
  "start_date": "2024-06-01",
  "end_date": "2024-08-31",
  "max_cloud_cover": 20,
  "workspace_dir": "$state.workspace.workspace_dir"
}
```

Typical output includes:

- `workspace_dir`
- `output_dir`
- `boundary_geojson_path`
- `index_name`
- `data_source`
- `provider`
- `collection`
- `required_bands`
- `band_roles`
- `index_formula`
- `band_paths`
- `scene_ids`
- `diagnostics`

### Scene Plan

The scene plan used for selecting Sentinel-2 scenes that cover the AOI includes an internal scene coverage check. If coverage fails, the tool short-circuits before download, returns diagnostics, and deletes generated AOI intermediate directories.

Scene plan uses STAC metadata for scene selection and does not download imagery directly.

The current strategy is coverage-aware greedy selection:

- first filter by cloud cover and required assets;
- select scenes by their additional contribution to uncovered AOI area;
- when contribution is close, prefer scenes with lower cloud cover;
- output coverage diagnostics for validator / adjuster.

A Sentinel-2 tile covers about 100 km * 100 km. Considering raster data download time, processing time, and runtime memory limits, the maximum number of downloadable scenes is 20. When local memory is insufficient, the actual processable count may be lower. The current version is therefore suitable for small to medium administrative regions or urban areas, with a recommended coverage area below 100,000 square kilometers.

## Validator / Adjuster

Currently, only `raster_prepare` has a tool rule.

The validator checks:

- whether the raster prepare result exists;
- whether required bands can be resolved;
- whether diagnostics exist;
- whether coverage passes;
- whether required band paths exist.

If diagnostics indicate that the issue can be fixed, the validator returns `retryable`. The adjuster can update the corresponding tool call params and retry. The maximum retry count is 5.

The adjuster does not modify `state.plan`. It only modifies `tool_calls[last_tool_index].params` and sets `runtime.current_tool_index` back to `raster_prepare`.

## Index Calculation

`index_calculation.calculate_raster_index` reads clipped bands and calculates the index according to band roles and formulas passed from the registry.

The output is always:

```text
data/<uuid>/output/result.tif
```

After calculation, the tool deletes the `clipped_raster/` intermediate directory. Final user results do not retain clipped rasters.

Currently supported Sentinel-2 indices:

| Index | Formula Meaning | Sentinel-2 Bands |
| --- | --- | --- |
| NDVI | `(nir - red) / (nir + red)` | B08, B04 |
| SAVI | `1.5 * (nir - red) / (nir + red + 0.5)` | B08, B04 |
| NDWI | `(green - nir) / (green + nir)` | B03, B08 |
| NDMI | `(nir - swir) / (nir + swir)` | B08, B11 |
| NDBI | `(swir - nir) / (swir + nir)` | B11, B08 |
| NBR | `(nir - swir2) / (nir + swir2)` | B08, B12 |

## Render Preview

`render_preview.render_index_preview` renders a PNG preview according to the render config in the registry.

The output is always:

```text
data/<uuid>/output/preview.png
```

The preview uses the index-specific colormap and keeps nodata areas transparent.

## Metadata Export

`metadata.export_metadata` extracts concise product information for users and result provenance from a workflow state snapshot. It is not a full `AgentState` dump.

Information sources include:

- `state.plan`
- `runtime["registry"]["raster_product"]`
- `tool_results`
- `raster_prepare` diagnostics
- validator results
- final GeoTIFF profile

The output is always:

```text
data/<uuid>/output/metadata.json
```

Example:

```json
{
  "area": {
    "aoi_query": "Chengdu, Sichuan, China"
  },
  "product": {
    "family": "raster",
    "method": {
      "formula": "(nir - red) / (nir + red)",
      "name": "index_formula"
    },
    "name": "NDVI",
    "type": "index"
  },
  "quality": {
    "coverage_ratio": 1,
    "coverage_status": "covered",
    "min_coverage_ratio": 0.7,
    "raster_prepare_validation_status": "passed",
    "selected_scene_count": 1
  },
  "source": {
    "data_source": "sentinel2",
    "provider": "earth_search"
  },
  "spatial": {
    "bounds": {
      "bottom": 30.0,
      "left": 103.0,
      "right": 104.0,
      "top": 31.0
    },
    "crs": "EPSG:32648",
    "height": 1024,
    "resolution": {
      "unit": "metre",
      "x": 10.0,
      "y": 10.0
    },
    "resolution_meters": 10.0,
    "width": 1024
  },
  "time_range": {
    "end_date": "2024-08-31",
    "max_cloud_cover": 20,
    "start_date": "2024-06-01"
  }
}
```

Actual output automatically omits empty sections according to available fields.

## Final Answer

`answer.generate_final_answer` is responsible for the final user-facing answer.

- Raster route: summarizes the result based on metadata product info.
- Direct answer route: answers general questions, system capability questions, or unsupported product requests.
- If the task fails, the answer explains the failed stage, known cause, and possible adjustments.

## Current Boundaries

- V1 executes only Sentinel-2 in the real pipeline.
- Landsat exists in the registry, but `raster_prepare` is not connected to it.
- DEM, population, night lights, land cover, GEE, and automatic multi-source selection are future work.
- The current version is suitable for small to medium AOIs, with a recommended area below 100,000 square kilometers.
- Very large, coastal, or complex MultiPolygon AOIs may cause slow downloads, insufficient coverage, or unstable visual results.
