# Raster Map Agent

Raster Map Agent 是一个自然语言驱动的遥感制图 Agent 项目。当前目标是完成一个本地可运行的 V1：用户输入制图需求后，系统能够规划任务、准备真实 Sentinel-2 栅格数据、计算 NDVI/NDWI 等已注册产品、渲染预览图、导出 metadata，并生成最终回答。

## 当前进展

已经完成：

- Python 项目骨架、测试、flake8、CI 和 MkDocs / ReadTheDocs 配置
- 动态 `AgentState`
- 真实 planner 节点接入
- workflow template 注册表
- workflow tool rules 注册表
- workspace 创建工具
- Sentinel-2 栅格数据准备链条
- NDVI/NDWI 产品注册表
- 指数 GeoTIFF 计算工具
- 指数 PNG 预览渲染工具
- metadata 导出工具
- final answer 生成工具
- `raster_prepare` validator 与 adjuster
- 真实工具节点编排的 V1 workflow 骨架
- 缺少 LangGraph 时的线性 fallback runner，便于轻量环境测试

真实工具链目前可以产出：

```text
data/<uuid>/clipped_raster/<band>_clipped.tif
data/<uuid>/output/<index>.tif
data/<uuid>/output/<index>_preview.png
data/<uuid>/output/metadata.json
```

## 当前架构

V1 采用受控 Agent workflow，而不是完全自由 tool-calling agent。

```text
planner
-> registry
-> workspace
-> raster_prepare
-> raster_prepare_validator
-> product_generation
-> answer
```

其中 `product_generation` 当前封装：

```text
index_calculation
render_preview
metadata export
```

Planner 只负责生成结构化 `state.plan`。工具顺序由 workflow/template 控制，后续 compiler 会根据 `plan + registry + workflow template` 生成 `state.tool_calls`。

## Planner 输出

全局 planner 位于：

```text
app/agent/planners/zhipu_planner.py
```

它只写入：

- `state.plan`
- `state.metadata["plan"]`
- `state.runtime["planners"]["global"]`

正常栅格产品任务示例：

```json
{
  "route": "raster_product_generate",
  "answer_mode": "metadata_summary",
  "aoi_query": "Chengdu, Sichuan, China",
  "index_name": "NDVI",
  "start_date": "2024-06-01",
  "end_date": "2024-08-31",
  "max_cloud_cover": 20
}
```

直接回答任务示例：

```json
{
  "route": "direct_answer",
  "answer_mode": "direct_answer"
}
```

Planner 不生成 `tool_calls`，也不输出 `workspace_dir`、`band_roles`、`index_formula`、`scene_limit`、`max_selected_scenes` 等内部工程参数。

## 本地环境变量

真实密钥只放在本地 `.env`，不要提交。`.env.example` 保留字段模板：

```env
ZHIPUAI_API_KEY=
ZHIPUAI_MODEL=glm-4.7-flash
ZHIPUAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
DATA_DIR=./data
```

全局 planner、`raster_prepare` adjuster 和 final answer 工具会通过这些配置调用智谱模型。测试中使用 fake client 或 monkeypatch，不依赖真实网络和 API key。

## 项目结构

```text
app/
  agent/                 # nodes、planner、validator、adjuster
  registry/              # 栅格产品、指数、数据源能力注册表
  schemas/               # AgentState
  tools/                 # 可独立运行的领域工具
  workflows/             # workflow graph、templates、tool rules
docs/                    # MkDocs / ReadTheDocs 文档
scripts/                 # 本地调试脚本
tests/                   # 单元测试
data/                    # 本地运行产物，不进入 git
```

## 验证

当前轻量环境可运行：

```bash
pytest -o addopts=
flake8
```

没有安装 `rasterio` 时，真实 GeoTIFF 读写测试会跳过；安装完整 GIS 依赖后会继续执行。

## 文档

详细设计见 `docs/`：

- `docs/architecture.md`
- `docs/raster-toolchain.md`
- `docs/design-decisions.md`
- `docs/development-log.md`
- `docs/roadmap.md`
