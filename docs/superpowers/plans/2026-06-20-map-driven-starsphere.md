# Map-Driven Starsphere Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the in-game sky as a view of the 3D sector model from the current system's vantage — one persistent galaxy, consistent everywhere — reusing the procedural shader/pass and swapping only the descriptor source.

**Architecture:** A baked `sector_model.json` (positions/sizes/colours of systems, nebulae, star-clouds) is projected from the current system's position into the existing backdrop descriptors: direction → `world_rotation`, apparent size → `span`, with near-field features enveloping the sky. The host loop picks this source when the procedural toggle is on, else falls back to stock BC. Almost entirely Python; the only C++ change is a one-line toggle *getter* binding.

**Tech Stack:** Python 3 (bake + projection), pybind11 (one getter binding), C++/GLSL renderer (reused unchanged), pytest, GoogleTest, CMake.

**Spec:** [`docs/superpowers/specs/2026-06-20-map-driven-starsphere-design.md`](../specs/2026-06-20-map-driven-starsphere-design.md)

## Global Constraints

- **Faithful fallback is sacred:** when the procedural toggle is OFF, the sky is byte-identical stock BC (authored TGAs via `aggregate_for_renderer`). The map-driven source is used ONLY when the toggle is ON.
- **Per-system, camera-anchored vantage:** vantage = the current system's position in the sector model. No ship-position parallax (that's deferred Phase 3).
- **One persistent model:** `engine/appc/sector_model.json` is the single source; positions are sector units, colours are `[r,g,b]` 0–1 floats.
- **Frame convention:** sector-model axes ARE world axes (identity); directions are correct relative to the model.
- **No shader change this phase:** the near-field "enveloping" nebula is achieved with a capped-large `span` on the existing procedural shader (span ≈ 8 → `edge=1` everywhere → fills the sphere). This is a deliberate simplification of the spec's "full-sphere branch" — same visual, zero shader risk.
- **Descriptor shape** must match the existing `set_backdrops` binding: every descriptor needs `texture_path` (use `""`), `kind` (`"star"`|`"backdrop"`), `h_tile`/`v_tile`, `h_span`/`v_span`, `world_rotation` (list[9], column-major), `target_poly_count`, plus the procedural fields `proc_kind` (`"stars"`|`"nebula"`|`"starcloud"`), `color` (list[3]), `coverage`, `seed`.
- Single build tree at `build/`; the C++ getter needs `cmake --build build` (NO shader reconfigure — no shader edit). Python tests: `uv run pytest`.

---

### Task 1: Sector-model bake tool

Transform the committed PoC map (`poc/map.json`) into the engine's `sector_model.json` schema. Offline tooling; pure transform (tested on an in-memory dict).

**Files:**
- Create: `tools/bake_sector_model.py`
- Test: `tests/tools/test_bake_sector_model.py`

**Interfaces:**
- Produces: `hex_to_rgb01("#rrggbb") -> [r,g,b]` floats 0–1.
- Produces: `build_sector_model(map_data: dict) -> dict` with keys `systems` (`[{id, position}]`), `nebulae` (`[{position, radius, color:[r,g,b]}]`), `starclouds` (`[{position, size, color:[r,g,b]}]`).

- [ ] **Step 1: Write the failing test**

