# Scene Selection Algorithm Evolution

中文版: [Scene 选择算法迭代](../scene-selection-evolution.md)

This document records the reasoning process and algorithm evolution of `scene_plan` in the raster data preparation module.

This is one of the most important engineering judgments in the current project: remote-sensing data is not simply "download one image for a place." The system needs to select a combination of candidate scenes that is as small as possible, as low-cloud as possible, and still able to cover the AOI.

## Starting Point

User input is usually like:

```text
Generate an NDVI vegetation map for Chengdu, Sichuan, China.
```

After AOI parsing, the tool gets:

```text
boundary_geojson_path
bbox
```

Where:

- `bbox` is used to search candidate scenes in STAC.
- `boundary_geojson_path` is used for real AOI coverage checks and later clipping.

STAC search returns candidate scenes that intersect the bbox. This has several natural limitations:

- Intersecting the bbox does not mean fully covering the AOI.
- A Sentinel-2 tile file is a regular raster rectangle, but the actual valid footprint may be a slanted polygon.
- Footprints for different dates or orbits within the same tile may cover different parts of the tile.
- A low-cloud scene does not necessarily help AOI coverage.

Therefore, scene selection cannot rely only on cloud cover or only on tile grouping.

## Approach 1: Lowest-Cloud Single Scene

The earliest implementation was:

```text
STAC search
-> filter by max_cloud_cover
-> select the single scene with the lowest cloud cover
-> download required bands
```

This approach was simple, but problems appeared quickly:

- A slightly larger AOI may cross multiple tiles.
- A single scene can cover only part of the AOI.
- In QGIS / GeoTIFF.io, large AOI regions may have no data.

Conclusion:

```text
A single scene is suitable only for minimal validation, not for V1 data preparation logic.
```

## Approach 2: Select Low-Cloud Scenes by Tile Group

The second version grouped scenes by Sentinel-2 tile:

```text
STAC search
-> filter by cloud cover
-> group by tile / MGRS
-> keep several low-cloud scenes per group
-> select several scenes from each group for the download plan
```

This solved the "select only one image" problem, but it embedded a wrong assumption:

```text
Scenes under the same tile have roughly the same spatial footprint, so selecting by cloud cover is enough.
```

Actual observation showed this assumption was false.

Within the same tile, two types of scene footprints may appear:

```text
Type A footprint covers the left side of the tile
Type B footprint covers the right side of the tile
```

If all Type A scenes have lower cloud cover, sorting by cloud cover selects Type A scenes repeatedly, leaving the AOI gap covered by Type B scenes unfilled.

Conclusion:

```text
Tile grouping can control candidate pool size, but it cannot be the final selection logic.
```

To keep V1 simple, tile grouping was temporarily removed, and selection logic now directly targets global AOI coverage.

## Approach 3: Real AOI Coverage Diagnostics

Before changing the selection algorithm, the coverage target needed to be fixed.

Early coverage used the AOI bbox:

```text
scene footprint union / AOI bbox polygon
```

This was too conservative. AOI boundaries for cities and provinces are often irregular, and bbox contains large areas outside the AOI, causing the coverage ratio to be underestimated.

It is now changed to:

```text
scene footprint union intersection AOI GeoJSON geometry / AOI GeoJSON geometry
```

In other words:

- STAC search still uses bbox.
- Coverage diagnostics use the real AOI GeoJSON.
- Clip also uses the real AOI GeoJSON.

If AOI GeoJSON is missing or cannot be parsed, diagnostics return:

```json
{
  "coverage_status": "unknown",
  "is_retriable": false,
  "failure_reason": "missing_aoi_geometry"
}
```

This error cannot be solved by expanding dates or relaxing cloud cover, so ReAct should not keep adjusting parameters.

## Approach 4: Global Coverage-Aware Greedy

The current implementation uses global greedy selection.

Core idea:

```text
In each round, select the scene in the time window that intersects the bbox
and contributes the most to the current uncovered AOI area.
If multiple scenes have similar additional contribution, choose the one with lower cloud cover.
```

Flow:

```text
STAC search candidate scenes
-> deduplicate by scene_id
-> hard filter by max_cloud_cover
-> accumulate into global RasterSceneCandidateStore
-> read real AOI GeoJSON
-> run coverage-aware greedy selection over all candidate scenes
-> select at most max_selected_scenes scenes
-> generate RasterScenePlanResult
```

### Input Objects

The algorithm truly cares about three objects:

```text
AOI geometry
candidate scenes
selection state
```

Where:

