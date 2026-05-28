# Scene 选择算法迭代

本文记录 raster 数据准备模块中 `scene_plan` 的推理过程和算法演进。

这一部分是当前项目里最关键的工程判断之一：遥感数据不是简单地“按地点下载一张图”，而是要从很多候选 scene 中选择一个尽量少、尽量低云、又能覆盖 AOI 的组合。

## 问题起点

用户输入通常是：

```text
Generate an NDVI vegetation map for Chengdu, Sichuan, China.
```

经过 AOI 解析后，工具会得到：

```text
boundary_geojson_path
bbox
```

其中：

- `bbox` 用于 STAC 搜索候选 scene
- `boundary_geojson_path` 用于真实 AOI coverage 检测和后续 clip

STAC 搜索返回的是与 bbox 相交的候选 scene。这个结果有几个天然限制：

- 与 bbox 相交不代表完整覆盖 AOI
- 一个 Sentinel-2 tile 文件是规则栅格矩形，但真实有效 footprint 可能是斜切多边形
- 同一个 tile 内不同日期或轨道的 footprint 可能覆盖 tile 的不同部分
- 云量低的 scene 不一定对 AOI coverage 有帮助

因此，scene 选择不能只按云量，也不能只按 tile 分组。

## 方案一：最低云量单 scene

最早的实现是：

```text
STAC 搜索
-> 按 max_cloud_cover 过滤
-> 选择云量最低的一个 scene
-> 下载 required bands
```

这个方案简单，但很快暴露问题：

- AOI 稍微大一点就可能跨多个 tile
- 单个 scene 只能覆盖 AOI 的一部分
- QGIS / GeoTIFF.io 中会看到 AOI 大量区域没有数据

结论：

```text
单 scene 只适合作为最小验证，不适合作为 V1 数据准备逻辑。
```

## 方案二：按 tile 分组选择低云量 scene

第二版尝试按 Sentinel-2 tile 分组：

```text
STAC 搜索
-> 按云量过滤
-> 按 tile / MGRS 分组
-> 每组保留若干低云量 scene
-> 每组选择若干 scene 进入下载 plan
```

这个方案解决了“只选一张”的问题，但隐含了一个错误假设：

```text
同一个 tile 下的 scene 空间 footprint 大致相同，只需要按云量选。
```

实际观察发现这个假设不成立。

同一个 tile 内可能出现两类 scene：

```text
A 类 footprint 覆盖 tile 左侧
B 类 footprint 覆盖 tile 右侧
```

如果 A 类 scene 云量都更低，按云量排序会连续选择 A 类 scene，导致 B 类覆盖的 AOI 缺口一直没有被补上。

结论：

```text
tile 分组可以控制候选池规模，但不能作为最终选择逻辑。
```

V1 为了保持简单，暂时进一步去掉 tile 分组，让选择逻辑直接面向全局 AOI coverage。

## 方案三：真实 AOI coverage diagnostics

在改选择算法前，先修正 coverage 的判断对象。

一开始 coverage 使用 AOI bbox：

```text
scene footprint union / AOI bbox polygon
```

这个判断过于保守。城市、省份等 AOI 边界通常非常不规则，bbox 会包含大量 AOI 外部区域，导致 coverage ratio 偏低。

现在改为：

```text
scene footprint union ∩ AOI GeoJSON geometry
/
AOI GeoJSON geometry
```

也就是说：

- STAC 搜索仍然用 bbox
- coverage diagnostics 使用真实 AOI GeoJSON
- clip 也使用真实 AOI GeoJSON

如果缺少 AOI GeoJSON，或者 GeoJSON 无法解析，diagnostics 会返回：

```json
{
  "coverage_status": "unknown",
  "is_retriable": false,
  "failure_reason": "missing_aoi_geometry"
}
```

这个错误不是扩大日期或放宽云量能解决的，所以 ReAct 不应该继续调参。

## 方案四：全局 coverage-aware greedy

当前实现采用全局贪心选择。

核心思想：

```text
每一轮选择最能补当前 AOI 缺口的 scene；
如果多个 scene 的新增贡献接近，再选择云量最低的 scene。
```

流程如下：

```text
STAC 搜索候选 scenes
-> 按 scene_id 去重
-> 按 max_cloud_cover 做硬过滤
-> 累积到全局 RasterSceneCandidateStore
-> 读取真实 AOI GeoJSON
-> 从所有候选 scene 中做 coverage-aware greedy selection
-> 最多选择 max_selected_scenes 个 scene
-> 生成 RasterScenePlanResult
```

### 输入对象

算法真正关心的是三个对象：

```text
AOI geometry
candidate scenes
selection state
```

其中：

- `AOI geometry` 来自 `boundary_geojson_path`，是用户真正关心的行政区或区域边界
- `candidate scenes` 来自 STAC 搜索结果，每个 scene 至少需要有 `scene_id`、`cloud_cover`、`geometry` 和 band asset URL
- `selection state` 是算法运行时维护的已选 scene、已覆盖区域和未覆盖区域

