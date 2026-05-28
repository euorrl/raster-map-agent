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

### `app/schemas`

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
- `plan`：结构化任务计划，例如 AOI、指数类型、日期、数据源和可调参数
- `workspace`：任务工作区信息，例如 `run_id` 和 `workspace_dir`
- `tool_results`：各工具的原始返回结果，按工具名分区保存
- `metadata`：最终记录和导出用的元数据分区
- `runtime`：workflow 运行时控制信息，例如 tool plan、retry 次数、validator 结果、adjuster 结果和局部 ReAct 状态
- `final_answer`：最终返回给用户的答案
- `status`：当前 workflow 状态
- `errors`：追加式错误列表
- `warnings`：追加式警告列表

`plan`、`workspace`、`tool_results`、`metadata`、`runtime` 使用递归 dict reducer。节点只需要返回局部更新，LangGraph 会把它合并进已有 state。

### `app/tools`

真实领域工具层。工具应尽量保持确定性、可单独测试、可离线调用，不直接依赖 LLM。

当前工具：

```text
app/tools/workspace/
app/tools/raster_prepare/
app/tools/index_calculation/
app/tools/render_preview/
```

职责：

- `workspace`：创建 `data/<uuid>/` 任务工作区
- `raster_prepare`：AOI 解析、scene plan、下载、mosaic、clip，输出裁剪后的 band GeoTIFF
- `index_calculation`：根据 band roles 和 formula 计算指数 GeoTIFF
- `render_preview`：根据 registry 渲染配置生成 PNG 预览图

### `app/registry`

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

### `app/agent`

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

当前分支已经引入智谱全局 planner、agent 层验证和调整策略。planner 负责把
自然语言需求转换成受约束的 `state.plan`，并把工具调用顺序写入
`runtime.tool_plan`，但暂未强制接入 mock workflow。
当前 `raster_prepare` 的治理关系由 `policies.py` 注册：

```text
raster_prepare
  validator: raster_prepare_validator
  adjuster: raster_prepare_adjuster
  max_retries: 5
```

长期目标是：

```text
tool 执行 -> validator 检查 -> adjuster 调整参数 -> runtime 记录 retry -> 路由决定继续/重试/失败
```

### `app/workflows`

保存 LangGraph workflow builder。

当前 `develop` 基线中仍然是：

```text
app/workflows/v1_workflow.py
```

它仍使用 mock nodes 验证 state 流转。后续工具接入分支会把 workflow 收敛为更粗粒度的状态转折点，例如：

```text
planner
-> registry
-> workspace
-> raster_prepare
-> raster_prepare_validator
-> product_generation
-> answer
```

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