```python
# tests/tools/test_bake_sector_model.py
from tools.bake_sector_model import build_sector_model, hex_to_rgb01


def test_hex_to_rgb01():
    assert hex_to_rgb01("#646392") == [0x64 / 255, 0x63 / 255, 0x92 / 255]


def test_build_sector_model_shapes():
    map_data = {
        "systems": [{"id": "vesuvi", "position": [1.0, 2.0, 3.0], "name": "Vesuvi"}],
        "nebulae": [{"position": [4.0, 5.0, 6.0], "radius": 26.0, "color": "#646392",
                     "type": "ambient", "name": "x"}],
        "galaxies": [{"position": [7.0, 8.0, 9.0], "size": 91.9,
                      "appearance": {"swatch": {"meanColor": [89, 74, 82]}}}],
    }
    out = build_sector_model(map_data)
    assert out["systems"] == [{"id": "vesuvi", "position": [1.0, 2.0, 3.0]}]
    neb = out["nebulae"][0]
    assert neb["position"] == [4.0, 5.0, 6.0] and neb["radius"] == 26.0
    assert neb["color"] == [0x64 / 255, 0x63 / 255, 0x92 / 255]
    sc = out["starclouds"][0]
    assert sc["position"] == [7.0, 8.0, 9.0] and sc["size"] == 91.9
    assert sc["color"] == [89 / 255, 74 / 255, 82 / 255]


def test_galaxy_missing_swatch_uses_default():
    out = build_sector_model({"galaxies": [{"position": [0, 0, 0], "size": 1.0, "appearance": {}}]})
    assert out["starclouds"][0]["color"] == [120 / 255, 120 / 255, 140 / 255]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_bake_sector_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.bake_sector_model'`

- [ ] **Step 3: Write the implementation**

```python
# tools/bake_sector_model.py
"""Bake poc/map.json -> engine/appc/sector_model.json (the sky's galaxy model).

Offline build step. The runtime reads the JSON; the heavy SDK inference lives
in the committed poc/map.json, which this transforms into the minimal schema the
sky projection needs.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "poc" / "map.json"
DEFAULT_OUT = ROOT / "engine" / "appc" / "sector_model.json"
_DEFAULT_GALAXY = [120, 120, 140]


def hex_to_rgb01(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def build_sector_model(map_data):
    systems = [{"id": s["id"], "position": s["position"]}
               for s in map_data.get("systems", [])]
    nebulae = [{"position": n["position"], "radius": n["radius"],
                "color": hex_to_rgb01(n["color"])}
               for n in map_data.get("nebulae", [])]
    starclouds = []
    for g in map_data.get("galaxies", []):
        mc = (g.get("appearance", {}).get("swatch", {}) or {}).get("meanColor") or _DEFAULT_GALAXY
        starclouds.append({"position": g["position"], "size": g["size"],
                           "color": [c / 255.0 for c in mc]})
    return {"systems": systems, "nebulae": nebulae, "starclouds": starclouds}


def main(in_path=DEFAULT_IN, out_path=DEFAULT_OUT):
    model = build_sector_model(json.loads(Path(in_path).read_text()))
    Path(out_path).write_text(json.dumps(model, indent=2) + "\n")
    print("[bake] %d systems, %d nebulae, %d star-clouds -> %s" % (
        len(model["systems"]), len(model["nebulae"]), len(model["starclouds"]), out_path))
    return model


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tools/test_bake_sector_model.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add tools/bake_sector_model.py tests/tools/test_bake_sector_model.py
git commit -m "feat(sky): sector-model bake tool"
```

---

### Task 2: Generate and commit the sector model

Run the bake against the committed `poc/map.json` to produce the runtime model.

**Files:**
- Create: `engine/appc/sector_model.json` (generated, committed)

- [ ] **Step 1: Run the bake**

Run: `uv run python tools/bake_sector_model.py`
Expected: prints `[bake] N systems, M nebulae, K star-clouds -> .../engine/appc/sector_model.json` (N≈34, M≈8, K≈5).

- [ ] **Step 2: Sanity-check**

Run: `uv run python -c "import json; d=json.load(open('engine/appc/sector_model.json')); print(len(d['systems']), len(d['nebulae']), len(d['starclouds'])); print('vesuvi' in [s['id'] for s in d['systems']]); print(d['nebulae'][0]['color'])"`
Expected: three counts, `True`, and a `[r,g,b]` of floats in 0–1.

- [ ] **Step 3: Commit**

```bash
git add engine/appc/sector_model.json
git commit -m "data(sky): committed sector model"
```

---

### Task 3: Vantage lookup (set → system → position)

New module `sky_projection.py`: load the model and resolve the current set's vantage position.

**Files:**
- Create: `engine/appc/sky_projection.py`
- Test: `tests/engine/appc/test_sky_projection_vantage.py`

