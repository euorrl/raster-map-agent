# 开发阶段记录

本文记录项目从空骨架到真实栅格工具链雏形的主要工作与推导过程。

## 阶段 1：项目工程初始化

最初目标是先建立一个可维护的 Python 项目骨架，而不是直接写业务功能。

完成内容：

- 创建 `app/`、`tests/`、`docs/`、`data/`、`outputs/` 等目录
- 添加 `pyproject.toml`
- 添加 `pytest.ini` 配置并逐步迁移到 `pyproject.toml`
- 添加 `requirements.txt` 和 `requirements-dev.txt`
- 添加 `.pre-commit-config.yaml`
- 添加 `.gitignore`
- 添加最小 smoke test

关键判断：

- `pyproject.toml` 适合承载 black、pytest 等工具配置
- `pre-commit` 是检查流程配置，不适合迁移到 `pyproject.toml`

## 阶段 2：Mock LangGraph Workflow

项目从空架子升级为可以流转 state 的 mock agent workflow。

完成内容：

- `AgentState`
- mock nodes
- `v1_workflow`
- workflow 测试
- warnings reducer 追加验证
- workflow 编译缓存

当时的重点不是 GIS 能力，而是验证：

```text
state 能否在节点之间完整流动
workflow 顺序是否清楚
测试是否能稳定跑通
```

关键判断：

- 早期 V1 state 先保持结构清楚，不追求动态扩展过度设计
- 最终改用 Pydantic，是为了运行时校验和后续忘记补类型检查的风险更低
- validator node 与 Pydantic 不冲突：Pydantic 负责结构和类型，validator node 负责业务完整性

后续随着真实工具链成形，`AgentState` 从早期摊平字段调整为分区式动态 state：

```text
plan
workspace
tool_results
metadata
```

这个设计让每个节点只需要把工具结果写入自己的分区，避免新增工具时不断扩展 state 顶层字段。

## 阶段 3：日志与基础模块整理

引入统一日志工具。

完成内容：

- `app/utils/logging.py`
- `configure_logging`
- `get_logger`
- 日志测试
- 补全必要的 `__init__.py`
- 整理 registry，拆出指数和数据源配置

关键判断：

- 日志用于工具开始、关键参数、结果路径、错误定位
- 不在所有小函数里刷日志，只在链路节点和外部服务请求处记录
- `__init__.py` 不过度导出，避免导入包时触发过重副作用

## 阶段 4：真实栅格下载工具

开始实现真实数据能力，选择 STAC + COG，而不是网页登录或爬虫。

完成内容：

- `RasterScenePlanRequest`
- `RasterDownloadRequest`
- `RasterScene`
- `RasterSceneCandidateStore`
- `RasterDownloadResult`
- `data_source` 接口参数，V1 固定为 `sentinel2`，作为后续扩展预留协议
- Earth Search STAC 搜索
- scene plan 与下载执行解耦
- 多次查询结果可累积到候选 store
- Sentinel-2 L2A `B04` / `B08` 下载
- RFC3339 datetime 修正
- Earth Search 400 错误信息增强
- `scripts/raster/run_download.py`

关键发现：

- bbox 当前只用于搜索，不代表只下载 bbox 内数据
- STAC 搜索返回的是与 bbox 相交的 scene，不保证完整覆盖 bbox
- 下载层应该只执行 scene plan，不应该继续承担 scene 选择逻辑

## 阶段 5：AOI 边界解析探索

最初使用 geoBoundaries，后来切换到 Nominatim / OpenStreetMap。

### geoBoundaries 尝试

完成内容：

- `AOIRequest` 使用 `name + iso3 + admin_level`
- 请求 geoBoundaries metadata
- 下载 GeoJSON
- 匹配行政区 feature
- 计算 bbox 和面积

关键问题：

- `ADM2`、`ADM3`、`ADM4` 在不同国家含义不直观
- 中国省市县效果较差
- `gbAuthoritative` 覆盖范围很小，不适合作为默认数据源
- LLM 需要猜行政层级，容易失败

### 切换到 Nominatim

最终改为：

```python
AOIRequest(
    query="Hangzhou, Zhejiang, China",
    workspace_dir=Path("data/speak1"),
)
```

