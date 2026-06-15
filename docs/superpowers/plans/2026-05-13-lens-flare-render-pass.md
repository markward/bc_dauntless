# Lens-flare render pass — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement BC's lens-flare visual effect: textured polygonal disks strung along the screen-space line from the system sun to the opposite point, with depth-buffer occlusion so they disappear behind ships and planets. Eliminates the rank-1 stub-profile entry (`LensFlare_Create().AddFlare`, 873 calls / 30 missions).

**Architecture:** Real `LensFlare` Python class registers on `SetClass._lens_flares`. Per-frame aggregator pushes a descriptor list to C++ via a new `set_lens_flares()` binding. A new `LensFlarePass` projects each flare's source to NDC, sub-samples the depth buffer for visibility, then renders each N-gon element with additive blending using a per-wedge UV-tiled mesh and the SDK-supplied texture. Runs after the dust pass, before the bridge pass.

**Tech Stack:** Python 3 (engine), CPython embedded via pybind11, OpenGL 3.3 core / GLSL 330, GoogleTest (C++ tests), pytest (Python tests), CMake.

**Spec:** [docs/superpowers/specs/2026-05-12-lens-flare-render-pass-design.md](../specs/2026-05-12-lens-flare-render-pass-design.md)

---

## File map

Create:

- `engine/appc/lens_flare.py` — `LensFlare` class, `LensFlare_Create` factory, `aggregate_lens_flares_for_renderer`
- `tests/unit/test_lens_flare.py` — `LensFlare` + aggregator tests
- `tests/unit/test_lens_flare_stub_regression.py` — stub-profile regression
- `native/src/renderer/include/renderer/lens_flare_pass.h` — pass class header + descriptor structs
- `native/src/renderer/lens_flare_pass.cc` — pass implementation + pure `build_ngon_mesh` helper
- `native/src/renderer/shaders/lens_flare.vert`
- `native/src/renderer/shaders/lens_flare.frag`
- `native/tests/renderer/lens_flare_pass_test.cc` — pure-function tests for `build_ngon_mesh`

Modify:

- `engine/appc/sets.py:38-44` — add `_lens_flares` attribute next to `_lights` / `_backdrops`
- `App.py:72-75` — import `LensFlare_Create` from `engine.appc.lens_flare`
- `engine/renderer.py` — add typed `set_lens_flares(...)` wrapper
- `engine/host_loop.py:648-666` — add `_aggregate_lens_flares()` helper
- `engine/host_loop.py:1302-1306` — push aggregated flares per frame
- `native/src/renderer/include/renderer/pipeline.h` — add `lens_flare_shader()`
- `native/src/renderer/pipeline.cc` — load lens_flare shader
- `native/src/renderer/CMakeLists.txt` — embed shaders, add source file
- `native/src/host/host_bindings.cc` — add `g_lens_flare_pass` global, `set_lens_flares` binding, invoke in `frame()`
- `native/tests/renderer/CMakeLists.txt` — register the new test

---

## Task 1: Add `_lens_flares` to SetClass

**Files:**
- Modify: `engine/appc/sets.py:38-44`
- Test: `tests/unit/test_lens_flare.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_lens_flare.py`:

```python
"""Tests for engine.appc.lens_flare."""
from engine.appc.sets import SetClass


def test_setclass_initializes_empty_lens_flares_list():
    pSet = SetClass()
    assert pSet._lens_flares == []
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_lens_flare.py -v
```

Expected: FAIL with `AttributeError: 'SetClass' object has no attribute '_lens_flares'`.

- [ ] **Step 3: Add the attribute**

Edit `engine/appc/sets.py` — after the `_backdrops` initialization at line 44:

```python
        # Backdrops — populated by pSet.AddBackdropToSet(). Ordered list
        # (insertion order = draw order); names aren't indexed because BC
        # scripts only ever pass them positionally to AddBackdropToSet,
        # never look them up later.
        self._backdrops: 'list["Backdrop"]' = []
        # Lens flares — populated by App.LensFlare_Create(pSet). Stored in
        # insertion order; the renderer aggregator walks this list.
        self._lens_flares: 'list["LensFlare"]' = []
```

- [ ] **Step 4: Run test to verify it passes**

```
uv run pytest tests/unit/test_lens_flare.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sets.py tests/unit/test_lens_flare.py
git commit -m "feat(sets): add _lens_flares list to SetClass for lens-flare registration"
```

---

## Task 2: `LensFlare` class + `LensFlare_Create` factory

**Files:**
- Create: `engine/appc/lens_flare.py`
- Test: `tests/unit/test_lens_flare.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_lens_flare.py`:

```python
from engine.appc.lens_flare import LensFlare, LensFlare_Create


def test_lens_flare_create_registers_on_set():
    pSet = SetClass()
    flare = LensFlare_Create(pSet)
    assert isinstance(flare, LensFlare)
    assert pSet._lens_flares == [flare]


def test_set_source_records_object_and_direction_mode():
    flare = LensFlare(pSet=None)
    sentinel = object()
    flare.SetSource(sentinel, 6)
    assert flare._source is sentinel
    assert flare._direction_mode == 6


def test_add_flare_accumulates_elements_with_defaults():
    flare = LensFlare(pSet=None)
    flare.AddFlare(8, "data/textures/rays.tga", 0.0, 0.3, 0.5, 0.1)
    flare.AddFlare(30, "data/textures/whiteloop.tga", 0.0, 0.075)
    assert flare._elements == [
        {"wedges": 8, "texture": "data/textures/rays.tga",
         "position": 0.0, "size": 0.3, "freq": 0.5, "amp": 0.1},
        {"wedges": 30, "texture": "data/textures/whiteloop.tga",
         "position": 0.0, "size": 0.075, "freq": 0.0, "amp": 0.0},
    ]


def test_build_marks_flare_as_built():
    flare = LensFlare(pSet=None)
    assert flare._built is False
    flare.Build()
    assert flare._built is True


def test_lens_flare_create_returns_early_when_pset_lacks_attr():
    """Defensive: a SetClass that somehow predates this feature (or a None
    pSet from a malformed mission script) shouldn't crash."""
    flare = LensFlare_Create(None)
    assert isinstance(flare, LensFlare)
    assert flare._set is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_lens_flare.py -v
```