**Interfaces:**
- Produces: `load_sector_model() -> dict` (cached read of `engine/appc/sector_model.json`).
- Produces: `system_id_for_set(set_name: str) -> str` — lowercases, maps synthetic members (`drydock`/`starbase12` → `tauceti`), strips a trailing region number (`"Vesuvi6"` → `"vesuvi"`).
- Produces: `vantage_for_set(pSet, model=None) -> list[float] | None` — the system's 3D position, or `None` if unmapped.

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/appc/test_sky_projection_vantage.py
from engine.appc import sky_projection as sp


class _Set:
    def __init__(self, name): self._n = name
    def GetName(self): return self._n


_MODEL = {"systems": [{"id": "vesuvi", "position": [1.0, 2.0, 3.0]},
                      {"id": "tauceti", "position": [9.0, 9.0, 9.0]}],
          "nebulae": [], "starclouds": []}


def test_system_id_strips_region_number():
    assert sp.system_id_for_set("Vesuvi6") == "vesuvi"
    assert sp.system_id_for_set("Biranu1") == "biranu"


def test_system_id_maps_synthetic_members():
    assert sp.system_id_for_set("Starbase12") == "tauceti"
    assert sp.system_id_for_set("DryDock") == "tauceti"


def test_vantage_resolves_position():
    assert sp.vantage_for_set(_Set("Vesuvi6"), _MODEL) == [1.0, 2.0, 3.0]
    assert sp.vantage_for_set(_Set("Starbase12"), _MODEL) == [9.0, 9.0, 9.0]


def test_vantage_unmapped_returns_none():
    assert sp.vantage_for_set(_Set("Nowhere9"), _MODEL) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/appc/test_sky_projection_vantage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.sky_projection'`

- [ ] **Step 3: Write the implementation**

```python
# engine/appc/sky_projection.py
"""Project the sector model into camera-anchored backdrop descriptors.

The in-game sky is a view of the persistent galaxy model from the current
system's position. See docs/superpowers/specs/2026-06-20-map-driven-starsphere-design.md.
"""
import json
import math
import re
import zlib
from functools import lru_cache
from pathlib import Path

_MODEL_PATH = Path(__file__).with_name("sector_model.json")

# Synthetic members folded under one star (mirrors the extractor's SYNTHETIC_SYSTEMS).
_MEMBER_TO_PARENT = {"drydock": "tauceti", "starbase12": "tauceti"}


@lru_cache(maxsize=1)
def load_sector_model():
    try:
        return json.loads(_MODEL_PATH.read_text())
    except (OSError, ValueError):
        return {"systems": [], "nebulae": [], "starclouds": []}


def system_id_for_set(set_name):
    name = set_name.lower()
    if name in _MEMBER_TO_PARENT:
        return _MEMBER_TO_PARENT[name]
    base = re.sub(r"\d+$", "", name)        # "vesuvi6" -> "vesuvi"
    return _MEMBER_TO_PARENT.get(base, base)


def vantage_for_set(pSet, model=None):
    if pSet is None:
        return None
    model = model or load_sector_model()
    sysid = system_id_for_set(pSet.GetName())
    for s in model.get("systems", []):
        if s["id"] == sysid:
            return s["position"]
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/appc/test_sky_projection_vantage.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sky_projection.py tests/engine/appc/test_sky_projection_vantage.py
git commit -m "feat(sky): sector model load + vantage lookup"
```

---

### Task 4: Projection — model + vantage → backdrop descriptors

The heart: project every feature into a descriptor (direction → `world_rotation`, apparent size → `span`, near-field envelop, distance falloff), plus the always-on base starfield.

**Files:**
- Modify: `engine/appc/sky_projection.py` (append helpers + `project_sky`)
- Test: `tests/engine/appc/test_sky_projection_project.py`

