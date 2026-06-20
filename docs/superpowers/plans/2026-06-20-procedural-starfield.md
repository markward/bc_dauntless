# Procedural Starfield Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace BC's static tiled-TGA starfield with a procedural sky — varied stars, Milky-Way star clusters (dust glow + dark lanes), and data-driven nebulae with subtle motion — as a Modern VFX toggle that defaults on and falls back byte-identically to stock BC.

**Architecture:** Extend the existing `backdrop_pass` (camera-anchored spheres → HDR target) with a procedural shader branch gated by a toggle. An offline bake turns the game backdrop TGAs into a committed appearance table; `engine/appc/backdrops.py` joins each SDK backdrop with its row and emits procedural fields in the existing `set_backdrops` descriptor; the fragment shader synthesizes stars/star-clouds/nebulae from those fields. No new pass, no NIF, no runtime image decode.

**Tech Stack:** Python 3 (extractor/aggregation, Pillow at bake time only), pybind11 (host bindings), C++17 + GLSL 330 (renderer), GoogleTest (C++), pytest (Python), CMake.

**Spec:** [`docs/superpowers/specs/2026-06-20-procedural-starfield-design.md`](../specs/2026-06-20-procedural-starfield-design.md)

## Global Constraints

- **Faithful fallback is sacred:** toggle OFF must be byte-identical to current stock-BC rendering. The existing texture path in `backdrop.frag` / `backdrop_pass.cc` must not change behaviour when `u_procedural == 0`.
- **Default ON:** the procedural toggle defaults to `true` (mirrors `dauntless_hdr`, default true).
- **Shader edits need a CMake reconfigure:** after editing any `.vert`/`.frag`, run `cmake -B build -S .` BEFORE `cmake --build build` — the shader-embedding headers regenerate at *configure* time (see CLAUDE.md). A `cmake --build` alone will NOT pick up shader edits.
- **Single build tree:** build at `<root>/build/`; binary `build/dauntless`. Never create `native/build/`.
- **Game units:** all spatial values stay in GU; `1 GU = 175 m`, `GU_TO_KM = 0.175`. (Not directly used here but applies if distances surface.)
- **Toggle/binding naming:** mirror existing VFX toggles — `procedural_sky_set_enabled` binding, `namespace dauntless_procedural_sky { bool enabled(); void set_enabled(bool); }` in `frame.cc`.
- Run Python tests with `uv run pytest`. Run C++ tests via `ctest --test-dir build`.

---

### Task 1: Backdrop appearance computation + bake tool

Productionize the PoC's `tga_appearance` (`poc/extract_map.py`) into a reusable function + CLI that emits the appearance table. The runtime never decodes a TGA; this is offline only.

**Files:**
- Create: `tools/bake_backdrop_appearance.py`
- Test: `tests/tools/test_bake_backdrop_appearance.py`

**Interfaces:**
- Produces: `compute_appearance(img) -> dict` where `img` is a `PIL.Image.Image`; returns
  `{"meanColor": [r,g,b], "palette": [[r,g,b]*5], "coverage": float}` (RGB ints 0–255, coverage 0–1).
- Produces: `main(game_dir: Path, out_path: Path) -> dict` writing `{ "<texture-basename>": <appearance>, ... }` JSON and returning the dict.

- [ ] **Step 1: Write the failing test**

```python
# tests/tools/test_bake_backdrop_appearance.py
from PIL import Image
from tools.bake_backdrop_appearance import compute_appearance


def _solid(rgb, size=64):
    return Image.new("RGBA", (size, size), rgb + (255,))


def test_compute_appearance_solid_colour():
    ap = compute_appearance(_solid((120, 40, 200)))
    # mean is the solid colour (within rounding of the 48x48 downsample)
    assert abs(ap["meanColor"][0] - 120) <= 3
    assert abs(ap["meanColor"][1] - 40) <= 3
    assert abs(ap["meanColor"][2] - 200) <= 3
    # fully lit -> coverage ~1.0
    assert ap["coverage"] >= 0.95
    assert len(ap["palette"]) == 5
    assert all(len(c) == 3 for c in ap["palette"])


def test_compute_appearance_mostly_black_low_coverage():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    for x in range(0, 6):
        for y in range(0, 6):
            img.putpixel((x, y), (255, 255, 255, 255))
    ap = compute_appearance(img)
    assert ap["coverage"] < 0.2  # ~36/4096 lit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_bake_backdrop_appearance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.bake_backdrop_appearance'`

