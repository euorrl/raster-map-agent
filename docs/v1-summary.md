# V1 总结

Raster Map Agent V1 是一个本地端到端可运行的受控型 Raster Workflow Agent。它可以把自然语言请求转为 Sentinel-2 指数产品生成 workflow，并输出统一命名的用户结果。

## V1 已实现能力

当前 V1 已经完成：

- 自然语言 planner；
- route decision；
- direct answer route；
- six Sentinel-2 index products；
- product registry；
- compiler；
- executor；
- single-step tool execution；
- raster_prepare validator / adjuster retry loop；
- workspace creation；
- raster preparation；
- index calculation；
- preview rendering；
- metadata export；
- final answer generation；
- terminal logging；
- output cleanup，只保留 output 结果。

## 支持产品

当前真实 raster preparation 只接入 Sentinel-2。

| 产品 | 用途 |
| --- | --- |
| NDVI | 植被绿度、植被覆盖、作物长势 |
| SAVI | 稀疏植被、裸土背景较强区域 |
| NDWI | 水体、水域分布、地表水提取 |
| NDMI | 植被含水量、地表湿度、干旱胁迫 |
| NDBI | 建成区、不透水面、城市扩张 |
| NBR | 火烧迹地、火灾影响、植被受损 |

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

Raster route 的 tool calls：

```text
workspace.create_workspace
raster_prepare.prepare_raster_inputs
index_calculation.calculate_raster_index
render_preview.render_index_preview
metadata.export_metadata
answer.generate_final_answer
```

Direct answer route 的 tool call：

```text
answer.generate_final_answer
```

## 输出结果

所有指数产品统一输出：

```text
data/
  <uuid>/
    output/
      metadata.json
      preview.png
      result.tif
```

产品类型、指数名、公式、数据源、时间范围、空间信息和质量诊断写入 `metadata.json`。

## Direct Answer

Direct answer route 用于：

- 普通知识问题；
- 系统能力问题；
- 当前不支持的产品请求。

该 route 不运行 raster tools。对于不支持任务，answer 会说明当前不支持，并建议用户询问系统功能或改用当前支持的 Sentinel-2 指数产品。

## V1 Limitations

这些限制是 V1 边界，不是缺陷：

- 当前真实 raster preparation 只接入 Sentinel-2；
- Sentinel-2 单 tile 约为 100 km * 100 km；
- 当前最大可下载 scene 数量限制为 20，本地运行内存不足时可能达不到这个数；
- 当前适合中小尺度行政区或城市区域，推荐覆盖面积小于 10 万平方千米；
- 过大的 AOI 可能导致下载慢、处理慢或失败；
- 靠海城市、包含领海、岛屿或复杂 MultiPolygon 的行政边界 AOI 可能存在卫星数据量不足，导致覆盖率与视觉效果不如内陆地区稳定；
- 当前日志主要输出在终端，尚未持久化为 `workflow_trace.json`；
- 当前是本地命令行 / local workflow，没有 Web 前端；
- 当前没有 FastAPI backend、Redis queue、worker、job lifecycle manager、用户系统；
- 当前没有 GEE、多数据源自动选择、DEM、population、night lights、land cover 产品；
- 当前不是生产级 GIS 平台，而是本地可运行的 V1 agent。

## 下一步

V2 将聚焦服务化和部署：

- FastAPI backend；
- Redis queue；
- worker；
- frontend；
- job status API；
- file download API；
- job lifecycle cleanup；
- CPU server deployment。

V3 / future research 可探索 GEE-based raster_prepare 替代工具包，但它不是 V2 必做项。
