# 路线图

本文记录当前阶段和后续方向。V1 已完成，最小后端服务层也已经完成，当前重点是进入前端、部署和生产化整理。

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
- 最小 FastAPI / Redis / worker backend 已经完成；
- Docker Compose 可以启动 API、Redis 和 2 个 worker；
- backend 已支持 job 创建、状态查询、结果下载和 30 分钟 job 清理；
- 准备进入前端和部署完善阶段。

## V2 方向

V2 聚焦服务化和部署，不把 GEE 产品引擎作为必做项。

已完成：

- FastAPI backend；
- Redis queue；
- worker；
- job status API；
- file download API；
- job lifecycle cleanup；
- Docker Compose local deployment。

后续方向：

- frontend；
- 更完整的 job status / progress API；
- 生产日志、监控和错误追踪；
- 用户系统和鉴权；
- 任务取消；
- deployment on CPU server。

V2 的目标是把当前 local workflow 进一步整理成可展示、可部署、可运维的服务。当前 backend 已经完成了可调用、可排队、可查看状态、可下载结果的最小闭环。

## V3 / Future Research

V3 或 future research 可以探索更强的 GEE-based raster_prepare 替代工具包，支持：

- 全球范围 scale-aware source 自动选择；
- DEM / population / night lights / land cover 等专题产品；
- 简单外部接口；
- 更全面的 registry；
- 多 route 复杂遥感数据处理实现。
