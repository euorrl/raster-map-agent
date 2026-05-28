# 关键设计决策

本文记录项目中比较重要的取舍，避免后续忘记为什么这样设计。

## 先工具链，后 Agent

项目最终目标是本地完整 Agent，但实现顺序不是先写复杂 Agent。

当前策略：

```text
先让真实工具链可运行
再让 planner 生成参数
再加入 validator / adjuster 局部 ReAct
最后接入 LangGraph 完整 workflow
```

原因：

- 工具输入输出稳定后，Agent 节点更容易设计
- 避免 LLM 层掩盖底层 GIS 工具不稳定的问题
- 本地能跑出真实图后，作品集展示价值更明确

## 工具层与 Agent 层分离

`app/tools` 保存确定性的领域工具：

```text
workspace
raster_prepare
index_calculation
render_preview
```

这些工具应该尽量：

- 输入输出清晰
- 可单独测试
- 不依赖 LLM
- 不直接读取 AgentState

`app/agent` 保存控制逻辑：

```text
nodes
planners
validators
adjusters
policies
```

也就是说：

```text
tool 负责做事
planner 负责把自然语言转换成结构化计划
validator 负责验收
adjuster 负责修正参数
policy 负责规定 tool、validator、adjuster 和 retry 的关系
workflow 负责路由
```

## 为什么不把 ReAct 放进 raster_prepare

`raster_prepare` 本质是数据准备工具：

```text
AOI + 日期 + 指数 + 数据源
-> clipped band GeoTIFF
```

如果把 LLM ReAct 直接塞进 `raster_prepare`，它会从确定性工具变成一个小 agent，导致：

- 工具层和 Agent 层边界模糊
- 离线复用和单元测试变困难
- 后续其他工具也难以复用统一验证策略

因此局部 ReAct 放在 agent 层更合适。

## 为什么保留强约束 workflow

GIS 处理有明确依赖：

```text
没有 workspace 不能稳定保存文件
没有 prepared raster 不能计算指数
没有 index GeoTIFF 不能渲染 preview
```

所以 V1 不追求完全自由 tool planning，而采用：

```text
LLM planner 负责计划和初始参数
Graph 负责执行顺序
Validator 负责质量检查
Adjuster 负责有限参数修正
```

这是一种受约束的 Agent workflow，比纯 pipeline 更有反馈能力，也比完全自由 agent 更稳定。

## Registry 负责知识，Tools 负责执行

指数、公式、波段角色和数据源配置属于稳定知识，不应散落在工具 schema 中。

当前约定：

```text
planner -> 输出 aoi_query + index_name + date range + max_cloud_cover
registry -> 展开 required_bands / band_roles / formula / render_config / STAC asset mapping
raster_prepare -> 准备裁剪后的 band GeoTIFF
index_calculation -> 根据 band_roles + formula 计算指数
render_preview -> 根据 index_name 和 render_config 渲染预览 PNG
```

这样 LLM 不需要直接输出公式或猜波段。

## Planner 是 Agent 组件，不是 Tool

全局 planner 使用智谱模型，但它不放在 `app/tools`。原因是 planner 的职责不是
执行领域计算，而是控制层的“理解需求与生成计划”。

当前约定：

```text
app/agent/planners/zhipu_planner.py
```

planner 的输出分成两部分：

```text
state.plan
runtime.tool_plan.steps
```

`state.plan` 只保留需要 LLM 决策的核心业务参数：

```text
aoi_query
index_name
start_date
end_date
max_cloud_cover
```

`runtime.tool_plan.steps` 保存 planner 给出的工具调用顺序和参数映射。当前 V1
只允许受支持的工具名，且会把每一步参数规范化，避免 LLM 把内部工程参数写乱。

planner 不会把 `data_source`、`need_render`、`include_colorbar`、
`need_metadata`、`scene_limit`、`max_selected_scenes`、`workspace_dir`
写入 `state.plan`。这些固定策略和工程参数仍由 registry、tool schema 和
policy 控制。

## V1 数据源固定为 Sentinel-2

Registry 已经保留 Landsat 的基础配置，但当前 `raster_prepare` 只真正执行 Sentinel-2。

原因：

- Sentinel-2 L2A 已能满足 V1 的 NDVI/NDWI 本地流程验证
- 多 provider 会引入不同 STAC endpoint、asset 命名和下载规则
- Landsat 不会从根本上解决超大 AOI 下载压力

因此 V1 的 ReAct 只允许有限调整：

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

## coverage 阈值不是 100%

Sentinel-2 scene footprint 与 AOI 几何存在真实空间关系，不应只用 bbox 最值判断。

当前 coverage diagnostics 使用：

```text
scene footprint union 对 AOI GeoJSON geometry 的覆盖率
```

V1 不强制 100% 覆盖，而使用较高但可接受的阈值：

```python
min_coverage_ratio = 0.7
```

失败时 diagnostics 会提供是否可重试、失败原因和建议动作。