Expected: 5 failures with `ImportError: cannot import name 'LensFlare'` (or similar).

- [ ] **Step 3: Implement the class**

Create `engine/appc/lens_flare.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_lens_flare.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/lens_flare.py tests/unit/test_lens_flare.py
git commit -m "feat(lens_flare): real LensFlare class + LensFlare_Create factory"
```

---

## Task 3: `aggregate_lens_flares_for_renderer`

**Files:**
- Modify: `engine/appc/lens_flare.py`
- Test: `tests/unit/test_lens_flare.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_lens_flare.py`:

```python
from pathlib import Path
from engine.appc.lens_flare import aggregate_lens_flares_for_renderer
from engine.appc.planet import Sun


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _make_set_with_built_flare(elements):
    pSet = SetClass()
    sun = Sun(radius=4000.0, model_path="data/Textures/SunBase.tga")
    sun.SetWorldLocation((10.0, 20.0, 30.0))
    pSet.AddObjectToSet(sun, "Sun")
    flare = LensFlare_Create(pSet)
    flare.SetSource(sun, 6)
    for e in elements:
        flare.AddFlare(**e)
    flare.Build()
    return pSet, sun, flare


def test_aggregator_returns_descriptor_for_built_flare():
    pSet, sun, _ = _make_set_with_built_flare([
        {"wedges": 8, "texture": "data/textures/rays.tga",
         "position": 0.0, "size": 0.3},
        {"wedges": 30, "texture": "data/textures/whiteloop.tga",
         "position": 1.4, "size": 0.075},
    ])

    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])

    assert len(out) == 1
    d = out[0]
    assert d["source_world_pos"] == (10.0, 20.0, 30.0)
    assert d["source_radius"] == 4000.0
    assert len(d["elements"]) == 2
    e0 = d["elements"][0]
    assert e0["wedges"] == 8
    assert e0["texture_path"].endswith("rays.tga")
    assert Path(e0["texture_path"]).is_absolute()
    assert e0["position"] == 0.0
    assert e0["size"] == 0.3
    assert e0["freq"] == 0.0
    assert e0["amp"] == 0.0


def test_aggregator_skips_unbuilt_flares():
    pSet = SetClass()
    sun = Sun(radius=4000.0)
    sun.SetWorldLocation((0.0, 0.0, 0.0))
    pSet.AddObjectToSet(sun, "Sun")
    flare = LensFlare_Create(pSet)
    flare.SetSource(sun, 6)
    flare.AddFlare(8, "data/textures/rays.tga", 0.0, 0.3)
    # No Build() call.
    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])
    assert out == []


def test_aggregator_skips_flares_with_no_source():
    pSet = SetClass()
    flare = LensFlare_Create(pSet)
    flare.AddFlare(8, "data/textures/rays.tga", 0.0, 0.3)
    flare.Build()
    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])
    assert out == []


def test_aggregator_skips_flares_with_no_elements():
    pSet, sun, flare = _make_set_with_built_flare([])
    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])
    assert out == []


def test_aggregator_drops_elements_whose_textures_do_not_resolve():
    pSet, sun, _ = _make_set_with_built_flare([
        {"wedges": 8, "texture": "data/textures/rays.tga",
         "position": 0.0, "size": 0.3},
        {"wedges": 6, "texture": "data/textures/nope_does_not_exist.tga",
         "position": 0.5, "size": 0.1},
    ])
    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])
    assert len(out) == 1
    assert len(out[0]["elements"]) == 1
    assert out[0]["elements"][0]["texture_path"].endswith("rays.tga")


def test_aggregator_clamps_wedges_to_valid_range():
    pSet, sun, _ = _make_set_with_built_flare([
        {"wedges": 2,  "texture": "data/textures/rays.tga", "position": 0.0, "size": 0.3},
        {"wedges": 99, "texture": "data/textures/rays.tga", "position": 0.0, "size": 0.3},
    ])
    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])
    assert out[0]["elements"][0]["wedges"] == 3   # min clamp
    assert out[0]["elements"][1]["wedges"] == 64  # max clamp
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/unit/test_lens_flare.py -v
```

Expected: 6 new failures (`ImportError: cannot import name 'aggregate_lens_flares_for_renderer'`).

- [ ] **Step 3: Implement the aggregator**

Append to `engine/appc/lens_flare.py`:

```python
def aggregate_lens_flares_for_renderer(project_root, pSets) -> list:
    """Return list[dict] for all built LensFlares across pSets.

    Resolves texture paths against ``project_root / "game"``. Drops:
      - flares whose Build() was never called
      - flares whose source object is missing or has no GetWorldLocation
      - flares with zero elements after texture-resolution filtering
    Within a flare, drops elements whose texture path does not resolve.
    Wedge counts are clamped to [3, 64]; very low or very high N produce
    degenerate or excessive meshes upstream.
    """
    game_root = project_root / "game"
    out = []
    for pSet in pSets:
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
                "source_world_pos": (loc.x, loc.y, loc.z),
                "source_radius":    radius,
                "elements":         elements_out,
            })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/unit/test_lens_flare.py -v
```

