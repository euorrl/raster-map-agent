# Raster Map Agent

Raster Map Agent 是一个自然语言驱动的遥感制图 Agent 项目。它的目标不是只写一个遥感处理脚本，而是逐步构建一个能够理解用户需求、准备空间数据、生成地图产品并解释结果的本地 Agent。

## 当前 V1 目标

V1 聚焦一个可落地的本地流程：

```text
用户自然语言请求
-> planner 生成结构化计划
-> registry 补全指数、波段、公式和渲染配置
-> workspace 创建任务目录
-> raster_prepare 准备真实 Sentinel-2 输入数据
-> index_calculation 计算 NDVI/NDWI
-> render_preview 生成 PNG 预览图
-> metadata 导出 JSON
-> answer 生成最终说明
```

当前真实工具链已经完成到：

```text
workspace
-> Nominatim AOI
-> Sentinel-2 scene planning
-> coverage diagnostics
-> raster download
-> first mosaic by band
-> AOI clip
-> index GeoTIFF
-> preview PNG
-> metadata JSON
-> final answer
```

Agent 层已经具备智谱全局 planner、raster_prepare validator、adjuster 和 tool rules 注册表。当前 `app/workflows/v1_workflow.py` 仍是 mock workflow，用于验证 LangGraph state 传递；真实 planner 和工具链接入 workflow 是下一步集成任务。

## 当前架构重点

### 动态 AgentState

`AgentState` 采用动态分区结构：

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

其中 `runtime` 是运行时控制分区，用于保存 planner 结果、tool plan、retry 次数、validator 结果、adjuster 结果和局部 ReAct 状态。

### 工具层与 Agent 层分离

项目刻意保持边界：

- `tools/` 负责确定性的领域能力
- `agent/` 负责规划、验证、调整、路由和恢复策略

因此 `raster_prepare` 不直接内置 LLM ReAct。当前局部 ReAct 的基础已经放在 agent 层：

```text
zhipu global planner
-> structured state.plan
-> workflow template compiler
-> raster_prepare validator
-> raster_prepare adjuster
-> tool rules registry
-> runtime retry count
```

planner 负责把自然语言需求转换为受约束的结构化 plan。`state.plan` 只保留 route、answer_mode、AOI、产品/指数、日期和云量这类核心业务参数；工具链顺序后续由系统根据 route 和 workflow template 编译到 `state.tool_calls`。validator 负责确定性验收，adjuster 通过智谱模型提出下一轮参数建议，tool rules 负责限制最大重试 5 次。

## 主要文档

- [项目架构](architecture.md)
- [栅格工具链](raster-toolchain.md)
- [Scene 选择算法迭代](scene-selection-evolution.md)
- [关键设计决策](design-decisions.md)
- [开发日志](development-log.md)
- [路线图](roadmap.md)
