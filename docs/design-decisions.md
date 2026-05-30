# 关键设计决策

本文记录当前 V1 中仍然有效的设计决策。V1 的目标是构建一个本地端到端可运行的受控型 raster workflow agent，而不是 production-ready GIS 平台。

## 受控型 Workflow，而不是自由 Tool Calling

LLM 只负责理解用户意图和生成结构化 `state.plan`。底层工具顺序、参数来源、validator 和 retry 逻辑由系统控制。

原因：

- 避免 LLM 直接拼接不稳定的 GIS 参数；
- 保证 raster route 的执行顺序可测试、可复现；
- 让 registry 成为产品能力的唯一稳定来源；
- 让 validator / adjuster 可以围绕确定的 tool call id 工作。

当前 compiler 为 raster route 生成固定工具链：

```text
workspace.create_workspace
raster_prepare.prepare_raster_inputs
index_calculation.calculate_raster_index
render_preview.render_index_preview
metadata.export_metadata
answer.generate_final_answer
```

## Route Decision

Planner 会在 `raster_product_generate` 和 `direct_answer` 之间选择。

使用 `direct_answer` 的情况：

- 普通知识问题；
- 系统能力问题；
- 当前不支持的产品请求；
- 与当前 raster workflow 无关的问题。

这样可以避免把 population、DEM、night lights、land cover 等未接入产品强行映射到 NDVI 或 NDWI。

## Registry 是产品能力边界

当前 V1 支持 6 个 Sentinel-2 指数：

- NDVI
- SAVI
- NDWI
- NDMI
- NDBI
- NBR

Registry 中可以保留尚未接入真实 prepare 链路的数据源配置，例如 Landsat，但文档和产品能力说明必须区分：

- registered configuration；
- enabled real execution path。

当前真实 `raster_prepare` 只执行 Sentinel-2。

## Compiler / Executor 分离

Compiler 只生成 `tool_calls`，不执行工具。Executor 按 `runtime.current_tool_index` 单步执行一个 tool call。

这种分离带来几个好处：

- 工具调用计划可以被测试和审计；
- executor 可以在每个工具后交给 workflow routing；
- validator / adjuster 可以只处理刚执行完成的工具；
- retry 时只需要把 `current_tool_index` 拉回目标 tool call。

## Validator / Adjuster 只处理 Tool Call，不改 Plan

当前只有 `raster_prepare` 的 tool rule。validator 根据 diagnostics 判断：

- `passed`：继续后续工具；
- `retryable`：进入 adjuster；
- `failed`：终止并交给 answer fallback。

Adjuster 不直接修改 `state.plan`。它只更新目标 `tool_call.params`，写入 retry runtime 信息，并让 executor 重试该工具。

这样可以保留用户原始意图，同时记录每次工程参数调整。

## 统一输出命名

最终用户-facing 输出统一命名：

```text
metadata.json
preview.png
result.tif
```

不再使用指数名作为文件名。产品类型、指数名、公式、数据源、时间范围和空间信息写入 `metadata.json`。

原因：

- 后续部署调用可以稳定读取固定文件；
- 不需要根据用户请求推断输出文件名；
- 输出路径可以被前端和 API 简化处理。

## Metadata 不是 AgentState Dump

`metadata.json` 是面向用户和结果溯源的精简产品信息，不是完整 `AgentState` dump。

它由 `metadata.export_metadata` 从 plan、runtime registry、tool_results、raster_prepare diagnostics、validator 结果和最终 GeoTIFF profile 中抽取关键字段。

这样可以避免把内部 tool calls、prompt、临时路径和运行时控制字段暴露为用户结果。

## Workspace 清理策略

V1 使用本地 workspace。处理过程中会出现 AOI、下载影像、mosaic raster、clipped raster 等中间数据，但最终用户侧只保留：

```text
data/<uuid>/output/
  metadata.json
  preview.png
  result.tif
```

`raster_prepare` 删除 AOI、download 和 mosaic 中间目录；`index_calculation` 消费 clipped bands 后删除 `clipped_raster/`。

V2 可以引入 job lifecycle manager，例如结果保留 30 分钟后自动删除整个 workspace。

## V1 边界

V1 不声明支持：

- production-ready 部署；
- 全球任意区域稳定运行；
- 所有遥感产品；
- GEE；
- 多数据源自动选择；
- DEM、population、night lights、land cover 产品；
- Web 前端和用户系统。

这些属于 V2/V3 或 future research 方向。
