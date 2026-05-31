# 开发日志

本文按阶段记录项目从工程骨架到 V1 收尾的演进。当前代码已经进入 V1 完成和文档对齐阶段。

## 阶段 1：工程骨架

完成：

- Python 项目结构；
- `app/`、`docs/`、`scripts/`、`tests/`、`data/`；
- 基础测试、lint、MkDocs 配置；
- 本地 `data/` 作为运行产物目录，不进入 git。

## 阶段 2：AgentState 与 Workflow 骨架

完成：

- `AgentState`；
- workflow runner；
- planner / registry / executor 等节点边界；
- LangGraph 缺失时的线性 fallback runner。

重点是验证状态能否在节点之间稳定流转，以及 workflow 顺序能否被测试。

## 阶段 3：Registry 与产品能力

完成：

- Sentinel-2 数据源配置；
- Landsat registry-only 配置；
- 6 个指数产品配置：NDVI、SAVI、NDWI、NDMI、NDBI、NBR；
- band roles、index formula、render config。

当前真实 `raster_prepare` 只接入 Sentinel-2。

## 阶段 4：真实 Raster Prepare 工具链

完成：

- AOI 解析；
- STAC scene plan；
- coverage-aware greedy scene selection；
- Sentinel-2 asset 下载；
- mosaic；
- AOI clip；
- coverage diagnostics；
- 中间目录清理。

如果 scene coverage 不达标，`raster_prepare` 会在下载前短路返回 diagnostics。

## 阶段 5：Workspace

完成：

- `workspace.create_workspace`；
- 每次任务创建 `data/<uuid>/`；
- 后续工具共享 `workspace_dir`。

最终用户结果统一保留在：

```text
data/<uuid>/output/
  metadata.json
  preview.png
  result.tif
```

## 阶段 6：Index Calculation

完成：

- `index_calculation.calculate_raster_index`；
- 受限 AST 执行指数公式；
- nodata mask；
- band 对齐；
- 输出 `output/result.tif`；
- 消费 clipped bands 后删除 `clipped_raster/`。

## 阶段 7：Preview Rendering

完成：

- `render_preview.render_index_preview`；
- registry 驱动 colormap；
- 透明 nodata；
- 可选 colorbar；
- 输出 `output/preview.png`。

## 阶段 8：Metadata Export

完成：

- `metadata.export_metadata`；
- 从 workflow state snapshot 中抽取精简产品信息；
- 读取最终 GeoTIFF profile；
- 输出 `output/metadata.json`；
- metadata 不再是完整 AgentState dump。

## 阶段 9：Planner 与 Direct Answer

完成：

- 自然语言 planner；
- route decision；
- `raster_product_generate`；
- `direct_answer`；
- 系统能力问答；
- 不支持产品请求不再强行运行 raster workflow。

当前 `direct_answer` 用于普通问题、系统能力问题和未支持产品请求。

## 阶段 10：Compiler / Executor

完成：

- `ToolCall` schema；
- compiler 根据 plan、registry 和 workflow template 生成 tool calls；
- executor 单步执行 tool calls；
- `$state...` 引用解析；
- dependency 检查；
- workspace、tool_results、final_answer 写回 state；
- `runtime.current_tool_index` 控制执行进度。

当前 raster route 的工具链：

```text
workspace.create_workspace
raster_prepare.prepare_raster_inputs
index_calculation.calculate_raster_index
render_preview.render_index_preview
metadata.export_metadata
answer.generate_final_answer
```

## 阶段 11：Validator / Adjuster

完成：

- `raster_prepare` validator；
- `raster_prepare` adjuster；
- retry runtime 记录；
- 最大 retry 次数 5；
- adjuster 修改 tool call params，不修改 `state.plan`。

当前 validator 主要检查 coverage、required bands、diagnostics 和 band paths。

## 阶段 12：Nodes 设计与 Langgraph nodes graph 构建

完成：

- 通用极简型 Nodes 设计
- 通用型 Langgraph nodes graph 构建
- 不用 Langgraph 的 nodes graph 构建

## 阶段 13：V1 收尾

当前 V1 已完成：

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
- output cleanup，只保留 output 结果。

当前阶段：

- V1 已经完成；
- 文档对齐；
- 最小 backend 服务层已经完成；
- 准备进入前端和部署完善阶段。

## 阶段 14：最小 Backend 服务层

当前 backend 已完成：

- FastAPI backend；
- Redis queue；
- worker；
- Docker Compose 启动；
- 默认 2 个 worker；
- `POST /jobs` 创建任务；
- `GET /jobs/{job_id}` 查询状态；
- `GET /jobs/{job_id}/metadata` 下载 metadata；
- `GET /jobs/{job_id}/preview` 下载预览图；
- `GET /jobs/{job_id}/result` 下载 GeoTIFF；
- `GET /health` 健康检查；
- job 创建时间记录；
- 30 分钟 job / workspace lifecycle cleanup；
- 结果文件完整但 final answer 超时时的可交付兜底。

当前 backend 仍然保持最小实现，不包含用户系统、鉴权、任务取消、细粒度进度百分比、持久化 workflow trace、生产日志和监控。

## 下一阶段

下一阶段将聚焦前端和部署完善：

- frontend；
- 更完整的 job status / progress API；
- 生产日志、监控和错误追踪；
- 用户系统和鉴权；
- 任务取消；
- CPU server deployment。

V3 / future research 可探索 GEE-based raster_prepare 替代工具包，用于全球范围 scale-aware source 自动选择和更多专题产品。
