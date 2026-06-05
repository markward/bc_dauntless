# ShipDisplay Damage-Row Hardpoint Drive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded four-entry `_DAMAGE_SUBSYSTEMS` walk in [engine/ui/ship_display_panel.py](engine/ui/ship_display_panel.py) with a hardpoint-driven walk that emits one row per damageable subsystem the hardpoint declared with `SetPosition2D`, glyphed from the BC `DamageIcons` enum (0-9), positioned on the silhouette via the hardpoint's pixel coordinates.

**Architecture:** Walk the ship's subsystem tree (top-level + children), keep only subsystems whose `Position2D` is non-zero, map each subsystem's class to a BC `DamageIcons` enum value (Hull→0, Impulse→1, Phaser→2, Power→3, Sensor→4, Shield→5, System→6, Torpedo→7, Warp→8, Disruptor→9), look up the traced SVG, emit `{x_px, y_px, icon_num, icon_svg, state}` descriptors, render in a new overlay container inside `.ship-display__silhouette-stack` via inline SVG injection.

**Tech Stack:**
- Python (`engine.ui.damage_icons`, `engine.ui.ship_display_panel`) — descriptor builder
- Shared trace pipeline (`engine.ui.icon_tracer` — extracted from `weapon_icons.py`)
- `potrace` + `mkbitmap` (already required by `weapon_icons.py`)
- HTML/CSS/JS in `native/assets/ui-cef/panels/ship_display/` — inline `<svg>` overlay