- `AOI geometry` comes from `boundary_geojson_path`; it is the administrative region or area boundary the user actually cares about.
- `candidate scenes` come from STAC search results; each scene needs at least `scene_id`, `cloud_cover`, `geometry`, and band asset URLs.
- `selection state` is the selected scenes, covered area, and uncovered area maintained during algorithm execution.

This is why coverage cannot continue to use bbox. Bbox is only a search parameter; AOI geometry is the real target during scene selection.

### Candidate Pool Construction

The candidate pool is not directly equal to STAC results. It goes through several processing steps:

```text
STAC features
-> extract RasterScene
-> write into RasterSceneCandidateStore by scene_id
-> automatic deduplication
-> filter scenes without required band assets
-> filter scenes with cloud_cover > max_cloud_cover
-> filter scenes without geometry
```

`RasterSceneCandidateStore` lets multiple queries accumulate candidate scenes. During later local ReAct adjustments, expanded date ranges or relaxed cloud cover can merge new query results into the same store and regenerate the scene plan.

In practice, scene plan generation is fast, so this dynamic storage capability is not used in the agent. Enabling it can slightly reduce time, but it also adds uncertainty because the adjuster LLM may not generate continuous date ranges, which could skip some dates and lose satellite data. This may require detailed prompt tuning to optimize.

### Covered and Uncovered Areas

The algorithm starts with:

```text
covered_geometry = empty
uncovered_geometry = AOI geometry
selected_scenes = []
```

Each time a scene is selected, it updates:

```text
covered_geometry = covered_geometry union scene.geometry
uncovered_geometry = AOI geometry difference covered_geometry
```

Intuitively:

```text
AOI areas already covered by imagery are removed from the remaining gap area.
```

Therefore, other scenes with the same footprint are usually not selected again, because their additional contribution to `uncovered_geometry` becomes zero or very small.

### Single-Round Selection Logic

Each round traverses all candidate scenes that have not yet been selected and calculates their contribution to the current AOI gap:

```text
contribution_area = area(scene.geometry intersection uncovered_geometry)
```

If the scene has no intersection with the AOI, or if its additional contribution is below `min_scene_overlap_ratio`, it does not compete in that round.

Then the algorithm finds the maximum contribution for the round:

```text
best_contribution = max(contribution_area)
```

Only scenes with contribution close to the maximum are allowed to compete by cloud cover:

```text
contribution_area >= best_contribution * contribution_tolerance
```

For example, with `contribution_tolerance=0.95`, any scene that reaches at least 95% of the best scene's contribution counts as spatially competitive. Among these competitors, the algorithm chooses the scene with the lowest cloud cover.

This rule means:

```text
Prioritize spatial coverage first and do not sacrifice too much AOI coverage
for extremely low cloud cover. When spatial contribution is similar,
prefer lower cloud cover.
```

### Pseudocode

