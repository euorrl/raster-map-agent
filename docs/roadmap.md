# 路线图

本文记录 V1 和 V2 的边界。

## 已完成

工程基础：

- Python 项目结构
- black / flake8 / pytest / coverage
- CI
- MkDocs / ReadTheDocs 配置

Agent 基础：

- Pydantic `AgentState`
- 动态 state 分区
- `runtime` 运行时控制分区
- 智谱全局 planner
- `route`：`raster_product_generate` / `direct_answer`
- `answer_mode`：`metadata_summary` / `direct_answer`
- agent validator / adjuster
- workflow templates 注册表
- workflow tool rules 注册表
- 真实 planner node 接入
- LangGraph 缺失时的线性 fallback runner

工具链：

- workspace 创建工具
- raster product registry
- Nominatim AOI 解析
- Sentinel-2 scene plan
- Shapely coverage diagnostics
- band asset 下载
- first mosaic by band
- AOI clip
- `prepare_raster_inputs`
- `calculate_raster_index`
- `render_index_preview`
- `export_metadata`
- `generate_final_answer`

真实工具链已经可以生成：

```text
clipped band GeoTIFF
index GeoTIFF
preview PNG
metadata JSON
final answer text
```

## 当前阶段：V1 Workflow Architecture

当前目标：

```text
把已完成的 planner、registry、tools、validator、answer 工具
对齐到受控 workflow 架构中
```

已完成：

- `app/workflows/templates.py`
- `app/workflows/tool_rules.py`
- `app/workflows/workflow.py`
- `planner_node` 调用真实 planner
- `registry_node` 解析产品配置
- `runtime["registry"]["raster_product"]` 保存过渡期执行配置
- `product_generation_node` 串联 index、preview、metadata
- `direct_answer` 路由可跳过栅格工具
- state 不再保留 `metadata` 分区
- metadata tool 从 state snapshot 生成精简产品信息对象

当前过渡状态：

- `workflow.py` 仍以显式节点编排真实工具
- `tool_calls` 字段已存在，但 compiler 尚未写入
- registry 解析结果暂存在 `runtime["registry"]`

## 下一阶段：Compiler + Executor

目标：

```text
plan + registry + workflow template
-> state.tool_calls
-> executor 执行 tool_calls
```

建议实现步骤：

1. 定义 `ToolCall` schema
2. 实现 compiler
3. 把 registry 解析结果写入 `tool_calls.params`
4. 实现 `$state...` 引用解析
5. 实现 executor
6. 将当前显式节点逐步收敛为 compiler/executor 驱动

建议 `tool_calls` 结构：

```json
[
  {
    "id": "raster_prepare",
    "tool_name": "raster_prepare.prepare_raster_inputs",
    "params": {
      "aoi_query": "$state.plan.aoi_query",
      "index_name": "$state.plan.index_name",
      "data_source": "sentinel2",
      "start_date": "$state.plan.start_date",
      "end_date": "$state.plan.end_date",
      "max_cloud_cover": "$state.plan.max_cloud_cover",
      "workspace_dir": "$state.workspace.workspace_dir"
    },
    "depends_on": ["workspace"]
  }
]
```

Compiler 负责把 registry 中的可信配置写进参数，例如：

```text
required_bands
band_roles
index_formula
render_config
```

Planner 不负责这些参数。

## Planner 输出约束

Planner 只负责生成 `state.plan`。

正常栅格任务示例：

```json
{
  "route": "raster_product_generate",
  "answer_mode": "metadata_summary",
  "aoi_query": "Chengdu, Sichuan, China",
  "index_name": "NDVI",
  "start_date": "2024-06-01",
  "end_date": "2024-08-31",
  "max_cloud_cover": 20
}
```

直接回答任务示例：

```json
{
  "route": "direct_answer",
  "answer_mode": "direct_answer"
}
```

V1 中 planner 不追求完全自由 tool planning。

## 后续阶段：局部 ReAct 接入 Graph

局部 ReAct 优先发生在 `raster_prepare` 阶段。

典型场景：

- AOI 查询失败：调整 `aoi_query`
- coverage 不足：优先扩大时间范围，必要时小幅放宽云量
- diagnostics 标记不可重试：终止循环并返回明确原因

循环次数由 `state.runtime` 中的 per-tool retry 计数控制。当前 `raster_prepare` 最大重试 5 次。

## V1 完成标准

本地完整运行：

```text
用户自然语言请求
-> Agent workflow
-> 真实工具链
-> GeoTIFF + PNG + metadata + final answer
```

V1 不要求：

- Web 前端
- MCP server
- 部署
- 多用户系统
- 完全自由 tool-calling agent

## V2 方向

V2 是产品化与标准化阶段：

- MCP server 化
- FastAPI 后端
- 前端
- 任务队列
- 缓存
- 更复杂的 ReAct
- 多 AOI provider
- 更多数据源
- 更多指数和专题图产品
- skill / workflow registry，用于管理更多工具和产品流程
- guarded tool-calling agent runtime
