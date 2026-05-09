# Phase 2 Sub-Project Status

Phase 2 of the open_stbc rebuild (the C++ engine replacing `Appc.dll`) is
broken into sub-projects, each with its own design spec under
`docs/superpowers/specs/`. This file is the long-term index of what's done,
in flight, and what remains; it survives across spec revisions and points
into the spec docs for full context.

## Renderer sub-projects (item-by-item from the renderer breakdown)

| # | Sub-project | Status | Spec | Deferred-work tracker |
|---|---|---|---|---|
| 1 | NIF loader | Implemented (v1 ship gate met 2026-05-09) | [2026-05-08-nif-loader-design.md](../superpowers/specs/2026-05-08-nif-loader-design.md) | (closed at v1; no backlog) |
| 2 | Asset pipeline | Implemented (v1 ship gate met 2026-05-09; 99 tests passing including end-to-end Galaxy.nif smoke) | [2026-05-09-asset-pipeline-design.md](../superpowers/specs/2026-05-09-asset-pipeline-design.md) | [§ Deferred / future work](../superpowers/specs/2026-05-09-asset-pipeline-design.md#deferred--future-work) + [`native/src/assets/docs/deferred_work.md`](../../native/src/assets/docs/deferred_work.md) |
| 3 | Scene-graph runtime | Not started | — | — |
| 4 | Render pipeline (window/context/shaders/draws) | Not started | — | — |
| 5 | Python ↔ C++ glue | Not started | — | — |
| 6 | BC-specific extensions (glow/specular conventions, hardpoint markers, damage nodes) | Not started | — | — |

## Asset pipeline — known follow-ups

The asset pipeline's spec carries an 18-item deferred-work backlog covering:

- **Rendering features that need new pipeline hooks:** vertex tangent slot
  (for normal mapping), HDR texture format, LOD chain population
  (meshoptimizer-driven), continuous LOD via mesh shaders.
- **Pipeline ergonomics that grow with the renderer:** async loading, GL
  context-loss recovery, Material normalization layer, glow/specular suffix
  conventions, mod / asset-overlay support.
- **Format support beyond TGA:** PNG / DDS / BC1-7 compressed textures.
- **Cross-cutting concerns:** Phase 1 Python bindings, save/load, streaming.
- **Out-of-scope handoffs:** skinned animation playback (item 3),
  hardpoint / damage-node interpretation (item 6), particle effects
  (gap_analysis confirms procedural, not asset-pipeline), `NiBinaryVoxelData`
  semantics.

See the spec's "Deferred / future work" section for the full list with
context for each item.

## Update protocol

When a sub-project's status changes (started → in flight → implemented), or
when an item is added/removed from a deferred-work backlog, update both:

1. The spec doc's "Deferred / future work" section
2. This index, if the headline status changes