```text
selected = []
covered = empty geometry
uncovered = AOI geometry

while len(selected) < max_selected_scenes:
    candidates = []

    for scene in remaining_scenes:
        contribution = area(scene.geometry intersection uncovered)
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

This is a greedy algorithm and does not guarantee a global optimum. Its engineering advantage is that it is clear, explainable, easy to debug, and closer to the current V1 objective than simply sorting by cloud cover.

### Stop Conditions

The algorithm stops when:

- the number of selected scenes reaches `max_selected_scenes`;
- the AOI is nearly fully covered;
- remaining candidate scenes cannot add new coverage to the uncovered area;
- there are no candidate scenes.

After stopping, it calculates the final coverage ratio and writes it to diagnostics.

Current key parameters:

```python
max_cloud_cover = 20
limit = 100
max_selected_scenes = 20
contribution_tolerance = 0.95
min_scene_overlap_ratio = 0
min_coverage_ratio = 0.9
```

Meanings:

- `max_cloud_cover`: maximum allowed cloud cover percentage for candidate scenes. V1 defaults to 20 and ReAct can relax it up to 30.
- `limit`: maximum number of candidate scenes returned by a single STAC request.
- `max_selected_scenes`: maximum number of scenes downloaded in the final plan.
- `contribution_tolerance`: when additional contribution reaches 95% of the best contribution, it is considered close enough to use cloud cover as the priority.
- `min_scene_overlap_ratio`: minimum overlap between a scene and AOI for the scene to participate in selection.
- `min_coverage_ratio`: minimum acceptable coverage ratio for diagnostics to pass the V1 quality threshold.

## Understanding Contribution Ratio

The algorithm maintains an internal variable:

```text
uncovered_geometry
```

It represents the parts of the AOI that have not yet been covered by selected scenes.

Each round calculates for every candidate scene:

```text
contribution_area = scene.geometry intersection uncovered_geometry
```

That is:

```text
How much new coverage this scene can add to the current blank AOI area.
```

Although the code sorts by area internally, it can be understood equivalently as:

```text
contribution_ratio = contribution_area / total AOI area
```

Because total AOI area is the same for all scenes in the same round, sorting by area and sorting by ratio produce the same result.

## How Cloud Cover Participates in Selection

Cloud cover is not considered only at the end, and it is not averaged with coverage.

The current rule is:

```text
First find the scene with the largest additional contribution.
Then find competitive scenes with contribution close to the maximum.
Finally choose the lowest-cloud scene among the competitive scenes.
```

Example:

```text
scene A: additional contribution 40%, cloud cover 18
scene B: additional contribution 39%, cloud cover 2
scene C: additional contribution 20%, cloud cover 1
```

If `contribution_tolerance=0.95`, A and B both enter the competitive set because B reaches more than 95% of A's contribution.

B is selected because its contribution is close and its cloud cover is lower.

C has the lowest cloud cover, but its contribution is too small, so it is not selected.

## Why It May Look Like "One Scene Per Tile"

The current algorithm does not contain any rule that says "only one scene per tile."

But real results often look like:

```text
one scene per effective footprint type
```

The reason is:

```text
After one scene is selected, the AOI area it covers is removed from uncovered_geometry.
```

If other scenes under the same tile highly overlap with it, their additional contribution to the remaining AOI becomes zero or very low.

Therefore, they do not compete again.

This is the desired effect:

```text
Avoid downloading many spatially redundant scenes that differ only in cloud cover.
```

Another scene under the same tile is selected only when it can fill a current AOI gap.

## What Insufficient Coverage Means

If greedy selection stops and coverage is still below the threshold, it means:

```text
The remaining scenes in the current candidate pool can no longer add new AOI coverage.
```

Diagnostics return:

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

This does not mean "the algorithm is broken." It means:

```text
Under the current query conditions, available scenes do not provide enough
valid footprint coverage for the AOI.
```

Later ReAct steps can try:

- expanding the date range;
- relaxing the cloud cover threshold;
- increasing the candidate query limit, which is not enabled because of user waiting time and runtime memory cost.

If none of these solve the issue, the final answer should explain to the user that available remote-sensing imagery coverage is insufficient.

## Functional Boundaries

`scene_plan` only handles metadata-level scene selection:

```text
whether coverage is sufficient
creating a scene download plan
creating a band asset download plan
```

It does not download data or merge pixels.

Therefore:

```text
scene_plan creates the download plan and reduces redundant downloads
download performs real downloading
mosaic merges pixels
clip clips to the real AOI
```

This boundary prevents `scene_plan` from taking on raster download and processing logic too early.

## Coverage Threshold Changed from "Full Coverage" to "Minimum Acceptable Coverage"

In real tests, some AOIs may still fail to reach 100% footprint coverage even when date range and cloud cover conditions are fairly broad. The usual reason is not a code bug, but gaps in the real valid footprints of candidate Sentinel-2 scenes, or AOI edge areas without suitable imagery. In addition, the external function used to calculate coverage can itself have some numerical error, so strict 100% coverage is often hard to reach.

Therefore, 100% coverage is no longer a hard pass condition. V1 introduces:

```python
min_coverage_ratio = 0.9
```

The new judgment logic is:

```text
coverage_ratio >= min_coverage_ratio -> covered
coverage_ratio < min_coverage_ratio  -> not_covered, can enter ReAct adjustment
```

Note: this threshold only affects the pass/fail decision in diagnostics. It does not make scene selection stop immediately when 90% coverage is reached. The selection algorithm still tries to fill AOI coverage until coverage is nearly complete, candidate scenes no longer add contribution, or `max_selected_scenes` is reached.

Reasons:

- Some real regions are still sufficient for demonstrating NDVI calculation, mosaic, clip, and render flow even with missing edge coverage.
- `coverage_ratio` is fully preserved, so the final answer can tell the user "current imagery coverage is about xx%."
- If the ratio is below the threshold, diagnostics still suggest expanding dates or relaxing cloud cover.

This does not abandon quality control. It changes coverage from an absolute gate into an explainable quality metric, greatly improving success rate without losing usability.

## Relationship to Metadata / Answer

Diagnostics produced by `scene_plan` are not only intermediate debugging information. They flow through `tool_results["raster_prepare"]` into state and ultimately serve two goals:

- `metadata.export_metadata`: extracts coverage ratio, coverage status, failure reason, suggested actions, and other product quality information from the state snapshot, then writes them to `output/metadata.json`;
- `answer.generate_final_answer`: explains imagery coverage, retry suggestions, or result limitations in the final answer.

Therefore, scene selection output should remain structured and explainable instead of returning only a success/failure boolean.
