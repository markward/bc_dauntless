"""Warm a hull's damage-related state before it is first hit.

The hull's FILL volume (the interior pass's left-the-ship test, decoded from
the hull's paired volume) is decoded on a native background worker, so the
first cut never loads it synchronously. The hull's ray-trace BVH is built
up front for the same reason: lazily, the first trace pays for it in combat
(perf-register SIG-039/040). The hull's structure-part detection (severance's
regions, layered damage phase 4 §2.2) starts here too, read from its .sps disk
cache when it holds the hull. Spawn (host_loop's realize paths) warms both
directly; the warp-tunnel preload, which runs before any ship is realised,
warms them from the model handle here.

The carve's per-instance hull-volume field pipeline (BC's authored
SetDamageResolution pushed per instance, the .dhv bake and its boot-time
pre-bake) was removed with the carve in layered damage phase 4.
"""
from engine import renderer as _renderer

__all__ = ["prewarm_for_model"]


def prewarm_for_model(handle) -> None:
    """Queue the fill-volume decode and the structure-part detection, and
    build the ray-trace BVH, for a loaded MODEL handle, no instance.

    For the warp-tunnel preload. A renderer failure (a stale .so missing the
    binding) propagates: the preload step logs it."""
    _renderer.prefetch_hull_fill(handle)
    _renderer.prefetch_structure_parts(handle)
    _renderer.prewarm_trace_accel(handle)
