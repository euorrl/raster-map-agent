# 开发日志

本文按阶段记录项目从工程骨架到真实工具链，再到 Agent 控制层的演进。

## 阶段 1：项目工程初始化

完成：

- `app/`、`tests/`、`docs/`、`scripts/`、`data/`
- `pyproject.toml`
- `requirements.txt` / `requirements-dev.txt`
- `.pre-commit-config.yaml`
- `.gitignore`
- smoke test
- CI

判断：

- 工程配置先稳定，后续工具和 Agent 才容易演进
- `data/` 只作为本地运行目录，不进入 git

## 阶段 2：Mock Workflow 与 AgentState

完成：

- `AgentState`
- mock nodes
- `workflow.py`
- workflow 测试
- reducer 验证

当时重点不是 GIS 能力，而是验证：

```text
state 能否在节点之间流转
workflow 顺序是否清晰
测试是否稳定
```

## 阶段 3：动态 state 分区

早期 state 是扁平字段。随着工具链变多，改为稳定顶层字段和动态分区。

当前顶层字段：

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

`runtime` 用于记录 planner 结果、registry 解析结果、validator 结果、adjuster 结果和 retry count。

曾短暂考虑单独的 `resolved` 分区，后续删除。原因是 registry 解析结果最终应进入 compiler 生成的 `tool_calls.params`，不需要额外顶层 state 字段。

## 阶段 4：日志与基础模块整理

完成：

- `app/utils/logging.py`
- `configure_logging`
- `get_logger`
- 必要 `__init__.py`
- registry 基础整理

日志只记录工具入口、关键参数、输出路径和错误定位，不在每个小函数里过度打印。

## 阶段 5：栅格数据准备工具链

完成：

- AOI 解析
- STAC scene plan
- Sentinel-2 asset 下载
- coverage diagnostics
- mosaic
- clip
- `prepare_raster_inputs`

关键演进：

- AOI 数据源从 geoBoundaries 切换到 Nominatim
- coverage 从 bbox 粗略判断改为 Shapely + AOI GeoJSON
- scene 选择从按云量排序演进为 coverage-aware greedy selection

## 阶段 6：Workspace 工具

完成：

- `app/tools/workspace`
- `create_workspace`
- `WorkspaceRequest`
- `WorkspaceResult`

设计变化：

```text
prepare 不再自己创建 UUID
流程开始时统一创建 workspace
后续工具共享 workspace_dir
```

## 阶段 7：Registry 重构

完成：

- `app/registry/raster_products.py`
- Sentinel-2 数据源配置
- Landsat 注册信息
- NDVI / NDWI 指数配置
- band roles
- index formula
- render config

判断：

- 公式、波段和渲染配置属于稳定知识，放在 registry
- LLM 不应直接猜公式或波段

## 阶段 8：指数计算工具

完成：

- `app/tools/index_calculation`
- `calculate_raster_index`
- AST 受限公式执行
- nodata mask
- GeoTIFF 输出

输出：

```text
data/<uuid>/output/<index>.tif
```

## 阶段 9：预览渲染工具

完成：

- `app/tools/render_preview`
- `render_index_preview`
- registry 驱动 colormap
- PNG 输出
- 透明 nodata
- 简化 colorbar

输出：

```text
data/<uuid>/output/<index>_preview.png
```

## 阶段 10：Validation / Adjustment / Tool Rules

验证和调整逻辑从工具层剥离，放到控制层。

当前结构：

```text
app/agent/validators/
app/agent/adjusters/
app/workflows/tool_rules.py
```

已完成：

- `raster_prepare_validator`：检查 prepare 结果是否可继续、可重试或失败
- `raster_prepare_adjuster`：调用智谱模型生成下一轮参数建议
- `tool_rules.py`：注册 tool、validator、adjuster 和最大重试次数
- `state.runtime`：记录 validator 结果、adjuster 结果和 retry count
- `prepare_raster_inputs`：scene coverage 不达标时在下载前短路返回 diagnostics

当前约束：