**Interfaces:**
- Consumes: `load_sector_model()` (Task 3).
- Produces: `project_sky(vantage: list[float], model: dict) -> list[dict]` — backdrop descriptors (see Global Constraints for the shape). Always includes one `proc_kind="stars"` full-sphere base; one descriptor per nebula and star-cloud. Near-field (`distance < extent`) features get `h_span/v_span = 8.0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/appc/test_sky_projection_project.py
import math
from engine.appc import sky_projection as sp


def _model():
    return {"systems": [],
            "nebulae": [
                {"position": [0.0, 0.0, 0.0], "radius": 30.0, "color": [0.9, 0.2, 0.8]},  # near-field (at vantage)
                {"position": [200.0, 0.0, 0.0], "radius": 20.0, "color": [0.3, 0.6, 0.9]},  # far, +X
            ],
            "starclouds": [{"position": [0.0, 300.0, 0.0], "size": 40.0, "color": [0.4, 0.4, 0.5]}]}


def test_includes_base_starfield():
    out = sp.project_sky([0.0, 0.0, 0.0], _model())
    stars = [d for d in out if d["proc_kind"] == "stars"]
    assert len(stars) == 1
    assert stars[0]["kind"] == "star"


def test_near_field_nebula_envelops():
    out = sp.project_sky([0.0, 0.0, 0.0], _model())
    # the nebula at the vantage (distance 0 < radius) fills the sphere
    near = [d for d in out if d["proc_kind"] == "nebula" and d["h_span"] >= 8.0]
    assert len(near) == 1


def test_far_nebula_direction_and_falloff():
    out = sp.project_sky([0.0, 0.0, 0.0], _model())
    far = [d for d in out if d["proc_kind"] == "nebula" and d["h_span"] < 8.0][0]
    # forward column (cols 3,4,5 of the column-major mat3) points +X toward [200,0,0]
    fwd = far["world_rotation"][3:6]
    assert fwd[0] > 0.99
    # dimmed by distance (colour scaled below its source 0.9 red)
    assert far["color"][2] < 0.9
    assert far["h_span"] < 8.0 and far["h_span"] > 0.0


def test_starcloud_projected():
    out = sp.project_sky([0.0, 0.0, 0.0], _model())
    sc = [d for d in out if d["proc_kind"] == "starcloud"]
    assert len(sc) == 1 and sc[0]["kind"] == "backdrop"


def test_descriptor_has_full_shape():
    out = sp.project_sky([0.0, 0.0, 0.0], _model())
    for d in out:
        for key in ("texture_path", "kind", "h_tile", "v_tile", "h_span", "v_span",
                    "world_rotation", "target_poly_count", "proc_kind", "color", "coverage", "seed"):
            assert key in d, key
        assert d["texture_path"] == "" and len(d["world_rotation"]) == 9 and len(d["color"]) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/appc/test_sky_projection_project.py -v`
Expected: FAIL — `AttributeError: module 'engine.appc.sky_projection' has no attribute 'project_sky'`

- [ ] **Step 3: Write the implementation (append to `engine/appc/sky_projection.py`)**

