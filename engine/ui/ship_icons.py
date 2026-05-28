"""On-demand TGA→PNG conversion + disk cache for ship-class icons.

Looks up `<game>/data/Icons/Ships/<name>.tga` (per the SDK loader at
sdk/Build/scripts/Icons/ShipIcons.py), decodes the TGA, encodes a PNG,
writes it to a cache directory, and returns the CEF-relative URL.
Subsequent calls return the cached URL without re-encoding.

The species name passed in must match the TGA filename stem (e.g.
"Galaxy", "Warbird", "BirdOfPrey"). The SDK exposes these via
App.SPECIES_GALAXY etc.; engine/appc/properties.py:ShipProperty
exposes the corresponding string via GetSpeciesName.
"""
from __future__ import annotations

import os
from typing import Optional

from engine.ui.tga import decode_tga
from engine.ui.png_encoder import encode_png_rgba


_GAME_ICONS_DIR = "game/data/Icons/Ships"
_CACHE_DIR      = "native/assets/ui-cef/icons/ships"
_URL_PREFIX     = "icons/ships"

_resolved: dict[str, Optional[str]] = {}


def reset_cache() -> None:
    _resolved.clear()


def icon_path_for_species(name: str) -> Optional[str]:
    if not name:
        return None
    if name in _resolved:
        return _resolved[name]

    tga_path = os.path.join(_GAME_ICONS_DIR, name + ".tga")
    if not os.path.isfile(tga_path):
        _resolved[name] = None
        return None

    cache_path = os.path.join(_CACHE_DIR, name + ".png")
    if not os.path.isfile(cache_path):
        with open(tga_path, "rb") as fp:
            blob = fp.read()
        width, height, rgba = decode_tga(blob)
        png = encode_png_rgba(width, height, rgba)
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(cache_path, "wb") as fp:
            fp.write(png)

    url = f"{_URL_PREFIX}/{name}.png"
    _resolved[name] = url
    return url
