# Raster Map Agent

Raster Map Agent 是一个自然语言驱动的遥感制图 Agent 项目。

当前目标是完成本地可运行的 V1 Agent：

```text
用户请求
-> planner
-> AOI
-> raster prepare
-> mosaic
-> clip
-> index calculation
-> render
-> metadata
-> answer
-> LangGraph workflow
```

## 当前重点

当前开发重点是先跑通真实的本地工具链：

```text
Nominatim AOI
-> Sentinel-2 scene planning
-> coverage diagnostics
-> raster download
-> multi-scene mosaic
-> AOI clip
-> NDVI
-> preview
```

其中 `scene_plan` 是当前最重要的算法模块。它负责从 STAC 返回的候选 scene 中选择一个尽量少、尽量低云、同时尽量覆盖 AOI 的组合。

相关推理过程见：

- [Scene 选择算法迭代](scene-selection-evolution.md)
- [栅格工具链](raster-toolchain.md)
- [关键设计决策](design-decisions.md)

## 文档导航

- [开发阶段记录](development-log.md)
- [项目架构](architecture.md)
- [栅格工具链](raster-toolchain.md)
- [Scene 选择算法迭代](scene-selection-evolution.md)
- [关键设计决策](design-decisions.md)
- [路线图](roadmap.md)
