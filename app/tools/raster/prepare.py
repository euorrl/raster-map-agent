"""栅格数据准备 pipeline。

本模块后续作为 raster 工具板块的对外入口，编排 AOI 解析、数据下载、
多 tile 合并和 AOI 裁剪，最终产出可直接进入指数计算的波段 GeoTIFF。
"""
