"""Lens-flare scene objects.

Mirrors the SDK-side App.LensFlare API surface. Mission/system scripts
construct flares with::

    pLensFlare = App.LensFlare_Create(pSet)
    pLensFlare.SetSource(pSun, 6)
    pLensFlare.AddFlare(8, "data/textures/rays.tga", 0.0, 0.3, 0.5, 0.1)
    pLensFlare.AddFlare(30, "data/textures/whiteloop.tga", 0.0, 0.075)
    pLensFlare.Build()

The data is renderer-side; gameplay code never reads back from the flare.
The per-frame renderer aggregator walks ``pSet._lens_flares`` and pushes
descriptors to the C++ lens-flare pass.
"""


class LensFlare:
    def __init__(self, pSet):
        self._set = pSet
        self._source = None
        self._direction_mode: int = 1   # SDK: 1=backdrop, 6=object
        self._elements: list[dict] = []
        self._built: bool = False

    def SetSource(self, obj, direction_mode) -> None:
        self._source = obj
        self._direction_mode = int(direction_mode)

    def AddFlare(self, wedges, texture, position, size,
                 freq: float = 0.0, amp: float = 0.0) -> None:
        self._elements.append({
            "wedges":   int(wedges),
            "texture":  str(texture),
            "position": float(position),
            "size":     float(size),
            "freq":     float(freq),
            "amp":      float(amp),
        })

    def Build(self) -> None:
        self._built = True


def LensFlare_Create(pSet) -> LensFlare:
    """SDK signature: ``LensFlare_Create(pSet) -> LensFlare``."""
    flare = LensFlare(pSet)
    if pSet is not None and hasattr(pSet, "_lens_flares"):
        pSet._lens_flares.append(flare)
    return flare


_ALL_SETS = object()   # aggregate_lens_flares_for_renderer's unscoped default


def aggregate_lens_flares_for_renderer(game_root, pSets, *, view=_ALL_SETS) -> list:
    """Return list[dict] for all built LensFlares across pSets.

    With `view` (the render call site passes frames.viewing_set()), only
    flares whose set is in the viewed frame are kept, the source position
    expressed in the viewed set's coordinates; view=None means nothing is
    viewed, so nothing is kept.

    Resolves texture paths against the game root. Drops:
      - flares whose Build() was never called
      - flares whose source object is missing or has no GetWorldLocation
      - flares with zero elements after texture-resolution filtering
    Within a flare, drops elements whose texture path does not resolve.
    Wedge counts are clamped to [3, 64]; very low or very high N produce
    degenerate or excessive meshes upstream.
    """
    from engine.systems import frames
    out = []
    if view is None:
        return out
    scoped = view is not _ALL_SETS
    for pSet in pSets:
        if scoped and frames.offset_between(view, pSet) is None:
            continue
        for flare in getattr(pSet, "_lens_flares", []):
            if not flare._built:
                continue
            src = flare._source
            if src is None:
                continue
            try:
                loc = src.GetWorldLocation()
            except Exception:
                continue
            pos = (loc.x, loc.y, loc.z)
            if scoped:
                pos = frames.in_view(view, pSet, *pos)
            try:
                radius = float(src.GetRadius())
            except Exception:
                radius = 0.0
            elements_out = []
            for e in flare._elements:
                abs_path = (game_root / e["texture"]).resolve()
                if not abs_path.is_file():
                    continue
                wedges = max(3, min(64, int(e["wedges"])))
                elements_out.append({
                    "wedges":       wedges,
                    "texture_path": str(abs_path),
                    "position":     float(e["position"]),
                    "size":         float(e["size"]),
                    "freq":         float(e["freq"]),
                    "amp":          float(e["amp"]),
                })
            if not elements_out:
                continue
            out.append({
                "source_world_pos": pos,
                "source_radius":    radius,
                "elements":         elements_out,
            })
    return out