Expected: all 12 pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/lens_flare.py tests/unit/test_lens_flare.py
git commit -m "feat(lens_flare): aggregate built flares + resolve textures for the renderer"
```

---

## Task 4: Wire `LensFlare_Create` into `App` module

**Files:**
- Modify: `App.py:72-75`
- Test: `tests/unit/test_lens_flare.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_lens_flare.py`:

```python
def test_app_lens_flare_create_is_real_function():
    """App.LensFlare_Create must be the real factory, not a _NamedStub."""
    import App
    from engine.appc.lens_flare import LensFlare_Create as expected
    assert App.LensFlare_Create is expected
    # And the returned object must not be a _NamedStub.
    pSet = SetClass()
    flare = App.LensFlare_Create(pSet)
    assert not isinstance(flare, App._NamedStub)
    assert isinstance(flare, LensFlare)
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/unit/test_lens_flare.py::test_app_lens_flare_create_is_real_function -v
```

Expected: FAIL — `App.LensFlare_Create` resolves to a `_NamedStub`.

- [ ] **Step 3: Add the import to App.py**

Edit `App.py` at line 72 (the `from engine.appc.planet import (...)` block). Add a new import block right after it:

```python
from engine.appc.planet import (
    Planet, Sun, ProximityManager,
    Planet_Create, Sun_Create, Planet_GetObject, Planet_Cast,
)
from engine.appc.lens_flare import LensFlare, LensFlare_Create
```

- [ ] **Step 4: Run test to verify it passes**

```
uv run pytest tests/unit/test_lens_flare.py::test_app_lens_flare_create_is_real_function -v
```

Expected: PASS.

- [ ] **Step 5: Run the broader test suite to confirm no regressions**

```
uv run pytest tests/unit/ -q -x
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add App.py tests/unit/test_lens_flare.py
git commit -m "feat(app): replace LensFlare_Create stub with real factory"
```

---

## Task 5: Stub-profile regression test

**Files:**
- Create: `tests/unit/test_lens_flare_stub_regression.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/test_lens_flare_stub_regression.py`:

```python
"""After Task 4, no LensFlare row may appear in the stub-call profile.

This exercises the same MakeLensFlare path that the gameloop harness
records — calling it directly avoids needing a full mission init."""
import App
from engine.appc.sets import SetClass
from engine.appc.planet import Sun


def test_make_lens_flare_records_no_stubs():
    App._stub_tracker.clear()
    App._stub_tracker.set_mission("regression")

    pSet = SetClass()
    pSun = Sun(radius=4040.0, model_path="data/Textures/SunBase.tga")
    pSun.SetWorldLocation((0.0, 0.0, 0.0))
    pSet.AddObjectToSet(pSun, "Sun")

    # Inlined MakeLensFlare equivalent — call the App-level surface so any
    # remaining _NamedStub fall-through is caught.
    pLensFlare = App.LensFlare_Create(pSet)
    pLensFlare.SetSource(pSun, 6)
    pLensFlare.AddFlare(8,  "data/textures/rays.tga",       0.0,  0.2, 0.5, 0.1)
    pLensFlare.AddFlare(30, "data/textures/whiteloop.tga",  0.0,  0.075)
    pLensFlare.AddFlare(30, "data/textures/whiteloop.tga", -0.5,  0.015)
    pLensFlare.AddFlare(30, "data/textures/white2.tga",     0.45, 0.005)
    pLensFlare.AddFlare(30, "data/textures/whitelines.tga", 0.55, 0.015)
    pLensFlare.AddFlare(6,  "data/textures/rays.tga",       0.8,  0.001)
    pLensFlare.AddFlare(30, "data/textures/white2.tga",     0.95, 0.038)
    pLensFlare.AddFlare(30, "data/textures/whiteloop.tga",  1.4,  0.03)
    pLensFlare.AddFlare(30, "data/textures/rainbowloop.tga", 1.6, 0.105)
    pLensFlare.Build()

    App._stub_tracker.reset_mission()
    leaked = {
        name for (name, _, _) in App._stub_tracker.report()
        if name.startswith("LensFlare")
    }
    assert leaked == set(), (
        "Lens-flare SDK calls still hit _NamedStub: " + repr(leaked))
```

- [ ] **Step 2: Run test to verify it passes**

```
uv run pytest tests/unit/test_lens_flare_stub_regression.py -v
```

Expected: PASS — no `LensFlare*` rows in the report.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_lens_flare_stub_regression.py
git commit -m "test(lens_flare): regression — no LensFlare rows in stub profile"
```

---

## Task 6: Renderer descriptor structs

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h:45-50` (insert after `SunDescriptor`)

- [ ] **Step 1: Add the structs**

Edit `native/src/renderer/include/renderer/frame.h` — after the `SunDescriptor` definition (around line 50), insert:

```cpp
struct LensFlareElement {
    int         wedges       = 8;
    std::string texture_path;
    float       position     = 0.0f;   // 0=at source, 1=screen center, 2=opposite
    float       size         = 0.1f;   // fraction of viewport height
    float       freq         = 0.0f;   // Hz wobble
    float       amp          = 0.0f;   // wobble amplitude (size multiplier delta)
};

struct LensFlareDescriptor {
    glm::vec3                       source_world_pos;
    float                           source_radius = 0.0f;
    std::vector<LensFlareElement>   elements;
};
```

- [ ] **Step 2: Confirm the build still configures**

```
cmake -B build -S . && cmake --build build --target renderer -j
```

Expected: builds clean (the structs are unused until later tasks).

- [ ] **Step 3: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h
git commit -m "renderer: add LensFlareDescriptor / LensFlareElement structs"
```

---

## Task 7: N-gon mesh builder (pure function) + tests

**Files:**
- Create: `native/src/renderer/include/renderer/lens_flare_pass.h`
- Create: `native/src/renderer/lens_flare_pass.cc`
- Create: `native/tests/renderer/lens_flare_pass_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add source file)
- Modify: `native/tests/renderer/CMakeLists.txt` (add test file)

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/lens_flare_pass_test.cc`:

