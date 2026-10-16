# tests/tools/test_sprite_drift.py
"""Committed sprite PNGs match a fresh prep run (spec 2026-10-16 §7.3).
Never hand-edit an output; regenerate with tools/sprites/prep.py --write."""
import json

import pytest
from PIL import Image, ImageChops

from tools.sprites import prep

ENTRIES = {k: v for k, v in json.loads((prep.sprites_dir() / "manifest.json").read_text())["sprites"].items()
           if isinstance(v, dict) and "prep" in v}


@pytest.mark.parametrize("sprite_id", sorted(ENTRIES))
def test_committed_png_matches_prep(sprite_id):
    entry = ENTRIES[sprite_id]
    fresh = prep.build(sprite_id, entry["prep"], prep.sprites_dir() / "src" / sprite_id)
    committed = Image.open(prep.sprites_dir() / entry["file"]).convert("RGBA")
    assert committed.size == fresh.size
    r, g, b, a = ImageChops.difference(committed, fresh).split()
    worst = ImageChops.lighter(ImageChops.lighter(r, g), ImageChops.lighter(b, a))
    off = sum(worst.histogram()[5:])  # per-pixel max channel diff > 4
    assert off <= 0.005 * committed.size[0] * committed.size[1], f"{off} pixels drifted"


def test_every_prep_entry_has_its_sources():
    for sid, entry in ENTRIES.items():
        src = prep.sprites_dir() / "src" / sid
        assert (src / "black.jpeg").is_file(), sid
        if entry["prep"].get("background") == "green_matte":
            assert (src / "green.jpeg").is_file(), sid