**Scope notes:**
- **Shields stay as-is.** Today's six CSS clip-path bubbles already work; the SDK positions shield faces from LCARS module constants (`LCARS.TOP_SHIELD_Y` etc.), NOT hardpoints. No shield work in this plan.
- **The existing `<ul class="ship-display__damage">` text list is replaced.** The new overlay positions per-subsystem glyphs ON the silhouette; the text list goes away.
- **Glyph comes from subsystem class, not from `SetIconNum`.** The damage subsystems' hardpoints set `Position2D` but not `IconNum` — the SDK `DamageIcon` C++ class picks the glyph based on subsystem type at instantiation. We mirror that with a Python-side class → enum table.
- **Position2D is already typed and tested** ([engine/appc/properties.py:235-238](engine/appc/properties.py#L235-L238)); no property work needed.
- **`SetIconNum` is reserved for WeaponsDisplay** and stays untouched (it's a per-weapon-arc icon number, unrelated to damage glyphs).

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| [engine/ui/icon_tracer.py](engine/ui/icon_tracer.py) | **Create** | Shared TGA → SVG trace helpers (extracted from `weapon_icons.py`) |
| [engine/ui/weapon_icons.py](engine/ui/weapon_icons.py) | Modify | Re-export trace helpers from `icon_tracer`; behaviour unchanged |
| [engine/ui/damage_icons.py](engine/ui/damage_icons.py) | **Create** | 10-entry registry mapping enum → TGA; subsystem-class → enum lookup; SVG resolver |
| [engine/ui/ship_display_panel.py](engine/ui/ship_display_panel.py) | Modify | Replace `_damage_states` + `_DAMAGE_SUBSYSTEMS` with hardpoint walk + descriptor builder; extend snapshot/payload |
| [native/assets/ui-cef/panels/ship_display/ship_display.html](native/assets/ui-cef/panels/ship_display/ship_display.html) | Modify | Add `.ship-display__damage-overlay` container in silhouette-stack; remove `<ul>` text list |
| [native/assets/ui-cef/panels/ship_display/ship_display.css](native/assets/ui-cef/panels/ship_display/ship_display.css) | Modify | Position rules for overlay icons; state colours; remove `.ship-display__damage` rules |
| [native/assets/ui-cef/panels/ship_display/ship_display.js](native/assets/ui-cef/panels/ship_display/ship_display.js) | Modify | Replace `rebuildDamageList` with `rebuildDamageOverlay` (inline SVG injection at x_px/y_px) |
| [tests/unit/test_damage_icons.py](tests/unit/test_damage_icons.py) | **Create** | Class → enum mapping, resolver fallback, registry coverage |
| [tests/unit/test_icon_tracer.py](tests/unit/test_icon_tracer.py) | **Create** | Smoke test for the extracted helpers |
| [tests/host/test_ship_display_damage_descriptors.py](tests/host/test_ship_display_damage_descriptors.py) | **Create** | Hardpoint-driven descriptor pipeline (Galaxy + Sovereign fixtures) |
| [tests/host/test_ship_display_panel.py](tests/host/test_ship_display_panel.py) | Modify | Update existing tests for new `damage_icons` payload field; remove text-list assertions |
| [native/assets/ui-cef/icons/damage/](native/assets/ui-cef/icons/damage/) | **Create** (dir) | Curated SVG overrides (optional — empty initially, cache fallback covers all 10) |

---

## Task 1: Extract trace helpers into `engine/ui/icon_tracer.py`

**Files:**
- Create: `engine/ui/icon_tracer.py`
- Modify: `engine/ui/weapon_icons.py` (re-export the helpers, drop the local copies)
- Test: `tests/unit/test_icon_tracer.py`

Pull the TGA → RGBA → PGM → mkbitmap → potrace → wrap pipeline out of `weapon_icons.py` so `damage_icons.py` can call into it without cross-module private imports. The set of functions to move (and their roles):
- `IconSpec` dataclass + `ROTATE_*` / `MIRROR_*` constants
- `_crop_rgba`, `_mirror_horizontal`, `_mirror_vertical`, `_rotate_180`, `_apply_transform`
- `_extract_region_from_tga`, `_rgba_to_pgm`
- `PotraceMissingError`, `_potrace_available`, `_trace_to_svg`
- `_normalize_svg`, `_wrap_with_inset_clip`
- `_needs_rebuild`

Re-publish the names from `weapon_icons.py` so existing imports keep working. Trace tuning constants (`_TRACE_UPSCALE`, `_TRACE_FILTER_RADIUS`, etc.) move with `_trace_to_svg` since they're its callers' knobs and are tuned for atlas sprites — damage icons can re-use the same tuning.

- [ ] **Step 1.1: Write the failing smoke test**

Create `tests/unit/test_icon_tracer.py`:

```python
"""icon_tracer is the shared TGA → SVG trace pipeline. weapon_icons +
damage_icons both call into it. Smoke-test the public surface so
moves between modules don't silently break either consumer."""
from engine.ui import icon_tracer


def test_icon_spec_exposed():
    spec = icon_tracer.IconSpec("X.tga", 0, 0, 16, 16)
    assert spec.tga == "X.tga"
    assert spec.w == 16


def test_transform_constants_exposed():
    assert icon_tracer.ROTATE_0 == 0
    assert icon_tracer.ROTATE_180 == 1
    assert icon_tracer.MIRROR_NONE == 0
    assert icon_tracer.MIRROR_HORIZONTAL == 1
    assert icon_tracer.MIRROR_VERTICAL == 2


def test_potrace_missing_error_class():
    assert issubclass(icon_tracer.PotraceMissingError, RuntimeError)


def test_wrap_with_inset_clip_idempotent():
    """Re-wrapping an SVG that already has a clipPath should be a no-op."""
    once = icon_tracer._wrap_with_inset_clip(
        '<svg><g><path d="M0,0 L1,1"/></g></svg>'
    )
    twice = icon_tracer._wrap_with_inset_clip(once)
    assert once == twice


def test_weapon_icons_reexports_from_tracer():
    """weapon_icons.py must keep the helpers available under the same
    names so any existing import path still works after the move."""
    from engine.ui import weapon_icons
    assert weapon_icons.IconSpec is icon_tracer.IconSpec
    assert weapon_icons._wrap_with_inset_clip is icon_tracer._wrap_with_inset_clip
```

- [ ] **Step 1.2: Verify it fails**

Run: `uv run pytest tests/unit/test_icon_tracer.py -q`
Expected: `ModuleNotFoundError: No module named 'engine.ui.icon_tracer'`

- [ ] **Step 1.3: Create `engine/ui/icon_tracer.py`**

Move the helpers (whole functions, unchanged) from `engine/ui/weapon_icons.py` into a new `engine/ui/icon_tracer.py`. Top-of-file docstring:

```python
"""Shared TGA → SVG trace pipeline.

Used by ``engine.ui.weapon_icons`` (PhaserArcs atlas) and
``engine.ui.damage_icons`` (per-system 16x16 TGAs in
``game/data/Icons/Damage/``). The pipeline is identical: TGA crop
→ alpha-to-PGM → mkbitmap upscale + threshold → potrace --svg →
normalise dimensions + currentColor → wrap with inset clipPath.

Trace tuning lives here too (``_TRACE_UPSCALE`` etc.) so both
consumers stay in sync. If the damage icons want different tuning
later, parametrise then.
"""
```

Then `cut` and `paste` from weapon_icons.py: `IconSpec`, `ROTATE_*`/`MIRROR_*`, the trace tuning constants block, all `_crop_*`/`_mirror_*`/`_rotate_180`/`_apply_transform`/`_extract_region_from_tga`/`_rgba_to_pgm`/`_potrace_available`/`PotraceMissingError`/`_trace_to_svg`/`_normalize_svg`/`_wrap_with_inset_clip`/`_needs_rebuild`. Imports needed: `import base64, hashlib, os, shutil, subprocess, re; from dataclasses import dataclass; from typing import Optional; from engine.ui.tga import decode_tga`.

- [ ] **Step 1.4: Re-export from `weapon_icons.py`**

At the top of `engine/ui/weapon_icons.py`, replace the moved bodies with a re-export block:

```python
from engine.ui.icon_tracer import (
    IconSpec,
    ROTATE_0, ROTATE_180,
    MIRROR_NONE, MIRROR_HORIZONTAL, MIRROR_VERTICAL,
    PotraceMissingError,
    _crop_rgba, _mirror_horizontal, _mirror_vertical, _rotate_180,
    _apply_transform, _extract_region_from_tga, _rgba_to_pgm,
    _potrace_available, _trace_to_svg, _normalize_svg,
    _wrap_with_inset_clip, _needs_rebuild,
)
```

Delete the now-moved function bodies + constants from `weapon_icons.py`. Keep everything else (registry, `trace_atlas`, `trace_all`, `export_reference_pngs`, `reset_cache`, `icon_svg_for_num`) — those stay weapon-specific.

- [ ] **Step 1.5: Verify the smoke test passes**

Run: `uv run pytest tests/unit/test_icon_tracer.py -q`
Expected: 5 passed.

- [ ] **Step 1.6: Verify existing weapon icon tests still pass**

Run: `uv run pytest tests/unit/test_weapon_icons.py tests/unit/test_property_icon_setters.py tests/unit/test_subsystem_mirrors_icons.py tests/host/test_weapons_display_panel.py -q`
Expected: all pass (no regressions).

- [ ] **Step 1.7: Commit**

```bash
git checkout -b feat/ship-display-damage-hardpoint
git add engine/ui/icon_tracer.py engine/ui/weapon_icons.py tests/unit/test_icon_tracer.py
git commit -m "refactor(ui): extract shared TGA→SVG trace pipeline into icon_tracer"
```

---

## Task 2: Subsystem-class → DamageIcons enum mapping

**Files:**
- Create: `engine/ui/damage_icons.py`
- Test: `tests/unit/test_damage_icons.py`

BC's `DamageIcons` enum (0-9) is keyed by C++ subsystem type at icon-instantiation time. We mirror that with an explicit class table. The 10 mappings come from `sdk/Build/scripts/Icons/DamageIcons.py:17-56`:

| Num | Glyph TGA | Subsystem class (engine.appc.subsystems) |
|----|----|----|
| 0 | Hull.tga | `HullSubsystem` |
| 1 | Impulse.tga | `ImpulseEngineSubsystem` |
| 2 | Phaser.tga | `PhaserBank` (children of `PhaserSystem`); fallback for the parent phaser system |
| 3 | Power.tga | `PowerSubsystem` |
| 4 | Sensor.tga | `SensorSubsystem` |
| 5 | Shield.tga | `ShieldSubsystem` |
| 6 | System.tga | unknown / fallback |
| 7 | Torpedo.tga | `TorpedoTube`, `TorpedoLauncher`, fallback for the parent torpedo system |
| 8 | Warp.tga | `WarpEngineSubsystem` |
| 9 | Disruptor.tga | `PulseWeapon`, fallback for the parent pulse-weapon system |

- [ ] **Step 2.1: Write the failing test**

Create `tests/unit/test_damage_icons.py`:

```python
"""damage_icons.icon_num_for_subsystem maps a ShipSubsystem instance
to its BC ``DamageIcons`` enum value. Mapping is keyed by isinstance
checks against the engine's subsystem classes; unknown types fall
back to System (6) — the SDK's "unknown system" slot.
"""
import pytest

from engine.appc import subsystems as ss
from engine.ui import damage_icons


@pytest.mark.parametrize("cls,expected", [
    (ss.HullSubsystem,          0),
    (ss.ImpulseEngineSubsystem, 1),
    (ss.PhaserBank,             2),
    (ss.PowerSubsystem,         3),
    (ss.SensorSubsystem,        4),
    (ss.ShieldSubsystem,        5),
    (ss.TorpedoTube,            7),
    (ss.WarpEngineSubsystem,    8),
    (ss.PulseWeapon,            9),
])
def test_known_classes_map_to_expected_enum(cls, expected):
    sub = cls.__new__(cls)
    assert damage_icons.icon_num_for_subsystem(sub) == expected


def test_unknown_class_falls_back_to_system_6():
    class Bogus:
        pass
    assert damage_icons.icon_num_for_subsystem(Bogus()) == 6


def test_none_falls_back_to_system_6():
    assert damage_icons.icon_num_for_subsystem(None) == 6


def test_registry_covers_all_10_enum_values():
    """damage_icons.ICON_REGISTRY must have entries 0..9 covering the
    full DamageIcons enum, so every mapped subsystem has a traceable
    glyph available."""
    assert set(damage_icons.ICON_REGISTRY.keys()) == set(range(10))
```

Note: the parametrize list will need adjustment for whatever the real class names are — Step 2.3 reads the actual class names from `engine/appc/subsystems.py` before fixing the test list.

- [ ] **Step 2.2: Verify it fails**

Run: `uv run pytest tests/unit/test_damage_icons.py -q`
Expected: `ModuleNotFoundError: No module named 'engine.ui.damage_icons'`

- [ ] **Step 2.3: Reconcile class names**

Open `engine/appc/subsystems.py` and confirm the exact names. The plan's expected names are `HullSubsystem`, `ImpulseEngineSubsystem`, `PhaserBank`, `PowerSubsystem`, `SensorSubsystem`, `ShieldSubsystem`, `TorpedoTube`, `WarpEngineSubsystem`, `PulseWeapon`. If any differ (e.g. `Phaser`, `TorpedoLauncher`, `WarpEngine`), update the test parametrize list and the implementation table to match. **Do not** add aliases — use whatever the canonical name in the engine is.

- [ ] **Step 2.4: Create `engine/ui/damage_icons.py`**

```python
"""DamageDisplay atlas tracer + subsystem-class → enum mapping.

BC's damage display picks a glyph per-subsystem at instantiation
time based on the subsystem's C++ type — see the comment in
``sdk/Build/scripts/Icons/DamageIcons.py:17`` ("Icon numbers should
match up with DamageIcon::DamageIcons enum"). We mirror that with
an explicit Python class table.

Glyph sources live as standalone 16x16 TGAs under
``game/data/Icons/Damage/`` (Hull.tga, Impulse.tga, ...). Trace
pipeline is the shared ``engine.ui.icon_tracer`` flow used by
``engine.ui.weapon_icons``. Cache: ``cache/icons/damage/{num}.svg``.
Curated overrides: ``native/assets/ui-cef/icons/damage/{num}.svg``.
"""
from __future__ import annotations

import os
from typing import Optional

from engine.appc import subsystems as ss
from engine.ui.icon_tracer import (
    IconSpec,
    PotraceMissingError,
    _extract_region_from_tga,
    _needs_rebuild,
    _trace_to_svg,
    _wrap_with_inset_clip,
)


_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_DAMAGE_DIR = os.path.join(_PROJECT_ROOT, "game", "data", "Icons", "Damage")
_CURATED_DIR = os.path.join(
    _PROJECT_ROOT, "native", "assets", "ui-cef", "icons", "damage",
)
_SVG_CACHE_DIR = os.path.join(_PROJECT_ROOT, "cache", "icons", "damage")


# Damage TGAs are 16x16 standalone files (not an atlas), so every
# IconSpec uses (0, 0, 16, 16) with no transform. Numbers mirror the
# DamageIcons enum at sdk/Build/scripts/Icons/DamageIcons.py:17-56.
ICON_REGISTRY: dict[int, IconSpec] = {
    0: IconSpec("Hull.tga",     0, 0, 16, 16),
    1: IconSpec("Impulse.tga",  0, 0, 16, 16),
    2: IconSpec("Phaser.tga",   0, 0, 16, 16),
    3: IconSpec("Power.tga",    0, 0, 16, 16),
    4: IconSpec("Sensor.tga",   0, 0, 16, 16),
    5: IconSpec("Shield.tga",   0, 0, 16, 16),
    6: IconSpec("System.tga",   0, 0, 16, 16),
    7: IconSpec("Torpedo.tga",  0, 0, 16, 16),
    8: IconSpec("Warp.tga",     0, 0, 16, 16),
    9: IconSpec("Disruptor.tga", 0, 0, 16, 16),
}


# Class → enum. First matching isinstance wins, so order subclasses
# before their superclasses if any are listed. The default fallback
# is 6 (System) per the SDK comment.
_CLASS_TABLE: tuple = (
    (ss.HullSubsystem,          0),
    (ss.ImpulseEngineSubsystem, 1),
    (ss.PhaserBank,             2),
    (ss.PowerSubsystem,         3),
    (ss.SensorSubsystem,        4),
    (ss.ShieldSubsystem,        5),
    (ss.TorpedoTube,            7),
    (ss.WarpEngineSubsystem,    8),
    (ss.PulseWeapon,            9),
)


def icon_num_for_subsystem(sub) -> int:
    """Returns the BC DamageIcons enum value for a ShipSubsystem.
    Unknown / None / non-subsystem inputs fall back to 6 (System)."""
    if sub is None:
        return 6
    for cls, num in _CLASS_TABLE:
        if isinstance(sub, cls):
            return num
    return 6
```

- [ ] **Step 2.5: Verify the mapping tests pass**

Run: `uv run pytest tests/unit/test_damage_icons.py -q -k "not registry"`
Expected: 11 passed (9 known classes + 2 fallbacks).

Then the registry coverage test:

Run: `uv run pytest tests/unit/test_damage_icons.py::test_registry_covers_all_10_enum_values -q`
Expected: passed.

- [ ] **Step 2.6: Commit**

```bash
git add engine/ui/damage_icons.py tests/unit/test_damage_icons.py
git commit -m "feat(ui): subsystem-class → DamageIcons enum mapping"
```

---

## Task 3: SVG resolver for damage icons

**Files:**
- Modify: `engine/ui/damage_icons.py`
- Test: `tests/unit/test_damage_icons.py`

Same curated → cache → trace fallback as `weapon_icons.icon_svg_for_num`. The damage TGAs trace cleanly because they're 16×16 anti-aliased symbols; the 4× upscale already used for weapons stays appropriate.

- [ ] **Step 3.1: Write the failing test**

Append to `tests/unit/test_damage_icons.py`:

```python
def test_icon_svg_for_num_returns_none_for_unknown(tmp_path, monkeypatch):
    # Force an empty curated dir + empty cache so the resolver has nothing
    # to find; for an unknown enum value it should return None without
    # raising.
    damage_icons.reset_cache()
    assert damage_icons.icon_svg_for_num(99) is None


def test_icon_svg_for_num_prefers_curated_when_present(tmp_path, monkeypatch):
    """Curated SVG under native/assets/ui-cef/icons/damage/{num}.svg
    wins over the trace cache. Verifies the lookup order matches
    weapon_icons.icon_svg_for_num."""
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    (curated_dir / "0.svg").write_text(
        '<svg><path d="M0,0 L1,1" fill="currentColor"/></svg>'
    )
    monkeypatch.setattr(damage_icons, "_CURATED_DIR", str(curated_dir))
    damage_icons.reset_cache()
    svg = damage_icons.icon_svg_for_num(0)
    assert svg is not None
    assert "clipPath" in svg  # _wrap_with_inset_clip applied
```

- [ ] **Step 3.2: Verify failure**

Run: `uv run pytest tests/unit/test_damage_icons.py -q -k icon_svg`
Expected: `AttributeError: module 'engine.ui.damage_icons' has no attribute 'icon_svg_for_num'` (or `reset_cache`).

- [ ] **Step 3.3: Add the resolver**

Append to `engine/ui/damage_icons.py`:

```python
# ── Resolver ───────────────────────────────────────────────────────────

_svg_cache: dict[int, Optional[str]] = {}


def reset_cache() -> None:
    """Drop the in-memory SVG cache. Tests use this between cases."""
    _svg_cache.clear()


def trace_all() -> set[int]:
    """Trace every registered icon into the cache dir. Skips icons
    whose source TGA is missing or whose cache entry is up-to-date.
    Swallows individual potrace failures (one bad icon doesn't block
    the others). Same idempotency contract as weapon_icons.trace_all.
    """
    import subprocess
    os.makedirs(_SVG_CACHE_DIR, exist_ok=True)
    written: set[int] = set()
    tga_cache: dict[str, bytes] = {}
    for num, spec in ICON_REGISTRY.items():
        out_path = os.path.join(_SVG_CACHE_DIR, f"{num}.svg")
        source_path = os.path.join(_DAMAGE_DIR, spec.tga)
        if not os.path.isfile(source_path):
            continue
        if not _needs_rebuild(out_path, source_path):
            continue
        if spec.tga not in tga_cache:
            with open(source_path, "rb") as fp:
                tga_cache[spec.tga] = fp.read()
        try:
            w, h, rgba = _extract_region_from_tga(
                tga_cache[spec.tga],
                spec.x, spec.y, spec.w, spec.h,
                spec.rotate, spec.mirror,
            )
            svg = _trace_to_svg(rgba, w, h)
        except (subprocess.CalledProcessError, PotraceMissingError):
            continue
        # _trace_to_svg returns SVG with native pixel width/height; the
        # damage panel renders these at the source 16×16 size against
        # the silhouette, so no extra normalisation needed.
        with open(out_path, "w") as fp:
            fp.write(svg)
        written.add(num)
    return written


def icon_svg_for_num(num: int) -> Optional[str]:
    """Returns SVG text for a DamageIcons enum value, or None for
    unknown numbers / missing source TGA / potrace not installed.

    Lookup order:
    1. Curated ``native/assets/ui-cef/icons/damage/{num}.svg``
    2. Auto-traced ``cache/icons/damage/{num}.svg`` (first call
       triggers ``trace_all`` for the whole registry)
    """
    if num in _svg_cache:
        return _svg_cache[num]
    if num not in ICON_REGISTRY:
        _svg_cache[num] = None
        return None
    curated_path = os.path.join(_CURATED_DIR, f"{num}.svg")
    if os.path.isfile(curated_path):
        with open(curated_path, "r", encoding="utf-8") as fp:
            svg = fp.read()
        svg = _wrap_with_inset_clip(svg)
        _svg_cache[num] = svg
        return svg
    svg_path = os.path.join(_SVG_CACHE_DIR, f"{num}.svg")
    if not os.path.isfile(svg_path):
        try:
            trace_all()
        except OSError:
            _svg_cache[num] = None
            return None
    if not os.path.isfile(svg_path):
        _svg_cache[num] = None
        return None
    with open(svg_path, "r", encoding="utf-8") as fp:
        svg = fp.read()
    svg = _wrap_with_inset_clip(svg)
    _svg_cache[num] = svg
    return svg
```

- [ ] **Step 3.4: Verify resolver tests pass**

Run: `uv run pytest tests/unit/test_damage_icons.py -q`
Expected: all pass.

- [ ] **Step 3.5: Commit**

```bash
git add engine/ui/damage_icons.py tests/unit/test_damage_icons.py
git commit -m "feat(ui): damage-icon SVG resolver with curated→cache→trace fallback"
```

---

## Task 4: Walk damageable subsystems with a `Position2D`

**Files:**
- Modify: `engine/ui/ship_display_panel.py`
- Test: `tests/host/test_ship_display_damage_descriptors.py`

Walk the ship's subsystem tree. For top-level systems (Hull, Sensor, Shield, ImpulseEngine, WarpEngine, Power, Repair, Cloaking, PhaserSystem, TorpedoSystem, PulseWeaponSystem), recurse into their children. Filter to subsystems whose `_property` has a non-`(0, 0)` `Position2D`. SDK convention: `Position2D == (0, 0)` means "not displayed."

Reading `Position2D` correctly: the property is mirrored on `ShipSubsystem` via `SetProperty` (per the `_icon_num` mirror at [engine/appc/subsystems.py:556-568](engine/appc/subsystems.py#L556-L568)). **Position2D is NOT yet mirrored** — we have to add it to that block. Add this as Step 4.1 before the descriptor walk.

- [ ] **Step 4.1: Write the failing mirror test**

Add to `tests/unit/test_subsystem_mirrors_icons.py` (existing file):

```python
def test_subsystem_mirrors_position_2d_from_property():
    """SubsystemProperty.SetPosition2D values must round-trip onto the
    runtime ShipSubsystem so the ship-display panel can read x/y_px
    without re-walking the property tree. Matches the existing
    IconNum / IconPosition mirror pattern."""
    from engine.appc import properties as p, subsystems as s
    prop = p.HullProperty("Hull")
    prop.SetPosition2D(64.0, 40.0)
    sub = s.HullSubsystem(prop)
    assert sub.GetPosition2D() == (64.0, 40.0)


def test_subsystem_position_2d_defaults_to_origin():
    """Subsystems without a Position2D set must report (0.0, 0.0).
    The damage descriptor builder treats (0,0) as "hide from panel" so
    Phase 1 ships without hardpoint coords stay invisible by default."""
    from engine.appc import properties as p, subsystems as s
    prop = p.HullProperty("Hull")
    sub = s.HullSubsystem(prop)
    assert sub.GetPosition2D() == (0.0, 0.0)
```

- [ ] **Step 4.2: Verify failure**

Run: `uv run pytest tests/unit/test_subsystem_mirrors_icons.py::test_subsystem_mirrors_position_2d_from_property tests/unit/test_subsystem_mirrors_icons.py::test_subsystem_position_2d_defaults_to_origin -q`
Expected: AttributeError on `sub.GetPosition2D`.

- [ ] **Step 4.3: Extend the SetProperty mirror + add the runtime getter**

In `engine/appc/subsystems.py`:

1. In the `__init__` of `ShipSubsystem` (find where `_icon_num: int = 0` is set; near line 430 per the codebase notes), add:

```python
        # DamageDisplay panel coord (pixel-space against SDK's 640x480
        # reference). Mirrored from SubsystemProperty.SetPosition2D.
        self._position_2d: tuple = (0.0, 0.0)
```

2. In the typed-mirror block at line ~556-568 (the for-loop with `("GetIconNum", "_icon_num", int), ...`), add a sibling block for Position2D. It returns a tuple not a scalar, so it gets its own short loop:

```python
        # DamageDisplay placement — typed on SubsystemProperty,
        # returned as a (x, y) tuple. Same defensive isinstance gate as
        # the icon mirror above so data-bag stubs don't poison the value.
        if hasattr(prop, "GetPosition2D"):
            v = prop.GetPosition2D()
            if (isinstance(v, tuple) and len(v) == 2
                and all(isinstance(c, (int, float)) for c in v)):
                self._position_2d = (float(v[0]), float(v[1]))
```

3. Near the WeaponsDisplay accessor block at ~line 690 (`def GetIconNum(self) -> int:`), add the runtime getter:

```python
    def GetPosition2D(self) -> tuple:
        return self._position_2d
```

- [ ] **Step 4.4: Verify mirror tests pass**

Run: `uv run pytest tests/unit/test_subsystem_mirrors_icons.py -q`
Expected: all pass.

- [ ] **Step 4.5: Commit the mirror**

```bash
git add engine/appc/subsystems.py tests/unit/test_subsystem_mirrors_icons.py
git commit -m "feat(subsystems): mirror SubsystemProperty.Position2D onto ShipSubsystem"
```

- [ ] **Step 4.6: Write the failing descriptor-walk test**

Create `tests/host/test_ship_display_damage_descriptors.py`:

```python
"""Damage-row descriptor pipeline — hardpoint-driven walk over the
ship's subsystem tree, filtered to subsystems with a non-zero
Position2D, glyphed via the DamageIcons enum.

Fixture: Galaxy. Hardpoint (sdk/Build/scripts/ships/Hardpoints/galaxy.py)
declares Hull@(64,40), SensorArray@(64,10), ShieldGenerator@(64,40),
WarpCore@(?), ImpulseEngines, plus per-bank phaser/torpedo positions.
The descriptor builder must surface each one as a row with the right
class-derived icon number.
"""
import pytest

from engine.ui import ship_display_panel as sdp


@pytest.fixture
def galaxy_ship(tmp_path):
    """Build a Galaxy ship from the hardpoint script via the production
    loader path. Phase 1 already exercises this in the bottom of the
    test suite; reuse the helper."""
    from engine.testing.ships import build_ship_from_hardpoint
    return build_ship_from_hardpoint("galaxy")


def test_damage_descriptors_emit_one_row_per_positioned_subsystem(galaxy_ship):
    rows = list(sdp._damage_icon_descriptors(galaxy_ship))
    assert len(rows) > 0
    for row in rows:
        # Position2D must not be (0, 0); SDK uses zeros for "hide"
        assert (row["x_px"], row["y_px"]) != (0.0, 0.0)
        # Every descriptor carries the four required keys
        for k in ("x_px", "y_px", "icon_num", "state"):
            assert k in row


def test_galaxy_hull_emits_row_at_hardpoint_position(galaxy_ship):
    rows = list(sdp._damage_icon_descriptors(galaxy_ship))
    hulls = [r for r in rows if r["icon_num"] == 0]
    assert len(hulls) == 1
    # Galaxy hardpoint: Hull.SetPosition2D(64, 40)
    assert hulls[0]["x_px"] == pytest.approx(64.0)
    assert hulls[0]["y_px"] == pytest.approx(40.0)


def test_galaxy_sensor_array_emits_row_with_sensor_icon_num(galaxy_ship):
    rows = list(sdp._damage_icon_descriptors(galaxy_ship))
    sensors = [r for r in rows if r["icon_num"] == 4]
    assert len(sensors) == 1
    assert sensors[0]["x_px"] == pytest.approx(64.0)
    assert sensors[0]["y_px"] == pytest.approx(10.0)


def test_damage_descriptor_state_reflects_subsystem_condition(galaxy_ship):
    """A healthy subsystem reports state='healthy'; damaging it flips
    the row to 'damaged' / 'disabled' / 'destroyed' following the
    same predicate ladder _subsystem_state uses today."""
    hull = galaxy_ship.GetHull()
    rows = list(sdp._damage_icon_descriptors(galaxy_ship))
    hull_row = next(r for r in rows if r["icon_num"] == 0)
    assert hull_row["state"] == "healthy"

    # Drop to 50% — damaged
    hull.SetCondition(hull.GetMaxCondition() * 0.5)
    rows = list(sdp._damage_icon_descriptors(galaxy_ship))
    hull_row = next(r for r in rows if r["icon_num"] == 0)
    assert hull_row["state"] == "damaged"
```

Note: `build_ship_from_hardpoint` may not exist under that name — check `tests/host/` for an existing hardpoint-loading fixture (one is used by `test_weapons_display_panel.py`) and reuse whatever helper that file uses. Fix the import before running.

- [ ] **Step 4.7: Verify the walk test fails**

Run: `uv run pytest tests/host/test_ship_display_damage_descriptors.py -q`
Expected: `AttributeError: module 'engine.ui.ship_display_panel' has no attribute '_damage_icon_descriptors'`

- [ ] **Step 4.8: Implement `_damage_icon_descriptors`**

In `engine/ui/ship_display_panel.py`, add the walk + descriptor builder. Replace `_DAMAGE_SUBSYSTEMS` with a wider list of source getters that covers all standard damageable systems:

```python
# Source getters for the hardpoint walk. Each getter returns either
# a single subsystem or None. We recurse into children to pick up
# per-bank phasers, per-tube torpedoes, etc. — those carry their own
# Position2D from the hardpoint.
_DAMAGE_SOURCE_GETTERS = (
    "GetHull",
    "GetSensorSubsystem",
    "GetShieldSubsystem",
    "GetImpulseEngineSubsystem",
    "GetWarpEngineSubsystem",
    "GetPowerSubsystem",
    "GetRepairSubsystem",
    "GetCloakingSubsystem",
    "GetPhaserSystem",
    "GetTorpedoSystem",
    "GetPulseWeaponSystem",
)


def _iter_damage_subsystems(ship):
    """Yield every ShipSubsystem reachable from ``ship`` via the
    standard damage source getters, recursing into child subsystems
    so per-bank phasers and per-tube torpedoes surface alongside their
    parent weapon systems. No filtering here — the caller decides
    which rows to render."""
    if ship is None:
        return
    seen = set()
    for getter_name in _DAMAGE_SOURCE_GETTERS:
        getter = getattr(ship, getter_name, None)
        if getter is None:
            continue
        try:
            sub = getter()
        except Exception:
            continue
        if sub is None or id(sub) in seen:
            continue
        seen.add(id(sub))
        yield sub
        # Recurse via the GetNumChildSubsystems / GetChildSubsystem
        # pair (same iteration the WeaponsDisplay walk uses at
        # weapons_display_panel.py:340-345).
        try:
            n = sub.GetNumChildSubsystems()
        except Exception:
            continue
        for i in range(n):
            try:
                child = sub.GetChildSubsystem(i)
            except Exception:
                continue
            if child is None or id(child) in seen:
                continue
            seen.add(id(child))
            yield child


def _damage_icon_descriptors(ship):
    """Per-row descriptors for the damage overlay. Filters to
    subsystems with a non-zero Position2D — the SDK uses (0, 0) to
    mean "don't display." Each descriptor:

        {
          "icon_num": int,        # DamageIcons enum value
          "icon_svg": str | None, # inline SVG, or None if no glyph available
          "x_px":    float,       # hardpoint pixel coord, SDK 640x480 frame
          "y_px":    float,
          "state":   "healthy" | "damaged" | "disabled" | "destroyed",
        }

    Order is the iteration order of _iter_damage_subsystems — stable
    for a given hardpoint, which keeps snapshot equality cheap.
    """
    from engine.ui import damage_icons
    out: list[dict] = []
    for sub in _iter_damage_subsystems(ship):
        try:
            pos = sub.GetPosition2D()
        except Exception:
            continue
        if not isinstance(pos, tuple) or len(pos) != 2:
            continue
        x_px, y_px = float(pos[0]), float(pos[1])
        if x_px == 0.0 and y_px == 0.0:
            continue
        icon_num = damage_icons.icon_num_for_subsystem(sub)
        out.append({
            "icon_num": icon_num,
            "icon_svg": damage_icons.icon_svg_for_num(icon_num),
            "x_px":     x_px,
            "y_px":     y_px,
            "state":    _row_state(sub),
        })
    return out


def _row_state(sub) -> str:
    """Same predicate ladder _subsystem_state uses, but returns
    "healthy" instead of None so the panel always has a class to
    apply. healthy → default text colour; damaged/disabled/destroyed
    → --bc-damage-* CSS tokens."""
    try:
        if hasattr(sub, "IsDestroyed") and sub.IsDestroyed():
            return "destroyed"
        if hasattr(sub, "IsDisabled") and sub.IsDisabled():
            return "disabled"
        if hasattr(sub, "IsDamaged") and sub.IsDamaged():
            return "damaged"
    except Exception:
        pass
    return "healthy"
```

- [ ] **Step 4.9: Verify the walk test passes**

Run: `uv run pytest tests/host/test_ship_display_damage_descriptors.py -q`
Expected: 4 passed.

- [ ] **Step 4.10: Commit**

```bash
git add engine/ui/ship_display_panel.py tests/host/test_ship_display_damage_descriptors.py
git commit -m "feat(ship-display): hardpoint-driven damage subsystem walk"
```

---

## Task 5: Wire damage descriptors into snapshot + payload

**Files:**
- Modify: `engine/ui/ship_display_panel.py`
- Modify: `tests/host/test_ship_display_panel.py`

The snapshot field today carries `damage` as `tuple[(label, state), ...]`. Replace it with `damage_icons` as a frozen tuple of descriptor primitives. The render payload emits `damage_icons: [{icon_num, icon_svg, x_px, y_px, state}]`. The old `damage:` field goes away (no consumer after this refactor).

- [ ] **Step 5.1: Read the existing test file**

```bash
sed -n '1,30p' tests/host/test_ship_display_panel.py
```

Identify which existing tests check the `damage` payload field and update them. Most likely candidates: any test asserting `payload["damage"] == [...]` or shape-checking the damage list.

- [ ] **Step 5.2: Update the failing existing tests**

For any test asserting on the old `damage` field, switch to `damage_icons`. Example:

```python
# Before
assert payload["damage"] == [{"name": "Sensors", "state": "disabled"}]

# After
icons = payload["damage_icons"]
sensor_rows = [r for r in icons if r["icon_num"] == 4]
assert len(sensor_rows) == 1
assert sensor_rows[0]["state"] == "disabled"
```

Run the updated tests — they should now FAIL because the panel still emits `damage`, not `damage_icons`. Confirm with:

```
uv run pytest tests/host/test_ship_display_panel.py -q
```

Expected: failures on the renamed-field assertions.

- [ ] **Step 5.3: Update `_snapshot` and `render_payload`**

In `engine/ui/ship_display_panel.py`:

1. Replace the `damage = _damage_states(ship)` line in `_snapshot` with:

```python
        damage_icons_list = _damage_icon_descriptors(ship)
        # Frozen form for snapshot equality. Position2D / icon_num
        # don't change at runtime, so bucket state only — that's the
        # field that actually flips frame-to-frame.
        damage_frozen = tuple(
            (d["icon_num"], d["x_px"], d["y_px"], d["state"])
            for d in damage_icons_list
        )
```

2. Replace the tuple line at the bottom of `_snapshot`:

```python
        return (ship_id, name, affiliation, species_key, hull_pct,
                shields_pct, damage_frozen, range_km, speed_kph,
                self._minimized, True)
```

3. In `render_payload`, replace the destructuring + the damage payload field:

```python
        (ship_id, name, affiliation, species, hull_pct,
         shields, damage_frozen, range_km, speed_kph,
         minimized, visible) = snap
        # damage_icons rebuilt from the live ship — _snapshot's
        # frozen form is for equality, not transport. The JSON
        # carries the full SVG inline.
        ship_now = _resolve_ship_for_role(self._role) if visible else None
        damage_icons_list = _damage_icon_descriptors(ship_now) if ship_now else []
        payload = {
            "visible":      visible,
            "ship_name":    name,
            "affiliation":  affiliation,
            "species":      species,
            "hull_pct":     hull_pct,
            "shields_pct":  list(shields),
            "damage_icons": damage_icons_list,
            "range_km":     range_km,
            "speed_kph":    speed_kph,
            "minimized":    minimized,
        }
```

4. Delete the now-unused `_damage_states`, `_subsystem_state`, and `_DAMAGE_SUBSYSTEMS` (kept only as helpers for the old text-list field).

5. Update the no-ship snapshot tuples at the top of `_snapshot` so they have the right arity (the `()` previously held the damage tuple — keep `()` as the empty `damage_frozen`):

```python
        if not self._visible:
            return (None, "", "NONE", "", 0.0, (0.0,) * 6, (),
                    None, None, self._minimized, False)
```

(unchanged structure; the `()` was already in the right slot.)

- [ ] **Step 5.4: Verify all ship_display tests pass**

Run: `uv run pytest tests/host/test_ship_display_panel.py tests/host/test_ship_display_damage_descriptors.py tests/unit/test_subsystem_mirrors_icons.py tests/unit/test_damage_icons.py -q`
Expected: all pass.

- [ ] **Step 5.5: Run the wider focused regression batch**

Run: `uv run pytest tests/unit/ tests/host/ --ignore=tests/unit/test_energy_weapon_gating.py -q`
Expected: no new failures (energy-weapon-gating is the pre-existing skip per CLAUDE.md).

- [ ] **Step 5.6: Commit**

```bash
git add engine/ui/ship_display_panel.py tests/host/test_ship_display_panel.py
git commit -m "feat(ship-display): emit damage_icons descriptors in render payload"
```

---

## Task 6: CEF HTML — damage overlay container

**Files:**
- Modify: `native/assets/ui-cef/panels/ship_display/ship_display.html`

The new overlay sits inside `.ship-display__silhouette-stack` so it shares the silhouette's coordinate system. The `<ul class="ship-display__damage">` text list is removed.

- [ ] **Step 6.1: Edit both panel templates**

In `ship_display.html`, inside each `<div class="ship-display__silhouette-stack">`, **after** the existing shield bubbles and **before** the closing `</div>`, add the overlay container:

```html
      <div class="ship-display__damage-overlay" data-bind="damage-overlay"></div>
```

And remove the `<ul class="ship-display__damage" data-bind="damage-list"></ul>` line from each panel body.

The full silhouette-stack for the player panel after edits:

```html
    <div class="ship-display__silhouette-stack">
      <img class="ship-display__silhouette" data-bind="silhouette" alt="" hidden>
      <div class="ship-display__shield shield--top"    data-bind="shield-top"    data-integrity="full"></div>
      <div class="ship-display__shield shield--bottom" data-bind="shield-bottom" data-integrity="full"></div>
      <div class="ship-display__shield shield--front"  data-bind="shield-front"  data-integrity="full"></div>
      <div class="ship-display__shield shield--rear"   data-bind="shield-rear"   data-integrity="full"></div>
      <div class="ship-display__shield shield--left"   data-bind="shield-left"   data-integrity="full"></div>
      <div class="ship-display__shield shield--right"  data-bind="shield-right"  data-integrity="full"></div>
      <div class="ship-display__damage-overlay" data-bind="damage-overlay"></div>
    </div>
```

Same change in the target panel block.

- [ ] **Step 6.2: Commit (HTML only; CSS + JS follow)**

```bash
git add native/assets/ui-cef/panels/ship_display/ship_display.html
git commit -m "feat(ship-display ui): damage-overlay container in silhouette stack"
```

---

## Task 7: CEF CSS — overlay positioning + state colours

**Files:**
- Modify: `native/assets/ui-cef/panels/ship_display/ship_display.css`

The overlay covers the silhouette stack. Each icon is `position: absolute` with `left:` / `top:` driven from the descriptor's `x_px` / `y_px`, expressed as percentages of the SDK 640×480 reference frame. The damage TGAs are 16×16; we render them at ~14px so they sit on the silhouette without dominating it.

SDK reference frame: 128 px wide × 120 px tall is the canonical SHIELDS_DISPLAY size at 640×480 mode (the SDK hardpoint coords like `Hull.SetPosition2D(64, 40)` land at the centre of the panel — `64/128 = 50%`, `40/120 = 33%`).

- [ ] **Step 7.1: Add overlay + icon CSS, remove old damage-list rules**

In `ship_display.css`, replace the `/* ── Damage list ── */` block (`.ship-display__damage` + `.damage-row` selectors, ~lines 233-251) with:

```css
/* ── Damage icon overlay ───────────────────────────────────────────── */

/* Overlay covers the silhouette stack; per-icon left/top use the
   SDK 640x480 hardpoint pixel coords expressed as percentages of
   the canonical SHIELDS_DISPLAY pane (128 × 120 px at 640×480 mode):
   x_pct = x_px / 128 * 100, y_pct = y_px / 120 * 100. The JS does
   the conversion when setting style.left / style.top. */
.ship-display__damage-overlay {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 5; /* above cardinal shields (z=4); above silhouette (z=2) */
}

.damage-icon {
    position: absolute;
    width: 14px;
    height: 14px;
    transform: translate(-50%, -50%);  /* hardpoint coord is the centre */
    color: var(--bc-row-text-bright);  /* drives currentColor in the SVG */
    transition: color 120ms ease;
}

.damage-icon svg {
    width: 100%;
    height: 100%;
    display: block;
}

.damage-icon[data-state="healthy"]   { color: var(--bc-row-text-bright); opacity: 0.55; }
.damage-icon[data-state="damaged"]   { color: var(--bc-damage-damaged); }
.damage-icon[data-state="disabled"]  { color: var(--bc-damage-disabled); }
.damage-icon[data-state="destroyed"] { color: var(--bc-damage-destroyed); }
```

- [ ] **Step 7.2: Confirm no other rules reference the old class names**

Search for `.ship-display__damage[^-]` and `.damage-row` to make sure nothing else in the codebase depends on the removed CSS:

```bash
grep -rn "ship-display__damage[^-]\|damage-row" native/assets/ui-cef/ engine/ tests/
```

Expected: no hits outside the file we just edited. If any tests reference `damage-row` text, that's covered by the Task 5 test update.

- [ ] **Step 7.3: Commit**

```bash
git add native/assets/ui-cef/panels/ship_display/ship_display.css
git commit -m "feat(ship-display ui): damage-icon overlay positioning + state colours"
```

---

## Task 8: CEF JS — inline SVG injection

**Files:**
- Modify: `native/assets/ui-cef/panels/ship_display/ship_display.js`

Replace `rebuildDamageList` with `rebuildDamageOverlay`. For each descriptor, create a positioned `<div class="damage-icon">` with `style.left = (x_px/128 * 100) + "%"` and the SVG injected via `innerHTML`. Stable IDs are not needed — we tear down and rebuild on every update (snapshot equality already gates the repaint, so this is rare).

- [ ] **Step 8.1: Update the state-shape comment + replace the function**

In `ship_display.js`, update the docstring at the top to replace `damage:` with `damage_icons:`:

```js
//     damage_icons: [{icon_num, icon_svg, x_px, y_px, state}],
```

Replace the `rebuildDamageList` function (currently lines 59-71) with:

```js
    // SDK reference panel size at 640x480: 128 wide x 120 tall.
    // Hardpoint Position2D coords are pixel-space against this frame;
    // the overlay covers the silhouette stack at 100% / 100%, so we
    // map x_px → percent by dividing by these constants.
    var SDK_PANE_WIDTH_PX  = 128;
    var SDK_PANE_HEIGHT_PX = 120;

    function rebuildDamageOverlay(overlay, rows) {
        overlay.innerHTML = "";
        var entries = rows || [];
        for (var i = 0; i < entries.length; i++) {
            var row = entries[i];
            if (!row || !row.icon_svg) { continue; }
            var el = document.createElement("div");
            el.className = "damage-icon";
            el.dataset.state = row.state || "healthy";
            el.dataset.iconNum = String(row.icon_num);
            el.style.left = (row.x_px / SDK_PANE_WIDTH_PX  * 100).toFixed(2) + "%";
            el.style.top  = (row.y_px / SDK_PANE_HEIGHT_PX * 100).toFixed(2) + "%";
            el.innerHTML = row.icon_svg;  // potrace-traced, deterministic; safe
            overlay.appendChild(el);
        }
    }
```

- [ ] **Step 8.2: Swap the binding call in `setShipDisplay`**

Replace the existing block (currently lines 113-114):

```js
        var ul = root.querySelector('[data-bind="damage-list"]');
        if (ul) { rebuildDamageList(ul, state.damage); }
```

With:

```js
        var overlay = root.querySelector('[data-bind="damage-overlay"]');
        if (overlay) { rebuildDamageOverlay(overlay, state.damage_icons); }
```

- [ ] **Step 8.3: Rebuild + verify the JS loads without console errors**

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: clean build. (Reminder per CLAUDE.md memory: CEF aggressively caches; if behaviour after launch doesn't match expectations, hard-reload the panel with Cmd+R.)

- [ ] **Step 8.4: Commit**

```bash
git add native/assets/ui-cef/panels/ship_display/ship_display.js
git commit -m "feat(ship-display ui): inline-inject damage SVGs at hardpoint coords"
```

---

## Task 9: Verification

**Files:** none (verification only)

- [ ] **Step 9.1: Focused test suite — clean**

Run: `uv run pytest tests/unit/test_damage_icons.py tests/unit/test_icon_tracer.py tests/unit/test_subsystem_mirrors_icons.py tests/host/test_ship_display_damage_descriptors.py tests/host/test_ship_display_panel.py tests/host/test_weapons_display_panel.py -q`
Expected: all pass.

- [ ] **Step 9.2: Wider regression sweep**

Run: `uv run pytest tests/unit/ tests/host/ --ignore=tests/unit/test_energy_weapon_gating.py -q`
Expected: no NEW failures relative to main. (Compare against `git stash && uv run pytest ... && git stash pop` if anything is unexpectedly broken.)

- [ ] **Step 9.3: Visual verification**

```bash
./build/dauntless --developer
```

Load a Galaxy mission (any quick-start episode works). Engage a Galaxy-vs-Galaxy or Galaxy-vs-Sovereign skirmish. Observe:

1. **Player panel** (bottom-right): damage icons appear on the silhouette at the hardpoint-declared positions. Hull centre, sensor at the bow, shield generator centre, impulse engines aft, etc. All icons start dim (healthy state — opacity 0.55).
2. **Target panel** (top-left): same overlay on the target's silhouette. Selecting a Sovereign should show DIFFERENT damage row positions than the Galaxy (Sovereign hardpoint puts Hull at (64, 60), Galaxy at (64, 40)).
3. **Damage state colour**: take phaser hits on the target. As subsystems take damage, their icons should brighten through `--bc-damage-damaged` (yellow-green) → `--bc-damage-disabled` (grey) → `--bc-damage-destroyed` (orange-red).
4. **Per-bank weapons**: individual phaser banks should appear as discrete `Phaser` icons (icon_num=2) at their hardpoint coords, separate from the parent weapon-system icon.

Take before-and-after screenshots for the PR description.

- [ ] **Step 9.4: Final commit / branch wrap-up**

If any verification-only fixes were needed (e.g. CSS tweaks after visual review), commit them. Then offer the branch up via the receiving skill:

```bash
git log --oneline main..HEAD
```

Expected: 5–8 commits, one per logical step.

---

## Self-Review

Spec coverage:
- ✅ Hardpoint-driven damage rows replacing the hardcoded `_DAMAGE_SUBSYSTEMS` tuple (Task 4 + Task 5)
- ✅ `SubsystemProperty.Position2D` mirror onto `ShipSubsystem` (Task 4.1-4.5)
- ✅ Subsystem-class → glyph mapping via the BC `DamageIcons` enum (Task 2)
- ✅ Trace pipeline reused via shared `icon_tracer` (Task 1) + new `damage_icons` registry (Task 3)
- ✅ CEF overlay with inline SVG injection (Tasks 6-8)
- ✅ Snapshot equality + payload format (Task 5)
- ✅ Verification (Task 9)

User-clarified scope:
- ✅ Shields untouched (no shield work anywhere in the plan)
- ✅ Damage glyphs come from subsystem class, not from a property-side `SetIconNum`
- ✅ Position2D is already typed; we only add the runtime mirror + getter

Placeholder scan: no TBDs; every code step shows concrete code.

Type consistency: `damage_icons.icon_num_for_subsystem` returns `int`; `icon_svg_for_num` returns `Optional[str]`; `_iter_damage_subsystems` yields subsystems; `_damage_icon_descriptors` returns `list[dict]`. JS field names (`icon_num`, `icon_svg`, `x_px`, `y_px`, `state`) match Python emit. CSS selectors (`.ship-display__damage-overlay`, `.damage-icon`, `data-state`) match the HTML + JS.
