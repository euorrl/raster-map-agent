# 项目架构

本文记录当前项目的代码结构、状态设计和模块边界。

## 总体分层

```text
app/
  agent/
  registry/
  schemas/
  tools/
  workflows/
```

## `app/schemas`

保存跨模块共享的数据结构。当前最重要的是 `AgentState`。

`AgentState` 采用“稳定顶层 + 动态分区”的设计：

```text
user_query
plan
workspace
tool_results
metadata
runtime
final_answer
status
errors
warnings
```

字段含义：

- `user_query`：用户原始输入
- `plan`：结构化任务计划，例如 `response_mode`、AOI、指数、日期和云量
- `workspace`：任务工作区信息，例如 `run_id` 和 `workspace_dir`
- `tool_results`：各工具的原始返回结果，按工具名分区保存
- `metadata`：最终记录、导出和回答生成用的元数据分区
- `runtime`：workflow 运行时控制信息，例如 planner 结果、tool plan、retry 次数、validator 和 adjuster 结果
- `final_answer`：最终返回给用户的答案
- `status`：当前 workflow 状态
- `errors`：追加式错误列表
- `warnings`：追加式警告列表

`plan`、`workspace`、`tool_results`、`metadata`、`runtime` 使用递归 dict reducer。节点只需要返回局部更新，LangGraph 会把它合并进已有 state。

## `app/tools`

真实领域工具层。工具应尽量保持确定性、可单独测试、可离线调用，并且不直接读写 `AgentState`。

当前工具：

```text
app/tools/workspace/
app/tools/raster_prepare/
app/tools/index_calculation/
app/tools/render_preview/
app/tools/metadata/
app/tools/answer/
```

职责：

- `workspace`：创建 `data/<uuid>/` 任务工作区
- `raster_prepare`：AOI 解析、scene plan、下载、mosaic、clip，输出裁剪后的 band GeoTIFF
- `index_calculation`：根据 band roles 和 formula 计算指数 GeoTIFF
- `render_preview`：根据 registry 渲染配置生成 PNG 预览图
- `metadata`：将 workflow metadata 导出为 `output/metadata.json`
- `answer`：通过 LLM 生成最终回答，支持 `metadata_summary` 和 `direct_answer`

注意：`answer` 是 tools 中少数需要 LLM 的工具。它仍被放在工具层，是因为它是最终产物生成器，而不是 planner 或 adjuster 这样的控制组件。测试通过 fake client 注入，不依赖真实 API key。

## `app/registry`

保存稳定知识和配置：

- 数据源配置
- 指数公式
- band roles
- STAC asset 映射
- 渲染参数

当前主要文件：

```text
app/registry/raster_products.py
```

目前 registry 已包含 Sentinel-2、Landsat 的基础配置，以及 NDVI / NDWI 的数据源波段映射。V1 的真实 `raster_prepare` 只执行 Sentinel-2。

## `app/agent`

Agent 控制层。它不直接承担 GIS 计算，而是负责：

- LangGraph 节点
- planner
- validator
- adjuster
- tool policy
- 后续局部 ReAct

当前结构：

```text
app/agent/
  nodes.py
  policies.py
  planners/
    zhipu_planner.py
  validators/
    raster_prepare_validator.py
  adjusters/
    raster_prepare_adjuster.py
```

全局 planner 负责把自然语言需求转换成受约束的 `state.plan`，并把工具调用顺序写入 `runtime.tool_plan`。

当前 planner 支持两种模式：

- `raster_workflow`：正常执行栅格专题图 workflow
- `direct_answer`：与当前栅格 workflow 无关的问题，或请求未注册产品时，直接进入最终回答

`raster_prepare` 的治理关系由 `policies.py` 注册：

```text
raster_prepare
  validator: raster_prepare_validator
  adjuster: raster_prepare_adjuster
  max_retries: 5
```

长期目标是：

```text
tool 执行
-> validator 检查
-> adjuster 调整参数
-> runtime 记录 retry
-> 路由决定继续、重试或失败
```

## `app/workflows`

保存 LangGraph workflow builder。

当前工具集成分支的真实 workflow 入口是：

```text
app/workflows/workflow.py
```

它已经开始编排真实工具节点：

```text
planner
-> registry
-> workspace
-> raster_prepare
-> raster_prepare_validator
-> product_generation
-> answer
```

其中 `product_generation` 当前包含：

```text
index_calculation
render_preview
metadata export
```

workflow 也已预留 `direct_answer` 路由：当 `state.plan.response_mode == "direct_answer"` 时，可以跳过栅格工具，直接进入 answer 节点。

## 数据目录

本地运行数据保存在：

```text
data/<uuid>/
```

典型结构：

```text
data/<uuid>/
  aoi/
  clipped_raster/
  output/
```

中间目录 `raster/` 和 `mosaic_raster/` 在 prepare 成功后会被清理。

最终输出放在：

```text
data/<uuid>/output/
```

例如：

```text
data/<uuid>/output/ndvi.tif
data/<uuid>/output/ndvi_preview.png
data/<uuid>/output/metadata.json
```
