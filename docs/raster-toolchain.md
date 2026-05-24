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
-> 每个空间分组最多保留 5 个候选 scene
-> 每个空间分组选择云量最低的 3 个 scene
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
- 当前会下载所有通过云量过滤的 scene
- 当前还没有检测这些 scene 是否完整覆盖 AOI
- 大 AOI 可能无法被单个 Sentinel-2 tile 完整覆盖

后续需要：

- 检测通过云量过滤后的 scenes 是否完整覆盖 AOI
- 将同一 band 的多个 scene/tile 合成为一张待计算 GeoTIFF

## Mosaic

当前为空模块，下一步重点实现。

目标：

```text
同一 band 的多个 tile
-> mosaic 成一张完整覆盖 AOI/bbox 的 GeoTIFF
```

建议输入：

```python
RasterMosaicRequest(
    band_paths=["tile1_B04.tif", "tile2_B04.tif"],
    output_path=Path("mosaic_B04.tif"),
)
```

建议输出：

```python
RasterMosaicResult(
    mosaic_path="mosaic_B04.tif",
)
```

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