这也是为什么 coverage 不能继续用 bbox。bbox 只是搜索参数，AOI geometry 才是选择 scene 时的真实目标。

### 候选池构建

候选池不是直接等于 STAC 返回结果，而是经过几层处理：

```text
STAC features
-> 提取 RasterScene
-> 按 scene_id 写入 RasterSceneCandidateStore
-> 自动去重
-> 过滤没有 required band asset 的 scene
-> 过滤 cloud_cover > max_cloud_cover 的 scene
-> 过滤没有 geometry 的 scene
```

`RasterSceneCandidateStore` 的作用是让多次查询可以累积候选 scene。后续局部 ReAct 扩大日期或放宽云量时，可以继续把新查询结果合并到同一个 store，再重新生成 plan。

### 已覆盖区域与未覆盖区域

算法开始时：

```text
covered_geometry = empty
uncovered_geometry = AOI geometry
selected_scenes = []
```

每选中一张 scene，就会更新：

```text
covered_geometry = covered_geometry union scene.geometry
uncovered_geometry = AOI geometry difference covered_geometry
```

直观理解是：

```text
已经被影像覆盖的 AOI 区域从“待补洞区域”里扣掉。
```

所以同一个 footprint 的其它 scene 通常不会再次被选中，因为它们对 `uncovered_geometry` 的新增贡献会变成 0 或非常小。

### 单轮选择逻辑

每一轮会遍历所有还没有被选中的候选 scene，计算它对当前 AOI 缺口的贡献：

```text
contribution_area = area(scene.geometry ∩ uncovered_geometry)
```

如果这张 scene 和 AOI 没有交集，或者新增贡献低于 `min_scene_overlap_ratio`，它不会进入本轮竞争。

接着找到本轮最大贡献：

```text
best_contribution = max(contribution_area)
```

只要贡献接近最大值的 scene 才有资格用云量比较：

```text
contribution_area >= best_contribution * contribution_tolerance
```

例如 `contribution_tolerance=0.95` 时，贡献达到最佳 scene 95% 以上的 scene 都算“空间贡献接近”。在这些竞争者中，选择云量最低的一张。

这条规则的含义是：

```text
先保证空间覆盖，不为了极低云量牺牲太多 AOI 覆盖；
当空间贡献差不多时，再选云量更低的 scene。
```

### 伪代码

```text
selected = []
covered = empty geometry
uncovered = AOI geometry

while len(selected) < max_selected_scenes:
    candidates = []

    for scene in remaining_scenes:
        contribution = area(scene.geometry ∩ uncovered)
        if contribution <= minimum_required_contribution:
            continue
        candidates.append((scene, contribution, cloud_cover))

    if candidates is empty:
        break

    best_contribution = max(contribution for each candidate)
    competitive = [
        candidate
        for candidate in candidates
        if candidate.contribution >= best_contribution * contribution_tolerance
    ]

    chosen = scene with lowest cloud_cover in competitive
    selected.append(chosen)
    covered = union(covered, chosen.geometry)
    uncovered = difference(AOI geometry, covered)

    if uncovered is almost empty:
        break
```

这个算法是贪心算法，不保证全局最优。但它的工程优势是清楚、可解释、容易调试，并且比单纯按云量排序更贴近当前 V1 的目标。

### 停止条件

算法会在以下情况停止：

- 已选 scene 数量达到 `max_selected_scenes`
- AOI 已经接近完整覆盖
- 剩余候选 scene 都无法给未覆盖区域带来新增贡献
- 候选 scene 为空

停止后会统一计算最终 coverage ratio，并写入 diagnostics。

当前关键参数：

```python
max_cloud_cover = 20
limit = 100
max_selected_scenes = 20
contribution_tolerance = 0.95
min_scene_overlap_ratio = 0
min_coverage_ratio = 0.7
```

含义：

- `max_cloud_cover`: 候选 scene 允许的最大云量百分比，V1 默认 20，ReAct 最多放宽到 30
- `limit`: 单次 STAC 请求最多返回多少候选 scene
- `max_selected_scenes`: 最终 plan 最多下载多少 scene
- `contribution_tolerance`: 当新增贡献达到最佳贡献的 95% 时，认为贡献接近，可以用云量决定优先级
- `min_scene_overlap_ratio`: scene 至少需要与 AOI 有多少重叠才参与选择
- `min_coverage_ratio`: diagnostics 判定 scene plan 是否达到 V1 最低可接受覆盖率

## 贡献率如何理解

算法内部维护一个变量：

```text
uncovered_geometry
```

它表示当前 AOI 中还没有被已选 scene 覆盖的部分。

每一轮对每个候选 scene 计算：