```cpp
// native/tests/renderer/lens_flare_pass_test.cc
#include <gtest/gtest.h>

#include <renderer/lens_flare_pass.h>

#include <cmath>

using renderer::build_ngon_mesh;
using renderer::NgonVertex;

TEST(LensFlareMesh, EightWedgesHas24Vertices) {
    auto mesh = build_ngon_mesh(8);
    EXPECT_EQ(mesh.vertices.size(), 24u);   // 3 verts per wedge, 8 wedges
    EXPECT_EQ(mesh.indices.size(), 24u);    // 3 indices per wedge, 8 wedges
}

TEST(LensFlareMesh, CenterVertexUvIsTopMiddle) {
    auto mesh = build_ngon_mesh(8);
    // The first vertex of every wedge is its center vertex (uv = 0.5, 1.0).
    for (std::size_t k = 0; k < 8; ++k) {
        const auto& v = mesh.vertices[k * 3 + 0];
        EXPECT_FLOAT_EQ(v.pos[0], 0.0f);
        EXPECT_FLOAT_EQ(v.pos[1], 0.0f);
        EXPECT_FLOAT_EQ(v.uv[0],  0.5f);
        EXPECT_FLOAT_EQ(v.uv[1],  1.0f);
    }
}

TEST(LensFlareMesh, OuterVertexUvsAreCornerBottoms) {
    auto mesh = build_ngon_mesh(8);
    for (std::size_t k = 0; k < 8; ++k) {
        const auto& left  = mesh.vertices[k * 3 + 1];
        const auto& right = mesh.vertices[k * 3 + 2];
        EXPECT_FLOAT_EQ(left.uv[0],  0.0f);
        EXPECT_FLOAT_EQ(left.uv[1],  0.0f);
        EXPECT_FLOAT_EQ(right.uv[0], 1.0f);
        EXPECT_FLOAT_EQ(right.uv[1], 0.0f);
    }
}

TEST(LensFlareMesh, OuterVerticesAreOnUnitCircle) {
    auto mesh = build_ngon_mesh(30);
    for (std::size_t k = 0; k < 30; ++k) {
        const auto& left  = mesh.vertices[k * 3 + 1];
        const auto& right = mesh.vertices[k * 3 + 2];
        const float lr = std::sqrt(left.pos[0]  * left.pos[0]  + left.pos[1]  * left.pos[1]);
        const float rr = std::sqrt(right.pos[0] * right.pos[0] + right.pos[1] * right.pos[1]);
        EXPECT_NEAR(lr, 1.0f, 1e-5f);
        EXPECT_NEAR(rr, 1.0f, 1e-5f);
    }
}

TEST(LensFlareMesh, IndicesAreSequential) {
    auto mesh = build_ngon_mesh(6);
    for (std::size_t i = 0; i < mesh.indices.size(); ++i) {
        EXPECT_EQ(mesh.indices[i], static_cast<unsigned int>(i));
    }
}
```

- [ ] **Step 2: Write the header**

Create `native/src/renderer/include/renderer/lens_flare_pass.h`:

```cpp
// native/src/renderer/include/renderer/lens_flare_pass.h
#pragma once

#include <renderer/frame.h>
#include <assets/texture.h>

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

// One vertex of the per-wedge mesh: 2D position in unit-disk-local space,
// UV in [0,1]. Kept POD-like so std::vector<NgonVertex> uploads directly.
struct NgonVertex {
    float pos[2];
    float uv[2];
};

struct NgonMeshData {
    std::vector<NgonVertex>     vertices;
    std::vector<unsigned int>   indices;
};

// Pure function: build CPU-side mesh data for an N-gon disk where each
// wedge has its own (0,0)→(1,0) bottom UV and (0.5, 1.0) center UV. No GL
// state touched, so this is unit-testable without a context.
NgonMeshData build_ngon_mesh(int wedges);

class LensFlarePass {
public:
    LensFlarePass() = default;
    ~LensFlarePass();
    LensFlarePass(const LensFlarePass&)            = delete;
    LensFlarePass& operator=(const LensFlarePass&) = delete;

    void render(const std::vector<LensFlareDescriptor>& flares,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                int viewport_w, int viewport_h,
                double now_seconds);

private:
    struct WedgeMesh {
        unsigned int vao = 0;
        unsigned int vbo = 0;
        unsigned int ebo = 0;
        int          index_count = 0;
    };

    std::unordered_map<int, WedgeMesh>                                 wedge_meshes_;
    std::unordered_map<std::string, std::unique_ptr<assets::Texture>>  texture_cache_;

    WedgeMesh&       ensure_wedge_mesh(int n);
    assets::Texture* ensure_texture(const std::string& path);
};

}  // namespace renderer
```

- [ ] **Step 3: Write the implementation stub**

Create `native/src/renderer/lens_flare_pass.cc`:

```cpp
// native/src/renderer/lens_flare_pass.cc
#include "renderer/lens_flare_pass.h"

#include "renderer/pipeline.h"

#include <assets/image.h>
#include <assets/tga.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cmath>
#include <cstdio>
#include <fstream>

namespace renderer {

NgonMeshData build_ngon_mesh(int wedges) {
    if (wedges < 3)  wedges = 3;
    if (wedges > 64) wedges = 64;

    NgonMeshData m;
    m.vertices.reserve(static_cast<std::size_t>(wedges) * 3);
    m.indices.reserve(static_cast<std::size_t>(wedges) * 3);

    const float kTwoPi = 6.28318530717958647692f;
    for (int k = 0; k < wedges; ++k) {
        const float a0 = (kTwoPi * static_cast<float>(k))       / static_cast<float>(wedges);
        const float a1 = (kTwoPi * static_cast<float>(k + 1))   / static_cast<float>(wedges);
        const NgonVertex center {{0.0f, 0.0f}, {0.5f, 1.0f}};
        const NgonVertex left   {{std::cos(a0), std::sin(a0)}, {0.0f, 0.0f}};
        const NgonVertex right  {{std::cos(a1), std::sin(a1)}, {1.0f, 0.0f}};
        const unsigned int base = static_cast<unsigned int>(m.vertices.size());
        m.vertices.push_back(center);
        m.vertices.push_back(left);
        m.vertices.push_back(right);
        m.indices.push_back(base + 0);
        m.indices.push_back(base + 1);
        m.indices.push_back(base + 2);
    }
    return m;
}

LensFlarePass::~LensFlarePass() {
    for (auto& [n, mesh] : wedge_meshes_) {
        if (mesh.ebo) glDeleteBuffers(1, &mesh.ebo);
        if (mesh.vbo) glDeleteBuffers(1, &mesh.vbo);
        if (mesh.vao) glDeleteVertexArrays(1, &mesh.vao);
    }
}

void LensFlarePass::render(const std::vector<LensFlareDescriptor>&,
                           const scenegraph::Camera&,
                           Pipeline&,
                           int, int, double) {
    // Implemented in Task 11.
}

LensFlarePass::WedgeMesh& LensFlarePass::ensure_wedge_mesh(int n) {
    auto it = wedge_meshes_.find(n);
    if (it != wedge_meshes_.end()) return it->second;
    NgonMeshData data = build_ngon_mesh(n);
    WedgeMesh m;
    glGenVertexArrays(1, &m.vao);
    glBindVertexArray(m.vao);
    glGenBuffers(1, &m.vbo);
    glBindBuffer(GL_ARRAY_BUFFER, m.vbo);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(data.vertices.size() * sizeof(NgonVertex)),
                 data.vertices.data(), GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(NgonVertex),
                          reinterpret_cast<void*>(offsetof(NgonVertex, pos)));
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(NgonVertex),
                          reinterpret_cast<void*>(offsetof(NgonVertex, uv)));
    glEnableVertexAttribArray(1);
    glGenBuffers(1, &m.ebo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, m.ebo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(data.indices.size() * sizeof(unsigned int)),
                 data.indices.data(), GL_STATIC_DRAW);
    glBindVertexArray(0);
    m.index_count = static_cast<int>(data.indices.size());
    auto [ins_it, _] = wedge_meshes_.emplace(n, m);
    return ins_it->second;
}

assets::Texture* LensFlarePass::ensure_texture(const std::string& path) {
    auto it = texture_cache_.find(path);
    if (it != texture_cache_.end()) {
        return (it->second && it->second->id() != 0) ? it->second.get() : nullptr;
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[lens_flare] failed to open '%s'\n", path.c_str());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
    in.seekg(0, std::ios::end);
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(size));
    try {
        assets::Image img = assets::decode_tga(bytes);
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        auto owned = std::make_unique<assets::Texture>(std::move(tex));
        auto* raw = owned.get();
        texture_cache_.emplace(path, std::move(owned));
        return raw;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[lens_flare] failed to decode '%s': %s\n",
                     path.c_str(), e.what());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
}

}  // namespace renderer
```

