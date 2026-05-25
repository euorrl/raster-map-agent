# Raster Map Agent

Raster Map Agent 是一个自然语言驱动的遥感制图 Agent 项目。

当前 V1 的目标是完成一个本地可运行的完整 Agent 流程：

```text
用户请求
-> planner
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

当前已经跑通真实数据准备链条：

```text
Nominatim AOI
-> Sentinel-2 scene planning
-> coverage diagnostics
-> raster download
-> first mosaic by band
-> AOI clip
-> prepared clipped band GeoTIFFs
```

`create_workspace` 现在负责为每次任务创建独立 UUID workspace，`prepare_raster_inputs` 只接收已有的 `workspace_dir` 并完成栅格数据准备。流程会保留 AOI GeoJSON 和裁剪后的 band GeoTIFF，并在成功后清理原始下载 raster 与 mosaic 中间结果。

下一步重点是：

```text
clipped B04 + clipped B08
-> NDVI GeoTIFF
-> preview PNG
-> metadata
```

## 重点文档

- [开发阶段记录](development-log.md)
- [项目架构](architecture.md)
- [栅格工具链](raster-toolchain.md)
- [Scene 选择算法迭代](scene-selection-evolution.md)
- [关键设计决策](design-decisions.md)
- [路线图](roadmap.md)
