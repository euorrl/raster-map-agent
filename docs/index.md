# Raster Map Agent 文档

Raster Map Agent 是一个自然语言驱动的、受控型 Raster Workflow Agent。当前 V1 已经可以在本地端到端运行 Sentinel-2 指数产品生成流程，并输出统一命名的结果文件。

## V1 能力概览

当前 V1 支持：

- 自然语言 planner；
- route decision；
- `raster_product_generate` 与 `direct_answer` 两条 route；
- 六个 Sentinel-2 指数产品：NDVI、SAVI、NDWI、NDMI、NDBI、NBR；
- 真实 STAC 查询、影像下载、AOI 裁剪、指数计算、预览图渲染；
- metadata 导出和 final answer 生成；
- `raster_prepare` validator / adjuster retry loop；
- 本地 workspace 创建与中间文件清理。

## 当前 workflow

```text
planner
-> route decision
-> registry if raster task
-> compiler
-> execute_tool loop
-> optional validate_tool / adjust_tool loop
-> final answer
```

Raster route 的 tool calls 由 compiler 生成，不由 LLM 自由决定：

```text
workspace.create_workspace
raster_prepare.prepare_raster_inputs
index_calculation.calculate_raster_index
render_preview.render_index_preview
metadata.export_metadata
answer.generate_final_answer
```

Direct answer route 只执行：

```text
answer.generate_final_answer
```

## 输出结构

所有指数产品统一输出：

```text
data/<uuid>/output/
  metadata.json
  preview.png
  result.tif
```

产品类型、指数名、公式、数据源、时间范围和空间信息写入 `metadata.json`，不通过文件名表达。

## 文档导航

- [V1 总结](v1-summary.md)
- [项目架构](architecture.md)
- [Backend 服务](backend.md)
- [开发日志](development-log.md)
- [栅格工具链](raster-toolchain.md)
- [关键设计决策](design-decisions.md)
- [Demo Cases](demo-cases.md)
- [Scene 选择算法迭代](scene-selection-evolution.md)
- [路线图](roadmap.md)