- [ ] **Step 4: Register the source file**

Edit `native/src/renderer/CMakeLists.txt` — append `lens_flare_pass.cc` to the `add_library(renderer STATIC ...)` list (after `shield_pass.cc`):

```cmake
add_library(renderer STATIC
    window.cc
    shader.cc
    pipeline.cc
    frame.cc
    sphere_mesh.cc
    backdrop_pass.cc
    sun_pass.cc
    dust_pass.cc
    aabb.cc
    shield_state.cc
    skin_shield.cc
    shield_pass.cc
    lens_flare_pass.cc
)
```

- [ ] **Step 5: Register the test file**

Edit `native/tests/renderer/CMakeLists.txt` — add `lens_flare_pass_test.cc` to the `add_executable(renderer_tests ...)` list.

- [ ] **Step 6: Configure and build the tests**

```
cmake -B build -S . && cmake --build build --target renderer_tests -j
```

Expected: builds clean.

- [ ] **Step 7: Run the new tests**

```
./build/native/tests/renderer/renderer_tests --gtest_filter='LensFlareMesh.*'
```

Expected: 5 tests pass.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/lens_flare_pass.h \
        native/src/renderer/lens_flare_pass.cc \
        native/tests/renderer/lens_flare_pass_test.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(lens_flare): N-gon mesh builder + LensFlarePass scaffolding"
```

---

## Task 8: Lens-flare shader pair

**Files:**
- Create: `native/src/renderer/shaders/lens_flare.vert`
- Create: `native/src/renderer/shaders/lens_flare.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (embed entries)

- [ ] **Step 1: Write the vertex shader**

Create `native/src/renderer/shaders/lens_flare.vert`:

```glsl
#version 330 core
layout(location = 0) in vec2 a_corner;   // unit-disk-local position
layout(location = 1) in vec2 a_uv;

uniform vec2  u_screen_center;            // NDC coordinates
uniform float u_scale;                    // NDC-Y radius of the disk
uniform float u_aspect;                   // viewport_w / viewport_h

out vec2 v_uv;

void main() {
    vec2 ndc = u_screen_center
             + vec2(a_corner.x / u_aspect, a_corner.y) * u_scale;
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_uv = a_uv;
}
```

- [ ] **Step 2: Write the fragment shader**

Create `native/src/renderer/shaders/lens_flare.frag`:

```glsl
#version 330 core
in  vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform float     u_brightness;   // global fade in [0, 1]

void main() {
    vec4 t = texture(u_texture, v_uv);
    frag_color = vec4(t.rgb, t.a) * u_brightness;
}
```

- [ ] **Step 3: Embed the shaders**

Edit `native/src/renderer/CMakeLists.txt`. Add after the existing `embed_shader(SHADER_SHIELD_FS ...)` line:

```cmake
embed_shader(SHADER_LENS_FLARE_VS shaders/lens_flare.vert lens_flare_vs)
embed_shader(SHADER_LENS_FLARE_FS shaders/lens_flare.frag lens_flare_fs)
```

- [ ] **Step 4: Confirm the build reconfigures**

```
cmake -B build -S . && cmake --build build --target renderer -j
```

Expected: builds clean — the embed headers are generated but not yet referenced.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/lens_flare.vert \
        native/src/renderer/shaders/lens_flare.frag \
        native/src/renderer/CMakeLists.txt
git commit -m "feat(lens_flare): GLSL shaders + CMake embed entries"
```

---

## Task 9: Pipeline registration

**Files:**
- Modify: `native/src/renderer/include/renderer/pipeline.h:14-26`
- Modify: `native/src/renderer/pipeline.cc:6-25`

- [ ] **Step 1: Add the accessor + field**

Edit `native/src/renderer/include/renderer/pipeline.h`:

```cpp
#pragma once

#include "renderer/shader.h"

#include <memory>

namespace renderer {

class Pipeline {
public:
    Pipeline();

