# 项目架构

当前项目采用分层结构：先保证真实工具链可以独立运行，再把工具链接入 Agent workflow。

## 顶层目录

```text
app/
  agent/
  registry/
  schemas/
  tools/
  utils/
  workflows/
tests/
scripts/
docs/
data/
outputs/
```

## app

### `app/schemas`

存放 Agent workflow 层面的 state。

当前重点：

- `AgentState`
- workflow 节点之间共享的状态字段

### `app/agent`

存放 LangGraph 节点函数。

当前已经有 mock nodes，后续会逐步替换为真实工具调用：

```text
planner_node
registry_node
aoi_node
download_node
mosaic_node
clip_node
process_node
render_node
metadata_node
answer_node
```

### `app/workflows`

存放 workflow builder。

当前：

- `v1_workflow.py`
- 已经能跑通 mock workflow

后续：

- 接入真实工具链
- 加入局部 ReAct 或条件路由

### `app/registry`

存放指数、产品类型等可扩展配置。

当前：

- `raster_products.py`
- Sentinel-2 数据源配置
- Landsat 数据源注册信息
- NDVI / NDWI 指数配置
- 指数在不同数据源下的 band roles
- 解析 `index_name + data_source` 的产品配置

后续扩展：

- NDBI
- SAVI
- 其他专题图产品

### `app/tools`

真实工具层。工具应尽量保持输入输出清晰，不依赖 LLM。

当前 raster prepare 工具结构：

```text
app/tools/raster_prepare/
  schemas.py
  aoi.py
  scene_plan.py
  download.py
  mosaic.py
  clip.py
  prepare.py
```

职责：

- `schemas.py`：工具请求、结果和错误模型
- `aoi.py`：通过 Nominatim 解析 AOI 边界，保存 GeoJSON，返回 bbox
- `scene_plan.py`：搜索 STAC metadata，累积候选 scene，执行 coverage-aware greedy 选择，并生成 diagnostics
- `download.py`：按 scene plan 下载 COG band asset
- `mosaic.py`：按 band 扫描输入目录，用 `first` 策略合并多张 GeoTIFF；遇到 CRS 不一致时用 `WarpedVRT` 临时重投影
- `clip.py`：按 AOI GeoJSON 裁剪 GeoTIFF，并将 AOI 外像素写为 `-9999.0`
- `prepare.py`：串联 AOI、scene plan、download、mosaic、clip，作为数据准备模块对外主入口

### `app/utils`

通用基础设施。

当前：

- 日志配置

## tests

测试按模块组织：

```text
tests/tools/raster_prepare/
  test_aoi.py
  test_download.py
  test_mosaic.py
  test_clip.py
  test_prepare.py
```

当前测试策略：

- 单元测试不访问真实网络
- 使用 monkeypatch mock 外部 API
- clip 和 mosaic 测试使用临时 GeoTIFF 验证真实 rasterio 行为
- prepare 测试 mock 各子工具，只验证 pipeline 编排、workspace 和清理逻辑

## scripts

本地手动验证入口，不作为正式 API。

当前：

```text
scripts/raster/run_aoi.py
scripts/raster/run_download.py
scripts/raster/run_mosaic.py
scripts/raster/run_clip.py
scripts/raster/run_prepare.py
```

定位：

- 快速试真实 API
- 快速检查产物
- 开发阶段辅助调试

## data / outputs

本地生成数据目录，不进入 git。

当前 `prepare` 每次运行会在 `data/` 下创建一个 UUID workspace：

```text
data/<uuid>/
  aoi/
  raster/
  mosaic_raster/
  clipped_raster/
```

成功完成裁剪后会保留：

```text
data/<uuid>/aoi
data/<uuid>/clipped_raster
```

并删除中间目录：

```text
data/<uuid>/raster
data/<uuid>/mosaic_raster
```

后续 `outputs/` 更适合存放最终用户可见结果，例如 NDVI GeoTIFF、preview PNG、metadata JSON。