好处：

- 输入更接近用户自然语言
- 不需要猜 ADM 层级
- 国内城市、省份等查询效果明显更好
- LLM 只需要生成消歧后的 query

当前输出仍然保持：

```text
boundary_geojson_path
bbox
area_km2
source
```

这样后续 download 和 clip 不需要知道 AOI 来自哪个数据源。

## 阶段 6：AOI 裁剪工具

实现真实 GeoTIFF 裁剪。

完成内容：

- 引入 `rasterio==1.4.4`
- `RasterClipRequest`
- `RasterClipResult`
- `RasterClipError`
- `clip_raster_to_aoi`
- `scripts/raster/run_clip.py`
- `tests/tools/raster_prepare/test_clip.py`

关键设计：

- 输入：一个 raster + 一个 AOI GeoJSON
- 输出：一个 clipped GeoTIFF
- 多波段不放进 clip 工具，由上层 pipeline 循环调用
- GeoJSON 是 EPSG:4326，Sentinel-2 常见为 UTM，需要把 geometry 转到 raster CRS
- 输出统一转 `float32`
- AOI 外像素填充 `-9999.0`
- metadata 写入 `nodata=-9999.0`

这解决了细长 AOI 或不规则 AOI 在规则 raster 外接矩形中产生冗余像素的问题。

## 阶段 7：Scene Plan 算法与 Coverage 设计

在真实下载跑通后，发现“能下载”并不等于“下载到适合 AOI 的数据”。

这个阶段专门解决：

```text
从 STAC 返回的候选 scene 中，如何选择一个尽量少、尽量低云、尽量覆盖 AOI 的组合
```

完成内容：

- `RasterScene`
- `RasterSceneCandidateStore`
- `RasterScenePlanDiagnostics`
- `RasterScenePlanResult`
- `build_raster_scene_plan`
- 候选 scene 按 `scene_id` 去重
- 多次查询可以累积到同一个 candidate store
- 按 `max_cloud_cover` 做硬过滤
- 使用真实 AOI GeoJSON，而不是 bbox，进行 coverage diagnostics
- 使用 Shapely 计算 scene footprint union 与 AOI geometry 的覆盖率
- scene 选择从按 tile 分组，演进为全局 coverage-aware greedy selection
- coverage 从 100% 硬门槛改为 `min_coverage_ratio=0.7` 的最低可接受阈值

关键推理：

- STAC 搜索用 bbox 只是粗筛，不代表 scene 完整覆盖 AOI
- Sentinel-2 tile 是规则栅格，但真实 footprint 可能是斜切多边形
- 同一个 tile 内不同日期或轨道的 footprint 可能覆盖不同部分
- 如果只按云量排序，可能连续选到空间上重复的低云 scene
- 更合理的做法是每轮优先补 AOI 当前未覆盖区域，贡献接近时再比较云量

当前算法细节见：

- [Scene 选择算法迭代](scene-selection-evolution.md)

## 阶段 8：first mosaic 工具

实现同一 band 的多 scene / 多 tile 合并。

完成内容：

- `RasterMosaicRequest`
- `RasterMosaicResult`
- `RasterMosaicError`
- `mosaic_rasters_by_band`
- `scripts/raster/run_mosaic.py`
- `tests/tools/raster_prepare/test_mosaic.py`

关键设计：

- 输入：一个包含多张 GeoTIFF 的目录
- 输出：每个 band 一张 mosaic GeoTIFF
- 自动从文件名末尾解析 `B04`、`B08` 等 band 名称
- 使用 `rasterio.merge.merge(..., method="first")`
- 如果输入 tif CRS 不一致，使用 `WarpedVRT` 做临时重投影

关键判断：

- V1 先不做 median mosaic，避免一次性进入像素级合成复杂度和内存压力
- scene plan 已经尽量选低云且补覆盖的 scene，first mosaic 足够先打通完整本地流程
- median、cloud mask、quality mask 留到后续版本

## 阶段 9：prepare pipeline

把 AOI、scene plan、download、mosaic、clip 串成一个对外入口。

完成内容：

