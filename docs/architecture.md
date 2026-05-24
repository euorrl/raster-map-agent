# 项目架构

当前项目采用分层结构，先保证工具链可独立运行，再接入 Agent workflow。

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

- NDVI 配置
- required bands
- formula

后续扩展：

- NDWI
- NDBI
- SAVI
- 其他专题图产品

### `app/tools`

真实工具层。工具应该尽量保持输入输出清晰，不依赖 LLM。

当前 raster 工具结构：

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

- `schemas.py`：工具请求和结果模型
- `aoi.py`：AOI 边界解析
- `scene_plan.py`：搜索 STAC metadata，累积候选 scene，并生成下载计划
- `download.py`：按下载计划拉取 COG band asset
- `mosaic.py`：后续实现 tile / scene 合并
- `clip.py`：按 AOI GeoJSON 裁剪 GeoTIFF
- `prepare.py`：后续编排 AOI -> download -> mosaic -> clip

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
  test_clip.py
```

当前测试策略：

- 单元测试不访问真实网络
- 使用 monkeypatch mock 外部 API
- clip 测试使用临时 GeoTIFF 进行真实 rasterio 裁剪

## scripts

本地手动验证入口，不作为正式 API。

当前：

```text
scripts/raster/run_aoi.py
scripts/raster/run_download.py
scripts/raster/run_clip.py
```

定位：

- 快速试真实 API
- 快速检查产物
- 开发阶段辅助调试

## data / outputs

本地生成数据目录，不进入 git。

建议：

- `data/` 放下载和中间数据
- `outputs/` 放最终结果
- 后续可以按 run id 或 query 组织
