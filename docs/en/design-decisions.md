# Key Design Decisions

中文版: [关键设计决策](../design-decisions.md)

This document records the design decisions that remain valid in the current V1.

## Controlled Workflow Instead of Free Tool Calling

The LLM is responsible only for understanding user intent and generating structured `state.plan`. Low-level tool order, parameter sources, validators, and retry logic are controlled by the system.

Reasons:

- GIS tasks often have strict data access requirements.
- It avoids unstable GIS parameters composed directly by the LLM.
- It keeps raster route execution order testable and reproducible.
- It makes the registry the single stable source of product capability.
- It lets validator / adjuster logic operate around deterministic tool call IDs.

The current compiler generates this fixed tool chain for the raster route:

```text
workspace.create_workspace
raster_prepare.prepare_raster_inputs
index_calculation.calculate_raster_index
render_preview.render_index_preview
metadata.export_metadata
answer.generate_final_answer
```

## Registry Defines Product Capability Boundaries

Current V1 supports 6 Sentinel-2 indices:

- NDVI
- SAVI
- NDWI
- NDMI
- NDBI
- NBR

Using a product registry makes it straightforward to extend satellite and index configurations. Real `raster_prepare` currently executes only Sentinel-2.

## Route Templates

Tool combinations and relationships for different tasks are designed as a registry-like structure. This lets the planner choose highly abstract and clearly distinguishable workflows, improving planner accuracy. Templates also absorb part of the project's structural complexity, keeping nodes minimal and greatly reducing graph complexity.

## Tool Rules

Tool rules contain validators and adjusters for functions that need checking. During distributed tool executor execution, they determine whether a single-step tool call needs validation and provide dynamic validator / adjuster composition for different tool calls. They also include functions for checking whether tool rules exist by tool call ID and whether an adjuster's retry count has reached the threshold.

## Compiler / Executor

The compiler only generates `tool_calls`; it does not execute tools. The executor executes one tool call at a time according to `runtime.current_tool_index`.

This design has several benefits:

- Tool call plans can be tested and audited.
- The step-by-step executor can check tool rules after each tool execution.
- Validator / adjuster logic only needs to handle the tool that just completed.
- Retry only needs to set `current_tool_index` back to the target tool call.

## Validator / Adjuster Handle Tool Calls, Not the Plan

Currently, only `raster_prepare` has a tool rule. The validator returns:

- `passed`: continue to later tools;
- `retryable`: enter the adjuster;
- `failed`: terminate and hand off to answer fallback.

The adjuster does not modify `state.plan` directly. It updates only the target `tool_call.params`, writes retry runtime information, and lets the executor retry that tool.

This preserves the user's original intent while recording each engineering parameter adjustment.

## Consistent Output Names

Final user-facing outputs are consistently named:

```text
metadata.json
preview.png
result.tif
```

Index names are no longer used as file names. Product type, index name, formula, data source, time range, and spatial information are written to `metadata.json`.

Reasons:

- Later deployment callers can read fixed files reliably.
- Output file names do not need to be inferred from user requests.
- Output paths can be simplified for the frontend and API.

## Metadata Is Not an AgentState Dump

`metadata.json` is concise product information for users and result provenance. It is not a full `AgentState` dump.

It is produced by `metadata.export_metadata`, which extracts key fields from the plan, runtime registry, tool results, `raster_prepare` diagnostics, validator results, and final GeoTIFF profile.

This avoids exposing internal tool calls, prompts, temporary paths, and runtime control fields as user-facing results.

## Workspace Cleanup Strategy

V1 uses a local workspace. During processing, intermediate data such as AOI files, downloaded imagery, mosaic rasters, and clipped rasters may appear, but final user-facing results keep only:

```text
data/<uuid>/output/
  metadata.json
  preview.png
  result.tif
```

`raster_prepare` deletes AOI, download, and mosaic intermediate directories. `index_calculation` deletes `clipped_raster/` after consuming clipped bands.

V2 can introduce a job lifecycle manager, for example retaining results for 30 minutes after completion and then automatically deleting the whole job workspace.