- `RasterPrepareRequest`
- `RasterPrepareResult`
- `prepare_raster_inputs`
- `scripts/raster/run_prepare.py`
- `tests/tools/raster_prepare/test_prepare.py`

关键设计：

- workspace 由 `create_workspace` 在流程开始前创建，prepare 只接收 `workspace_dir`
- 对外接收 `index_name + data_source`，并通过 registry 展开 required bands
- 任务目录包括 `aoi/`、`raster/`、`mosaic_raster/`、`clipped_raster/`、`output/`
- 成功完成 clip 后删除 `raster/` 和 `mosaic_raster/`
- 保留 `aoi/`、`clipped_raster/` 和 `output/`
- 返回后续指数计算需要的 band paths、scene ids 和 diagnostics

这个阶段证明：数据准备模块已经能为 NDVI 计算提供真实裁剪后的 B04/B08 输入。

## 当前阶段性结论

目前已经证明：

```text
AOI 边界可获取
真实 Sentinel-2 波段可下载
真实 GeoTIFF 可裁剪
nodata 策略明确
scene plan 可返回 coverage diagnostics
coverage 默认使用最低可接受阈值而不是 100% 硬门槛
同一 band 的多张 tif 可先用 first 策略合并成 mosaic GeoTIFF
prepare pipeline 可串联 AOI、scene plan、download、mosaic、clip
每次任务先创建独立 UUID workspace，prepare 在该 workspace 内运行并在成功后清理中间 raster
```

## 阶段 10：指数计算工具骨架与真实计算

本阶段新增 `app/tools/index_calculation/`。

关键设计：

- 计算模块接收 `workspace_dir`
- 从 `clipped_raster/` 中按 `band_roles` 推导输入 band 路径
- 按 registry 传下来的 `index_formula` 计算指数
- 输出只返回最终 GeoTIFF 路径 `index_tif_path`
- 当前公式执行只支持受限的四则运算，避免直接执行任意代码
- 计算前检查输入 band 的 shape、transform 和 CRS 是否一致
- 基于输入 band 的 nodata 构建 valid mask
- 公式结果中的 `nan` 和 `inf` 会写成统一 nodata

这一步让流程从“数据准备完成”推进到“可以生成真实指数 GeoTIFF”。

本阶段新增的本地验证脚本：

```text
scripts/run_index_calculation.py
```

下一座关键桥是：

```text
渲染与 metadata
```

这会把已经生成的指数 GeoTIFF 转换为用户更容易查看的 preview PNG，并沉淀 AOI、scene、coverage、公式和输出路径等 metadata。

在进入真实渲染实现前，先把指数的默认渲染配置放入 `raster_products.py`：

```text
NDVI -> vmin=-0.2, vmax=0.8, colormap=greens
NDWI -> vmin=-0.5, vmax=0.5, colormap=blues
```

同时新增 `render_preview` 接口骨架，让渲染模块后续只需要接收 `index_name + index_tif_path`，并返回一个 `preview_path`。

## 阶段 11：基础渲染预览工具

本阶段把 `render_preview` 从接口骨架推进为可运行工具。

关键设计：

- 渲染模块接收 `index_name + index_tif_path`
- 通过 `index_name` 从 registry 读取 `vmin`、`vmax` 和 `colormap`
- 读取单波段指数 GeoTIFF
- 根据 nodata 和非有限值构建有效像素 mask
- 将指数值按 `vmin / vmax` 裁剪并归一化到 0 到 1
- 渲染前按最长边 `max_size=2048` 做降采样，避免大范围 GeoTIFF 直接造成内存压力
- 根据简化色带生成 RGBA PNG
- nodata 区域写入透明 alpha
- 默认在 PNG 右下角绘制紧凑 colorbar，并显示 `vmin / vmax` 数值，帮助快速理解色带方向
- 输出只返回 `preview_path`

当前 V1 支持：

```text
NDVI -> greens
NDWI -> blues
```

本阶段新增的本地验证脚本：

```text
scripts/run_render_preview.py
```

渲染模块当前仍保持轻量实现，不引入 matplotlib 或 Pillow。这样可以先打通本地完整链条，后续如果需要更专业的色带、图例、标题或降采样策略，再单独扩展。
