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

## AOI

当前实现：Nominatim / OpenStreetMap。

输入：

```python
AOIRequest(
    query="Hangzhou, Zhejiang, China",
    output_dir=Path("data/aoi"),
)
```

输出：

```python
AOIResult(
    name="杭州市, 浙江省, 中国",
    boundary_geojson_path="data/aoi/Hangzhou_Zhejiang_China.geojson",
    bbox=[118.3396948, 29.1888286, 120.7254851, 30.5648514],
    area_km2=35275.45,
    spatial_scale="regional",
    source="nominatim",
)
```

关键逻辑：

- 请求 Nominatim search API
- 设置 `polygon_geojson=1`
- 只接受 `Polygon` 或 `MultiPolygon`
- 保存为本地 GeoJSON
- 计算 bbox
- 估算面积和空间尺度

LLM planner 的任务：

```text
把用户输入地点规范化成消歧 query：
Hangzhou, Zhejiang, China
Milan, Lombardy, Italy
New York City, New York, United States
```

## Download

当前实现：Earth Search STAC + COG。

输入：

```python
RasterDownloadRequest(
    bbox=[min_lon, min_lat, max_lon, max_lat],
    start_date="2024-06-01",
    end_date="2024-08-31",
    max_cloud_cover=20,
    required_bands=["B04", "B08"],
    output_dir=Path("data/raster"),
)
```

输出：

```python
RasterDownloadResult(
    selected_scene="S2A_...",
    band_paths={
        "B04": "...B04.tif",
        "B08": "...B08.tif",
    },
    provider="earth_search",
    collection="sentinel-2-l2a",
)
```

当前限制：

- bbox 只用于搜索，不用于裁剪下载内容
- STAC 搜索返回与 bbox 相交的 scene
- 当前只选择一个 scene
- 大 AOI 可能无法被单个 Sentinel-2 tile 完整覆盖

后续需要：

- 搜索多个 scene
- 选择覆盖 AOI 的 scene 组合
- 按 band 下载多个 tile

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
    output_path=Path("clipped_B04.tif"),
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