```python
# --- projection -----------------------------------------------------------
_SIZE_SCALE = 6.0       # span per (extent/distance) — apparent-size tuning
_MIN_SPAN = 0.08
_ENVELOP_SPAN = 8.0     # near-field: fills the sphere on the existing shader
_REF_DIST = 120.0       # distance-falloff reference
_DEFAULT_COVERAGE = 0.5
_STAR_SEED = 1.0


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _norm(a):
    m = math.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2]) or 1.0
    return (a[0]/m, a[1]/m, a[2]/m)


def _basis_from_forward(fwd):
    """Column-major mat3 [right, forward, up] (9 floats) with forward = fwd.
    Patch is radially symmetric, so the roll (right/up) is arbitrary."""
    f = _norm(fwd)
    up_hint = (0.0, 0.0, 1.0) if abs(f[2]) < 0.99 else (0.0, 1.0, 0.0)
    right = _norm(_cross(f, up_hint))
    up = _cross(right, f)
    return [right[0], right[1], right[2], f[0], f[1], f[2], up[0], up[1], up[2]]


def _seed_for(label):
    return (zlib.crc32(label.encode("utf-8")) % 100000) / 1000.0


def _base_starfield():
    return {"texture_path": "", "kind": "star", "h_tile": 1.0, "v_tile": 1.0,
            "h_span": 1.0, "v_span": 1.0,
            "world_rotation": [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0],
            "target_poly_count": 256,
            "proc_kind": "stars", "color": [0.0, 0.0, 0.0], "coverage": 0.0, "seed": _STAR_SEED}


def _project_feature(vantage, pos, extent, color, proc_kind, label):
    d = _sub(pos, vantage)
    dist = math.sqrt(d[0]*d[0] + d[1]*d[1] + d[2]*d[2])
    if dist < 1e-3:
        direction, near = (0.0, 1.0, 0.0), True
    else:
        direction, near = (d[0]/dist, d[1]/dist, d[2]/dist), dist < extent
    if near:
        span = _ENVELOP_SPAN
        coverage = min(1.0, _DEFAULT_COVERAGE * 2.0)
        col = list(color)
    else:
        span = max(_MIN_SPAN, min(_ENVELOP_SPAN, _SIZE_SCALE * extent / dist))
        falloff = max(0.15, min(1.0, _REF_DIST / dist))
        col = [c * falloff for c in color]
        coverage = _DEFAULT_COVERAGE
    return {"texture_path": "", "kind": "backdrop", "h_tile": 1.0, "v_tile": 1.0,
            "h_span": span, "v_span": span,
            "world_rotation": _basis_from_forward(direction),
            "target_poly_count": 256,
            "proc_kind": proc_kind, "color": col, "coverage": coverage,
            "seed": _seed_for(label)}


def project_sky(vantage, model):
    out = [_base_starfield()]
    for i, n in enumerate(model.get("nebulae", [])):
        out.append(_project_feature(vantage, n["position"], n["radius"], n["color"],
                                    "nebula", "neb%d" % i))
    for i, g in enumerate(model.get("starclouds", [])):
        out.append(_project_feature(vantage, g["position"], g["size"], g["color"],
                                    "starcloud", "sc%d" % i))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/appc/test_sky_projection_project.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sky_projection.py tests/engine/appc/test_sky_projection_project.py
git commit -m "feat(sky): project sector model into backdrop descriptors"
```

---

### Task 5: Toggle getter binding + renderer wrapper

The host loop must read the procedural toggle to choose the descriptor source. Add a getter mirroring the existing setter.

**Files:**
- Modify: `native/src/host/host_bindings.cc` (add `procedural_sky_enabled` binding by `procedural_sky_set_enabled`)
- Modify: `engine/renderer.py` (add a `procedural_sky_enabled()` wrapper)

**Interfaces:**
- Produces (Python): `engine.renderer.procedural_sky_enabled() -> bool`.

- [ ] **Step 1: Add the binding**

In `native/src/host/host_bindings.cc`, immediately after the `m.def("procedural_sky_set_enabled", ...)` block, add:

```cpp
    m.def("procedural_sky_enabled",
          []() { return dauntless_procedural_sky::enabled(); },
          "Read the procedural-sky toggle (Modern VFX). Default: on.");
```

- [ ] **Step 2: Build and verify the symbol exists**

Run: `cmake --build build -j 2>&1 | tail -2 && ls build/python/_open_stbc_host*.so`
Expected: clean build; the `.so` exists. (No shader reconfigure — no shader edit.)

Run: `uv run python -c "import sys; sys.path.insert(0,'build/python'); import _open_stbc_host as h; print(callable(h.procedural_sky_enabled), h.procedural_sky_enabled())"`
Expected: `True True` (callable; defaults on).

- [ ] **Step 3: Add the renderer wrapper**

In `engine/renderer.py`, near the existing `set_backdrops` wrapper, add:

