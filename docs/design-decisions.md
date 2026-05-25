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

当前 registry 已经登记 Sentinel-2 和 Landsat 的基础信息，也登记了 NDVI / NDWI 在不同数据源下的波段关系。

但是当前 `raster_prepare` 保留 `data_source` 参数时，V1 只真正执行：

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

这次边界是：

```text
registry 可以知道 Landsat
raster_prepare 暂时不执行 Landsat
```

这样既保留后续扩展接口，也避免把未验证的数据源提前接入真实下载流程。

## Registry 负责知识，Tools 负责执行

指数、卫星和公式属于稳定知识，不应散落在工具 schema 中。

当前约定：

```text
planner -> 输出 index_name + data_source
registry -> 展开 required_bands / band_roles / formula / render_config / STAC asset mapping
raster_prepare -> 对外接收 index_name + data_source，内部用 required_bands 准备裁剪后的 band GeoTIFF
index_calculation -> 根据 band_roles + formula 计算指数
render_preview -> 根据 index_name 和 render_config 渲染预览 PNG
```

这样 LLM 不需要直接输出公式或猜波段，后续新增 NDWI、NDBI、Landsat 等能力时，也优先扩展 registry，而不是改动每个工具。

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

`scene_plan` 负责候选累积和选择；`download` 只负责按 plan 下载。
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
全局累积候选 scene
每轮选择对 AOI 未覆盖区域贡献最大的 scene
贡献接近时再选择云量较低的 scene
按 band mosaic
再 clip
```

scene plan 默认 `limit=100`，用单次查询上限尽量增加候选覆盖面；最终
下载量由 `max_selected_scenes` 控制。

当前 coverage diagnostics 已经使用真实 scene footprint union 和真实 AOI
GeoJSON geometry。bbox 只保留为 STAC 搜索参数，不再作为 coverage 判断对象。

## Scene 选择改为全局 coverage-aware greedy

早期实现按 Sentinel-2 tile 分组，并在每个 tile 内选择云量最低的 scene。
后来发现这个假设不稳：同一个 tile 内，不同日期/轨道的真实 footprint 可能
只覆盖 tile 的不同部分。如果某一侧 footprint 的云量整体更低，按云量排序会
连续选择同一侧 scene，导致 AOI 另一侧缺数据。

因此 V1 改为：

```text
所有候选 scene 进入全局候选池
每轮计算 scene.geometry 与当前未覆盖 AOI 的新增交集面积
优先选择新增贡献最大的 scene
如果贡献接近，再选择云量更低的 scene
最多选择 max_selected_scenes 个 scene
```

这里不再维护 tile 分组。tile 合并、重叠区 median/mean 等像素层逻辑放到
`mosaic` 模块处理；`scene_plan` 只处理 metadata 层的 scene 选择。

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

## V1 Mosaic 先使用 first 策略

median mosaic 更适合多时相遥感合成，但需要把同一 band 的多张 GeoTIFF 对齐到统一网格，
再做逐像素统计。对于完整 Sentinel-2 tile 来说，这会带来较高内存压力，也会让 V1 过早
进入像素级合成复杂度。

因此当前 V1 先选择：

```text
download -> first mosaic by band -> clip -> index calculation
```

重叠区域使用 rasterio 的 `first` 策略，保留排序后第一张有数据的 tif。由于上游
scene_plan 已经按 coverage 和云量筛过 scene，这个策略足以先打通本地完整流程。median、
cloud mask、quality mask 等更高质量合成策略留到后续版本。

## Workspace 独立于 Prepare 创建

数据准备流程会产生较多中间文件：AOI GeoJSON、原始下载 tif、mosaic tif、最终 clipped tif。
为了避免不同运行互相覆盖，流程开始时先由 `create_workspace` 在 `data/` 下创建：

```text
data/<uuid>/
```

成功完成 clip 后，只保留后续计算真正需要的文件：

```text
aoi/
clipped_raster/
```

并删除：

```text
raster/
mosaic_raster/
```

这样做的取舍是：

- 保留 AOI，便于复查边界和后续渲染 metadata
- 保留 clipped band，作为指数计算的直接输入
- 删除原始下载 tif 和 mosaic tif，降低磁盘占用
- 如果流程中途失败，则不主动清理中间文件，方便调试

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

## Coverage 不是 V1 的 100% 硬门槛

真实遥感数据存在一个作品集项目必须接受的现实：某些 AOI 在给定日期、云量和
Sentinel-2 数据源下，可能很难得到 100% footprint 覆盖。继续把 100% 作为硬门槛，
会让很多已经足够展示完整流程的区域被判定失败。

因此当前设计改为：

```text
coverage_ratio >= min_coverage_ratio -> 允许继续
coverage_ratio < min_coverage_ratio  -> 反馈给 ReAct 调参
```

V1 默认：

```python
min_coverage_ratio = 0.7
```

这意味着 coverage 仍然是质量控制指标，但不是绝对阻塞条件。最终回答层需要保留并说明
真实 coverage_ratio，例如“当前可用影像覆盖约 94.8% 的 AOI”。如果低于阈值，则说明
当前影像覆盖不足，并让 ReAct 优先尝试扩大日期、放宽云量或增加 limit。

`min_coverage_ratio` 只影响 diagnostics 的通过/失败，不改变 scene 选择算法的目标。
scene selection 仍然优先补未覆盖区域，直到接近完整覆盖、没有新的有效贡献，或达到
`max_selected_scenes`。
