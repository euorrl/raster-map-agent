# Raster Map Agent

Raster Map Agent 是一个自然语言驱动的遥感制图 Agent 项目。它的目标不是只写一个遥感处理脚本，而是逐步构建一个能够理解用户需求、准备空间数据、生成地图产品并解释结果的本地 Agent。

## 当前 V1 目标

V1 聚焦一个可落地的本地流程：

```text
用户自然语言请求
-> planner 生成结构化 plan
-> registry 解析已注册产品能力
-> workspace 创建任务目录
-> raster_prepare 准备真实 Sentinel-2 输入数据
-> validator 检查 raster_prepare 结果
-> index_calculation 计算 NDVI/NDWI
-> render_preview 生成 PNG 预览图
-> metadata 导出 JSON
-> answer 生成最终说明
```

当前代码已经从纯 mock workflow 进入真实工具节点编排阶段。`app/workflows/workflow.py` 是当前入口；如果本地没有安装 LangGraph，会使用等价的线性 fallback runner，方便在轻量环境中验证核心逻辑。

## 架构重点

### State 分区

`AgentState` 采用稳定顶层字段和动态分区：

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

关键边界：

- `plan`：planner 生成的用户任务意图
- `tool_calls`：后续 compiler 生成的带参数工具调用计划
- `runtime`：运行时控制信息，例如 planner 结果、registry 解析结果、validator/adjuster 结果、retry count

项目不再保留单独的 `resolved` state 分区。当前 registry 解析结果暂存在 `runtime["registry"]["raster_product"]`，后续 compiler 落地后会直接编译进 `tool_calls.params`。

Metadata 导出不依赖 state 中的 metadata 分区。`metadata.export_metadata`
接收 state snapshot，并抽取精简产品信息对象，用于最终回答和用户查看。

### Planner

Planner 位于：

```text
app/agent/planners/zhipu_planner.py
```

它只负责把自然语言需求转换为受约束的 `state.plan`。Planner 不决定底层工具顺序，不生成 `tool_calls`，也不决定 validator、adjuster 或 retry。

### Workflows

Workflow 编排相关文件位于：

```text
app/workflows/
  workflow.py
  templates.py
  tool_rules.py
```

- `templates.py` 声明 route 对应的工具序列骨架
- `tool_rules.py` 声明工具结果后处理规则，例如 validator、adjuster 和最大 retry 次数
- `workflow.py` 负责当前 V1 图编排和 fallback runner

### Tools

`app/tools` 保存确定性的领域能力。工具不直接读写 `AgentState`，而是通过请求/结果 schema 与节点交互。

当前工具包括：

```text
workspace
raster_prepare
index_calculation
render_preview
metadata
answer
```

## 主要文档

- [项目架构](architecture.md)
- [栅格工具链](raster-toolchain.md)
- [Scene 选择算法迭代](scene-selection-evolution.md)
- [关键设计决策](design-decisions.md)
- [开发日志](development-log.md)
- [路线图](roadmap.md)
