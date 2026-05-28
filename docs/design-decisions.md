# 关键设计决策

本文记录项目中的重要取舍，避免后续忘记为什么这样设计。

## 先工具链，后 Agent

项目最终目标是本地完整 Agent，但实现顺序不是先写复杂 Agent。

当前策略：

```text
先让真实工具链可运行
再让 planner 生成受约束 plan
再加入 validator / adjuster 局部恢复能力
再接入 workflow template、compiler 和 executor
```

原因：

- 工具输入输出稳定后，Agent 节点更容易设计
- 避免 LLM 层掩盖底层 GIS 工具不稳定的问题
- 本地能跑出真实图后，项目价值更明确

## 工具层与控制层分离

`app/tools` 保存确定性的领域工具：

```text
workspace
raster_prepare
index_calculation
render_preview
metadata
answer
```

工具应尽量：

- 输入输出清晰
- 可单独测试
- 不直接读取 `AgentState`
- 不承担 workflow 路由职责

`app/agent` 保存控制组件：

```text
nodes
planners
validators
adjusters
```

`app/workflows` 保存编排规则：

```text
workflow graph
workflow templates
tool rules
```

因此当前边界是：

```text
tool 负责做事
planner 负责把自然语言转换成结构化计划
validator 负责验收
adjuster 负责有限参数修正
tool_rules 负责声明 tool / validator / adjuster / retry 的关系
workflow 负责路由和编排
```

`answer` 工具有 LLM 调用，但它仍是最终产物生成器，不是控制层 planner。

## 为什么不让 LLM 完全自由控制 tool

GIS 处理有明确依赖：

```text
没有 workspace 不能稳定保存文件
没有 prepared raster 不能计算指数
没有 index GeoTIFF 不能渲染 preview
没有 metadata 很难生成可信最终回答
```

所以 V1 不追求完全自由 tool planning，而采用：

```text
LLM planner 负责用户意图和初始业务参数
workflow template 负责工具骨架
compiler 负责生成 tool_calls
executor 负责执行 tool_calls
validator / adjuster 负责局部恢复
```

这比纯 pipeline 更有反馈能力，也比完全自由 agent 更稳定。

## Planner 只生成 plan

全局 planner 位于：

```text
app/agent/planners/zhipu_planner.py
```

Planner 只写：

```text
state.plan
state.metadata["plan"]
state.runtime["planners"]["global"]
```

`state.plan` 只保存 LLM 真正需要决策的核心业务字段：

```text
route
answer_mode
aoi_query
index_name
start_date
end_date
max_cloud_cover
```

Planner 不生成 `tool_calls`。后续 `tool_calls` 将由系统 compiler 根据 `plan + registry + workflow template` 生成。

Planner 也不写这些内部字段：

```text
data_source
workspace_dir
band_roles
index_formula
scene_limit
max_selected_scenes
validator
adjuster
retry
```

这些由 registry、tool schema、workflow template 和 tool rules 控制。

## 为什么删除 `resolved`

曾经考虑过在 `AgentState` 中加入 `resolved`，用于保存 registry 解析后的配置。

最终删除该字段，原因是：

- `tool_calls` 未来会保存带参数的工具调用计划
- registry 解析结果最终应进入 `tool_calls.params`
- 额外的 `resolved` 容易和 `tool_calls` 职责重叠
- state 顶层字段应尽量稳定和少

当前过渡方案：

```python
state.runtime["registry"]["raster_product"]
```

用于保存当前节点执行需要的 registry 解析结果。同时也写入：

```python
state.metadata["registry"]
```

用于最终记录和回答生成。

当 compiler 实现后，这部分配置会被编译进 `tool_calls.params`。

## Registry 负责知识，Tools 负责执行

指数、公式、波段角色和数据源配置属于稳定知识，不应散落在工具 schema 或 LLM 输出中。

当前约定：

```text
planner -> 输出 route + answer_mode + aoi_query + index_name + date range + max_cloud_cover
registry -> 展开 data_source / required_bands / band_roles / formula / render_config / STAC asset mapping
raster_prepare -> 准备裁剪后的 band GeoTIFF
index_calculation -> 根据 band_roles + formula 计算指数
render_preview -> 根据 index_name 和 render_config 渲染预览 PNG
```

这样 LLM 不需要直接输出公式或猜波段。

## 为什么引入 route 和 answer_mode

并不是所有用户输入都应该进入栅格工作流。例如：

```text
什么是遥感？
你支持哪些地图？
生成成都人口密度图
```

如果当前 registry 不支持用户请求的产品，强行映射到 NDVI/NDWI 会产生错误结果。

因此 planner 输出：

```text
route = raster_product_generate | direct_answer
answer_mode = metadata_summary | direct_answer
```

- `raster_product_generate`：用户请求可由当前注册表和工具链完成
- `direct_answer`：普通问答、无关问题、系统能力询问，或当前未支持产品

这样 final answer 节点可以选择：

- 基于 metadata 总结真实 workflow 结果
- 直接回答用户问题或说明当前不支持

## 为什么不把 ReAct 放进 raster_prepare

`raster_prepare` 本质是数据准备工具：

```text
AOI + 日期 + 指数 + 数据源 -> clipped band GeoTIFF
```

如果把 LLM ReAct 直接塞进 `raster_prepare`，它会从确定性工具变成一个小 agent，导致：

- 工具层和控制层边界模糊
- 离线复用和单元测试变困难
- 后续其他工具难以复用统一验证策略

因此局部 ReAct 放在 agent/workflow 控制层。

## V1 数据源固定为 Sentinel-2

Registry 已经保留 Landsat 的基础配置，但当前 `raster_prepare` 只真正执行 Sentinel-2。

原因：

- Sentinel-2 L2A 已能满足 V1 的 NDVI/NDWI 本地流程验证
- 多 provider 会引入不同 STAC endpoint、asset 命名和下载规则
- Landsat 不会从根本上解决超大 AOI 下载压力

因此 V1 adjuster 只允许有限调整：

- 日期范围，优先向前扩展 `start_date`
- 云量阈值，尽量少改，只能递增且不超过 30

而不是自动切换 provider。

## AOI 数据源从 geoBoundaries 切到 Nominatim

最初考虑 geoBoundaries，因为它有清晰行政区 API 和 GeoJSON。

后来发现：

- 国内省市县效果较差
- ADM 层级对用户和 LLM 都不直观
- `gbAuthoritative` 覆盖范围有限

因此改为 Nominatim / OpenStreetMap。

新的输入协议更简单：

```text
query + workspace_dir
```

LLM 负责把地点整理成更适合查询的自然语言地址，例如：

```text
Chengdu, Sichuan, China
Hangzhou, Zhejiang, China
```

## 输出目录统一放入 workspace

每次任务先创建：

```text
data/<uuid>/
```

最终输出统一放在：

```text
data/<uuid>/output/
```

不再使用项目根目录下的外部 `outputs/` 作为主要输出位置。
