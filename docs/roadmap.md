# 路线图

本文记录 V1 和 V2 的边界。

## 已完成

工程基础：

- Python 项目结构
- black / flake8 / pytest / coverage
- CI
- MkDocs / ReadTheDocs 配置

Agent 基础：

- mock LangGraph workflow
- Pydantic `AgentState`
- 动态 state 分区
- `runtime` 运行时控制分区
- agent validator / adjuster / policy 注册表

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

真实工具链已经可以生成：

```text
clipped band GeoTIFF
index GeoTIFF
preview PNG
```

## 当前阶段：Agent Validation Policy

当前分支目标：

```text
为 Agent 引入 validator / adjuster / retry runtime 基础结构
```

主要任务：

- 完善 `AgentState.runtime`
- 实现 raster_prepare validator
- 实现基于智谱模型的 raster_prepare adjuster
- 实现 tool policy 注册表
- 为局部 ReAct 准备 retry 计数和路由依据

这一阶段已经具备真实 LLM adjuster 调用能力，但测试通过 fake client 离线验证，不要求改造完整 workflow。

## 下一阶段：V1 Agent Tool Integration

目标：

```text
mock workflow
-> 真实工具入口编排
```

建议 workflow：

```text
planner
-> registry
-> workspace
-> raster_prepare
-> raster_prepare_validator
-> product_generation
-> answer
```

其中 `product_generation` 暂时包括：

- index calculation
- render preview
- metadata export

## 后续阶段：Planner

Planner 负责把自然语言转成结构化计划：

```json
{
  "aoi_query": "Chengdu, Sichuan, China",
  "index_name": "NDVI",
  "data_source": "sentinel2",
  "start_date": "2024-06-01",
  "end_date": "2024-08-31",
  "max_cloud_cover": 20
}
```

V1 中 planner 可以先是受约束的结构化输出，不追求完全自由 tool planning。

## 后续阶段：局部 ReAct

局部 ReAct 优先发生在 `raster_prepare` 阶段。

典型场景：

- AOI 查询失败：调整 `aoi_query`
- coverage 不足：优先扩大时间范围，必要时小幅放宽云量
- diagnostics 标记不可重试：终止循环并返回明确原因

循环次数由 `state.runtime` 中的 per-tool retry 计数控制。当前 `raster_prepare` 最多重试 5 次。

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
- Guarded tool-calling agent runtime