```python
def procedural_sky_enabled() -> bool:
    """True when the procedural sky (Modern VFX) is on; False = stock BC."""
    return _h.procedural_sky_enabled()
```

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(sky): expose procedural-sky toggle getter to Python"
```

---

### Task 6: Host-loop wiring — choose source by toggle

When procedural is on and the system is mapped, feed map-driven descriptors; otherwise fall back to the authored backdrops (never blank the sky).

**Files:**
- Modify: `engine/host_loop.py` (`_aggregate_backdrops`, ~line 1887)
- Test: `tests/engine/test_host_loop_backdrops.py`

**Interfaces:**
- Consumes: `engine.renderer.procedural_sky_enabled()` (Task 5); `engine.appc.sky_projection.vantage_for_set` + `project_sky` (Tasks 3–4); `engine.appc.backdrops.aggregate_for_renderer` (existing).

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_host_loop_backdrops.py
import types
import engine.host_loop as hl


class _Set:
    def GetName(self): return "Vesuvi6"


def test_map_driven_when_toggle_on(monkeypatch):
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: True))
    monkeypatch.setattr(hl, "_authored_backdrops", lambda pSet: [{"src": "authored"}])
    import engine.appc.sky_projection as sp
    monkeypatch.setattr(sp, "vantage_for_set", lambda pSet, model=None: [0.0, 0.0, 0.0])
    monkeypatch.setattr(sp, "project_sky", lambda v, m=None: [{"src": "map"}])
    out = hl._aggregate_backdrops(_Set())
    assert out == [{"src": "map"}]


def test_falls_back_to_authored_when_unmapped(monkeypatch):
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: True))
    monkeypatch.setattr(hl, "_authored_backdrops", lambda pSet: [{"src": "authored"}])
    import engine.appc.sky_projection as sp
    monkeypatch.setattr(sp, "vantage_for_set", lambda pSet, model=None: None)  # unmapped
    out = hl._aggregate_backdrops(_Set())
    assert out == [{"src": "authored"}]


def test_stock_when_toggle_off(monkeypatch):
    monkeypatch.setattr(hl, "r", types.SimpleNamespace(procedural_sky_enabled=lambda: False))
    monkeypatch.setattr(hl, "_authored_backdrops", lambda pSet: [{"src": "authored"}])
    out = hl._aggregate_backdrops(_Set())
    assert out == [{"src": "authored"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_host_loop_backdrops.py -v`
Expected: FAIL — `AttributeError: module 'engine.host_loop' has no attribute '_authored_backdrops'`

- [ ] **Step 3: Rewrite `_aggregate_backdrops`**

Replace the existing `_aggregate_backdrops` function in `engine/host_loop.py` with:

```python
def _authored_backdrops(pSet):
    """Stock-BC backdrops: this set's authored BackdropSphere objects."""
    from engine.appc.backdrops import aggregate_for_renderer
    return aggregate_for_renderer(pSet, PROJECT_ROOT)


def _aggregate_backdrops(pSet):
    """Backdrop descriptors for the active set.

    Procedural toggle ON  -> map-driven sky (the sector model projected from
    this system's vantage), falling back to authored backdrops if the system
    is unmapped. Toggle OFF -> stock BC (authored backdrops).
    """
    if r.procedural_sky_enabled():
        from engine.appc import sky_projection as sp
        vantage = sp.vantage_for_set(pSet)
        if vantage is not None:
            return sp.project_sky(vantage, sp.load_sector_model())
    return _authored_backdrops(pSet)
```

Note: `r` is the `engine.renderer` module already imported in `host_loop.py` (used as `r.set_backdrops`). Confirm that alias exists at the top of the file; if it is imported under a different name, use that name.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_host_loop_backdrops.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/engine/test_host_loop_backdrops.py
git commit -m "feat(sky): host loop selects map-driven vs stock backdrops by toggle"
```

---

### Task 7: End-to-end verification + cleanup note

Confirm the projection produces renderable descriptors against the real committed model, and record the live-verify gate.

**Files:**
- Test: `tests/engine/appc/test_sky_projection_realmodel.py`
- Modify: `docs/sector-cartography.md` (one-line note)

- [ ] **Step 1: Write an integration test against the committed model**

```python
# tests/engine/appc/test_sky_projection_realmodel.py
from engine.appc import sky_projection as sp


