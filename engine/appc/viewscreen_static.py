"""Viewscreen static/"snow" overlay support (Python side).

The SDK's `"View Screen Static"` icon group maps, via
`sdk/Build/scripts/Tactical/EffectTextures.py:262` (`LoadStatic`), to three
noise textures under the game data tree:

    data/Textures/Effects/Noise1.tga
    data/Textures/Effects/Noise2.tga
    data/Textures/Effects/Noise3.tga

Our `g_kIconManager` is not built, so this module owns that fixed mapping (and
cites its SDK source) while everything that varies per mission — on/off and the
fMin/fMax intensity range — stays driven by the SDK's SetStaticIsOn /
SetStaticVariation calls. If the icon manager is ever implemented, this constant
is the single thing to replace.
"""
import random
from pathlib import Path

# bridge_set.py-style root resolution: this file is engine/appc/ -> root is two
# parents up, then "game".
_GAME_ROOT = Path(__file__).resolve().parent.parent.parent / "game"

# icon-group name -> ordered list of texture file names (SDK: EffectTextures.LoadStatic)
_STATIC_TEXTURE_FILES = {
    "View Screen Static": ["Noise1.tga", "Noise2.tga", "Noise3.tga"],
}


def static_texture_paths(icon_group):
    """Absolute paths to the noise frames for `icon_group`, or [] if unknown."""
    files = _STATIC_TEXTURE_FILES.get(icon_group)
    if not files:
        return []
    base = _GAME_ROOT / "data" / "Textures" / "Effects"
    return [str(base / f) for f in files]


def static_intensity(fmin, fmax, rng=random.random):
    """Per-frame static intensity: a random flicker in [fmin, fmax], clamped to
    [0, 1] (so the SDK's E5M4 (5,5) reads as full snow). `rng` returns a float
    in [0, 1); injectable for deterministic tests."""
    value = float(fmin) + (float(fmax) - float(fmin)) * rng()
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