- [ ] **Step 3: Write minimal implementation**

```python
# tools/bake_backdrop_appearance.py
"""Bake game backdrop TGAs -> appearance table for the procedural sky.

Offline build step (needs game/ + Pillow). The runtime consumes the JSON;
it never decodes a TGA. Ports poc/extract_map.py:tga_appearance.
"""
import json
import os
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAME_DIRS = ["game/data/Backgrounds/High", "game/data/Backgrounds"]
DEFAULT_OUT = ROOT / "engine" / "appc" / "backdrop_appearance.json"


def compute_appearance(img):
    """Mean colour, dominant 5-palette, and lit-coverage for a PIL image."""
    im = img.convert("RGBA")
    small = im.resize((48, 48))
    raw = small.tobytes()  # RGBA
    px = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]
    opaque = [(r, g, b) for r, g, b, a in px if a > 16]
    lit = [c for c in opaque if max(c) > 24]
    mean = [round(sum(c[i] for c in opaque) / max(len(opaque), 1)) for i in range(3)]
    q = small.convert("RGB").quantize(colors=5)
    pal = q.getpalette()[:15]
    palette = [[pal[i], pal[i + 1], pal[i + 2]] for i in range(0, 15, 3)]
    return {
        "meanColor": mean,
        "palette": palette,
        "coverage": round(len(lit) / max(len(px), 1), 3),
    }


def main(game_root=ROOT, out_path=DEFAULT_OUT):
    dirs = [game_root / d for d in DEFAULT_GAME_DIRS]
    table = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(".tga"):
                continue
            if fn in table:
                continue
            try:
                table[fn] = compute_appearance(Image.open(d / fn))
            except Exception as e:  # corrupt/unsupported - skip, don't fail bake
                print(f"[bake] skip {fn}: {e}", file=sys.stderr)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
    print(f"[bake] wrote {len(table)} entries -> {out_path}")
    return table


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tools/test_bake_backdrop_appearance.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tools/bake_backdrop_appearance.py tests/tools/test_bake_backdrop_appearance.py
git commit -m "feat(sky): backdrop appearance bake tool"
```

---

### Task 2: Generate and commit the appearance table

Run the bake against the local `game/` install to produce the committed table the runtime reads. Data-generation task (no unit test; the generator was tested in Task 1).

**Files:**
- Create: `engine/appc/backdrop_appearance.json` (generated, committed)

- [ ] **Step 1: Run the bake**

Run: `uv run python tools/bake_backdrop_appearance.py`
Expected: prints `[bake] wrote N entries -> .../engine/appc/backdrop_appearance.json` with N ≈ 25.

- [ ] **Step 2: Sanity-check the output**

Run: `uv run python -c "import json; d=json.load(open('engine/appc/backdrop_appearance.json')); print(len(d), 'treknebula6.tga' in d, d.get('treknebula6.tga',{}).get('meanColor'))"`
Expected: a count ≈ 25, `True`, and a purple-ish meanColor near `[111, 94, 169]`.

- [ ] **Step 3: Commit**

```bash
git add engine/appc/backdrop_appearance.json
git commit -m "data(sky): committed backdrop appearance table"
```

---

### Task 3: Aggregate procedural descriptor fields in backdrops.py

Extend `aggregate_for_renderer` so each descriptor also carries procedural fields. Classify by texture basename: `stars*` → `stars`, `galaxy*` → `starcloud`, else → `nebula`. Add `proc_kind`, `color` (0–1 floats; nebula = brightened dominant, starcloud = dim galaxy mean), `coverage`, `seed`. Unknown texture → still classify by name, default neutral colour (graceful; renderer falls back fine).

