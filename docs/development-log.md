# 开发日志

本文按阶段记录项目从工程骨架到真实工具链，再到 Agent 控制层的演进。

## 阶段 1：项目工程初始化

完成：

- `app/`、`tests/`、`docs/`、`scripts/`、`data/`
- `pyproject.toml`
- `requirements.txt` / `requirements-dev.txt`
- `.pre-commit-config.yaml`
- `.gitignore`
- smoke test
- CI

判断：

- 工程配置先稳定，后续工具和 Agent 才容易演进
- `data/` 只作为本地运行目录，不进入 git

## 阶段 2：Mock LangGraph Workflow

完成：

- `AgentState`
- mock nodes
- `v1_workflow.py`
- workflow 测试
- reducer 验证

当时重点不是 GIS 能力，而是验证：

```text
state 能否在节点之间流转
workflow 顺序是否清晰
测试是否稳定
```

## 阶段 3：动态 AgentState

早期 state 是扁平字段。随着工具链变多，改为动态分区：

```text
plan
workspace
tool_results
metadata
```

当前又加入：

```text
runtime
```

用于后续记录 retry 次数、validator 结果和局部 ReAct 状态。

## 阶段 4：日志与基础模块整理

完成：

- `app/utils/logging.py`
- `configure_logging`
- `get_logger`
- 必要 `__init__.py`
- registry 基础整理

日志只记录工具入口、关键参数、输出路径和错误定位，不在每个小函数里过度打印。

## 阶段 5：栅格数据准备工具链

完成：

- AOI 解析
- STAC scene plan
- Sentinel-2 asset 下载
- coverage diagnostics
- mosaic
- clip
- `prepare_raster_inputs`

关键演进：

- AOI 数据源从 geoBoundaries 切换到 Nominatim
- coverage 从 bbox 粗略判断改为 Shapely + AOI GeoJSON
- scene 选择从按云量排序，演进为 coverage-aware greedy selection

## 阶段 6：Workspace 工具

完成：

- `app/tools/workspace`
- `create_workspace`
- `WorkspaceRequest`
- `WorkspaceResult`

设计变化：

```text
prepare 不再自己创建 UUID
流程开始时统一创建 workspace
后续工具共享 workspace_dir
```

## 阶段 7：Registry 重构

完成：

- `app/registry/raster_products.py`
- Sentinel-2 数据源配置
- Landsat 注册信息
- NDVI / NDWI 指数配置
- band roles
- index formula
- render config

判断：

- 公式、波段和渲染配置属于稳定知识，放在 registry
- LLM 不应直接猜公式或波段

## 阶段 8：指数计算工具

完成：

- `app/tools/index_calculation`
- `calculate_raster_index`
- AST 受限公式执行
- nodata mask
- GeoTIFF 输出

输出：

```text
data/<uuid>/output/<index>.tif
```

## 阶段 9：预览渲染工具

完成：

- `app/tools/render_preview`
- `render_index_preview`
- registry 驱动 colormap
- PNG 输出
- 透明 nodata
- 简化 colorbar

输出：

```text
data/<uuid>/output/<index>_preview.png
```

## 阶段 10：Agent Validation Policy 骨架

当前分支开始把验证和调整逻辑从工具层剥离出来，放到 agent 层。

新增结构：

```text
app/agent/validators/
app/agent/adjusters/
app/agent/policies.py
```

目标：

```text
tool 执行
-> validator 检查结果
-> adjuster 根据 diagnostics 调整参数
-> runtime 记录 retry
-> workflow 路由决定继续、重试或失败
```

这为后续局部 ReAct 做准备，同时保持 `tools/` 仍然是确定性工具层。
