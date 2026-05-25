# Raster Map Agent

Raster Map Agent 是一个自然语言驱动的遥感制图 Agent 项目。

当前 V1 的目标是完成一个本地可运行的完整 Agent 流程：

```text
用户请求
-> planner
-> workspace
-> raster prepare
   -> AOI
   -> scene plan
   -> download
   -> mosaic
   -> clip
-> index calculation
-> render
-> metadata
-> answer
-> LangGraph workflow
```

## 当前状态

当前已经跑通真实数据准备、指数计算与基础渲染链条：

```text
create workspace
-> Nominatim AOI
-> Sentinel-2 scene planning
-> coverage diagnostics
-> raster download
-> first mosaic by band
-> AOI clip
-> prepared clipped band GeoTIFFs
-> index GeoTIFF
-> preview PNG
```

`create_workspace` 负责为每次任务创建独立 UUID workspace。`prepare_raster_inputs` 接收已有的 `workspace_dir` 并完成栅格数据准备，保留 AOI GeoJSON 和裁剪后的 band GeoTIFF，并在成功后清理原始下载 raster 与 mosaic 中间结果。

`calculate_raster_index` 负责读取 `clipped_raster/` 中的 band GeoTIFF，根据 registry 传下来的 `band_roles` 和 `index_formula` 计算指数，并输出到：

```text
data/<uuid>/output/<index>.tif
```

`render_index_preview` 负责读取指数 GeoTIFF，根据 registry 中的 `vmin`、`vmax` 和 `colormap` 渲染预览 PNG，并输出到：

```text
data/<uuid>/output/<index>_preview.png
```

下一步重点是：

```text
index GeoTIFF + preview PNG
-> metadata
-> final answer
```

## 重点文档

- [开发阶段记录](development-log.md)
- [项目架构](architecture.md)
- [栅格工具链](raster-toolchain.md)
- [Scene 选择算法迭代](scene-selection-evolution.md)
- [关键设计决策](design-decisions.md)
- [路线图](roadmap.md)
