"""On-demand TGA→PNG conversion + in-memory data-URL cache for ship-class
icons.

Looks up `<game>/data/Icons/Ships/<name>.tga` (per the SDK loader at
sdk/Build/scripts/Icons/ShipIcons.py), decodes the TGA, encodes a PNG,
base64-encodes the PNG into a `data:image/png;base64,...` URL, and
caches that URL in memory keyed by species filename stem. The PNG is
also written to disk under native/assets/ui-cef/icons/ships/ for
inspection/debugging — that copy is gitignored.

Returning a data URL (instead of a relative file path) sidesteps
Chromium's file:// same-origin restriction: an <img src="data:..."> is
just inline bytes, so the browser doesn't need to issue a sub-resource
request. The hello.html page can then render the silhouette without
needing --allow-file-access-from-files or a custom CEF scheme handler.

The species name passed in must match the TGA filename stem (e.g.
"Galaxy", "Warbird", "BirdOfPrey"). The mapping from the integer
species enum to filename stem lives in engine.ui.species_icons.
"""
from __future__ import annotations

import base64
import os
from typing import Optional

from engine.ui.tga import decode_tga
from engine.ui.png_encoder import encode_png_rgba


_GAME_ICONS_DIR = "game/data/Icons/Ships"
_CACHE_DIR      = "native/assets/ui-cef/icons/ships"

# species stem → data URL (or None for known-missing).
_resolved: dict[str, Optional[str]] = {}


def reset_cache() -> None:
    _resolved.clear()


def icon_path_for_species(name: str) -> Optional[str]:
    """Returns a `data:image/png;base64,...` URL ready to drop into an
    <img src=...>, or None when the species has no registered TGA.

    First call for a species reads the TGA from disk, decodes it,
    encodes a PNG, base64-encodes the result, and caches the URL.
    Subsequent calls return the cached URL.
    """
    if not name:
        return None
    if name in _resolved:
        return _resolved[name]

    tga_path = os.path.join(_GAME_ICONS_DIR, name + ".tga")
    if not os.path.isfile(tga_path):
        _resolved[name] = None
        return None

    with open(tga_path, "rb") as fp:
        blob = fp.read()
    width, height, rgba = decode_tga(blob)
    png = encode_png_rgba(width, height, rgba)

    # Keep the disk cache for inspection / debugging.
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(_CACHE_DIR, name + ".png")
        with open(cache_path, "wb") as fp:
            fp.write(png)
    except OSError:
        pass  # disk cache is best-effort; data URL still works

    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    _resolved[name] = data_url
    return data_url
