# 栅格工具链

本文记录当前 `raster_prepare` 工具链的输入输出、职责边界和后续扩展点。

## 总体目标

V1 的真实工具链目标是：

```text
AOI query
-> boundary GeoJSON + bbox
-> scene plan
-> download Sentinel-2 bands
-> mosaic per band
-> clip per band
-> prepared band inputs
-> calculate index
-> index GeoTIFF
-> render preview
-> metadata
```

当前已经实现到 `index GeoTIFF`：数据准备模块输出裁剪后的 band GeoTIFF，指数计算模块继续生成 NDVI / NDWI 等指数 GeoTIFF。

## Workspace Directory

低层工具仍然可以单独接收 `workspace_dir`、`input_dir` 或 `output_dir`，方便开发阶段单独调试。

完整流程开始前先调用 `create_workspace` 创建一次任务级 workspace：

```python
workspace = create_workspace(WorkspaceRequest(root_dir=Path("data")))
```

`prepare_raster_inputs` 不再生成 UUID，而是接收已经创建好的 `workspace_dir`。每次任务目录结构为：

```text
data/<uuid>/
  aoi/
  raster/
  mosaic_raster/
  clipped_raster/
  output/
```

成功完成 clip 后，prepare 会删除中间目录：

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

这样后续指数计算只需要读取裁剪后的 band，不需要关心原始下载文件和 mosaic 中间文件。

## AOI

当前实现：Nominatim / OpenStreetMap。

输入：

```python
AOIRequest(
    query="Hangzhou, Zhejiang, China",
    workspace_dir=Path("data/speak1"),
)
```

输出：

```python
AOIResult(
    name="杭州市, 浙江省, 中国",
    boundary_geojson_path="data/speak1/aoi/Hangzhou_Zhejiang_China.geojson",
    bbox=[118.3396948, 29.1888286, 120.7254851, 30.5648514],
    area_km2=35275.45,
    source="nominatim",
)
```

关键逻辑：

- 请求 Nominatim search API
- 设置 `polygon_geojson=1`
- 只接受 `Polygon` 或 `MultiPolygon`
- 保存本地 GeoJSON
- 计算 bbox
- 估算 bbox 面积，作为 metadata 记录

LLM planner 的任务是把用户输入地点规范化成可消歧的 query：

```text
Hangzhou, Zhejiang, China
Milan, Lombardy, Italy
New York City, New York, United States
```

## Scene Plan

当前实现：Earth Search STAC + Sentinel-2 L2A。

V1 数据源边界：

```text
data_source="sentinel2"
provider="earth_search"
collection="sentinel-2-l2a"
```

`data_source` 是给上游 planner/ReAct 使用的稳定协议字段。registry 中已经保留 Landsat 的指数波段映射，但当前 `raster_prepare` 只执行 `sentinel2`，不自动切换 Landsat、MODIS 或其他 provider。

指数和数据源知识位于：

```text
app/registry/raster_products.py
```

其中 registry 负责解析：

```text
index_name + data_source
-> required_bands
-> band_roles
-> index_formula
-> provider / collection / band asset mapping
```

输入：

```python
RasterScenePlanRequest(
    bbox=[min_lon, min_lat, max_lon, max_lat],
    boundary_geojson_path=Path("data/speak1/aoi/Hangzhou_Zhejiang_China.geojson"),
    start_date="2024-06-01",
    end_date="2024-08-31",
    max_cloud_cover=30,
    required_bands=["B04", "B08"],
    data_source="sentinel2",
    limit=100,
)
```

职责：

```text
搜索 STAC metadata
-> 按 scene_id 去重
-> 按 max_cloud_cover 过滤
-> 累积候选 scene
-> 读取真实 AOI GeoJSON
-> coverage-aware greedy 选择 scene
-> 生成 RasterScenePlanResult
```

scene 选择规则：

```text
1. STAC 搜索与 bbox 相交的候选 scene
2. 按 scene_id 去重
3. 按 max_cloud_cover 做硬过滤
4. 每轮计算候选 scene 对当前未覆盖 AOI 的新增贡献
5. 优先选择新增贡献最大的 scene
6. 如果多个 scene 贡献接近，再选择云量更低的 scene
7. 最多选择 max_selected_scenes 个 scene
```

当前默认参数：

```python
max_cloud_cover = 30
limit = 100
max_selected_scenes = 20
contribution_tolerance = 0.95
min_scene_overlap_ratio = 0
min_coverage_ratio = 0.7
```

## Coverage Diagnostics

STAC 搜索继续使用 `bbox`，因为它是稳定的粗筛方式。

coverage diagnostics 使用真实 AOI GeoJSON，而不是 AOI bbox：

```text
scene footprint union ∩ AOI GeoJSON geometry
/
AOI GeoJSON geometry
```

如果缺少 `boundary_geojson_path`，或 GeoJSON 无法解析，diagnostics 会返回：

```text
coverage_status="unknown"
is_retriable=false
```

这表示问题不是扩大日期、放宽云量或增加 limit 能解决的，后续 ReAct 应结束当前调参循环并返回明确原因。

如果 coverage 低于阈值，则 diagnostics 会返回：

```text
coverage_status="not_covered"
is_retriable=true
suggested_actions=[
    "expand_date_range",
    "increase_max_cloud_cover",
    "increase_limit",
]
```

`min_coverage_ratio` 只影响 diagnostics 的通过/失败，不会让 greedy selection 在达到 70% 后提前停止。选择阶段仍然会尽量提高覆盖率，直到接近完整覆盖、没有新的有效贡献，或达到 `max_selected_scenes`。

