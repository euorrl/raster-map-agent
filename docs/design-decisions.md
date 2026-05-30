# 关键设计决策

本文记录当前 V1 中仍然有效的设计决策。

## 受控型 Workflow，而不是自由 Tool Calling

LLM 只负责理解用户意图和生成结构化 `state.plan`。底层工具顺序、参数来源、validator 和 retry 逻辑由系统控制。

原因：

- GIS 任务往往具有严格的数据接入要求；
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

## Registry 是产品能力边界

当前 V1 支持 6 个 Sentinel-2 指数：

- NDVI
- SAVI
- NDWI
- NDMI
- NDBI
- NBR

使用产品 Registry 可以很方便地拓展不同的卫星与指数配置。当前真实 `raster_prepare` 只执行 Sentinel-2。

## Route templates

将不同任务中工具的组合以及关系设计为注册表形式，这样 planner 只需要选择高度抽象并且区分度明显的workflow, 提高 plnner 的准确性。此外，templates 分摊了项目的结构复杂度，可以让 nodes 变为极简，从而大大减轻 graph 的复杂度。

## tool rules
包含需要检验的函数的 validator 和 adjuster，用于在分布 tool executor 执行时检测单步 tool call是否需要检测，具备对于不同的 tool calls 动态组合 validator/adjuster 的能力。同时还包含`根据tool call id 判断是否存在 tool rules`以及`判断 adjuster 的 retry 次数是否已经达到阈值`的函数。

## Compiler / Executor

Compiler 只生成 `tool_calls`，不执行工具。Executor 按 `runtime.current_tool_index` 单步执行一个 tool call。

这种设计带来几个好处：

- 工具调用计划可以被测试和审计；
- 分步 executor 可以在每个工具执行后根据 tool rules 判断是否需要检测；
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