def test_real_model_projects_from_vesuvi():
    model = sp.load_sector_model()
    assert model["systems"], "sector_model.json must be committed (Task 2)"
    vesuvi = next(s for s in model["systems"] if s["id"] == "vesuvi")
    out = sp.project_sky(vesuvi["position"], model)
    # base starfield + every nebula + every star-cloud
    assert len(out) == 1 + len(model["nebulae"]) + len(model["starclouds"])
    # at least one feature is near/large from vesuvi (its own nebula)
    assert any(d["proc_kind"] == "nebula" and d["h_span"] >= 8.0 for d in out)
    # every descriptor is well-formed
    for d in out:
        assert d["texture_path"] == "" and len(d["world_rotation"]) == 9
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/engine/appc/test_sky_projection_realmodel.py -v`
Expected: PASS.

- [ ] **Step 3: Run the full sky/backdrop Python suite (no regressions)**

Run: `uv run pytest tests/ -k "backdrop or sky or sector" -q`
Expected: PASS (new + existing).

- [ ] **Step 4: Live A/B verification (manual, human gate)**

Run `./build/dauntless`, load a mission (e.g. E1M2 / Vesuvi 6), and verify with the user observing (no synthetic input on the live workstation):
- Procedural on (default): the sky is the galaxy from Vesuvi — Vesuvi's own nebula envelops/looms; other features sit in their directions; base starfield behind.
- `procedural_sky_set_enabled(False)`: reverts to stock BC authored backdrops, unchanged.
Record the outcome; do not claim success without the user's confirmation.

- [ ] **Step 5: Note it in the findings doc + record the cleanup**

Append under `docs/sector-cartography.md` §7: "Map-driven starsphere shipped — the sky is the sector model projected from the current system's vantage (procedural toggle on); stock BC on toggle off. The procedural fields on `aggregate_for_renderer` (proc_kind/color/coverage/seed) are now used only on the unmapped-system fallback path."

- [ ] **Step 6: Commit**

```bash
git add tests/engine/appc/test_sky_projection_realmodel.py docs/sector-cartography.md
git commit -m "test(sky): map-driven projection against committed model + notes"
```

---

## Self-Review

**Spec coverage:**
- Sector-model bake → Task 1–2. ✓
- Vantage lookup (per-system, synthetic-aware, unmapped→fallback) → Task 3 + Task 6. ✓
- Projection (direction/world_rotation, apparent size, distance falloff, near-field envelop, base starfield, colours/proc_kind) → Task 4. ✓
- Two modes / toggle / faithful fallback → Task 5 (getter) + Task 6 (selection). ✓
- Persistence (one model from every vantage) → Task 2 model + Task 6 wiring. ✓
- Reuse procedural shader/pass/descriptor contract → Tasks 4/6 emit the existing descriptor shape; no shader/pass change. ✓
- Testing (deterministic + integration) → Tasks 1,3,4,6,7; visual via the existing shader tests + the live A/B (Task 7). ✓
- Edge cases (unmapped→fallback, nothing-nearby→base only, toggle-off parity) → Tasks 6,7. ✓
- Cleanup note (vestigial `aggregate_for_renderer` fields) → Task 7. ✓

**Deviation from spec (intentional, in Global Constraints):** the near-field enveloping nebula uses a capped-large `span` on the *existing* procedural patch shader (`span = 8` → no angular discard → fills the sphere) instead of a dedicated full-sphere shader branch. Same visual; this phase touches **no shader and no pass code** (only one C++ getter binding). If the user prefers a true full-sphere branch later, it's an additive shader change behind the same descriptor.

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `system_id_for_set(str)->str`, `vantage_for_set(pSet, model=None)->list|None`, `project_sky(vantage, model)->list[dict]`, `procedural_sky_enabled()->bool` are used identically across tasks. Descriptor keys match the `set_backdrops` binding (Global Constraints) and the projection (Task 4). `_MEMBER_TO_PARENT` mapping matches the extractor's synthetic systems.
