# 路线图

本文记录 V1 和 V2 的计划边界。

## 当前已完成

工程基础：

- Python 项目结构
- 依赖文件
- black / flake8 / pytest / coverage
- pre-commit
- CI

Agent 基础：

- mock LangGraph workflow
- Pydantic state
- mock nodes
- workflow 测试

工具基础：

- logging
- index registry 雏形
- AOI 解析
- Sentinel-2 scene plan
- 多 scene band asset 下载
- Shapely coverage diagnostics
- GeoTIFF clip

## 下一阶段：mosaic

目标：

```text
AOI bbox + AOI GeoJSON
-> 搜索多个 Sentinel-2 scenes
-> 判断候选 scene 是否覆盖真实 AOI GeoJSON
-> 下载规划选中的 tile / scene
-> 每个 band 分别 mosaic
```

建议先实现最小可行版本：

```text
搜索候选 scenes
过滤云量
全局累积候选 scenes
按 coverage-aware greedy 选择最多 `max_selected_scenes` 个 scene
读取 coverage diagnostics
下载通过规划的 required bands
按 band 调用 rasterio merge
输出 mosaic_B04.tif / mosaic_B08.tif
```

coverage diagnostics 已使用 Shapely 对 scene footprint union 和真实 AOI
GeoJSON geometry 进行判断。下一步重点是把通过规划的多个 scene/tile 按 band 合并。

当前 scene plan 默认 `limit=100`，先尽量拿到足够候选；下载量仍由最终
plan 控制，而不是直接下载全部搜索结果。

## 下一阶段：指数计算与渲染

目标：

```text
clipped B04 + clipped B08
-> NDVI GeoTIFF
-> preview PNG
-> metadata JSON
```

NDVI 计算必须处理：

- nodata = `-9999.0`
- denominator 为 0
- 输出范围
- dtype

渲染需要处理：

- nodata mask
- colormap
- percentile stretch
- PNG 输出

## 下一阶段：prepare pipeline

目标：

```text
AOI
-> download
-> mosaic
-> clip
-> prepared band paths
```

这一步会固定工具链的主要输入输出，是接入 Agent workflow 的前置条件。

## 下一阶段：planner

输入：

```text
Generate an NDVI vegetation map for Hangzhou, Zhejiang, China.
```

输出：

```json
{
  "query": "Hangzhou, Zhejiang, China",
  "index": "NDVI",
  "date_range": ["2024-06-01", "2024-08-31"],
  "max_cloud_cover": 20,
  "data_source": "sentinel2"
}
```

planner 初期可以简单，不需要复杂对话。

## 下一阶段：局部 ReAct

ReAct 不作为主流程一开始就引入，而是用于容易失败的局部环节。

适合位置：

- AOI 查询失败：修改 query
- 数据下载覆盖不足：放宽时间窗或云量
- scene 太多：调整候选策略
- 渲染异常：调整 nodata 或拉伸参数

## 下一阶段：answer

根据 metadata 和产物路径生成最终回答。

示例：

```text
NDVI vegetation map generated for Hangzhou, Zhejiang, China.
Preview: outputs/...
GeoTIFF: outputs/...
```

## V1 完成标准

本地运行：

```text
用户自然语言请求
-> Agent workflow
-> 真实工具链
-> 输出 GeoTIFF + PNG + metadata + final answer
```

V1 不要求：

- Web 前端
- MCP server
- 部署
- 多用户系统
- 复杂人机交互

## V2 方向

V2 是产品化与标准化阶段：

- MCP server 化
- FastAPI 后端
- 前端
- 部署
- 任务队列
- 缓存
- 更复杂的 ReAct
- 多 AOI provider
- 多数据源
- 更多指数和专题图产品
## 当前 Coverage 规则更新

scene plan 仍然使用 AOI bbox 进行 STAC 搜索，但 coverage diagnostics 已改为读取
真实 AOI GeoJSON。后续 ReAct observation 应基于：

```text
scene footprint union 对 AOI GeoJSON geometry 的覆盖率
```

如果 AOI GeoJSON 缺失或无效，diagnostics 会返回 `unknown` 且
`is_retriable=false`，表示当前不是可通过日期、云量或 limit 调整解决的问题。