    Shader& opaque_shader() noexcept     { return *opaque_; }
    Shader& backdrop_shader() noexcept   { return *backdrop_; }
    Shader& sun_shader() noexcept        { return *sun_; }
    Shader& dust_shader() noexcept       { return *dust_; }
    Shader& shield_shader() noexcept     { return *shield_; }
    Shader& lens_flare_shader() noexcept { return *lens_flare_; }

private:
    std::unique_ptr<Shader> opaque_;
    std::unique_ptr<Shader> backdrop_;
    std::unique_ptr<Shader> sun_;
    std::unique_ptr<Shader> dust_;
    std::unique_ptr<Shader> shield_;
    std::unique_ptr<Shader> lens_flare_;
};

}  // namespace renderer
```

- [ ] **Step 2: Load the shader**

Edit `native/src/renderer/pipeline.cc`. Add the include and constructor line:

```cpp
#include "embedded_shield_vs.h"
#include "embedded_shield_fs.h"
#include "embedded_lens_flare_vs.h"
#include "embedded_lens_flare_fs.h"

namespace renderer {

Pipeline::Pipeline() {
    opaque_     = std::make_unique<Shader>(shader_src::opaque_vs,    shader_src::opaque_fs);
    backdrop_   = std::make_unique<Shader>(shader_src::backdrop_vs,  shader_src::backdrop_fs);
    sun_        = std::make_unique<Shader>(shader_src::sun_vs,       shader_src::sun_fs);
    dust_       = std::make_unique<Shader>(shader_src::dust_vs,      shader_src::dust_fs);
    shield_     = std::make_unique<Shader>(shader_src::shield_vs,    shader_src::shield_fs);
    lens_flare_ = std::make_unique<Shader>(shader_src::lens_flare_vs, shader_src::lens_flare_fs);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CW);
}

}  // namespace renderer
```

- [ ] **Step 3: Build**

```
cmake -B build -S . && cmake --build build --target renderer -j
```

Expected: builds clean.

- [ ] **Step 4: Run renderer_tests to confirm no regressions**

```
cmake --build build --target renderer_tests -j && ./build/native/tests/renderer/renderer_tests
```

Expected: all existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/pipeline.h \
        native/src/renderer/pipeline.cc
git commit -m "feat(pipeline): register lens-flare shader"
```

---

## Task 10: LensFlarePass `render()` implementation

**Files:**
- Modify: `native/src/renderer/lens_flare_pass.cc`

- [ ] **Step 1: Replace the stub `render()` body**

Edit `native/src/renderer/lens_flare_pass.cc` — replace the `render(...)` body with the full implementation:

```cpp
void LensFlarePass::render(const std::vector<LensFlareDescriptor>& flares,
                           const scenegraph::Camera& camera,
                           Pipeline& pipeline,
                           int viewport_w, int viewport_h,
                           double now_seconds) {
    if (flares.empty() || viewport_w <= 0 || viewport_h <= 0) return;

    auto& shader = pipeline.lens_flare_shader();
    shader.use();

    const float aspect =
        static_cast<float>(viewport_w) / static_cast<float>(viewport_h);
    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();

    bool gl_state_active = false;
    auto activate_gl_state = [&]() {
        if (gl_state_active) return;
        glDisable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE);
        glDisable(GL_CULL_FACE);
        gl_state_active = true;
    };

    for (const auto& f : flares) {
        const glm::vec4 clip = vp * glm::vec4(f.source_world_pos, 1.0f);
        if (clip.w <= 0.0f) continue;
        const glm::vec3 ndc = glm::vec3(clip) / clip.w;
        if (std::abs(ndc.x) > 1.2f || std::abs(ndc.y) > 1.2f) continue;
        if (ndc.z < -1.0f || ndc.z > 1.0f) continue;

        // Depth occlusion: sample the depth buffer at the source's pixel.
        // The sun sphere itself was drawn into the depth buffer earlier in
        // the frame; eps lifts the test off the sphere's own surface.
        const float u01 = (ndc.x * 0.5f + 0.5f);
        const float v01 = (ndc.y * 0.5f + 0.5f);
        const int px = std::min(viewport_w - 1, std::max(0,
                          static_cast<int>(u01 * static_cast<float>(viewport_w))));
        const int py = std::min(viewport_h - 1, std::max(0,
                          static_cast<int>(v01 * static_cast<float>(viewport_h))));
        float sampled_depth = 1.0f;
        glReadPixels(px, py, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, &sampled_depth);
        const float source_depth01 = ndc.z * 0.5f + 0.5f;
        constexpr float kDepthEps = 1e-4f;
        if (sampled_depth + kDepthEps < source_depth01) continue;

        activate_gl_state();
        shader.set_float("u_aspect", aspect);
        shader.set_int("u_texture", 0);
        glActiveTexture(GL_TEXTURE0);

        for (const auto& e : f.elements) {
            assets::Texture* tex = ensure_texture(e.texture_path);
            if (!tex) continue;
            const WedgeMesh& mesh = ensure_wedge_mesh(e.wedges);
            if (mesh.index_count == 0) continue;

            const glm::vec2 src_ndc(ndc.x, ndc.y);
            const glm::vec2 center =
                glm::mix(src_ndc, glm::vec2(0.0f, 0.0f), e.position);
            const float kTwoPi = 6.28318530717958647692f;
            const float wobble = (e.amp != 0.0f && e.freq != 0.0f)
                ? e.amp * std::sin(kTwoPi * e.freq * static_cast<float>(now_seconds))
                : 0.0f;
            const float scale = e.size * (1.0f + wobble);

            shader.set_vec2("u_screen_center", center);
            shader.set_float("u_scale", scale);
            shader.set_float("u_brightness", 1.0f);
            glBindTexture(GL_TEXTURE_2D, tex->id());
            glBindVertexArray(mesh.vao);
            glDrawElements(GL_TRIANGLES, mesh.index_count, GL_UNSIGNED_INT, nullptr);
        }
    }

    if (gl_state_active) {
        glBindVertexArray(0);
        glEnable(GL_CULL_FACE);
        glDepthMask(GL_TRUE);
        glEnable(GL_DEPTH_TEST);
        glDisable(GL_BLEND);
    }
}
```

- [ ] **Step 2: Check that `set_vec2` exists on Shader**

```
grep -n "set_vec2\|set_vec3" native/src/renderer/include/renderer/shader.h
```

