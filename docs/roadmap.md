# 路线图

本文记录当前阶段和后续方向。
- V1 已完成本地端到端功能闭环；
- V2 已完成本地服务化、前端展示和基于内网穿透的外部访问闭环。

## V1 已完成

V1 当前已经完成：

- 自然语言 planner；
- route decision；
- direct answer route；
- six Sentinel-2 index products；
- product registry；
- tool rules；
- route templates；
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

## V2 已完成

V2 聚焦服务化、前端和部署展示，不改变 V1 的 raster workflow、工具链、算法或架构。

当前 V2 已完成：

- FastAPI backend；
- Redis queue；
- 默认 2 个 worker；
- Docker Compose local backend deployment；
- `POST /jobs` 创建任务；
- `GET /jobs/{job_id}` 查询状态；
- `GET /jobs/{job_id}/metadata` 下载 metadata；
- `GET /jobs/{job_id}/preview` 下载预览图；
- `GET /jobs/{job_id}/result` 下载 GeoTIFF；
- `GET /health` 健康检查；
- job `stage` / `message` 状态字段；
- worker heartbeat；
- running job 心跳失联兜底；
- 30 分钟 job / workspace lifecycle cleanup；
- Vue / Vite / TypeScript frontend；
- 前端任务提交、轮询状态、展示回答、展示预览图和下载结果；
- Vercel 前端部署；
- 本地电脑后端通过内网穿透提供公网访问；
- Vercel 前端通过 `VITE_API_BASE_URL` 调用公网后端。

当前 V2 部署形态：

```text
Vercel frontend
  -> backend public URL from tunnel
    -> local Docker backend
      -> FastAPI / Redis / workers
```

## V2 边界

当前 V2 仍然不是生产级 GIS 平台。已知边界：

- 本地电脑关机后，后端不可用；
- 临时内网穿透地址可能变化；
- Vercel 修改环境变量后必须重新部署；
- 当前没有用户系统和鉴权；
- 当前没有任务取消；
- 当前没有硬性任务运行超时终止；
- 当前没有细粒度百分比进度；
- 当前没有持久化 workflow trace；
- 当前没有生产级日志、监控和告警；
- 当前没有多机 worker 调度。

## 后续方向

后续服务化方向可以包括：

- 固定域名和 named tunnel；
- 后端部署到稳定 CPU server；
- 更完整的 job status / progress API；
- 任务取消；
- 持久化日志与 workflow trace；
- 监控、告警和错误追踪；
- 用户系统和鉴权；
- 多机 worker 调度；
- 文件保留策略和下载权限控制。

## V3 / Future Research

V3 或 future research 可以探索更强的 GEE-based raster_prepare 替代工具包，支持：

- 全球范围 scale-aware source 自动选择；
- DEM / population / night lights / land cover 等专题产品；
- 简单外部接口；
- 更全面的 registry；
- 多 route 复杂遥感数据处理实现。
