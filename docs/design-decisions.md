# 关键设计决策

本文记录开发过程中的重要取舍，避免后续忘记为什么这样设计。

## 先工具链，后 Agent

项目最终目标是本地完整 Agent，但实现顺序不是先写复杂 Agent。

当前策略：

```text
先让真实工具链可运行
再让 planner 生成参数
再加入局部 ReAct
最后接回 LangGraph
```

原因：

- 工具输入输出稳定后，Agent 节点更容易设计
- 避免 LLM 层掩盖底层 GIS 工具不稳定的问题
- 本地能跑出真实图后，作品集展示价值更明确

## V1 与 V2 边界

V1 目标：

```text
本地完整 Agent 流程
```

包括：

- 自然语言输入
- planner
- AOI
- download
- mosaic
- clip
- index calculation
- render
- metadata
- answer
- LangGraph workflow

V2 目标：

- MCP server 化
- 前后端
- 部署
- 更复杂 ReAct
- 任务队列
- 缓存
- 多 provider 策略
- 用户交互式修正

## V1 数据源固定为 Sentinel-2

当前 `raster_prepare` 保留 `data_source` 参数，但 V1 只接受：

```text
data_source="sentinel2"
```

原因：

- Sentinel-2 L2A 已能满足 V1 的 NDVI 本地流程验证
- Earth Search 中没有适合直接替代 MODIS 级粗分辨率 NDVI 的同源数据
- Landsat 能降低部分下载压力，但覆盖范围并非数量级变化，暂时不解决大 AOI 的根本问题
- 过早加入多 provider 会让 STAC endpoint、asset 命名和下载规则变复杂

因此，V1 的 ReAct 优先调整日期、云量和 limit；如果 AOI 过大，则通过
diagnostics 明确反馈当前 V1 流程不适合，而不是自动切换 provider。

## AOI 数据源：从 geoBoundaries 切到 Nominatim

最初选择 geoBoundaries，因为它有清晰的行政区 API 和 GeoJSON。

后来发现：

- 国内省市县效果较差
- ADM 层级对用户和 LLM 都不直观
- `gbAuthoritative` 覆盖范围很小
- LLM 猜 `ADM2/ADM3/ADM4` 容易失败

因此切换到 Nominatim / OpenStreetMap。

新的输入：

```text
query + workspace_dir
```

LLM 负责把用户地点整理成：

```text
城市, 省/州, 国家
省/州, 国家
```

工具负责查边界。

## 输出接口保持稳定

无论 AOI 数据源如何变化，输出都应保持稳定：

```text
boundary_geojson_path
bbox
area_km2
source
```

因为后续模块只关心这些字段：

- download 使用 bbox
- clip 使用 boundary_geojson_path
- 全局 planner / ReAct 使用 data_source

## GeoJSON 作为主边界格式

曾考虑保留 shapefile，但最终放弃。

原因：

- GeoJSON 是单文件
- Python 可直接用 JSON 读取
- 前端地图天然支持
- rasterio 可以直接用 GeoJSON geometry 做 mask
- 对本项目的内部流转更简单

shapefile 可以作为未来兼容格式，但不是 V1 主路径。

## bbox 不是最终裁剪范围

当前 download 阶段的 bbox 只用于 STAC 搜索。

重要结论：

```text
bbox 搜索到的是与区域相交的 scene/tile
不是只下载 bbox 内像素
```

因此下载结果看起来是规则 tile，这是正常的。

真正得到 AOI 内数据需要：

```text
download -> mosaic -> clip
```

## scene plan 使用 Shapely coverage diagnostics

Sentinel-2 单 tile 大约 100km x 100km。

城市圈、省、市等 AOI 很可能跨多个 tile。

如果只按云量选择 scene，可能会出现：

- 只覆盖 AOI 一部分
- 选择到云量低但空间覆盖差的 tile
- GeoTIFF.io 中看到 tile 与 AOI 不完全重合

当前已经把下载拆成两步：

```text
scene_plan -> download
```

`scene_plan` 负责候选累积、分组和选择；`download` 只负责按 plan 下载。
scene plan 会用 Shapely 将选中 scene 的 footprint 做 union，并与真实 AOI
GeoJSON geometry 比较覆盖比例。诊断结果写入 `RasterScenePlanResult.diagnostics`，
作为后续局部 ReAct 的 observation。

diagnostics 使用 `is_retriable` 明确告诉 ReAct 是否继续循环：

- `true`：当前问题可以通过日期、云量或 limit 调参继续尝试
- `false`：当前问题不是 V1 支持的可调参数问题，应结束 ReAct 并返回说明

## Scene 选择算法思路

之前提出的三维模型：

```text
x/y = 空间
z = 时间
```

每个 scene 是时间轴上的一个空间覆盖块。

目标函数优先级：

```text
1. AOI 覆盖完整性
2. 时间一致性
3. 云量低
```

当前 V1 先做简单版本：

```text
搜索与 bbox 相交的 scene
按云量过滤
按空间分组保留候选
每组选择云量较低的 scene
按 band mosaic
再 clip
```

scene plan 默认 `limit=100`，用单次查询上限尽量增加候选覆盖面；最终
下载量仍由每组候选上限和每组选中数量控制。

当前 coverage diagnostics 已经使用真实 scene footprint union 和真实 AOI
GeoJSON geometry。bbox 只保留为 STAC 搜索参数，不再作为 coverage 判断对象。

## Clip 的 nodata 策略

GeoTIFF 必须是规则矩阵，因此裁剪后仍然是规则方块。

但是 AOI 外像素应被标记为无效。

当前策略：

```text
输出 dtype = float32
AOI 外像素 = -9999.0
metadata nodata = -9999.0
```

原因：

- 如果用 0，AOI 内真实 0 值可能混淆
- Sentinel-2 原始 uint16 不能存负值
- 转 float32 后可安全使用 `-9999.0`
- 后续 NDVI 计算时可以明确跳过 nodata

## 多 band 处理放在 pipeline

clip 工具只处理：

```text
一个 raster + 一个 AOI GeoJSON -> 一个 clipped raster
```

多 band 裁剪由上层 pipeline 循环调用。

这样工具更原子，测试更简单，也方便后续接 mosaic。
## Coverage 使用真实 AOI GeoJSON

STAC 搜索阶段继续使用 AOI bbox。bbox 的职责只是粗筛候选 scene：

```text
搜索与 AOI 外接矩形相交的 scene
```

但 coverage diagnostics 不再使用 bbox polygon。原因是 bbox 会包含大量真实
AOI 外部区域，尤其城市、省份等不规则边界会导致 coverage ratio 偏低。

当前规则是：

```text
scene footprint union ∩ AOI GeoJSON geometry
/
AOI GeoJSON geometry
```

如果缺少 `boundary_geojson_path`，或 GeoJSON 无法解析，诊断结果会标记为
`unknown`，并设置 `is_retriable=false`。这表示问题不是扩大日期、放宽云量或
增加 limit 能解决的，后续 ReAct 应停止当前数据下载调参循环并返回明确原因。
