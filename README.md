# Raster Map Agent

一个自然语言驱动的遥感制图 Agent 项目。

当前目标是完成本地可运行的 V1 Agent：用户输入自然语言请求后，系统能够准备真实 Sentinel-2 数据，计算指数，渲染预览，并生成最终回答。

## 当前状态

已完成：

- Python 项目骨架、测试、格式化、CI
- mock LangGraph workflow
- AOI 解析
- Sentinel-2 scene plan
- coverage diagnostics
- raster download
- first mosaic by band
- AOI clip
- raster prepare pipeline

当前数据准备链条已经能输出后续 NDVI 计算需要的裁剪后 B04/B08 GeoTIFF。

下一步重点：

```text
clipped B04 + clipped B08
-> NDVI GeoTIFF
-> preview PNG
-> metadata
-> Agent answer
```

## 项目结构

- `app/`：项目源代码
- `tests/`：测试代码
- `scripts/`：本地调试脚本
- `docs/`：项目笔记和设计文档
- `data/`：本地临时数据
- `outputs/`：本地生成结果

## 文档

详细设计记录见 `docs/`，可通过 MkDocs / Read the Docs 构建。
