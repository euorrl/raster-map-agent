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
- 功能分支完成后可以合并并删除，后续修改用新分支继续推进

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

- V1 state 先保持结构清楚，不追求动态扩展过度设计
- 最终改用 Pydantic，是为了运行时校验和后续忘记补类型检查的风险更低
- validator node 与 Pydantic 不冲突：Pydantic 负责结构和类型，validator node 负责业务完整性

## 阶段 3：日志与基础模块整理

为了让项目更像真实工程，引入了统一日志工具。

完成内容：

- `app/utils/logging.py`
- `configure_logging`
- `get_logger`
- 日志测试
- 补全必要的 `__init__.py`
- 整理 registry，拆出 `app/registry/indices.py`

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
- Sentinel-2 L2A `B04` / `B08` 下载
- RFC3339 datetime 修正
- Earth Search 400 错误信息增强
- `scripts/raster/run_download.py`

关键发现：

- bbox 当前只用于搜索，不代表只下载 bbox 内数据
- STAC 搜索返回的是与 bbox 相交的 scene，不保证完整覆盖 bbox
- 当前单 scene 下载对大 AOI 不够，需要后续多 scene 下载和 mosaic

## 阶段 5：AOI 边界解析探索

最初使用 geoBoundaries，后来切换到 Nominatim / OpenStreetMap。

### geoBoundaries 尝试

完成内容：

- `AOIRequest` 使用 `name + iso3 + admin_level`
- 请求 geoBoundaries metadata
- 下载 GeoJSON
- 匹配行政区 feature
- 计算 bbox、面积和 scale

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

## 当前阶段性结论

目前已经证明：

```text
AOI 边界可获取
真实 Sentinel-2 波段可下载
真实 GeoTIFF 可裁剪
nodata 策略明确
```

下一座关键桥是：

```text
多 scene 下载 + tile 合并
```

这会解决 bbox 较大时单 scene 无法覆盖 AOI 的问题。