If `set_vec2` is missing, fall back to two separate float uniforms instead. (Search will show its presence; the existing dust shader uses `set_vec3("u_camera_pos", ...)` so a `vec2` variant is the natural sibling.) If absent, add this method to `shader.h` / `shader.cc` (one-line wrapper around `glUniform2f`) before continuing.

- [ ] **Step 3: Build**

```
cmake -B build -S . && cmake --build build --target renderer -j
```

Expected: builds clean.

- [ ] **Step 4: Run existing renderer tests to confirm no regressions**

```
cmake --build build --target renderer_tests -j && ./build/native/tests/renderer/renderer_tests
```

Expected: all green (the LensFlarePass tests still only exercise `build_ngon_mesh`, which is unaffected).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/lens_flare_pass.cc \
        native/src/renderer/include/renderer/shader.h \
        native/src/renderer/shader.cc
git commit -m "feat(lens_flare): render() — projection, depth-test, additive draw"
```

(Omit `shader.h` / `shader.cc` from the `git add` if `set_vec2` already existed.)

---

## Task 11: Host bindings — `set_lens_flares` + `frame()` integration

**Files:**
- Modify: `native/src/host/host_bindings.cc`

- [ ] **Step 1: Add includes + globals**

Edit `native/src/host/host_bindings.cc` near the top, after the `shield_pass.h` include:

```cpp
#include <renderer/shield_pass.h>
#include <renderer/lens_flare_pass.h>
```

In the anonymous-namespace globals block (near `g_shield_pass`):

```cpp
std::vector<renderer::LensFlareDescriptor> g_lens_flares;
std::unique_ptr<renderer::LensFlarePass>   g_lens_flare_pass;
```

- [ ] **Step 2: Allocate + free in init / shutdown**

In `init(...)`, after `g_shield_pass = std::make_unique<...>();`:

```cpp
    g_lens_flare_pass = std::make_unique<renderer::LensFlarePass>();
```

In `shutdown()`, after `g_shield_pass.reset();`:

```cpp
    g_lens_flares.clear();
    g_lens_flare_pass.reset();
```

- [ ] **Step 3: Invoke the pass in `frame()`**

Locate the line `if (g_dust_pass) g_dust_pass->render(g_camera, dt, *g_pipeline);` and add immediately after it:

```cpp
    if (g_dust_pass) g_dust_pass->render(g_camera, dt, *g_pipeline);

    if (g_lens_flare_pass) {
        int fw2 = 0, fh2 = 0;
        g_window->framebuffer_size(&fw2, &fh2);
        g_lens_flare_pass->render(g_lens_flares, g_camera, *g_pipeline,
                                  fw2, fh2, now);
    }
```

- [ ] **Step 4: Add the `set_lens_flares` binding**

Append inside the `PYBIND11_MODULE` block, after the existing `m.def("set_suns", ...)`:

```cpp
    m.def("set_lens_flares",
          [](const std::vector<py::dict>& descs) {
              g_lens_flares.clear();
              g_lens_flares.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::LensFlareDescriptor f;
                  auto pos = d["source_world_pos"].cast<std::tuple<float,float,float>>();
                  f.source_world_pos = {std::get<0>(pos),
                                        std::get<1>(pos),
                                        std::get<2>(pos)};
                  f.source_radius    = d["source_radius"].cast<float>();
                  auto elements      = d["elements"].cast<std::vector<py::dict>>();
                  f.elements.reserve(elements.size());
                  for (const auto& ed : elements) {
                      renderer::LensFlareElement e;
                      e.wedges       = ed["wedges"].cast<int>();
                      e.texture_path = ed["texture_path"].cast<std::string>();
                      e.position     = ed["position"].cast<float>();
                      e.size         = ed["size"].cast<float>();
                      e.freq         = ed["freq"].cast<float>();
                      e.amp          = ed["amp"].cast<float>();
                      f.elements.push_back(std::move(e));
                  }
                  g_lens_flares.push_back(std::move(f));
              }
          },
          py::arg("flares"),
          "Set the active lens-flare list, applied each frame().");
```

- [ ] **Step 5: Build**

```
cmake -B build -S . && cmake --build build -j
```

Expected: builds clean. Both `build/dauntless` and `build/python/_open_stbc_host.cpython-*.so` rebuild.

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): set_lens_flares binding + LensFlarePass in frame()"
```

---

## Task 12: Python `set_lens_flares` wrapper

**Files:**
- Modify: `engine/renderer.py`

- [ ] **Step 1: Add the typed wrapper**

Edit `engine/renderer.py` — after the existing `set_suns(...)` definition (around line 73):

```python
def set_lens_flares(flares: list) -> None:
    """Configure the renderer's lens-flare list. Each entry is a dict:
        {
            "source_world_pos": (x, y, z),
            "source_radius":    float,
            "elements": [
                {
                    "wedges":       int,    # 3..64
                    "texture_path": str,    # absolute
                    "position":     float,  # 0=at source, 1=screen center, 2=opposite
                    "size":         float,  # fraction of viewport height
                    "freq":         float,  # Hz wobble (0 = off)
                    "amp":          float,  # wobble amplitude (0 = off)
                }, ...
            ],
        }
    """
    _h.set_lens_flares(flares)
```

- [ ] **Step 2: Smoke-test the binding round-trip**

Run a quick interactive check:

```
uv run python -c "
from engine import renderer as r
r.init(320, 200, 'smoke')
r.set_lens_flares([{
    'source_world_pos': (0.0, 0.0, 0.0),
    'source_radius':    100.0,
    'elements': [{
        'wedges': 8, 'texture_path': 'game/data/Textures/rays.tga',
        'position': 0.0, 'size': 0.1, 'freq': 0.0, 'amp': 0.0,
    }],
}])
r.shutdown()
print('OK')
"
```

Expected: `OK` printed; no crash, no exception. (Empty flare list is also valid — invoke it once with `[]` to confirm.)

- [ ] **Step 3: Commit**

```bash
git add engine/renderer.py
git commit -m "feat(engine): set_lens_flares typed wrapper"
```

---

## Task 13: host_loop aggregation + per-frame push

