# 栅格工具链

本文记录当前 raster 工具链的输入输出、职责边界和后续扩展点。

## 总体目标

V1 的真实工具链目标是：

```text
AOI query
-> boundary GeoJSON + bbox
-> search/download Sentinel-2 bands
-> mosaic per band
-> clip per band
-> calculate index
-> render preview
-> metadata
```

## Workspace Directory

当前 raster_prepare 工具链对外只接收一个任务根目录，例如：

```python
workspace_dir = Path("data/speak1")
```

工具内部自动使用固定子目录：

```text
data/speak1/aoi
data/speak1/raster
data/speak1/clipped_raster
```

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
- 保存为本地 GeoJSON
- 计算 bbox
- 估算 bbox 面积，作为 metadata 记录

LLM planner 的任务：

```text
把用户输入地点规范化成消歧 query：
Hangzhou, Zhejiang, China
Milan, Lombardy, Italy
New York City, New York, United States
```

## Download

当前 download 已拆成两层：

```text
scene_plan.py
-> 搜索 STAC metadata
-> 合并到 RasterSceneCandidateStore
-> 按 scene_id 去重
-> 按云量过滤
-> 全局累积候选 scene
-> 用 coverage-aware greedy 最多选择 max_selected_scenes 个 scene
-> 使用 Shapely 检查选中 scene footprints 对真实 AOI GeoJSON 的覆盖
-> 生成 RasterScenePlanResult

download.py
-> 按 RasterScenePlanResult 下载 band asset
-> 返回本地 tif 路径
```

当前实现：Earth Search STAC + COG。

V1 数据源边界：

```text
data_source="sentinel2"
provider="earth_search"
collection="sentinel-2-l2a"
```

`data_source` 是给上游 planner/ReAct 使用的稳定协议字段。当前只支持
`sentinel2`，不自动切换 Landsat、MODIS 或其他 provider。

输入：

```python
RasterScenePlanRequest(
    bbox=[min_lon, min_lat, max_lon, max_lat],
    start_date="2024-06-01",
    end_date="2024-08-31",
    max_cloud_cover=20,
    required_bands=["B04", "B08"],
    data_source="sentinel2",
    boundary_geojson_path=Path("data/speak1/aoi/Hangzhou_Zhejiang_China.geojson"),
    limit=100,
)

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
- STAC 搜索返回与 bbox 相交的 scene
- 当前会下载 `RasterScenePlanResult` 中选中的 scene asset
- coverage diagnostics 使用 scene footprint union 与真实 AOI GeoJSON geometry 对比
- diagnostics 通过 `is_retriable` 告诉 ReAct 是否应该继续调参
- 大 AOI 可能无法被单个 Sentinel-2 tile 完整覆盖
- coverage 默认不再要求 100% 完整覆盖，而是要求达到 `min_coverage_ratio=0.7`

当前默认 `limit=100`。这是 Earth Search 单次请求允许的上限，用来降低
STAC 返回结果被少数 tile 或少数日期占满的风险；真正进入下载的 scene
仍由 `max_selected_scenes` 控制。

`min_coverage_ratio` 是 V1 的最低可接受覆盖率。达到该阈值时，scene plan
会标记为 `covered`，但仍然保留真实 `coverage_ratio`，方便后续 answer
向用户说明当前影像覆盖情况。低于该阈值时，diagnostics 会标记为
`not_covered`，并建议扩大日期、放宽云量或增加 limit。

该阈值只用于诊断，不会让 greedy selection 在达到 70% 后提前停止；选择阶段仍会
尽量提高覆盖率，直到接近完整覆盖、没有新增贡献或达到 `max_selected_scenes`。

scene 选择规则：

```text
1. STAC 搜索候选 scenes
2. 按 scene_id 去重
3. 按 max_cloud_cover 做硬过滤
4. 读取真实 AOI GeoJSON
5. 每轮选择对当前未覆盖 AOI 贡献最大的 scene
6. 如果多个 scene 的贡献接近，则选择云量更低的 scene
7. 最多选择 max_selected_scenes 个 scene
```

这个设计不再按 tile 分组选择。原因是同一个 tile 内不同日期的真实 footprint
可能只覆盖 tile 的不同部分；如果只按云量选，可能连续选到同一侧 footprint，
导致 AOI 另一侧缺数据。现在的全局 greedy 会优先补未覆盖区域。

后续需要：

- 将同一 band 的多个 scene/tile 合成为一张待计算 GeoTIFF

## Mosaic

当前实现：按 band 扫描输入目录，并用 `first` 策略输出每个 band 的 mosaic GeoTIFF。

目标：

```text
输入 raster 文件夹
-> 按 B04、B08 等 band 自动分组
-> 每个 band 的多张 tif 合并成一张 mosaic tif
-> 输出 mosaic_raster 文件夹
```

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

也就是说，重叠区域保留排序后第一张有数据的 tif。V1 先使用这个策略降低复杂度和
内存压力；median / cloud mask 等更复杂的像素级合成留到后续版本。

如果输入 tif 跨不同 CRS，mosaic 会以排序后第一张 tif 的 CRS 作为目标 CRS，并用
`WarpedVRT` 对其他 tif 做临时重投影后再合并。这个过程不会写出中间重投影文件。

## Clip

当前实现：rasterio mask。

输入：

```python
RasterClipRequest(
    raster_path=Path("mosaic_or_single_band.tif"),
    boundary_geojson_path=Path("aoi.geojson"),
    workspace_dir=Path("data/speak1"),
    output_filename="clipped_B04.tif",
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

设计边界：

- clip 只处理一个 raster
- 多 band 裁剪由上层 pipeline 循环调用

## Index Calculation

尚未实现。

NDVI 计划：

```text
NDVI = (B08 - B04) / (B08 + B04)
```

需要注意：

- 输入 clipped bands 是 `float32`
- nodata 为 `-9999.0`
- 计算前必须构建 valid mask
- 避免 `(nir + red) == 0`

建议输出：

```text
outputs/ndvi.tif
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

## Prepare Pipeline

尚未实现。

最终职责：

```text
resolve AOI
-> download bands
-> mosaic bands
-> clip bands
-> return prepared inputs for index calculation
```

prepare pipeline 是工具链和 Agent workflow 之间的桥。

## Coverage Diagnostics 当前规则

STAC 搜索仍然使用 `bbox`，因为它是最稳定、最简单的候选 scene 粗筛方式。

coverage diagnostics 不再使用 AOI bbox polygon 计算覆盖率，而是读取
`RasterScenePlanRequest.boundary_geojson_path` 指向的真实 AOI GeoJSON，并用：

```text
AOI GeoJSON geometry
scene footprint union
```

计算覆盖比例。

如果 `boundary_geojson_path` 缺失或 GeoJSON 无法解析，diagnostics 会返回
`coverage_status="unknown"`，并通过 `failure_reason` 写明原因。这个问题不是
V1 支持的 ReAct 调参问题，因此 `is_retriable=false`。
