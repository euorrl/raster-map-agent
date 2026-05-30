# 项目架构

本文记录当前 V1 的代码结构、workflow 架构和主要节点职责。以当前实现为准，V1 是一个受控型 workflow agent，而不是让 LLM 自由调用底层工具的 agent。

## 总体定位

Raster Map Agent 当前是一个本地端到端可运行的 Sentinel-2 raster map generation agent。

核心原则：

```text
planner 负责理解用户想做什么
registry 负责系统支持什么产品
compiler 负责把 plan 编译成受控 tool calls
executor 负责单步执行 tool calls
validator / adjuster 负责工具后的质量检查和有限重试
tools 负责确定性的遥感数据处理
answer 负责最终面向用户的回答
```

## 代码结构

```text
app/
  agent/
    nodes.py
    planners/
    validators/
    adjusters/
  registry/
  schemas/
  tools/
    workspace/
    raster_prepare/
    index_calculation/
    render_preview/
    metadata/
    answer/
  workflows/
    templates.py
    compiler.py
    executor.py
    tool_rules.py
    workflow.py
```

## AgentState

`AgentState` 是 workflow 中共享的状态对象，主要字段包括：

- `user_query`：用户原始请求；
- `plan`：planner 生成的结构化任务计划；
- `tool_calls`：compiler 生成的受控工具调用列表；
- `workspace`：当前任务 workspace 信息；
- `tool_results`：各工具执行结果；
- `runtime`：planner、registry、compiler、executor、validator、adjuster 等运行时信息；
- `final_answer`：最终回答；
- `status`：当前 workflow 状态；
- `errors` / `warnings`：追加式错误和警告。

`plan`、`workspace`、`tool_results`、`runtime` 使用递归合并语义，节点只需要返回局部更新。

## 当前 Workflow

当前准确的高层流程是：

```text
planner
-> route decision
-> registry if raster task
-> compiler
-> execute_tool loop
-> optional validate_tool / adjust_tool loop
-> final answer
```

`workflow.py` 提供 LangGraph graph；缺少 LangGraph 时使用 `_LinearWorkflow` fallback runner，模拟同样的执行顺序。

## 节点职责

### planner_node

`planner_node` 调用 planner，解析用户自然语言请求，生成 `state.plan`，并决定 route。

当前 route：

- `raster_product_generate`：已支持的 raster map generation 任务；
- `direct_answer`：普通问题、系统能力问题、当前不支持的产品请求。

planner 只生成结构化 plan，不生成 `tool_calls`，也不决定底层工具顺序、band roles、index formula、validator 或 retry 参数。planner runtime 信息写入 `runtime["planners"]["global"]`。

### registry_node

`registry_node` 仅 raster route 使用。它根据 `state.plan["index_name"]` 和数据源解析 raster product 配置，并写入：

```python
runtime["registry"]["raster_product"]
```

当前真实 raster preparation 只接入 Sentinel-2。Registry 中存在 Landsat 基础配置，但 V1 不把 Landsat 写成真实可执行链路。

### compiler_node

`compiler_node` 将 `state.plan`、registry 配置和 workflow template 编译成标准 `tool_calls`，并初始化 `runtime.current_tool_index`。

这样做的目的：

- 不让 LLM 自由决定底层工具参数；
- 将工具顺序固定在 workflow template 中；
- 让 executor 通过 `$state...` 引用在运行时解析依赖结果。

### tool_executor_node

`tool_executor_node` 每次只执行一个 tool call。它读取：

```python
runtime["current_tool_index"]
```

然后执行 `tool_calls[current_tool_index]`，将结果写入 `workspace`、`tool_results` 或 `final_answer`，并把 `current_tool_index` 推进到下一个工具。

executor 还会记录：

- `runtime.last_tool_index`
- `runtime.last_tool_call_id`
- `runtime.last_tool_name`

这些字段用于后续 validator / adjuster routing。

### tool_validator_node

如果刚执行完成的 tool call 存在 tool rule，workflow 会进入 validator。当前只有 `raster_prepare` 的 tool rule。

`raster_prepare` validator 重点检查：

- 是否存在 raster prepare 结果；
- registry 或 prepare 结果中的 required bands；
- diagnostics 是否存在；
- coverage 是否达到要求；
- 所需 band path 是否存在。

validator 只判断 `passed`、`retryable` 或 `failed`，不修改 tool call 参数，也不执行工具。

### tool_adjuster_node

当 validator 判断结果可重试时，workflow 进入 adjuster。

当前 `raster_prepare` adjuster 会：

- 读取上一次 `raster_prepare` 的 tool call params；
- 根据 validator 的 suggested actions 调整允许的字段；
- 可调整 `start_date`、`end_date`、`max_cloud_cover`；
- 不修改 `state.plan`；
- 更新对应 `tool_calls[last_tool_index].params`；
- 写入 `runtime.adjustments` 和 `runtime.retry_counts`；
- 将 `runtime.current_tool_index` 拉回对应工具，使 executor 重试。

最大 retry 次数为 5。

### answer.generate_final_answer

`answer.generate_final_answer` 当前通常作为最后一个 tool call 执行。

- raster route 基于 `metadata.export_metadata` 产出的 product info 生成最终回答；
- direct answer route 直接回答普通问题、系统能力问题或不支持的产品请求；
- 对不支持产品，应诚实说明当前暂不支持，而不是强行映射到已有指数。

### answer_node

`answer_node` 现在主要是安全兜底和终止节点：

- 如果 `final_answer` 已存在，直接返回；
- 如果 workflow 在 answer tool 前失败，生成失败回答；
- 如果没有 final answer 且 workflow 未失败，生成兜底回答。

## Tool Call 顺序

`raster_product_generate` route 的 compiler 输出：

```text
1. workspace.create_workspace
2. raster_prepare.prepare_raster_inputs
3. index_calculation.calculate_raster_index
4. render_preview.render_index_preview
5. metadata.export_metadata
6. answer.generate_final_answer
```

`direct_answer` route 的 compiler 输出：

```text
1. answer.generate_final_answer
```

## 输出目录

最终用户-facing 输出统一为：

```text
data/
  <uuid>/
    output/
      metadata.json
      preview.png
      result.tif
```

中间目录如 `aoi/`、`raster/`、`mosaic_raster/`、`clipped_raster/` 只在处理过程中临时存在。`raster_prepare` 会删除 AOI、下载影像和 mosaic 中间目录，`index_calculation` 消费 clipped bands 后会删除 `clipped_raster/`。