**Files:**
- Modify: `engine/host_loop.py:648-666` (after `_aggregate_suns`)
- Modify: `engine/host_loop.py:1302-1306` (per-tick render block)
- Test: `tests/integration/test_host_loop_lens_flares.py` (new)

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_host_loop_lens_flares.py`:

```python
"""host_loop._aggregate_lens_flares pulls built flares from g_kSetManager
and shapes them for the renderer binding."""
from pathlib import Path
import App
from engine.host_loop import _aggregate_lens_flares
from engine.appc.sets import SetClass
from engine.appc.planet import Sun


def test_aggregate_lens_flares_pulls_from_active_sets():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    sun = Sun(radius=4040.0, model_path="data/Textures/SunBase.tga")
    sun.SetWorldLocation((1.0, 2.0, 3.0))
    pSet.AddObjectToSet(sun, "Sun")
    pLens = App.LensFlare_Create(pSet)
    pLens.SetSource(sun, 6)
    pLens.AddFlare(8, "data/textures/rays.tga", 0.0, 0.2)
    pLens.Build()
    App.g_kSetManager._sets["Tau Ceti"] = pSet

    out = _aggregate_lens_flares()
    assert len(out) == 1
    f = out[0]
    # ASTRO_SCALE may be applied; assert structure rather than exact numbers.
    assert isinstance(f["source_world_pos"], tuple)
    assert len(f["source_world_pos"]) == 3
    assert len(f["elements"]) == 1
    assert Path(f["elements"][0]["texture_path"]).is_absolute()
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/integration/test_host_loop_lens_flares.py -v
```

Expected: `ImportError: cannot import name '_aggregate_lens_flares'`.

- [ ] **Step 3: Add `_aggregate_lens_flares` to host_loop**

Edit `engine/host_loop.py` — add immediately after `_aggregate_suns` (line 666):

```python
def _aggregate_lens_flares() -> list:
    """Collect lens-flare descriptors with ASTRO_SCALE applied to source pos."""
    from engine.appc.lens_flare import aggregate_lens_flares_for_renderer
    import App
    raw = aggregate_lens_flares_for_renderer(
        PROJECT_ROOT, list(App.g_kSetManager._sets.values()))
    return [
        {
            "source_world_pos": (
                f["source_world_pos"][0] * ASTRO_SCALE,
                f["source_world_pos"][1] * ASTRO_SCALE,
                f["source_world_pos"][2] * ASTRO_SCALE,
            ),
            "source_radius": f["source_radius"] * ASTRO_SCALE,
            "elements":      f["elements"],
        }
        for f in raw
    ]
```

- [ ] **Step 4: Push the descriptors each tick**

Edit `engine/host_loop.py` around line 1305 (the existing `suns = _aggregate_suns()` / `r.set_suns(suns)` block). Add immediately after `r.set_suns(suns)`:

```python
            suns = _aggregate_suns()
            r.set_suns(suns)

            lens_flares = _aggregate_lens_flares()
            r.set_lens_flares(lens_flares)
```

And add to the `verbose and ticks == 0` diagnostics block:

```python
                print(f"[host_loop] tick 0 lens flares: "
                      f"{len(lens_flares)} flare(s)", flush=True)
```

- [ ] **Step 5: Run the test to verify it passes**

```
uv run pytest tests/integration/test_host_loop_lens_flares.py -v
```

Expected: PASS.

- [ ] **Step 6: Run the gameloop harness to confirm the stub row is gone**

```
uv run python -u tools/gameloop_harness.py --ticks 60 --profile 2>&1 | grep -E "LensFlare|Stub call|PASS:"
```

Expected: `PASS: 35`, no `LensFlare` row anywhere in the profile table.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/integration/test_host_loop_lens_flares.py
git commit -m "feat(host_loop): per-frame lens-flare aggregation + push"
```

---

## Task 14: Visual smoke verification + memory update

**Files:**
- Modify: `/Users/mward/.claude/projects/-Users-mward-Documents-Projects-open-stbc/memory/MEMORY.md` (add lens-flare project memory if anything surprising surfaces)

- [ ] **Step 1: Run the renderer host on E1M1**

```
./build/dauntless
```

In the running window, navigate to Maelstrom Episode 1 Mission 1 (Tau Ceti). Confirm visually:

1. A yellow lens flare appears when the camera looks toward the sun (off-axis is fine — the flare elements trail across the screen toward the opposite point).
2. The flare disappears when a ship hull or planet passes between camera and sun.
3. The primary rays element (with `freq=0.5, amp=0.1`) wobbles slightly over time.
4. Switching to Cebalrai (red-orange `RedOrangeLensFlare`) shows a red-orange palette.

If any of those fail, the bug is downstream of the descriptor list — log `lens_flares` from `_aggregate_lens_flares` to confirm the data is right, then inspect the pass's projection/depth-test logic.

- [ ] **Step 2: Run full test suite**

```
uv run pytest -q
```

Expected: green.

- [ ] **Step 3: Build all native tests + run them**

```
cmake --build build --target renderer_tests -j && ./build/native/tests/renderer/renderer_tests
```

Expected: green.

- [ ] **Step 4: Add a project memory if anything was non-obvious**

If the visual smoke surfaces any tunable that's load-bearing (e.g., `kDepthEps` had to be larger than expected, off-screen culling margin needed adjustment), add a one-line `feedback_*.md` or `project_*.md` memory pointing future-you at the constraint. Skip if the implementation was clean.

- [ ] **Step 5: Final commit if any tuning changes landed**

```bash
git add -p
git commit -m "tune(lens_flare): <whatever you changed>"
```

(Skip if Step 1 was clean.)

---

## Self-review checklist

After implementation:

1. **Spec coverage** — every section of `2026-05-12-lens-flare-render-pass-design.md` has a corresponding task. ✓
2. **Stub regression test green** — `LensFlare` rows absent from `_stub_tracker.report()`. (Task 5 + Task 13 Step 6.)
3. **Visual smoke passes** — Task 14 Step 1.
4. **All unit + integration tests green** — Task 14 Step 2.
5. **Renderer tests green** — Task 14 Step 3.
