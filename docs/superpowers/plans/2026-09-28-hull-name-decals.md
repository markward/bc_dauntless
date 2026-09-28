# Hull Name Decals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render Federation registry names back onto patched stock hulls as model-space projected PNG decals. This first cut covers the Ambassador's top saucer only.

**Architecture:**
- A per-class `Masks/decals.json` declares the placements; each is a projector in the ship-body frame. Masks live in per-registry folders, e.g. `Masks/Zhukov/top.png`.
- Python resolves the registry (the stem of BC's `ReplaceTexture(..., "ID")` path) and the files, then passes a decal list to `load_model`.
- Native build puts the mask in the named shape's material `Decal0` stage, together with a projector matrix.
- `opaque.frag` projects `p_body`, replaces albedo under the mask's alpha, and adds a paint specular term.

**Tech Stack:** C++20 assets and renderer (GL 4.1 GLSL), pybind11 host binding, Python 3.11 stdlib plus Pillow, GoogleTest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-hull-name-decals-design.md`

## Global Constraints

- **Branch** `feat/hull-name-decals`, worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/hull-name-cut-fix`. **Never commit to `main`**; check `git branch --show-current` before each commit.
- **Banned git commands:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths only. To mutate a file temporarily, use a `cp` backup, a `cp` restore, then `diff`.
- **Never launch** `./build/dauntless`.
- **Build:** `cmake --build build -j` from the worktree root. C++ tests run with `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"`, and asset-backed tests must PASS, not SKIP.
- **Paths rule:** Python never spells `game` or `sdk` as a path segment, and never captures a path at import. Resolve BC-relative files with `engine.paths.game_asset(rel)`, which honours mods and project replacements and returns a Path without checking existence.
- **No numpy.** Masks are decoded natively with `assets::decode_image` (PNG or TGA).
- **Frame:** every decal vector is in the **ship-body frame**, the one `opaque.frag` reconstructs as `p_body = (u_ship_world_inv * vec4(v_position_ws,1)).xyz`: model space with all NIF node transforms applied, and the instance placement and scale removed.
- **Look (verbatim from spec §2):**
  - albedo `base.rgb = mix(base.rgb, mask.rgb, mask.a)`;
  - glow, emissive formula and normal map unchanged;
  - specular `+ mask.a × kDecalPaintSpecular (0.8) × paint_spec_acc`, computed even with no specular map, using the material's own specular power.
- **Texture unit 8** carries the decal mask in the opaque pass. Units 0–7 are taken.
- **Errors never throw out of a ship load** (spec §5 table). Each fault skips what it affects and logs once. A missing `decals.json` is silent.
- **Scope:** Ambassador, `top` placement only. The other masks are committed but not declared.
- **Final gate:** `scripts/check_tests.sh`, in the foreground. It must print "OK — no new failures" with no "NO BC CONTENT ROOT" banner.

## Review Focus

1. **Frame mismatch:** the generator's projector (from `nif_shapes` world space) must be in the same frame as the renderer's `p_body`, or the name lands in the wrong place. Task 3 pins this with a test that compares `nif_block_world` against the model's node chain for the saucer.
2. **A ship with several queued `"ID"` swaps** (a mission re-registers it): the last one must win, matching `registry_texture`'s last-write-wins. Task 2 pins this.
3. **Two instances of one class with different registries:** they must not share a model variant. Tasks 2 and 3 pin this with key tests.
4. **Mask sampling at the rectangle edge:** no derivative artefacts. Task 5 samples with `textureGrad` from gradients taken outside the branch, and its GL test checks both sides of the edge.
5. **A class with `decals.json` but a registry folder missing that placement's PNG:** the ship still loads, nameless. Task 2 pins this.

---

### Task 1: Masks into the branch, and the `decals.json` generator

**Files:**
- Copy in: the mask and template files from the main checkout into `native/assets/replacements/data/Models/Ships/Ambassador/Masks/` (see Step 1).
- Modify: `tools/gen_mesh_fixes.py`
- Create: `native/assets/replacements/data/Models/Ships/Ambassador/Masks/decals.json` (generated)
- Test: `tests/tools/test_gen_decals.py`

**Interfaces:**
- Consumes: `_dauntless_host.nif_shapes(path) -> list[dict]` (keys `block`, `name`, `textures`, `vertices` [world = ship-body frame], `normals`, `uvs`, `triangles`, `hidden`), and the existing `fnv1a64_hex`, `to_f32`.
- Produces:
  ```python
  DECAL_CLASSES: dict[str, dict]  # e.g. {"Ambassador": {"nif": "data/Models/Ships/Ambassador/Ambassador.nif",
                                   #   "id_texture": "data/Models/Ships/Ambassador/High/AmbassadorSaucerID_glow.tga",
                                   #   "reference_registry": "data/Models/Ships/Ambassador/High/Zhukov.tga",
                                   #   "reference_mask": "data/Models/Ships/Ambassador/Masks/Zhukov/top.png",
                                   #   "target_shape": "amb saucer:0", "placement": "top"}}
  def fit_plane_st(points, sts) -> dict      # {"origin","s_axis","t_axis","normal","st_origin"} affine plane map s,t -> p
  def lettering_bbox(ref_rgba, base_rgba) -> tuple[float,float,float,float]   # (s0,t0,s1,t1) normalised, changed-pixel box
  def alpha_bbox(mask_rgba) -> tuple[float,float,float,float]                # normalised, alpha>0 box
  def build_decal(shapes, cls_cfg, ref_img, base_img, mask_img) -> dict      # one decals.json "decals" entry
  def decals_json(entries: dict) -> str                                      # json.dumps({"format":1,"decals":entries}, indent=2)+"\n"
  ```

- [ ] **Step 1: Bring Mark's masks onto the branch.** Mark's masks exist only in the main checkout, untracked. Copy them; don't move them:
  ```bash
  mkdir -p native/assets/replacements/data/Models/Ships/Ambassador/Masks
  cp -R /Users/mward/Documents/Projects/bc_dauntless/native/assets/replacements/data/Models/Ships/Ambassador/Masks/Zhukov /Users/mward/Documents/Projects/bc_dauntless/native/assets/replacements/data/Models/Ships/Ambassador/Masks/Excalibur /Users/mward/Documents/Projects/bc_dauntless/native/assets/replacements/data/Models/Ships/Ambassador/Masks/templates native/assets/replacements/data/Models/Ships/Ambassador/Masks/
  find native/assets/replacements/data/Models/Ships/Ambassador/Masks -name .DS_Store -delete
  ```
  Expected: `Zhukov/` and `Excalibur/` hold `top`, `bottom`, `nacelle` and `pylon.png`, all 128×64 for `top`; `templates/` holds 4 SVGs.

- [ ] **Step 2: Write failing tests** in `tests/tools/test_gen_decals.py`. They're synthetic, with no BC content:
  ```python
  import pytest
  from tools import gen_mesh_fixes as g

  def _plane_patch():
      # flat patch in z=5, s = 0.1 + x/200, t = 0.2 + y/100 (x in [-50,50], y in [0,60])
      pts, sts = [], []
      for x in (-50, 0, 50):
          for y in (0, 30, 60):
              pts.append((float(x), float(y), 5.0))
              sts.append((0.1 + x / 200.0, 0.2 + y / 100.0))
      return pts, sts

  def test_fit_plane_st_inverts_exactly():
      pts, sts = _plane_patch()
      f = g.fit_plane_st(pts, sts)
      # the point at (s,t)=(0.1,0.2) is x=0,y=0,z=5
      p = [f["origin"][k] + 0.0 for k in range(3)]
      assert p == pytest.approx([0.0, 0.0, 5.0], abs=1e-6)
      assert f["s_axis"] == pytest.approx([200.0, 0.0, 0.0], abs=1e-4)   # d p / d s
      assert f["t_axis"] == pytest.approx([0.0, 100.0, 0.0], abs=1e-4)
      assert abs(f["normal"][2]) == pytest.approx(1.0, abs=1e-6)

  def test_lettering_and_alpha_bboxes():
      from PIL import Image
      base = Image.new("RGBA", (10, 10), (100, 100, 100, 255))
      ref = base.copy(); ref.putpixel((2, 3), (0, 0, 0, 255)); ref.putpixel((7, 5), (0, 0, 0, 255))
      assert g.lettering_bbox(ref, base) == pytest.approx((0.2, 0.3, 0.8, 0.6))
      m = Image.new("RGBA", (20, 10), (0, 0, 0, 0)); m.putpixel((4, 2), (0, 0, 0, 255)); m.putpixel((15, 7), (0, 0, 0, 255))
      assert g.alpha_bbox(m) == pytest.approx((0.2, 0.2, 0.8, 0.8))

  def test_build_decal_centres_and_scales_on_bc_lettering(monkeypatch):
      pts, sts = _plane_patch()
      patch = {"block": 2, "name": "idpatch", "textures": ["X_ID_glow.tga"], "vertices": pts,
               "normals": [(0.0, 0.0, 1.0)] * len(pts), "uvs": sts, "triangles": [(0, 1, 4)], "hidden": False}
      target = {"block": 1, "name": "saucer", "textures": ["X_glow.tga"], "vertices": [(0.0, 0.0, 5.0)],
                "normals": [(0.0, 0.0, 1.0)], "uvs": [(0.0, 0.0)], "triangles": [], "hidden": False}
      from PIL import Image
      base = Image.new("RGBA", (100, 100), (100, 100, 100, 255))
      ref = base.copy()
      for x in range(20, 61):          # BC lettering box s 0.2..0.6, t 0.3..0.5 (normalised to pixel edges)
          for y in range(30, 51):
              ref.putpixel((x, y), (0, 0, 0, 255))
      mask = Image.new("RGBA", (128, 64), (0, 0, 0, 0))
      for x in range(32, 97):          # mask lettering box u 0.25..0.75, v 0.25..0.75
          for y in range(16, 49):
              mask.putpixel((x, y), (0, 0, 0, 255))
      cfg = {"target_shape": "saucer", "placement": "top"}
      d = g.build_decal([target, patch], cfg, ref, base, mask)
      assert d["shape"] == "saucer"
      s0, t0, s1, t1 = g.lettering_bbox(ref, base)
      u0, v0, u1, v1 = g.alpha_bbox(mask)
      O, U, V = d["origin"], d["u_axis"], d["v_axis"]
      def at(a, b):
          return [O[k] + a * U[k] + b * V[k] for k in range(3)]
      # Mask lettering centre lands on BC lettering centre (plane: x=(s-0.1)*200, y=(t-0.2)*100, z=5)
      sc, tc = (s0 + s1) / 2, (t0 + t1) / 2
      assert at((u0 + u1) / 2, (v0 + v1) / 2) == pytest.approx(
          [(sc - 0.1) * 200.0, (tc - 0.2) * 100.0, 5.0], abs=1e-3)
      # Uniform scale: mask lettering width == BC lettering width on the hull
      ulen = sum(x * x for x in U) ** 0.5
      vlen = sum(x * x for x in V) ** 0.5
      assert ulen * (u1 - u0) == pytest.approx((s1 - s0) * 200.0, rel=1e-4)
      # 128x64 mask keeps square pixels: |U| / |V| == 2
      assert ulen / vlen == pytest.approx(2.0, rel=1e-6)
      # V runs down the image = +t direction here; normal faces +z like the patch normals
      assert V[1] > 0 and d["normal"] == pytest.approx([0.0, 0.0, 1.0], abs=1e-6)

  def test_decals_json_is_deterministic():
      e = {"top": {"shape": "s", "origin": [0.0, 0.0, 0.0], "u_axis": [1.0, 0.0, 0.0],
                   "v_axis": [0.0, 1.0, 0.0], "normal": [0.0, 0.0, 1.0], "depth": 2.0}}
      assert g.decals_json(e) == g.decals_json(e) and g.decals_json(e).endswith("\n")

  def test_build_decal_refuses_missing_target_shape():
      pts, sts = _plane_patch()
      patch = {"block": 2, "name": "idpatch", "textures": ["X_ID_glow.tga"], "vertices": pts,
               "normals": [(0.0, 0.0, 1.0)] * len(pts), "uvs": sts, "triangles": [], "hidden": False}
      from PIL import Image
      img = Image.new("RGBA", (4, 4))
      with pytest.raises(ValueError):
          g.build_decal([patch], {"target_shape": "nope", "placement": "top"}, img, img, img)
  ```

- [ ] **Step 3: Run them and watch them fail**

Run: `uv run pytest tests/tools/test_gen_decals.py -q`
Expected: AttributeError, because the functions don't exist yet.

- [ ] **Step 4: Implement** in `tools/gen_mesh_fixes.py`:
  - **`fit_plane_st`:**
    1. Least-squares `p = O + s·S + t·T` (solve each coordinate of p as affine in (s,t) with a 3-unknown normal-equation solve; reuse the module's Gaussian elimination).
    2. `normal` = normalised `S × T`, flipped if it disagrees with the mean patch vertex normal (pass the normals in as an optional argument).
    3. `st_origin` = (0,0).
  - **`lettering_bbox`:** pixels where max |ΔRGB| > 24 or |ΔA| > 24. The box spans pixel edges, normalised by width and height: `(min_x/W, min_y/H, (max_x+1)/W, (max_y+1)/H)`.
  - **`alpha_bbox`:** the same over alpha > 8.
  - **`build_decal`** works in ship-body units throughout. Put this recipe in its docstring:
    1. The patch is the only shape with a texture basename containing `ID`. Raise `ValueError` if there isn't exactly one, or if `cfg["target_shape"]` names no shape.
    2. Fit on the patch's `vertices`/`uvs` with its `normals`: `P(s,t) = O + s·S + t·T`.
    3. BC's box `(s0,t0,s1,t1)` comes from `lettering_bbox`, and the mask box `(u0,v0,u1,v1)` from `alpha_bbox`. Centres: `sc,tc` and `uc,vc`.
    4. `U = S · (s1-s0)/(u1-u0)`, the ship-body vector for one full mask width. Uniform scale: the mask lettering width equals BC's lettering width.
    5. `V = normalise(T − (T·Û)Û) · |U| · (mask_h / mask_w)`. It's perpendicular to U, in the same sense as T, and keeps the mask's pixels square.
    6. `origin = P(sc, tc) − uc·U − vc·V`, which puts the mask lettering centre on BC's.
    7. Return `{"shape": cfg["target_shape"], "origin": origin, "u_axis": U, "v_axis": V, "normal": plane normal, "depth": 2.0}`, all floats passed through `to_f32`.
  - **`decals_json`:** deterministic `json.dumps(..., indent=2) + "\n"`.
  - **CLI:** add `--decals`. For each `DECAL_CLASSES` entry, load the NIF via `nif_shapes(str(paths.game_root() / nif))`. Load the two BC textures via `paths.game_root() / rel`; load the reference mask via `paths.game_asset(rel)` (project replacement). Then write `native/assets/replacements/data/Models/Ships/<Class>/Masks/decals.json`. `--decals` and `--write` are independent.

- [ ] **Step 5: Run the tests, then generate the file**

Run: `uv run pytest tests/tools/test_gen_decals.py -q` → PASS.
Run: `uv run python tools/gen_mesh_fixes.py --decals`

Sanity check the generated `top` entry:
- `normal` z > 0.9 (the saucer top faces +z);
- the rectangle's centre lies within the old patch's x/y bounds (x ∈ [−86, 86], y ∈ [129, 244]);
- `|u_axis|` roughly 60–170 model units (BC's lettering width).

Record the numbers in the report.

- [ ] **Step 6: Commit**
  ```bash
  git add tools/gen_mesh_fixes.py tests/tools/test_gen_decals.py native/assets/replacements/data/Models/Ships/Ambassador/Masks
  git commit -m "feat(tools): Ambassador registry masks + generated top-saucer decals.json"
  ```

---

### Task 2: Python decal resolution and wiring into model loads

**Files:**
- Create: `engine/appc/hull_decals.py`
- Modify: `engine/host_loop.py` (`_ship_load_key` around 5150; the two `load_model` call sites near 5632 and 6696)
- Modify: `engine/renderer.py:168-174` (`load_model` gains `decals=None`)
- Test: `tests/unit/test_hull_decals.py`

**Interfaces:**
- Consumes: `engine.appc.registry_texture.replacements_for(ship) -> [(old, new_path)]`; `engine.paths.game_asset(rel) -> Path`.
- Produces:
  ```python
  # engine/appc/hull_decals.py
  DecalSpec = tuple[str, tuple, tuple, tuple, tuple, float, str]
  #           (shape, origin, u_axis, v_axis, normal, depth, mask_abs_path)
  def registry_stem(replacements) -> str | None     # stem of the LAST ("ID", path) entry, e.g. "Zhukov"
  def decals_for(nif_rel_dir: str, registry: str | None) -> list[DecalSpec]
  # engine/renderer.py
  def load_model(nif_path, texture_search_path, texture_replacements=None, decals=None) -> int
  ```
  `renderer.load_model` forwards `decals` to `_h.load_model(nif_path, search, reps, decals)`; Task 4 adds that parameter to the binding. Until then, pass `decals` only when it's non-empty, so nothing breaks between tasks.

- [ ] **Step 1: Failing tests** (`tests/unit/test_hull_decals.py`). Use `tmp_path` plus monkeypatching of `engine.paths.game_asset` to point `data/Models/Ships/X/Masks/...` at a temp tree. Write the temp `decals.json` and a 2×1 PNG with Pillow.
  - `registry_stem([("ID", "Data/Models/Ships/Ambassador/Zhukov.tga")]) == "Zhukov"`;
  - last-wins with two ID entries;
  - `None` with no ID entry;
  - `decals_for` returns one spec with the absolute mask path when `decals.json` declares `top` and `Zhukov/top.png` exists;
  - it returns `[]` silently when `decals.json` is missing;
  - it returns `[]` plus exactly one warning line (capture with `capsys`, and call twice to prove once) when the JSON is malformed or `format` ≠ 1;
  - a declared placement with no PNG is skipped (one line), and other placements still load;
  - a degenerate projector (u_axis parallel to v_axis) is skipped;
  - `registry is None` → `[]`.
  - **Key test:** `_ship_load_key(nif, reps, decals)` differs for Zhukov and Excalibur decal lists and is stable for equal lists.

- [ ] **Step 2: Run and watch them fail.** `uv run pytest tests/unit/test_hull_decals.py -q` → ImportError.

- [ ] **Step 3: Implement `engine/appc/hull_decals.py`.**
  - Resolve `f"{nif_rel_dir}/Masks/decals.json"` and `f"{nif_rel_dir}/Masks/{registry}/{placement}.png"` through `paths.game_asset` at call time.
  - Warn once per (path, reason) with a module-level set. `reset()` clears it, and it's registered in `tests/conftest.py`'s `_reset_leakable_engine_globals` the way `registry_texture.reset` is (find it there and follow the pattern).
  - Validate vectors: 3 floats each, finite; `|u×v| > 1e-9`; depth > 0.

- [ ] **Step 4: Wire it in.**
  - At both `host_loop` call sites, compute the NIF's BC-relative directory (follow the existing `nif_dir.relative_to(_paths.game_root()).as_posix()` pattern in `_ship_texture_search`; if that raises ValueError, the path came from a mod overlay: use `None` and skip decals).
  - Compute `decals = hull_decals.decals_for(nif_rel_dir, hull_decals.registry_stem(reps or []))`.
  - Pass `decals` to `_ship_load_key(nif_path, reps, decals)` and to `r_.load_model(nif_path, tex_search, reps, decals=decals or None)`.
  - `_ship_load_key` appends `"|decals:" + ";".join(mask_path for each)` when there are decals, so the existing keys are byte-identical when there aren't.

- [ ] **Step 5: Run the tests and the host-loop suite**

Run: `uv run pytest tests/unit/test_hull_decals.py tests/unit -q -k "hull_decals or load_key or registry"` → PASS.
Run: `uv run pytest tests/unit/test_path_indirection.py -q` → PASS.

- [ ] **Step 6: Commit**
  ```bash
  git add engine/appc/hull_decals.py engine/host_loop.py engine/renderer.py tests/unit/test_hull_decals.py tests/conftest.py
  git commit -m "feat(decals): resolve registry masks from decals.json and pass them to load_model"
  ```

---

### Task 3: Native decal stage and projector in `build_model`

**Files:**
- Modify: `native/src/assets/include/assets/model.h` (add `DecalRequest`)
- Modify: `native/src/assets/include/assets/material.h` (add `DecalProjector` to `Material`)
- Modify: `native/src/assets/include/assets/cache.h`, `native/src/assets/src/cache.cc` (a `load` overload taking decals, and the key)
- Modify: `native/src/assets/src/model_build.cc` (apply decals after materials are built)
- Test: `native/tests/assets/cpu/decal_build_test.cc` (register it in `native/tests/assets/CMakeLists.txt`)

**Interfaces:**
- Produces:
  ```cpp
  // model.h
  struct DecalRequest {
      std::string shape;                 // NIF shape name (NiTriShape av.obj.name)
      glm::vec3 origin, u_axis, v_axis, normal;
      float depth = 0.0f;
      std::filesystem::path mask;        // absolute path to PNG/TGA
  };
  // material.h (inside Material)
  struct DecalProjector {
      bool      enabled = false;
      glm::mat4 body_to_mask{1.0f};      // p_body -> (u, v, w, 1); w = signed distance along unit normal
      glm::vec3 normal{0, 0, 1};         // unit, ship-body frame
      float     depth = 0.0f;
  };
  DecalProjector decal;                  // texture in stages[StageSlot::Decal0]
  // cache.h
  ModelHandle load(const std::filesystem::path& nif,
                   const std::vector<std::filesystem::path>& search,
                   const std::vector<TextureReplacement>& reps,
                   const std::vector<DecalRequest>& decals);
  // detail (model_build): ModelBuildContext::decals (std::vector<DecalRequest>)
  // free function, exposed for tests in the detail header model_build uses:
  glm::mat4 decal_body_to_mask(const glm::vec3& origin, const glm::vec3& u_axis,
                               const glm::vec3& v_axis, const glm::vec3& normal);
  ```
  The existing 3-argument `load` forwards with an empty decals vector, so there's no behaviour change.

- [ ] **Step 1: Failing tests** (`decal_build_test.cc`). Follow `model_build_test.cc`'s helpers (`stub_texture`, `stub_mesh`, `make_ctx`) and its minimal-file builders:
  - `DecalProjector, MapsCornersToUnitSquare`: `decal_body_to_mask` maps `origin` → (0,0,0), `origin+u` → (1,0,0), `origin+v` → (0,1,0), and `origin + 3·n̂` → (0,0,3).
  - `DecalBuild, AttachesToNamedShapeOnly`: a synthetic 2-shape file, with a decal naming shape "a" and a real temp PNG (write one with `stbi_write_png`, or embed the 2×1 PNG bytes from `texture_decode_test.cc` into a temp file). Shape "a"'s material has `stages[Decal0].texture_index >= 0` and `decal.enabled`; shape "b" has neither.
  - `DecalBuild, SkipsUnknownShapeMissingMaskAndDegenerate`: each case builds successfully with no material enabled.
  - `DecalCache, RegistriesAreSeparateEntries`: asset-backed on the real Ambassador (skip if absent). Two loads with different mask paths return different handles; the same path returns the same handle.
  - **Frame agreement, `DecalFrame, NifBlockWorldMatchesModelNodeChain`** (asset-backed, Ambassador): for the shape `amb saucer:0`, compose `model.nodes` local transforms from the root down to the node owning that shape's mesh. It must equal `assets::nif_block_world(file, shape_block)` to within 1e-4. (That's the frame `nif_shapes` gives the generator; this proves it's the renderer's model frame.) If they differ, **stop and report BLOCKED** with both matrices.

- [ ] **Step 2: Run and watch them fail.** Build → compile errors on the missing types.

- [ ] **Step 3: Implement.**
  - **`decal_body_to_mask`:**
    1. `n̂ = normalize(normal)`;
    2. `B` = the 3×3 matrix with columns `u_axis, v_axis, n̂`;
    3. `M = inverse(B)`;
    4. `body_to_mask = [M | −M·origin]`.
  - **In `build_model`**, after all materials are built:
    - map each NiTriShape's `av.obj.name` to its material index(es), recorded during the shape loop;
    - for each request:
      1. skip + warn once if the shape is unknown or the projector is degenerate (`|u×v| < 1e-9`);
      2. read and decode the mask with `decode_image`;
      3. `upload(img, /*mipmaps=*/true)` and push it to `model.textures`;
      4. set `stages[Decal0].texture_index` and `clamp_mode` (clamp-to-edge);
      5. fill `decal`.

      A decode failure → skip + warn once.
  - **In `cache.cc`,** append `"|decals:" + joined mask paths + shape names` to the key when decals are present.

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" ./build/native/tests/assets/assets_tests --gtest_filter='Decal*'` → all PASS, none SKIP.

- [ ] **Step 5: Commit**
  ```bash
  git add native/src/assets/include/assets/model.h native/src/assets/include/assets/material.h native/src/assets/include/assets/cache.h native/src/assets/src/cache.cc native/src/assets/src/model_build.cc native/tests/assets/cpu/decal_build_test.cc native/tests/assets/CMakeLists.txt
  git commit -m "feat(assets): Decal0 stage + ship-body projector on the named shape's material"
  ```

---

### Task 4: Host binding accepts decals

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`load_model_impl` near 504, its dedupe key near 527–550, `m.def("load_model", ...)` near 1814)
- Modify: `engine/renderer.py` (always forward `decals`)
- Test: `tests/host/test_load_model_decals.py`

**Interfaces:**
- Consumes: Task 3's `AssetCache::load(..., decals)`, and Task 2's `DecalSpec` tuple shape.
- Produces: `_dauntless_host.load_model(nif_path, search, texture_replacements=None, decals=None) -> int`. Each decal is a 7-sequence `(shape, origin3, u3, v3, n3, depth, mask_path)`. The dedupe key includes the decals.

- [ ] **Step 1: Failing test** (`tests/host/test_load_model_decals.py`, asset-backed; skip if the Ambassador or its masks are absent, resolving via `paths.game_root()` and `paths.game_asset`). It needs a host init/shutdown fixture: find how the other `tests/host` tests that call `load_model` set up the host, and reuse it. Assertions:
  - `load_model` with the Zhukov decal and with the Excalibur decal returns **different** handles;
  - calling it again with Zhukov returns the first handle;
  - calling it with `decals=None` returns a third, distinct handle.

- [ ] **Step 2: Run and watch it fail** (a TypeError on the extra argument).

- [ ] **Step 3: Implement.**
  - Parse the list into `std::vector<assets::DecalRequest>`.
  - Extend the dedupe key with `"|decals:" + shape + '=' + mask + ';'` per decal.
  - Call the 4-argument cache `load`.
  - Bind with `py::arg("decals") = py::none()`.
  - `renderer.load_model` now always forwards `decals`.

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && uv run pytest tests/host/test_load_model_decals.py tests/unit/test_hull_decals.py -q` → PASS.

- [ ] **Step 5: Commit**
  ```bash
  git add native/src/host/host_bindings.cc engine/renderer.py tests/host/test_load_model_decals.py
  git commit -m "feat(host): load_model accepts hull decals; dedupe key includes them"
  ```

---

### Task 5: Draw — bind the mask, and the `opaque.frag` albedo + paint specular

**Files:**
- Modify: `native/src/renderer/frame.cc` (the opaque per-mesh bind loop around 703–813)
- Modify: `native/src/renderer/shaders/opaque.frag` (uniforms; albedo after `base` is sampled near 1130; paint specular alongside the spec loops near 1184 and 1269; final composition near 1321)
- Test: `native/tests/renderer/decal_render_test.cc` (register it with renderer_tests)

**Interfaces:**
- Consumes: `Material::decal`, `stages[Decal0]`.
- Produces: uniforms `u_decal_mask` (sampler2D, unit 8), `u_decal_mask_enabled` (int), `u_decal_proj` (mat4), `u_decal_normal` (vec3), `u_decal_depth` (float); the shader constant `const float kDecalPaintSpecular = 0.8;`.

- [ ] **Step 1: Failing GL test** (`decal_render_test.cc`), modelled on `native/tests/renderer/frame_test.cc`'s `FrameTest` (the headless `renderer::Window(256,256,"decal-test",false)`, `Pipeline`, `FrameSubmitter::submit_opaque`, `glReadPixels`). Skip when no GL context or no BC content.
  - Load the real Ambassador twice through an `AssetCache`: once plain, and once with one decal whose mask is a **solid opaque pure-red PNG** written to a temp file. Its projector spans the whole saucer top: take `u_axis`/`v_axis` from the model's AABB x/y extents, `origin` at the min corner at top-z, `normal` = +z, and `depth` = the AABB z extent.
  - Render each with a camera straight above (eye = (0,0,+big), target = the origin, up = +y) and read back the full 256×256.
  - Assert:
    - (a) the decal render has more than 200 "red-dominant" pixels (r > 2·g and r > 2·b);
    - (b) the plain render has fewer than 10;
    - (c) `glGetError() == GL_NO_ERROR`.
  - A second test, **orientation** (it pins mask row 0 = the top of the image):
    - Use a mask whose top half is pure red and bottom half pure blue.
    - The projector: `origin` = (xmin, ymax, ztop), `u_axis` = (+width, 0, 0), `v_axis` = (0, −height, 0) (mask v runs down, toward −y), `normal` = +z.
    - Use the same camera, looking down with up = +y.
    - Assert that the mean screen row of the red-dominant pixels is nearer the top of the image than that of the blue-dominant ones. `glReadPixels` row 0 is the **bottom**, so red's mean row index is the larger.
    - A flipped v fails this test.
  - The paint specular term isn't asserted headless. It's checked in Mark's live look.

- [ ] **Step 2: Run and watch it fail.** (No red pixels appear, because nothing binds the mask yet.)

- [ ] **Step 3: Implement.**
  - **`frame.cc`**, per mesh:
    - if `mat.decal.enabled && stages[Decal0].texture_index >= 0`: `glActiveTexture(GL_TEXTURE8)`, bind that texture, `set_int("u_decal_mask", 8)`, `set_int("u_decal_mask_enabled", 1)`, `set_mat4("u_decal_proj", mat.decal.body_to_mask)`, `set_vec3("u_decal_normal", ...)`, `set_float("u_decal_depth", ...)`;
    - else `set_int("u_decal_mask_enabled", 0)`, and bind the black fallback on unit 8 so the sampler is never unbound.
    - Follow the existing unit-1/2/4 patterns exactly, including the fallback-texture idiom.
  - **`opaque.frag`:**
    - Declare the uniforms and `kDecalPaintSpecular`.
    - Right after `p_body` and `n_body` are computed (near 1129), **outside any branch**: `vec3 dpdx_d = dFdx(p_body), dpdy_d = dFdy(p_body);`
    - After `base` is sampled (near 1130):
      ```glsl
      float decal_a = 0.0;
      if (u_decal_mask_enabled != 0) {
          vec4 q = u_decal_proj * vec4(p_body, 1.0);
          if (q.x >= 0.0 && q.x <= 1.0 && q.y >= 0.0 && q.y <= 1.0 &&
              abs(q.z) <= u_decal_depth && dot(n_body, u_decal_normal) > 0.0) {
              vec2 gx = (mat3(u_decal_proj) * dpdx_d).xy;
              vec2 gy = (mat3(u_decal_proj) * dpdy_d).xy;
              vec4 m = textureGrad(u_decal_mask, q.xy, gx, gy);
              base.rgb = mix(base.rgb, m.rgb, m.a);
              decal_a = m.a;
          }
      }
      ```
      Mask image row 0 is the top. Check the upload's row order (whether `upload_image` flips) and flip `q.y` (`1.0 - q.y`) if needed. The orientation test from Step 1 decides this.
    - Paint specular: inside the directional and dynamic light loops, **also** when `decal_a > 0.0` (regardless of `u_specular_enabled`), accumulate `paint_spec_acc` with the same `H`/`pow(…, spec_power)`/`spec_norm` terms. Where the code computes `spec`, add `+ decal_a * kDecalPaintSpecular * paint_spec_acc`.
    - Leave the glow, emissive and normal paths untouched.

- [ ] **Step 4: Build and run.** Shader edits need the reconfigure the project notes require: `cmake -B build -S . -DPython3_EXECUTABLE=/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/hull-name-cut-fix/.venv/bin/python3 && cmake --build build -j`, then run the `decal_render_test` binary filter with `DAUNTLESS_GAME_DIR` set → PASS. Also run the full `renderer_tests` once; nothing else should change.

- [ ] **Step 5: Commit**
  ```bash
  git add native/src/renderer/frame.cc native/src/renderer/shaders/opaque.frag native/tests/renderer/decal_render_test.cc native/tests/renderer/CMakeLists.txt
  git commit -m "feat(render): opaque pass draws hull decal masks with paint specular"
  ```

---

### Task 6: End to end, docs and gate

**Files:**
- Modify: `CLAUDE.md` (a reference-table row after the hull name-cut row)
- Test: `tests/integration/test_hull_decals_e2e.py` (or the closest existing integration folder)

- [ ] **Step 1: End-to-end test** (asset-backed; skip without content). Through the real Python path (`hull_decals.decals_for` with the committed `decals.json` + `Zhukov/top.png`, then `renderer.load_model`), load the Ambassador with the Zhukov registry queued by `registry_texture.apply_class_default`. Assert:
  - the returned decal list has exactly one entry, shape `amb saucer:0`;
  - `load_model` returns a handle distinct from a no-registry load.

  Use the host fixture from Task 4.

- [ ] **Step 2: CLAUDE.md row:**
  ```
  | Hull name decals — registry masks projected in the ship-body frame | `engine/appc/hull_decals.py`, `native/src/assets/src/model_build.cc` (Decal0), `native/src/renderer/shaders/opaque.frag`, `native/assets/replacements/data/Models/Ships/<Class>/Masks/`, `docs/superpowers/specs/2026-09-28-hull-name-decals-design.md` | Names on patched Fed hulls. `ReplaceTexture(".../Zhukov.tga","ID")` → registry `Zhukov` → `Masks/Zhukov/<placement>.png` for each placement DECLARED in `Masks/decals.json` (the JSON is the authority on which decals exist and where; generated once by `tools/gen_mesh_fixes.py --decals`, then hand-editable). Mask REPLACES albedo; glow/emissive/normal unchanged (windows glow through letters, by design); paint specular `kDecalPaintSpecular` 0.8 under the mask. Vectors are SHIP-BODY frame (`p_body`). Mask on texture unit 8. Only the Ambassador has masks so far. |
  ```

- [ ] **Step 3: Full gate.** Run `scripts/check_tests.sh` in the foreground. It must end "OK — no new failures", with no content-root banner.

- [ ] **Step 4: Commit**
  ```bash
  git add CLAUDE.md tests/integration/test_hull_decals_e2e.py
  git commit -m "test(decals): Ambassador Zhukov end to end; CLAUDE.md row"
  ```

---

## After the plan

Mark's live check:
- a QuickBattle Ambassador (Zhukov): the name sits where BC drew it, glossy, with windows glowing through;
- the `E3M1` USS Excalibur, loaded via the developer mission picker.
