# 路线图

本文记录当前阶段和后续方向。V1 已完成，当前重点是文档对齐和进入 V2 前的整理。

## V1 已完成

V1 当前已经完成：

- 自然语言 planner；
- route decision；
- direct answer route；
- six Sentinel-2 index products；
- product registry；
- tool rules;
- route templates
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
- output cleanup，只保留 `output/` 结果。

V1 支持的 Sentinel-2 指数：

- NDVI；
- SAVI；
- NDWI；
- NDMI；
- NDBI；
- NBR。

V1 输出：

```text
data/<uuid>/output/
  metadata.json
  preview.png
  result.tif
```

## 当前阶段

当前阶段是：

- V1 已经完成；
- 文档与代码实现对齐；
- 准备进入 V2。

## V2 方向

V2 聚焦服务化和部署，不把 GEE 产品引擎作为必做项。

计划方向：

- FastAPI backend；
- Redis queue；
- worker；
- frontend；
- job status API；
- file download API；
- job lifecycle cleanup；
- deployment on CPU server。

V2 的目标是把当前 local workflow 包装成可调用、可排队、可查看状态、可下载结果的服务。

## V3 / Future Research

V3 或 future research 可以探索更强的 GEE-based raster_prepare 替代工具包，支持：

- 全球范围 scale-aware source 自动选择；
- DEM / population / night lights / land cover 等专题产品；
- 简单外部接口；
- 更全面的 registry；
- 多 route 复杂遥感数据处理实现。