```text
contribution_area = scene.geometry ∩ uncovered_geometry
```

也就是：

```text
这张 scene 能给当前 AOI 空白区域新增多少覆盖
```

虽然代码内部使用面积排序，但可以等价理解为：

```text
contribution_ratio = contribution_area / AOI 总面积
```

因为同一轮所有 scene 的 AOI 总面积相同，用面积排序和用比例排序结果一致。

## 云量如何参与选择

云量不是最后才考虑，也不是和 coverage 做简单平均。

当前规则是：

```text
先找出新增贡献最大的 scene
再找出贡献接近最大值的竞争 scene
最后在竞争 scene 中选择云量最低的一张
```

例如：

```text
scene A: 新增贡献 40%, 云量 18
scene B: 新增贡献 39%, 云量 2
scene C: 新增贡献 20%, 云量 1
```

如果 `contribution_tolerance=0.95`，那么 A 和 B 都进入竞争集合，因为 B 的贡献达到了 A 的 95% 以上。

最终会选择 B，因为它贡献接近但云量更低。

C 虽然云量最低，但贡献差太多，不会被选。

## 为什么看起来像“每个 tile 只选一张”

当前算法没有写任何“每个 tile 只能选一张”的规则。

但实际结果经常表现为：

```text
每个有效 footprint 类型只选一张 scene
```

原因是：

```text
一张 scene 被选中后，它覆盖的 AOI 区域会从 uncovered_geometry 中扣掉。
```

如果同一个 tile 下的其它 scene footprint 与它高度重叠，那么这些 scene 对剩余 AOI 的新增贡献会变成 0 或很低。

因此它们不会再次进入竞争。

这正是想要的效果：

```text
避免下载大量空间上重复、只是云量不同的 scene。
```

只有当同一个 tile 的另一张 scene 能补上当前 AOI 的缺口时，它才会再次被选中。

## coverage 不达标时说明什么

如果 greedy 选择停止后仍然不达标，说明：

```text
当前候选池中剩余 scene 已经无法补充新的 AOI 覆盖。
```

这时 diagnostics 会返回：

```json
{
  "coverage_status": "not_covered",
  "failure_reason": "insufficient_spatial_coverage",
  "is_retriable": true,
  "suggested_actions": [
    "expand_date_range",
    "increase_max_cloud_cover"
  ]
}
```

它的含义不是“算法坏了”，而是：

```text
当前查询条件下，可用 scene 对 AOI 的有效 footprint 覆盖不足。
```

后续 ReAct 可以尝试：

- 扩大日期范围
- 放宽云量阈值
- 增加查询候选数量

如果这些都无法解决，最终 answer 应该向用户说明遥感影像可用覆盖率不足。

## 与 mosaic 的边界

`scene_plan` 只处理 metadata 层面的 scene 选择：

```text
选哪些 scene
下载哪些 band asset
coverage 是否足够
```

它不处理像素合并，也不做 median。

后续 `mosaic` 模块负责：

```text
同一 band 的多个 GeoTIFF
-> 空间合并
-> 重叠区 median / mean / first 等策略
-> 输出一张 band mosaic GeoTIFF
```

因此：

```text
scene_plan 负责减少冗余下载
mosaic 负责像素层合并
clip 负责裁剪到真实 AOI
```

这个边界可以避免 scene_plan 过早承担 raster 像素处理逻辑。

## Coverage 阈值从“完整覆盖”改为“最低可接受覆盖”

在真实测试中发现，即使日期范围和云量条件已经比较宽泛，部分 AOI 仍然可能无法达到
100% footprint 覆盖。原因通常不是代码错误，而是当前候选 Sentinel-2 scene 的真实有效
footprint 本身存在缺口，或者 AOI 边缘区域没有合适影像。

因此 V1 不再把 100% coverage 作为硬性通过条件，而是引入：

```python
min_coverage_ratio = 0.7
```

新的判断逻辑是：

```text
coverage_ratio >= min_coverage_ratio -> covered
coverage_ratio < min_coverage_ratio  -> not_covered，可进入 ReAct 调参
```

注意：这个阈值只影响 diagnostics 的通过/失败判断，不会让 scene 选择在刚达到
70% 时立刻停止。选择算法仍然会尽量补足 AOI coverage，直到接近完整覆盖、候选
scene 没有新增贡献，或达到 `max_selected_scenes`。

这样做的原因：

- 对作品集 V1 来说，跑通完整本地流程比追求工业级完整覆盖更重要
- 一些真实地区即使缺少边缘覆盖，仍然足以展示 NDVI 计算、mosaic、clip、render 流程
- coverage_ratio 会被完整保留，后续 answer 可以向用户说明“当前影像覆盖率约为 xx%”
- 如果低于阈值，diagnostics 仍然会建议扩大日期或放宽云量

这不是放弃质量控制，而是把 coverage 从绝对门槛改成可解释的质量指标。