- `raster_prepare` 最多重试 5 次
- adjuster 优先扩大日期范围，尤其优先提前 `start_date`
- `max_cloud_cover` 默认 20，只能递增，单次最多增加 5，最大不超过 30
- `scene_limit` 和 `max_selected_scenes` 是工具内部工程参数，不允许 adjuster 修改

## 阶段 11：Agent Planner

全局 planner 放在 agent 层：

```text
app/agent/planners/
  zhipu_planner.py
```

职责：

- 读取用户自然语言需求
- 调用智谱模型生成结构化 plan
- `state.plan` 只保存 V1 workflow 需要 LLM 决策的核心字段
- 不直接执行工具
- 不生成自由 tool graph
- 不生成 `tool_calls`

当前 planner 核心字段：

```text
route
answer_mode
aoi_query
index_name
start_date
end_date
max_cloud_cover
```

约束：

- `route` 为 `raster_product_generate` 或 `direct_answer`
- `answer_mode` 为 `metadata_summary` 或 `direct_answer`
- `index_name` 必须来自 registry，例如 `NDVI` / `NDWI`
- `max_cloud_cover` 初始值优先为 20，不得超过 30
- `state.plan` 不保存 `data_source`、`need_render`、`include_colorbar`、`need_metadata`
- 不允许把 `scene_limit`、`max_selected_scenes` 等工具内部工程参数写入 `state.plan`

## 阶段 12：Metadata Export Tool

新增：

```text
app/tools/metadata/
  schemas.py
  metadata.py
  __init__.py
```

职责：

- 从 workflow state snapshot 抽取精简产品信息并导出为 JSON
- 默认输出到 `workspace_dir/output/metadata.json`
- JSON 顶层直接保存产品信息对象，不再包含 `schema_version`、`exported_at` 或外层 `product_info`
- metadata 包含通用产品类型、产品名称、AOI、日期、云量、数据来源、提供方、分辨率、CRS 和质量诊断
- `source` 只保留通用 `data_source` 和 `provider`，不输出 `satellite`、`collection` 等数据源特有字段
- 指数公式只作为 `product.method.formula` 的可选信息出现，非指数产品不会写入 `index_formula`
- CRS、分辨率、bounds、宽高优先从真实产品 GeoTIFF 读取，不再用数据源默认值伪造空间信息
- metadata 不输出 GeoJSON、GeoTIFF、PNG 等文件路径
- 支持序列化 `Path`、Pydantic model、`set`

它是确定性工具，不依赖 LLM。

## 阶段 13：Final Answer Tool

新增：

```text
app/tools/answer/
  schemas.py
  answer.py
  __init__.py
```

职责：

- 生成最终面向用户的回答
- `metadata_summary`：根据 `user_query` 和 workflow metadata 总结结果
- `direct_answer`：对普通问答、无关问题或当前未支持产品直接回答

它通过智谱模型生成结构化 JSON：

```json
{
  "final_answer": "..."
}
```

测试通过 fake client 注入响应，不依赖真实 API key。

## 阶段 14：Workflow 架构对齐

完成：

- `workflow_templates.py` 移入 `app/workflows/templates.py`
- `tool_rules.py` 移入 `app/workflows/tool_rules.py`
- `planner_node` 接入真实 planner
- `registry_node` 不再把 registry 解析结果写回 `plan`
- registry 解析结果写入 `runtime["registry"]["raster_product"]`
- state 不再保留 `metadata` 分区
- metadata tool 根据 state snapshot 导出精简产品信息对象
- `raster_prepare_validator_node` 调用正式 validator
- `raster_prepare_validated` 作为统一通过状态
- 删除 `AgentState.resolved`
- `index_calculation`、`render_preview`、`raster_prepare` 包入口改为懒加载
- `workflow.py` 增加 LangGraph 缺失时的线性 fallback runner

当前 workflow 节点：

```text
planner
-> registry
-> workspace
-> raster_prepare
-> raster_prepare_validator
-> product_generation
-> answer
```

当前仍未完成：

- compiler：`plan + registry + workflow template -> tool_calls`
- executor：解析并执行 `tool_calls`
- retry/adjuster 接入完整 graph 路由