## Download

下载层只执行 scene plan，不再负责选 scene。

输入：

```python
RasterDownloadRequest(
    plan=plan,
    workspace_dir=Path("data/speak1"),
)
```

输出：

```python
RasterDownloadResult(
    scene_ids=["S2A_...", "S2B_..."],
    band_paths={
        "B04": ["...scene1_B04.tif", "...scene2_B04.tif"],
        "B08": ["...scene1_B08.tif", "...scene2_B08.tif"],
    },
    data_source="sentinel2",
    provider="earth_search",
    collection="sentinel-2-l2a",
)
```

当前限制：

- bbox 只用于搜索，不用于裁剪下载内容
- 下载的是 STAC asset 指向的 COG 文件
- 真正的 AOI 裁剪在 clip 阶段完成

## Mosaic

当前实现：按 band 扫描输入目录，并用 `first` 策略输出每个 band 的 mosaic GeoTIFF。

输入：

```python
RasterMosaicRequest(
    input_dir=Path("data/speak1/raster"),
    output_dir=Path("data/speak1/mosaic_raster"),
)
```

输出：

```python
RasterMosaicResult(
    band_paths={
        "B04": "data/speak1/mosaic_raster/mosaic_B04.tif",
        "B08": "data/speak1/mosaic_raster/mosaic_B08.tif",
    }
)
```

当前策略：

```text
rasterio.merge.merge(..., method="first")
```

重叠区域保留排序后第一张有数据的 tif。V1 先用该策略降低内存压力和实现复杂度；median、quality mask、cloud mask 等更高质量合成策略留到后续版本。

如果输入 tif 跨 CRS，mosaic 会以排序后第一张 tif 的 CRS 作为目标 CRS，并用 `WarpedVRT` 对其他 tif 做临时重投影后再合并。这个过程不会写出中间重投影文件。

## Clip

当前实现：rasterio mask。

输入：

```python
RasterClipRequest(
    raster_path=Path("mosaic_B04.tif"),
    boundary_geojson_path=Path("aoi.geojson"),
    workspace_dir=Path("data/speak1"),
    output_filename="B04_clipped.tif",
)
```

输出：

```python
RasterClipResult(
    source_raster_path="...",
    boundary_geojson_path="...",
    clipped_raster_path="...",
)
```

关键逻辑：

- 读取 AOI GeoJSON
- 打开输入 GeoTIFF
- 将 GeoJSON geometry 从 EPSG:4326 转到 raster CRS
- 使用 `rasterio.mask.mask(..., crop=True, filled=False)`
- 输出转为 `float32`
- AOI 外像素填充 `-9999.0`
- metadata 写入 `nodata=-9999.0`

clip 只处理一个 raster。多 band 裁剪由上层 pipeline 循环调用。

## Prepare Pipeline

当前实现：`prepare_raster_inputs`。

职责：

```text
resolve AOI
-> scene plan
-> download raw bands
-> mosaic bands
-> clip bands
-> return prepared inputs for index calculation
```

输入：

```python
RasterPrepareRequest(
    aoi_query="Chengdu, Sichuan, China",
    index_name="NDVI",
    start_date="2023-12-01",
    end_date="2024-01-31",
    max_cloud_cover=30,
    workspace_dir=Path(workspace.workspace_dir),
)
```

输出：

```python
RasterPrepareResult(
    workspace_dir="data/<uuid>",
    output_dir="data/<uuid>/output",
    boundary_geojson_path="data/<uuid>/aoi/Chengdu_Sichuan_China.geojson",
    index_name="NDVI",
    data_source="sentinel2",
    required_bands=["B04", "B08"],
    band_roles={"red": "B04", "nir": "B08"},
    index_formula="(nir - red) / (nir + red)",
    band_paths={
        "B04": "data/<uuid>/clipped_raster/B04_clipped.tif",
        "B08": "data/<uuid>/clipped_raster/B08_clipped.tif",
    },
    scene_ids=[...],
    diagnostics=...,
)
```

prepare pipeline 是工具链和 Agent workflow 之间的桥。它对外隐藏 AOI、scene plan、download、mosaic 和 clip 的内部编排，让后续指数计算模块只需要读取每个 band 一张已经裁剪到 AOI 的 GeoTIFF。

## Index Calculation

当前实现：`calculate_raster_index`。

职责：

```text
读取 workspace/clipped_raster 中的 band GeoTIFF
-> 根据 band_roles 把公式变量映射到真实 band
-> 用受限公式解析执行四则运算
-> 写出 workspace/output/<index>.tif
-> 返回 index_tif_path
```

输入示例：

```python
IndexCalculationRequest(
    workspace_dir=Path("data/<uuid>"),
    index_name="NDVI",
    band_roles={"red": "B04", "nir": "B08"},
    index_formula="(nir - red) / (nir + red)",
)
```

输出示例：

```python
IndexCalculationResult(
    index_tif_path="data/<uuid>/output/ndvi.tif",
)
```

NDVI：

```text
NDVI = (B08 - B04) / (B08 + B04)
```

需要注意：

- 输入 clipped bands 是 `float32`
- nodata 是 `-9999.0`
- 计算前会基于每个输入 band 构建 valid mask
- 公式结果中的 `inf` 和 `nan` 会写成 nodata
- 输入 bands 必须已经对齐到同一 shape、transform 和 CRS

默认输出：

```text
data/<uuid>/output/ndvi.tif
```

## Render

尚未实现。

目标：

```text
index GeoTIFF -> preview PNG
```

需要处理：

- nodata mask
- min/max 或 percentile stretch
- colormap
- 输出 PNG