**Files:**
- Modify: `engine/appc/backdrops.py` (add helpers + extend the `out.append({...})` dict)
- Test: `tests/engine/appc/test_backdrops_procedural.py`

**Interfaces:**
- Consumes: `compute_appearance` table JSON at `engine/appc/backdrop_appearance.json`.
- Produces: each descriptor dict gains
  `"proc_kind": "stars"|"starcloud"|"nebula"`, `"color": [r,g,b] (0..1 floats)`,
  `"coverage": float`, `"seed": float`.

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/appc/test_backdrops_procedural.py
from engine.appc import backdrops as bd


def _backdrop(kind, tex):
    b = bd.Backdrop(kind)
    b.SetTextureFileName(tex)
    return b


class _Set:
    def __init__(self, items): self._backdrops = items
    def GetName(self): return "TestSet"


def test_procedural_fields_classify_and_colour(monkeypatch, tmp_path):
    # fake appearance table
    monkeypatch.setattr(bd, "_appearance_table", lambda: {
        "treknebula6.tga": {"meanColor": [111, 94, 169], "palette": [], "coverage": 0.5},
        "galaxy4.tga":     {"meanColor": [55, 44, 44], "palette": [], "coverage": 0.31},
    })
    # make texture paths resolve: point project_root at a tmp tree with the files
    for sub in ("data",):
        (tmp_path / "game" / sub).mkdir(parents=True, exist_ok=True)
    for name in ("stars.tga", "treknebula6.tga", "galaxy4.tga"):
        (tmp_path / "game" / "data" / name).write_bytes(b"x")
    items = [
        _backdrop(bd.Backdrop.KIND_STAR, "data/stars.tga"),
        _backdrop(bd.Backdrop.KIND_BACKDROP, "data/treknebula6.tga"),
        _backdrop(bd.Backdrop.KIND_BACKDROP, "data/galaxy4.tga"),
    ]
    out = bd.aggregate_for_renderer(_Set(items), tmp_path)
    by_kind = {d["proc_kind"]: d for d in out}
    assert set(by_kind) == {"stars", "starcloud", "nebula"}
    # nebula colour is brightened dominant (max channel near 0.8)
    assert max(by_kind["nebula"]["color"]) > 0.75
    # starcloud keeps the dim galaxy mean (max channel < 0.5)
    assert max(by_kind["starcloud"]["color"]) < 0.5
    assert by_kind["nebula"]["coverage"] == 0.5
    # seed stable + per-texture distinct
    assert by_kind["nebula"]["seed"] != by_kind["starcloud"]["seed"]


def test_unknown_texture_is_graceful(monkeypatch, tmp_path):
    monkeypatch.setattr(bd, "_appearance_table", lambda: {})
    (tmp_path / "game" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "game" / "data" / "mystery.tga").write_bytes(b"x")
    b = _backdrop(bd.Backdrop.KIND_BACKDROP, "data/mystery.tga")
    out = bd.aggregate_for_renderer(_Set([b]), tmp_path)
    assert out[0]["proc_kind"] == "nebula"
    assert "color" in out[0] and "seed" in out[0]  # defaults, no crash
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/appc/test_backdrops_procedural.py -v`
Expected: FAIL with `KeyError: 'proc_kind'`

- [ ] **Step 3: Write the implementation**

Add near the top of `engine/appc/backdrops.py` (after the imports):

```python
import json as _json
from functools import lru_cache as _lru_cache
from pathlib import Path as _P

_APPEARANCE_PATH = _P(__file__).with_name("backdrop_appearance.json")


