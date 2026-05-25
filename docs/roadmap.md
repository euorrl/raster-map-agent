# 路线图

本文记录 V1 和 V2 的计划边界。

## 当前已完成

工程基础：

- Python 项目结构
- 依赖文件
- black / flake8 / pytest / coverage
- pre-commit
- CI
- Read the Docs / MkDocs 配置

Agent 基础：

- mock LangGraph workflow
- Pydantic state
- mock nodes
- workflow 测试

工具基础：

- logging
- workspace 创建工具
- raster product registry 雏形
- AOI 解析
- Sentinel-2 scene plan
- 多 scene band asset 下载
- Shapely coverage diagnostics
- first mosaic by band
- GeoTIFF clip
- `prepare_raster_inputs` 数据准备 pipeline
- `calculate_raster_index` 指数计算工具

当前工具链已经可以输出真实指数 GeoTIFF：

```text
AOI query
-> workspace
-> AOI GeoJSON + bbox
-> scene plan
-> download raw bands
-> mosaic bands
-> clip bands
-> clipped B04 / clipped B08
-> NDVI / NDWI GeoTIFF
```

## 下一阶段：渲染与 metadata

目标：

```text
index GeoTIFF
-> preview PNG
-> metadata JSON
```

渲染需要处理：

- nodata mask
- colormap
- percentile stretch
- PNG 输出

metadata 需要记录：

- AOI 名称和边界路径
- data source
- scene ids
- coverage diagnostics
- band paths
- index formula
- index GeoTIFF 路径
- preview PNG 路径

## 下一阶段：planner

输入示例：

```text
Generate an NDVI vegetation map for Hangzhou, Zhejiang, China.
```

输出示例：

```json
{
  "aoi_query": "Hangzhou, Zhejiang, China",
  "index": "NDVI",
  "date_range": ["2024-06-01", "2024-08-31"],
  "max_cloud_cover": 30,
  "data_source": "sentinel2"
}
```

planner 初期可以简单，不需要复杂对话。它的重点是生成能对齐真实工具链的稳定参数。

## 下一阶段：局部 ReAct

ReAct 不作为主流程一开始就引入，而是用于容易失败的局部环节。

适合位置：

- AOI 查询失败：修改 query
- scene plan 覆盖不足：扩大时间窗、放宽云量或增加 limit
- coverage diagnostics 标记不可重试：结束循环并返回明确说明
- 渲染异常：调整 nodata 或拉伸参数

## 下一阶段：answer

根据 metadata 和产品路径生成最终回答。

示例：

```text
NDVI vegetation map generated for Hangzhou, Zhejiang, China.
Preview: outputs/...
GeoTIFF: outputs/...
Coverage: 94.8%
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

## 当前 Coverage 规则

scene plan 仍然使用 AOI bbox 进行 STAC 搜索，但 coverage diagnostics 已改为读取真实 AOI GeoJSON。

判断对象是：

```text
scene footprint union 对 AOI GeoJSON geometry 的覆盖率
```

当前 V1 不再要求 100% 覆盖，而是使用最低可接受阈值：

```python
min_coverage_ratio = 0.7
```

如果 AOI GeoJSON 缺失或无效，diagnostics 会返回 `unknown` 和 `is_retriable=false`，表示当前问题不是可通过日期、云量或 limit 调整解决的。
