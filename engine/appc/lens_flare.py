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
