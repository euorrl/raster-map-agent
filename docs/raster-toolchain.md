# 栅格工具链

本文说明当前 V1 真实 raster 工具链的输入、输出和边界。V1 的真实执行链路基于 Sentinel-2。

## 总体流程

Raster route 中，compiler 生成以下受控工具链：

```text
workspace.create_workspace
-> raster_prepare.prepare_raster_inputs
-> index_calculation.calculate_raster_index
-> render_preview.render_index_preview
-> metadata.export_metadata
-> answer.generate_final_answer
```

executor 每次只执行一个 tool call。执行完某个工具后，如果该 tool call 存在 rule，则进入 validator / adjuster；当前只有 `raster_prepare` 有 tool rule。

## Workspace

每次使用 agent 生成 raster 产品时，workflow 会先调用：

```python
workspace.create_workspace
```

它在 `data/` 下创建一个 UUID 工作区。处理中可能产生：

- AOI 文件；
- 下载的 raster；
- mosaic raster；
- clipped raster；
- output 结果。

V1 当前是本地 workspace 生命周期。workflow 会清理中间文件和中间目录，最终用户侧只保留：

```text
data/
  <uuid>/
    output/
      metadata.json
      preview.png
      result.tif
```

V2 计划进一步引入 job lifecycle manager；部署版可以在任务完成后保留 output 一段时间，例如 30 分钟，然后自动删除整个 job workspace。

## Raster Prepare

`raster_prepare.prepare_raster_inputs` 是数据准备入口。它负责：

1. 解析 AOI；
2. 查询 STAC；
3. 选择覆盖 AOI 的 Sentinel-2 scenes；
4. 下载所需 bands；
5. mosaic 拼接；
6. clip 到 AOI；
7. 返回 band paths 和 diagnostics；
8. 删除 AOI、下载影像和 mosaic 中间目录。

典型输入来自 compiler 编译后的 tool call：

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

典型输出包含：

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

用于选择覆盖 AOI 的 Sentinel-2 scenes 的 scene plan 内部存在 scene coverage 检验，如果不达标，工具会在下载前短路返回 diagnostics，并删除已生成的 AOI 中间目录。

Scene plan 使用 STAC metadata 进行 scene 选择，不直接下载影像。

当前策略是 coverage-aware greedy selection：

- 先筛选云量和必要 assets；
- 按 AOI 未覆盖区域的新增贡献选择 scenes；
- 对贡献接近的 scenes 优先选择云量更低的；
- 输出 coverage diagnostics，供 validator / adjuster 使用。

Sentinel-2的单tile覆盖区域为100km*100km, 考虑栅格数据下载和处理时间以及运行内存的限制，最大可下载的scene的数量限制为20，本地内存不足时，实际可处理数量可能更低。因此当前适合中小尺度行政区或城市区域，推荐覆盖面积小于10万平方千米；

## Validator / Adjuster

当前只有 `raster_prepare` 的 tool rule。

validator 检查：

- raster prepare 结果是否存在；
- required bands 是否可解析；
- diagnostics 是否存在；
- coverage 是否通过；
- 所需 band paths 是否存在。

如果 diagnostics 表明问题可修复，validator 会返回 `retryable`。adjuster 可以更新对应 tool call 的 params 并重试，最大 retry 次数为 5。

adjuster 不修改 `state.plan`，只修改 `tool_calls[last_tool_index].params`，并把 `runtime.current_tool_index` 拉回 `raster_prepare`。

## Index Calculation

`index_calculation.calculate_raster_index` 从 clipped bands 读取输入，根据 registry 传入的 band roles 和 formula 计算指数。

输出统一为：

```text
data/<uuid>/output/result.tif
```

计算完成后，工具会删除 `clipped_raster/` 中间目录。最终用户结果不保留 clipped raster。

当前支持的 Sentinel-2 指数：

| 指数 | 公式语义 | Sentinel-2 bands |
| --- | --- | --- |
| NDVI | `(nir - red) / (nir + red)` | B08, B04 |
| SAVI | `1.5 * (nir - red) / (nir + red + 0.5)` | B08, B04 |
| NDWI | `(green - nir) / (green + nir)` | B03, B08 |
| NDMI | `(nir - swir) / (nir + swir)` | B08, B11 |
| NDBI | `(swir - nir) / (swir + nir)` | B11, B08 |
| NBR | `(nir - swir2) / (nir + swir2)` | B08, B12 |

## Render Preview

`render_preview.render_index_preview` 根据 registry 中的 render config 渲染 PNG 预览图。

输出统一为：

```text
data/<uuid>/output/preview.png
```

预览图使用指数对应的 colormap，并对 nodata 区域保持透明。

## Metadata Export

`metadata.export_metadata` 从 workflow state snapshot 中抽取面向用户和结果溯源的精简产品信息。它不是完整 `AgentState` dump。

信息来源包括：

- `state.plan`
- `runtime["registry"]["raster_product"]`
- `tool_results`
- `raster_prepare` diagnostics
- validator 结果
- 最终 GeoTIFF profile

输出统一为：

```text
data/<uuid>/output/metadata.json
```


示例：

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

实际输出会按可获得字段自动省略空 section。

## Final Answer

`answer.generate_final_answer` 负责最终用户回答。

- raster route：基于 metadata product info 总结结果；
- direct answer route：回答普通问题、系统能力问题或不支持产品请求；
- 如果任务失败，answer 会说明失败阶段、已知原因和可调整方向。

## 当前边界

- V1 只真实执行 Sentinel-2；
- Landsat 虽在 registry 中存在配置，但 `raster_prepare` 未接入；
- DEM、population、night lights、land cover、GEE、多数据源自动选择属于未来工作；
- 当前适合中小尺度 AOI，推荐面积小于 10 万平方千米；
- 过大、靠海或复杂 MultiPolygon AOI 可能出现下载慢、覆盖不足或视觉效果不稳定。
