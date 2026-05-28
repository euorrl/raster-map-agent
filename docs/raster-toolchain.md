# 栅格工具链

本文记录当前真实工具链的输入输出、职责边界和扩展点。

## 总体流程

当前真实工具链：

```text
create_workspace
-> prepare_raster_inputs
   -> resolve_administrative_aoi
   -> build_raster_scene_plan
   -> download_raster_assets
   -> mosaic_rasters_by_band
   -> clip_raster_to_aoi
-> calculate_raster_index
-> render_index_preview
-> export_metadata
-> generate_final_answer
```

这些工具可以单独调用和测试。当前 compiler 已经会把 workflow template 编译为
`state.tool_calls`，executor 已可独立执行这些 tool calls。当前
`app/workflows/workflow.py` 仍以显式节点执行真实工具，后续会继续收敛到
executor 驱动。

## Workspace

完整任务开始前先创建 workspace：

```python
workspace = create_workspace(WorkspaceRequest(root_dir=Path("data")))
```

目录结构：

```text
data/<uuid>/
  aoi/
  raster/
  mosaic_raster/
  clipped_raster/
  output/
```

`prepare_raster_inputs` 成功后会清理中间目录：

```text
data/<uuid>/raster
data/<uuid>/mosaic_raster
```

保留：

```text
data/<uuid>/aoi
data/<uuid>/clipped_raster
data/<uuid>/output
```

## AOI

当前 AOI 工具使用 Nominatim / OpenStreetMap。

输入：

```python
AOIRequest(
    query="Chengdu, Sichuan, China",
    workspace_dir=Path("data/<uuid>"),
)
```

输出：

```python
AOIResult(
    name="...",
    boundary_geojson_path="data/<uuid>/aoi/Chengdu_Sichuan_China.geojson",
    bbox=[...],
    area_km2=...,
    source="nominatim",
)
```

后续：

- STAC 搜索使用 bbox
- coverage 检测使用真实 AOI GeoJSON
- clip 使用真实 AOI GeoJSON

## Scene Plan

`scene_plan` 只处理 STAC metadata 层面的 scene 选择，不下载影像。

输入：

```python
RasterScenePlanRequest(
    bbox=[...],
    boundary_geojson_path=Path("...geojson"),
    start_date="2024-06-01",
    end_date="2024-08-31",
    max_cloud_cover=20,
    required_bands=["B04", "B08"],
    data_source="sentinel2",
)
```

输出：

```python
RasterScenePlanResult(
    scene_ids=[...],
    assets=[...],
    diagnostics=...,
    data_source="sentinel2",
    provider="earth_search",
    collection="sentinel-2-l2a",
)
```

当前选择策略是 coverage-aware greedy selection：

- 先筛选云量和必要 asset
- 逐步选择对 AOI 未覆盖部分贡献最大的 scene
- 贡献接近时优先云量更低的 scene
- 输出 coverage diagnostics，供 agent validator / adjuster 使用

如果 scene plan 的 coverage 低于 `min_coverage_ratio`，`prepare_raster_inputs` 会在下载前短路返回 diagnostics，不再执行 download、mosaic 和 clip。后续由 agent validator / adjuster 决定是否扩大日期或小幅放宽云量后重试。

详细算法演进见 [Scene 选择算法迭代](scene-selection-evolution.md)。

## Download

`download_raster_assets` 根据 scene plan 中的 asset URL 下载 GeoTIFF。它不负责选择 scene，只执行下载计划。

输出会按 band 汇总下载路径。

## Mosaic

`mosaic_rasters_by_band` 读取一个目录内的 GeoTIFF，按 band 分组，并使用 `first` 策略合并。

当前选择 `first` 的原因：

- 内存压力小
- 适合先跑通 V1
- 不需要一次性把同一 band 的所有影像读入内存计算 median

后续如需更高质量合成，可扩展 median / percentile 等策略。

## Clip

`clip_raster_to_aoi` 使用 AOI GeoJSON 裁剪每个 band 的 mosaic GeoTIFF。

裁剪后 nodata 使用负值标记，避免和真实正值像素混淆。

输出：

```text
data/<uuid>/clipped_raster/B04_clipped.tif
data/<uuid>/clipped_raster/B08_clipped.tif
```

## Prepare

`prepare_raster_inputs` 是对外的数据准备入口。

输入：

