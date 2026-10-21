"""Warm a hull's damage-related volumes before it is first hit.

The hull's FILL volume (the interior pass's left-the-ship test, decoded from
the hull's paired volume) is decoded on a native background worker, so the
first cut never loads it synchronously. Spawn (host_loop's realize paths)
queues it directly; the warp-tunnel preload, which runs before any ship is
realised, queues it from the model handle here.

The carve's per-instance hull-volume field pipeline (BC's authored
SetDamageResolution pushed per instance, the .dhv bake and its boot-time
pre-bake) was removed with the carve in layered damage phase 4.
"""
from engine import renderer as _renderer

__all__ = ["prewarm_for_model"]


def prewarm_for_model(handle) -> None:
    """Queue the fill-volume decode for a loaded MODEL handle, no instance.

    For the warp-tunnel preload. A renderer failure (a stale .so missing the
    binding) propagates: the preload step logs it."""
    _renderer.prefetch_hull_fill(handle)