@_lru_cache(maxsize=1)
def _appearance_table():
    try:
        return _json.loads(_APPEARANCE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _proc_kind(basename):
    b = basename.lower()
    if b.startswith("stars"):
        return "stars"
    if b.startswith("galaxy"):
        return "starcloud"
    return "nebula"


def _display_tint(rgb, target=205):
    m = max(rgb) or 1
    f = target / m
    return [min(255, round(c * f)) / 255.0 for c in rgb]


def _proc_fields(basename):
    """proc_kind, colour (0..1), coverage, seed for one backdrop texture."""
    kind = _proc_kind(basename)
    row = _appearance_table().get(basename)
    mean = row["meanColor"] if row else [90, 90, 110]
    coverage = row["coverage"] if row else 0.4
    # nebula -> vivid; starcloud dust -> keep dim; stars -> unused
    color = _display_tint(mean) if kind == "nebula" else [c / 255.0 for c in mean]
    seed = (abs(hash(basename)) % 100000) / 1000.0  # stable per texture
    return {"proc_kind": kind, "color": color, "coverage": coverage, "seed": seed}
```

Then in `aggregate_for_renderer`, change the `out.append({...})` to merge the procedural fields. Replace:

```python
        out.append({
            "texture_path": str(abs_path),
            "kind": b._kind,
            "h_tile": b._texture_h_tile,
            "v_tile": b._texture_v_tile,
            "h_span": b._horizontal_span,
            "v_span": b._vertical_span,
            "world_rotation": m9,
            "target_poly_count": max(int(b._target_poly_count), 64),
        })
```

with:

```python
        entry = {
            "texture_path": str(abs_path),
            "kind": b._kind,
            "h_tile": b._texture_h_tile,
            "v_tile": b._texture_v_tile,
            "h_span": b._horizontal_span,
            "v_span": b._vertical_span,
            "world_rotation": m9,
            "target_poly_count": max(int(b._target_poly_count), 64),
        }
        entry.update(_proc_fields(_P(b._texture_path).name))
        out.append(entry)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/appc/test_backdrops_procedural.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the existing backdrop tests to confirm no regression**

Run: `uv run pytest tests/ -k backdrop -q`
Expected: PASS (existing + new)

- [ ] **Step 6: Commit**

```bash
git add engine/appc/backdrops.py tests/engine/appc/test_backdrops_procedural.py
git commit -m "feat(sky): procedural descriptor fields from appearance table"
```

---

### Task 4: C++ plumbing — toggle, struct fields, bindings, render signature

Add the procedural toggle (mirrors `dauntless_hdr`), extend the `Backdrop` struct + `set_backdrops` to carry procedural fields, widen `BackdropPass::render` to take `procedural` + `time`, and pass them at the call site. No shader logic yet — the new uniforms are set but unused until Task 5 (setting an absent uniform is a harmless no-op in GL).

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h` (Backdrop struct)
- Modify: `native/src/renderer/frame.cc` (add `dauntless_procedural_sky` namespace)
- Modify: `native/src/renderer/include/renderer/backdrop_pass.h` (render signature)
- Modify: `native/src/renderer/backdrop_pass.cc` (accept + set uniforms)
- Modify: `native/src/host/host_bindings.cc` (forward-decl, set_backdrops fields, binding, call site)
- Test: `native/tests/renderer/backdrop_pass_test.cc` (extend)

**Interfaces:**
- Produces (C++): `renderer::Backdrop` gains `int proc_kind` (0 stars,1 starcloud,2 nebula), `glm::vec3 color`, `float coverage`, `float seed`.
- Produces (C++): `BackdropPass::render(backdrops, camera, pipeline, bool procedural, float now_seconds)`.
- Produces (Python): `_dauntless_host.procedural_sky_set_enabled(bool)`; `dauntless_procedural_sky::enabled()` defaults `true`.

- [ ] **Step 1: Write the failing test**

```cpp
// append to native/tests/renderer/backdrop_pass_test.cc (inside the anon namespace)
TEST_F(BackdropPassTest, ProceduralRenderProducesNoGLError) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::Backdrop b;
    b.texture_path = "/dev/null";   // texture load fails; procedural path is data-driven
    b.kind = renderer::BackdropKind::Backdrop;
    b.proc_kind = 2;                // nebula
    b.color = glm::vec3(0.6f, 0.3f, 0.7f);
    b.coverage = 0.5f;
    b.seed = 12.0f;
    b.h_span = 0.3f; b.v_span = 0.3f;

    pass.render({b}, cam, *pipeline, /*procedural=*/true, /*now=*/1.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
```

- [ ] **Step 2: Run test to verify it fails (compile error)**

Run: `cmake --build build -j --target renderer_tests 2>&1 | tail -5`
Expected: FAIL — `too many arguments to function call` / `no member named 'proc_kind'`.

- [ ] **Step 3: Extend the `Backdrop` struct**

In `native/src/renderer/include/renderer/frame.h`, inside `struct Backdrop`, after `int target_poly_count = 256;` add:

```cpp
    // Procedural sky (Modern VFX). Ignored when the procedural toggle is off.
    int   proc_kind = 0;        // 0 = stars, 1 = starcloud (galaxy), 2 = nebula
    glm::vec3 color = glm::vec3(0.5f);  // recorded dominant colour, 0..1
    float coverage = 0.4f;      // density 0..1
    float seed = 0.0f;          // per-backdrop stable seed
```

- [ ] **Step 4: Add the toggle namespace**

In `native/src/renderer/frame.cc`, alongside the other `dauntless_*` toggle namespaces (near `dauntless_hdr`), add:

```cpp
// Toggle for the procedural sky (Modern VFX). Default on; off = stock BC.
namespace dauntless_procedural_sky {
    bool g_procedural_sky_enabled = true;
    bool enabled() { return g_procedural_sky_enabled; }
    void set_enabled(bool v) { g_procedural_sky_enabled = v; }
}
```

- [ ] **Step 5: Widen the render signature**

In `native/src/renderer/include/renderer/backdrop_pass.h`, change the `render` declaration to:

```cpp
    void render(const std::vector<Backdrop>& backdrops,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                bool procedural,
                float now_seconds);
```

In `native/src/renderer/backdrop_pass.cc`, change the definition signature to match and, inside the per-backdrop loop (after the existing `shader.set_vec2("u_span", ...)` line), add:

```cpp
        shader.set_int("u_procedural", procedural ? 1 : 0);
        shader.set_int("u_proc_kind", b.proc_kind);
        shader.set_vec3("u_color", b.color);
        shader.set_float("u_coverage", b.coverage);
        shader.set_float("u_seed", b.seed);
        shader.set_float("u_time", now_seconds);
```

Note: when `procedural` is true, the data-driven path does not need a texture, so the early `if (!sphere || !tex) continue;` must not skip procedural backdrops. Change that line to:

```cpp
        if (!sphere) continue;
        if (!tex && !procedural) continue;
```

- [ ] **Step 6: Wire bindings + call site**

In `native/src/host/host_bindings.cc`:

(a) Forward-declare the namespace near the other toggle forward-decls (by `dauntless_hdr`):

```cpp
namespace dauntless_procedural_sky {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
```

(b) In the `set_backdrops` lambda, after `b.target_poly_count = d["target_poly_count"].cast<int>();` add (guarded so older descriptors still load):

```cpp
                  if (d.contains("proc_kind")) {
                      std::string pk = d["proc_kind"].cast<std::string>();
                      b.proc_kind = (pk == "stars") ? 0 : (pk == "starcloud") ? 1 : 2;
                      auto col = d["color"].cast<std::vector<float>>();
                      if (col.size() == 3) b.color = glm::vec3(col[0], col[1], col[2]);
                      b.coverage = d["coverage"].cast<float>();
                      b.seed = d["seed"].cast<float>();
                  }
```

(c) Change the render call site (the line `g_backdrop_pass->render(g_backdrops, cam, *g_pipeline);`) to:

```cpp
        g_backdrop_pass->render(g_backdrops, cam, *g_pipeline,
                                dauntless_procedural_sky::enabled(), g_now_seconds);
```

Use the same time value passed to `g_sun_pass->render(...)` in this scope (the sun pass already receives `now_seconds`); reuse that exact variable name rather than introducing a new one.

(d) Add the Python binding near `rim_set_enabled`:

```cpp
    m.def("procedural_sky_set_enabled",
          [](bool enabled) { dauntless_procedural_sky::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the procedural sky (Modern VFX). Default: on; off = stock BC.");
```

- [ ] **Step 7: Build and run the test**

Run: `cmake --build build -j && ctest --test-dir build -R BackdropPass --output-on-failure`
Expected: PASS, including `ProceduralRenderProducesNoGLError`.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h native/src/renderer/frame.cc \
        native/src/renderer/include/renderer/backdrop_pass.h native/src/renderer/backdrop_pass.cc \
        native/src/host/host_bindings.cc native/tests/renderer/backdrop_pass_test.cc
git commit -m "feat(sky): procedural plumbing - toggle, struct, bindings, render signature"
```

---

### Task 5: Procedural fragment shader (the visual heart)

Add the procedural branch to `backdrop.frag`: inlined hash/noise (GLSL has no `#include`, and shaders are embedded per-file), then stars / star-cloud (Milky-Way dust) / nebula synthesis. The branch is gated by `u_procedural`; the existing texture path is untouched when off.

**Files:**
- Modify: `native/src/renderer/shaders/backdrop.frag`
- Test: `native/tests/renderer/backdrop_pass_test.cc` (add a pixel-readback test)

**Interfaces:**
- Consumes: uniforms `u_procedural, u_proc_kind, u_color, u_coverage, u_seed, u_time` (set in Task 4).

- [ ] **Step 1: Write the failing test (pixel readback)**

```cpp
// append to native/tests/renderer/backdrop_pass_test.cc
#include <vector>
TEST_F(BackdropPassTest, ProceduralNebulaPaintsItsColour) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.eye = {0, 0, 0}; cam.target = {0, 1, 0}; cam.aspect = 1.0f;

    renderer::Backdrop b;
    b.kind = renderer::BackdropKind::Backdrop;
    b.proc_kind = 2;                       // nebula
    b.color = glm::vec3(0.9f, 0.1f, 0.1f); // strongly red
    b.coverage = 0.9f; b.seed = 3.0f;
    b.h_span = 1.0f; b.v_span = 1.0f;
    // point the patch down +Y (camera looks at +Y); identity rotation maps
    // mesh (0,1,0) -> +Y, the patch centre.

    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    pass.render({b}, cam, *pipeline, /*procedural=*/true, /*now=*/0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);

    std::vector<unsigned char> px(256 * 256 * 4);
    glReadPixels(0, 0, 256, 256, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    // accumulate channel sums over the frame
    long rsum = 0, gsum = 0, bsum = 0, lit = 0;
    for (size_t i = 0; i < px.size(); i += 4) {
        if (px[i] + px[i + 1] + px[i + 2] > 10) lit++;
        rsum += px[i]; gsum += px[i + 1]; bsum += px[i + 2];
    }
    EXPECT_GT(lit, 200);          // the nebula painted a visible patch
    EXPECT_GT(rsum, gsum * 2);    // and it reads red (its recorded colour)
    EXPECT_GT(rsum, bsum * 2);
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j && ctest --test-dir build -R "BackdropPass.ProceduralNebulaPaintsItsColour" --output-on-failure`
Expected: FAIL — patch renders black (no procedural branch yet), `lit` ~0.

- [ ] **Step 3: Add the procedural branch to the shader**

In `native/src/renderer/shaders/backdrop.frag`, add the uniforms after the existing `uniform int u_use_alpha;` line:

```glsl
uniform int   u_procedural;   // 0 = stock texture path, 1 = procedural
uniform int   u_proc_kind;    // 0 = stars, 1 = starcloud (galaxy), 2 = nebula
uniform vec3  u_color;        // recorded dominant colour, 0..1
uniform float u_coverage;     // density 0..1
uniform float u_seed;
uniform float u_time;
```

Add `in vec3 v_pos_local;` is already present. Insert the noise helpers + `proc_main` ABOVE `void main()`:

```glsl
float hash13(vec3 p3){ p3 = fract(p3*0.1031); p3 += dot(p3, p3.zyx+31.32); return fract((p3.x+p3.y)*p3.z); }
vec3  hash33(vec3 p3){ p3 = fract(p3*vec3(0.1031,0.1030,0.0973)); p3 += dot(p3, p3.yxz+33.33); return fract((p3.xxy+p3.yxx)*p3.zyx); }
float vnoise(vec3 p){
    vec3 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
    float n000=hash13(i), n100=hash13(i+vec3(1,0,0));
    float n010=hash13(i+vec3(0,1,0)), n110=hash13(i+vec3(1,1,0));
    float n001=hash13(i+vec3(0,0,1)), n101=hash13(i+vec3(1,0,1));
    float n011=hash13(i+vec3(0,1,1)), n111=hash13(i+vec3(1,1,1));
    return mix(mix(mix(n000,n100,f.x),mix(n010,n110,f.x),f.y),
               mix(mix(n001,n101,f.x),mix(n011,n111,f.x),f.y), f.z);
}
float fbm(vec3 p){ float a=0.5,s=0.0; for(int k=0;k<5;k++){ s+=a*vnoise(p); p*=2.02; a*=0.5; } return s; }

vec3 proc_stars(vec3 dir, float density){
    vec3 g = dir*220.0; vec3 cell = floor(g);
    vec3 rnd = hash33(cell + u_seed);
    float present = step(1.0 - density, rnd.x);
    vec3 starPos = cell + 0.2 + 0.6*hash33(cell+7.1);
    float d = length(g - starPos);
    float core = present * smoothstep(0.6, 0.0, d);
    float tw = 0.75 + 0.25*sin(u_time*(1.0+2.0*rnd.z) + rnd.y*6.2831);
    vec3 tint = mix(vec3(0.7,0.8,1.0), vec3(1.0,0.9,0.75), rnd.z);
    return core * (0.4 + 0.6*rnd.y) * tw * tint;
}

void proc_main(vec3 dir, vec2 offset){
    if (u_proc_kind == 0) {
        vec3 c = proc_stars(dir, 0.06) + 0.5*proc_stars(dir*1.7+11.0, 0.04);
        frag_color = vec4(c, 1.0); return;
    }
    float rx = abs(offset.x)/max(u_span.x*0.25, 1e-3);
    float ry = abs(offset.y)/max(u_span.y*0.25, 1e-3);
    float edge = 1.0 - smoothstep(0.6, 1.0, max(rx, ry));
    if (edge <= 0.0) discard;
    vec3 np = dir*3.0 + u_seed; float drift = u_time*0.01;
    if (u_proc_kind == 2) {
        float n = fbm(np + vec3(drift));
        float dens = smoothstep(1.0 - u_coverage*0.9, 1.0, n + 0.15);
        frag_color = vec4(u_color*(0.6 + 0.8*n), dens*edge);
    } else {
        vec3 stars = proc_stars(dir, 0.18) * edge;
        float glowN = fbm(np*0.6 + vec3(drift));
        float lanes = smoothstep(0.55, 0.75, fbm(np*1.8));
        float dust = (0.3 + 0.5*glowN) * (1.0 - 0.85*lanes);
        vec3 col = stars*(1.0 - 0.85*lanes) + u_color*dust;
        frag_color = vec4(col, max(dust*edge, length(stars)));
    }
}
```

Then at the very top of `void main()`, before the existing `vec2 offset = ...` line, add:

```glsl
    if (u_procedural == 1) {
        proc_main(normalize(v_pos_local), v_uv - vec2(0.25, 0.5));
        return;
    }
```

- [ ] **Step 4: Reconfigure (shader embed) + build + test**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R BackdropPass --output-on-failure`
Expected: PASS, including `ProceduralNebulaPaintsItsColour` (red patch) and the existing tests.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/backdrop.frag native/tests/renderer/backdrop_pass_test.cc
git commit -m "feat(sky): procedural backdrop shader - stars, star-clouds, nebulae"
```

---

### Task 6: End-to-end verification + faithful-fallback regression

Confirm the full Python→C++ path lights up in the live app and that toggle-off is unchanged. Visual features need a human gate; this task is that gate plus the regression assertion.

**Files:**
- Test: `native/tests/renderer/backdrop_pass_test.cc` (toggle-off parity assertion)

- [ ] **Step 1: Add a toggle-off parity test**

```cpp
// append to native/tests/renderer/backdrop_pass_test.cc
TEST_F(BackdropPassTest, ToggleOffDiscardsProceduralNebula) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.eye = {0,0,0}; cam.target = {0,1,0}; cam.aspect = 1.0f;
    renderer::Backdrop b;
    b.kind = renderer::BackdropKind::Backdrop;
    b.texture_path = "/dev/null";  // no texture -> stock path draws nothing
    b.proc_kind = 2; b.color = glm::vec3(0.9f,0.1f,0.1f);
    b.h_span = 1.0f; b.v_span = 1.0f;

    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    pass.render({b}, cam, *pipeline, /*procedural=*/false, /*now=*/0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    std::vector<unsigned char> px(256*256*4);
    glReadPixels(0,0,256,256, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    long lit = 0;
    for (size_t i=0;i<px.size();i+=4) if (px[i]+px[i+1]+px[i+2] > 10) lit++;
    EXPECT_EQ(lit, 0);  // off + no texture => stock path paints nothing
}
```

- [ ] **Step 2: Build and run the full renderer test suite**

Run: `cmake --build build -j && ctest --test-dir build -R BackdropPass --output-on-failure`
Expected: PASS (all backdrop tests, including the new parity test).

- [ ] **Step 3: Live A/B verification (manual, human gate)**

Run: `./build/dauntless` and load a mission with a nebula (e.g. an E1M1/Vesuvi system).
Verify, with the user observing (no synthetic input on the live workstation):
- Default (procedural on): varied starfield, a coloured living nebula in the authored direction, star-cloud dust bands where galaxy backdrops sit.
- Toggle off via `_dauntless_host.procedural_sky_set_enabled(False)`: reverts to the stock textured backdrop, identical to pre-change.
Record the outcome; do not claim success without the user's confirmation.

- [ ] **Step 4: Note the toggle in the findings doc**

Append a one-line pointer under the procedural-sky section of `docs/sector-cartography.md` (§7): "Procedural sky shipped on `feat/procedural-starfield` — Modern VFX toggle `procedural_sky_set_enabled`, default on."

- [ ] **Step 5: Commit**

```bash
git add native/tests/renderer/backdrop_pass_test.cc docs/sector-cartography.md
git commit -m "test(sky): toggle-off parity + verification notes"
```

---

## Self-Review

**Spec coverage:**
- Driven by recorded appearance data → Tasks 1–3 (bake, table, aggregation). ✓
- Nebulae as procedural texture on backdrop spheres → Task 5 (`proc_kind==2`). ✓
- Hash point-field stars → Task 5 (`proc_stars`, `proc_kind==0`). ✓
- Star clusters as Milky-Way bands (dust glow + dark lanes) → Task 5 (`proc_kind==1` star-cloud). ✓
- Subtle living motion → Task 5 (`u_time` twinkle + drift). ✓
- Modern VFX toggle, default on, byte-identical off → Tasks 4 (toggle/binding) + 6 (parity test). ✓
- HDR integration → automatic (pass already emits to `g_hdr_target`; no change needed). ✓
- Components/data contracts/testing/edge cases → covered across tasks; unknown-texture fallback in Task 3. ✓

**Deviation from spec (intentional simplification):** the spec §4 described attaching a `clusters[]` array to the star-sphere descriptor; the plan instead renders each `galaxy*` backdrop as its own independent **star-cloud patch** (`proc_kind==1`). Same end visual (dense star+dust bands at the galaxy directions), but decoupled — no cross-backdrop aggregation. Also: the recorded 5-colour `palette` is kept in the table/data but the shader tints from the single dominant `color` (palette gradient deferred, per spec §12 "intensity/sub-toggles future"). Both reduce complexity without changing the approved approach.

**Placeholder scan:** none — every code step has complete content.

**Type consistency:** `proc_kind` is a string in Python descriptors (`"stars"|"starcloud"|"nebula"`) mapped to int (0/1/2) in `set_backdrops`; the shader switches on the int. `color` is `[r,g,b]` 0–1 floats in Python → `glm::vec3` in C++ → `vec3 u_color`. `render(...)` signature (`+bool procedural, +float now_seconds`) matches between header, definition, and call site. Consistent.
