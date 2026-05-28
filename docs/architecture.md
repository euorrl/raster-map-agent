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

当前核心原则：

```text
registry 负责系统支持什么
planner 负责理解用户想做什么
workflow/template/rules 负责系统怎么执行
tools 负责确定性领域计算
state 负责节点间共享上下文
```

## `app/schemas`

保存跨模块共享的数据结构。当前最重要的是 `AgentState`。

`AgentState` 顶层字段：

```text
user_query
plan
tool_calls
workspace
tool_results
runtime
final_answer
status
errors
warnings
```

字段含义：

- `user_query`：用户原始输入
- `plan`：planner 生成的结构化用户任务意图
- `tool_calls`：compiler 生成的带参数工具调用计划
- `workspace`：任务工作区信息，例如 `run_id` 和 `workspace_dir`
- `tool_results`：各工具的原始返回结果，按工具名分区保存
- `runtime`：workflow 运行时控制信息
- `final_answer`：最终返回给用户的文本答案
- `status`：当前 workflow 状态
- `errors`：追加式错误列表
- `warnings`：追加式警告列表

`plan`、`workspace`、`tool_results`、`runtime` 使用递归 dict reducer。节点只需要返回局部更新，LangGraph 或 fallback runner 会把它合并进已有 state。当前 state 不包含 `metadata` 分区，避免把完整中间状态混入最终产品说明。

当前没有单独的 `resolved` 字段。registry 解析结果在过渡期写入：

```python
state.runtime["registry"]["raster_product"]
```

当前 compiler 会把 registry 解析结果编译进
`state.tool_calls[*]["params"]`。`runtime["registry"]` 仍作为过渡期真实节点执行
的上下文保留。

## `app/registry`

保存稳定知识和产品能力配置。

当前主要文件：

```text
app/registry/raster_products.py
```

当前 registry 包含：

- Sentinel-2 数据源配置
- Landsat 注册信息
- NDVI / NDWI 指数配置
- band roles
- index formula
- render config
- STAC provider / collection / asset mapping

V1 的真实 `raster_prepare` 只执行 Sentinel-2；Landsat 当前是 registry-only 能力。

Registry 不保存 workflow template、tool order、validator、adjuster 或 retry 规则。

## `app/tools`

真实领域工具层。工具应保持确定性、可单独测试、可离线调用，并且不直接读写 `AgentState`。

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
- `metadata`：从 state snapshot 抽取用户关心的产品信息，导出为 `output/metadata.json`
- `answer`：通过 LLM 生成最终回答，支持 `metadata_summary` 和 `direct_answer`

部分 GIS 工具依赖 `rasterio`。包入口采用懒加载，避免仅导入 workflow 或 schema 时强制要求完整 GIS 依赖。

## `app/agent`

Agent 控制组件层。它不承载稳定产品知识，也不直接执行 GIS 计算。

当前结构：

```text
app/agent/
  nodes.py
  planners/
    zhipu_planner.py
  validators/
    raster_prepare_validator.py
  adjusters/
    raster_prepare_adjuster.py
```

职责：

- `nodes.py`：当前 workflow 节点函数
- `planners/`：把自然语言需求转换为结构化 `state.plan`
- `validators/`：检查工具结果是否可继续、可重试或失败
- `adjusters/`：根据 validator diagnostics 生成有限参数调整

Planner 不输出工具调用顺序，不生成 `tool_calls`，不决定 validator、adjuster 或 retry。

## `app/workflows`

保存 workflow 编排层。

当前结构：

```text
app/workflows/
  compiler.py
  workflow.py
  templates.py
  tool_rules.py
```

职责：

- `templates.py`：route 到工具序列骨架的注册表
- `compiler.py`：根据 `plan + registry + workflow template` 生成 `tool_calls`
- `tool_rules.py`：工具结果后处理规则，包含 validator、adjuster、最大 retry 次数
- `workflow.py`：当前 V1 workflow graph；缺少 LangGraph 时提供线性 fallback runner

当前支持两个 route：

```text
raster_product_generate
direct_answer
```

`raster_product_generate` 模板声明的目标工具序列：

```text
workspace.create_workspace
raster_prepare.prepare_raster_inputs
index_calculation.calculate_raster_index
render_preview.render_index_preview
metadata.export_metadata
answer.generate_final_answer
```

当前 `workflow.py` 仍以节点方式显式执行真实工具，但已经在 planner/registry 后
编译 `state.tool_calls`。executor 尚未实现。

当前节点流程：

```text
planner
-> registry
-> compiler
-> workspace
-> raster_prepare
-> raster_prepare_validator
-> product_generation
-> answer
```

其中 `product_generation` 当前封装 index calculation、preview rendering 和 metadata export。

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