```python
RasterPrepareRequest(
    aoi_query="Chengdu, Sichuan, China",
    index_name="NDVI",
    data_source="sentinel2",
    start_date="2024-06-01",
    end_date="2024-08-31",
    workspace_dir=Path("data/<uuid>"),
)
```

输出：

```python
RasterPrepareResult(
    workspace_dir="data/<uuid>",
    output_dir="data/<uuid>/output",
    boundary_geojson_path="...",
    index_name="NDVI",
    data_source="sentinel2",
    required_bands=["B04", "B08"],
    band_roles={"red": "B04", "nir": "B08"},
    index_formula="(nir - red) / (nir + red)",
    band_paths={...},
    scene_ids=[...],
    diagnostics=...,
)
```

## Index Calculation

`calculate_raster_index` 从 `clipped_raster/` 读取 band GeoTIFF，根据 registry 传入的公式计算指数。

输出：

```text
data/<uuid>/output/ndvi.tif
```

## Render Preview

`render_index_preview` 根据 registry 中的 `vmin`、`vmax` 和 `colormap` 渲染 PNG。

输出：

```text
data/<uuid>/output/ndvi_preview.png
```

## Metadata Export

`export_metadata` 从 workflow state snapshot 中抽取精简产品信息，并导出为 JSON。

输入：

```python
MetadataExportRequest(
    workspace_dir=Path("data/<uuid>"),
    workflow_state={...},
)
```

输出：

```text
data/<uuid>/output/metadata.json
```

JSON 顶层就是面向用户的产品信息对象，不再包含 `schema_version`、
`exported_at` 或外层 `product_info`：

```json
{
  "product": {},
  "area": {},
  "time_range": {},
  "source": {},
  "spatial": {},
  "quality": {}
}
```

metadata 只保留用户需要理解产品的关键信息，例如产品类型、产品名称、AOI、日期范围、云量、数据来源、提供方、CRS、分辨率和质量诊断。它不会原样导出完整 `AgentState`，也不会输出 GeoJSON、GeoTIFF、PNG 等文件路径。

metadata 的字段来源遵循：

- `plan`：用户任务相关字段，例如 AOI、日期范围、云量阈值
- `tool_results`：真实工具输出，例如 `raster_prepare`、`index_calculation`、`render_preview`
- `runtime.registry`：注册表解析结果，只作为产品和数据源配置补充

`source` 使用通用结构，只保留：

```json
{
  "data_source": "sentinel2",
  "provider": "earth_search"
}
```

`satellite`、`collection` 等数据源特有字段不进入用户侧 metadata。

`spatial.crs`、`spatial.resolution`、`spatial.bounds`、`spatial.width` 和 `spatial.height` 优先从最终产品 GeoTIFF 读取；如果最终产品 GeoTIFF 不存在，则尝试读取 `raster_prepare.band_paths` 中的裁剪波段。不会再用数据源默认值伪造 CRS 或分辨率。

其中 `product` 是通用结构，不再使用指数专属字段：

```json
{
  "type": "index",
  "name": "NDVI",
  "family": "raster",
  "method": {
    "name": "index_formula",
    "formula": "(nir - red) / (nir + red)"
  }
}
```

对于 `landtype`、人口、夜光等非指数产品，`method.formula` 会被省略，避免把 `index_formula` 写进不适用的产品信息。

当前 workflow 节点中 metadata export 仍在 `product_generation_node` 内显式调用；
executor 已支持通过 `metadata.export_metadata` tool call 执行该工具，后续会接管
主 workflow 的真实执行。

## Final Answer

`generate_final_answer` 负责生成最终面向用户的回答。

它支持两种模式：

- `metadata_summary`：根据用户原始需求和 workflow metadata 生成结果说明
- `direct_answer`：对不相关问题、普通问答或当前未支持产品进行直接回答

测试通过 fake client 注入 LLM 响应，真实运行时读取智谱环境变量。

## 未来扩展：成品栅格产品

未来人口、土地覆盖、夜光、DEM 等成品栅格产品不一定需要 scene plan。

可以在 `raster_prepare` 内部新增与 `scene_plan` 平行的：

```text
product_tile_select
```

两条路径：

```text
原始影像类：AOI -> scene_plan -> download -> mosaic -> clip
成品栅格类：AOI -> product_tile_select -> download -> mosaic -> clip
```
