# Raster Map Agent

Raster Map Agent 是一个自然语言驱动的遥感制图 Agent 项目。

当前目标是完成本地可运行的 V1 Agent：

```text
用户请求
-> planner
-> AOI
-> download
-> mosaic
-> clip
-> index calculation
-> render
-> metadata
-> answer
-> LangGraph workflow
```

## Contents

- [开发阶段记录](development-log.md)
- [项目架构](architecture.md)
- [栅格工具链](raster-toolchain.md)
- [关键设计决策](design-decisions.md)
- [路线图](roadmap.md)

## Current Focus

当前重点是先补齐本地真实工具链：

```text
Nominatim AOI
-> Sentinel-2 download
-> coverage diagnostics
-> multi-scene mosaic
-> AOI clip
-> NDVI
-> preview
```

随后再接入 planner、局部 ReAct、answer 和 LangGraph workflow，形成完整本地 Agent。
