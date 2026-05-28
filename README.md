# Raster Map Agent

Raster Map Agent 是一个自然语言驱动的遥感制图 Agent 项目。当前目标是完成一个本地可运行的 V1：用户输入地图需求后，系统能够准备真实 Sentinel-2 栅格数据，计算 NDVI/NDWI 等指数，渲染预览图，并逐步接入 LangGraph Agent workflow。

## 当前进展

已经完成：

- Python 项目骨架、测试、格式化、CI 和 MkDocs 文档配置
- 动态 `AgentState` 设计
- mock LangGraph workflow
- workspace 创建工具
- Sentinel-2 栅格数据准备链条
- NDVI/NDWI 指数计算工具
- 指数 GeoTIFF 预览渲染工具
- agent 层 raster_prepare validator、智谱 adjuster 与 policy 注册表
- agent 层智谱全局 planner，可生成核心业务 plan 和工具调用顺序

当前真实工具链已经可以产出：

```text
data/<uuid>/clipped_raster/<band>_clipped.tif
data/<uuid>/output/<index>.tif
data/<uuid>/output/<index>_preview.png
```

当前 `v1_workflow.py` 仍是 mock workflow；真实 planner 和工具链已经可以单独调用，
接入 Agent workflow 的工作在后续分支中完成。

## 本地环境变量

真实密钥只放在本地 `.env`，不要提交。`.env.example` 保留字段模板：

```env
ZHIPUAI_API_KEY=
ZHIPUAI_MODEL=glm-4.7-flash
ZHIPUAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
DATA_DIR=./data
```

全局 planner 和 `raster_prepare` adjuster 会通过这些配置调用智谱模型。
测试中使用 fake client，不依赖真实网络和 API key。

## 项目结构

```text
app/
  agent/                 # LangGraph 节点、planner、validator、adjuster、policy
  registry/              # 指数、数据源、渲染配置注册表
  schemas/               # AgentState
  tools/                 # 可独立运行的领域工具
  workflows/             # LangGraph workflow builder
docs/                    # MkDocs / ReadTheDocs 文档
scripts/                 # 本地调试脚本
tests/                   # 单元测试
data/                    # 本地运行产生的任务数据，不进入 git
```

## 文档

详细设计见 `docs/`：

- `docs/architecture.md`
- `docs/raster-toolchain.md`
- `docs/design-decisions.md`
- `docs/development-log.md`
- `docs/roadmap.md`
