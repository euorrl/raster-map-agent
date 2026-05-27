# 栅格工具链

本文记录当前真实栅格工具链的输入输出、职责边界和扩展点。

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
```

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
    max_cloud_cover=30,
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
- 输出 coverage diagnostics，供后续 validator / ReAct 使用

详细算法演进见 [Scene 选择算法迭代](scene-selection-evolution.md)。

## Download

`download_raster_assets` 根据 scene plan 中的 asset URL 下载 GeoTIFF。

它不负责选择 scene，只执行下载计划。

输出会按 band 汇总下载路径。

## Mosaic

`mosaic_rasters_by_band` 读取一个目录内的 GeoTIFF，按 band 分组，并使用 `first` 策略合并。

当前选择 `first` 的原因：

- 内存压力小
- 适合先跑通 V1
- 不需要一次性把同一 band 的所有影像读入内存计算 median

后续如需更高质量合成，可扩展 median / percentile 策略。

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

`calculate_raster_index` 从 `clipped_raster/` 中读取 band GeoTIFF，根据 registry 传入的公式计算指数。

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

## 未来扩展：成品栅格产品

未来人口、土地覆盖、夜光、DEM 等成品栅格产品不需要 scene plan。

可以在 `raster_prepare` 内部新增与 `scene_plan` 平行的：

```text
product_tile_select
```

两条路径：

```text
原始影像类：AOI -> scene_plan -> download -> mosaic -> clip
成品栅格类：AOI -> product_tile_select -> download -> mosaic -> clip
```
