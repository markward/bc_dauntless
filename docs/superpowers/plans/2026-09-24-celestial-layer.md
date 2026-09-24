> **SUPERSEDED** by `docs/superpowers/specs/2026-09-24-system-frames-design.md`.
> Kept as the record of how the design got here. Several decisions below are
> reversed there — see its "Decisions this reverses". Do not implement from
> this document.

# Celestial layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standing anywhere in a BC star system, see that system — its star in a
consistent direction, its other worlds at their true bearings and distances, at
the sizes the checked-in maps specify.

**Architecture:** A set name resolves to a system through the checked-in maps, or
it does not and nothing changes. Entering a system creates every one of its
regions and stops `DeleteSet` firing within it, so the other worlds are real
objects rather than pictures. Each region's bodies take the map's radius and
position when its set is created. The renderer's far plane rises from 5,000 to
500,000 GU so the sky is drawable at all, and body render data is gathered from
every resident region, shifted by the difference between its anchor and the
player's.

**Tech Stack:** Python 3 (`engine/`), C++ (`native/src/renderer/`), `uv run
pytest`, `scripts/check_tests.sh`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-celestial-layer-design.md`
(implements §2, §4 and the first half of §3 of
`docs/superpowers/specs/2026-09-22-in-system-navigation-design.md`)

## Global Constraints

- **Never spell `game` or `sdk` as a path segment** in `engine/`, `tools/`,
  `tests/conftest.py` or `native/src`. Ask `paths.game_asset(rel)`,
  `paths.sdk_scripts()`. Enforced by `tests/unit/test_path_indirection.py`,
  which parses rather than greps.
- **Never capture a path at import time** in `engine/`. `paths.configure()` is
  callable again after boot, so a module-level path constant is stale the moment
  the first-run picker changes a root.
- **One build tree**, `<project-root>/build/`. Build with
  `cmake -B build -S . && cmake --build build -j`. **Never run `cmake` from
  inside `native/`.** The host binary is `build/dauntless`.
- **Shader and CMake-visible changes need a reconfigure**, not just a rebuild.
- **`validate()` never raises.** Untouched by this plan, but do not make it a
  liar in passing.
- **Shared checkout.** Stage with an explicit pathspec. Never `git add -A`,
  `git add .`, `git checkout -- <path>`, `git restore`, `git stash`,
  `git clean`, `git reset --hard`. To mutate a file temporarily: `cp` to
  `/tmp`, edit, restore by `cp`, `diff` to prove it.
- **Gate with `scripts/check_tests.sh`**, never `run_tests.sh` alone. Expect
  `OK — no new failures. 1 known failure(s) still baselined.`
  `tests/unit/test_decal_emission.py::test_dent_weight_reaches_the_decal` is a
  known non-deterministic flake, deliberately NOT baselined — if it appears,
  re-run to confirm and do not add it to the ledger.
- **Do not regenerate any map.** `git status --porcelain engine/systems/maps`
  must stay empty for this entire plan.
- **Never launch the game.** Live verification is the user's, not yours.

## The numbers this plan turns on

Measured from the committed maps, not assumed:

| | |
|---|---|
| Exterior camera far plane today | 5,000 GU (`host_loop.py:9661`) |
| Widest sightline in the game | **452,715 GU** (Itari) |
| Ona 1's own planet, from its anchor | 5,997 GU — **already outside the frustum** |
| Ona 2 and Ona 3, from Ona 1 | 93,538 and 96,211 GU, 2.2° and 2.1° across |
| Depth precision cost of far 5,000 → 500,000 | **0.02%** |

## File Structure

| File | Responsibility |
|---|---|
| `engine/systems/resolve.py` | **Create.** Set name → (system, region), built once from the checked-in maps. |
| `engine/host_loop.py` | **Modify.** Far planes; `_live_sets()` scope; celestial gathering. |
| `engine/systems/residency.py` | **Create.** Which system is live; create its regions; tear it down. |
| `engine/appc/warp.py` | **Modify.** Suppress `DeleteSet` on departure within a system. |
| `native/src/renderer/sun_pass.cc` | **Modify.** Virtual distance becomes conditional. |
| `native/src/renderer/lens_flare_pass.cc` | **Modify.** Same. |
| `engine/dev_missions/system_preview.py` | **Create.** A developer mission that drops the player into a chosen region. |

---

### Task 1: Resolve a set name to its system and region

**Files:**
- Create: `engine/systems/resolve.py`
- Test: `tests/unit/test_system_resolve.py`

**Interfaces:**

- Produces `for_set(set_name: str) -> tuple | None` — `(SystemMap, Region)` when
  that set is a region of a checked-in map, else `None`.
- Produces `system_of(set_name: str) -> str | None` — the system's name only.
- Produces `regions_of(system: str) -> list[str]` — every region set name in
  that system, in map order.
- The index is built once from `engine.systems.map.available()` / `load()` and
  cached with `functools.lru_cache`, plus a `reset_cache()` for tests.
- **Never capture a path at import.** `map_dir()` is computed per call and the
  cache must be built lazily on first use, never at module import.
- Case-sensitive: BC's set names are exact (`Ona1`, not `ona1`).

**Ruling to implement, not to revisit:** a set absent from every map resolves to
`None` and its caller behaves exactly as today. That covers the bridge,
QuickBattle arenas, and the seven single-set multiplayer systems, whose maps
carry zero regions.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_region_resolves_to_its_system_and_region():
    m, r = resolve.for_set("Ona1")
    assert m.system == "Ona"
    assert r.set_name == "Ona1"
    assert r.anchor_gu != (0.0, 0.0, 0.0)


def test_every_region_of_every_map_resolves():
    """The index must cover the whole tree, not just the systems a test names."""
    for name in available():
        m = load(name)
        for r in m.regions:
            got = resolve.for_set(r.set_name)
            assert got is not None, r.set_name
            assert got[0].system == m.system


def test_a_set_that_is_not_a_region_resolves_to_nothing():
    for name in ("bridge", "QuickBattle", "Multi5", "", "ona1"):
        assert resolve.for_set(name) is None


def test_regions_of_lists_the_whole_system():
    assert sorted(resolve.regions_of("Ona")) == ["Ona1", "Ona2", "Ona3"]
    assert resolve.regions_of("Nowhere") == []


def test_vesuvi_has_three_regions_and_the_cloud_is_innermost():
    """Vesuvi1 is an orphan BC never lists and the layout no longer places it.
    Vesuvi4 -- the dust cloud -- is BC's first listed place and must be first."""
    import math
    names = resolve.regions_of("Vesuvi")
    assert names == ["Vesuvi4", "Vesuvi5", "Vesuvi6"]
    m = load("vesuvi")
    first = m.region("Vesuvi4")
    assert all(math.dist(first.anchor_gu, (0, 0, 0))
               <= math.dist(m.region(n).anchor_gu, (0, 0, 0)) for n in names)
```

- [ ] **Step 2: Run them and confirm they fail** —
`uv run pytest tests/unit/test_system_resolve.py -v`

- [ ] **Step 3: Implement** per the Interfaces block.

- [ ] **Step 4: Run the tests and confirm they pass**, then
`uv run pytest tests/unit/ -q` and report the count.

- [ ] **Step 5: Commit**

```bash
git add engine/systems/resolve.py tests/unit/test_system_resolve.py
git commit -m "feat(systems): resolve a set name to its system and region"
```

---

### Task 2: The far plane, and conditional virtual distance

**Why.** Nothing in the celestial layer renders until this lands — at ×20 scale
even the *local* planet sits at 5,997 GU, outside the 5,000 GU frustum. And the
moment the far plane is real, `sun_pass` and `lens_flare_pass` become wrong:
both re-place their object at `far × 0.95` unconditionally, which is harmless
while everything is inside 5,000 GU and not afterwards. Standing in Ona 1 the
star is 34,097 GU away and Ona 3 is 96,211 GU away on the far side; the star
should occlude it, and `sun_pass` would draw the star at 475,000 GU, behind it.

**Files:**
- Modify: `engine/host_loop.py` (the exterior `set_camera`, `VS_FAR`)
- Modify: `native/src/renderer/sun_pass.cc`, `native/src/renderer/lens_flare_pass.cc`
- Test: `tests/unit/test_camera_far_plane.py`, and the C++ suite

**Interfaces:**

- The exterior scene camera and the bridge viewscreen both use **500,000.0** GU
  as `far`. Introduce one named constant rather than repeating the literal.
- `_BridgeCamera.FAR` (800), the Ship Property Viewer camera and the comm
  viewscreen camera are **unchanged**. A room, a hologram and a face in a window
  gain nothing and lose depth precision.
- In both passes: compute the object's true distance first. Apply the
  virtual-distance scaling **only when that distance exceeds the far plane**;
  otherwise draw at true position with true radius. Keep the branch — the trick
  stays correct for anything that ever does exceed it.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_exterior_and_viewscreen_cameras_reach_the_whole_system():
    """452,715 GU is the widest sightline across all 32 maps (Itari). A far
    plane under it silently clips the most distant world in one system."""
    assert host_loop.SCENE_FAR_GU >= 452_715.0
    assert host_loop.VS_FAR >= 452_715.0


def test_the_bridge_camera_is_left_alone():
    """A room. Raising its far plane costs precision for nothing."""
    assert host_loop._BridgeCamera.FAR == 800.0


def test_depth_precision_is_effectively_unchanged():
    """The whole argument for raising the far plane rather than faking the
    distance. Forward-Z precision is governed by the NEAR plane."""
    def dz(z, n, f):
        return (1.0 / 2**24) * z * z * (f - n) / (f * n)
    before = dz(4900.0, 1.0, 5000.0)
    after = dz(4900.0, 1.0, host_loop.SCENE_FAR_GU)
    assert after / before < 1.001
```

For the C++ side add a `FrameTest` asserting that a sun at a distance **inside**
the far plane is drawn at its true position and radius, and one at a distance
**beyond** it is drawn at the scaled position. Follow the existing test file's
conventions; do not invent a new harness.

- [ ] **Step 2: Run them and confirm they fail**

`uv run pytest tests/unit/test_camera_far_plane.py -v`, then
`cmake --build build -j && ctest --test-dir build --output-on-failure -R Sun`

- [ ] **Step 3: Implement** per the Interfaces block.

- [ ] **Step 4: Verify**

```bash
uv run pytest tests/unit/test_camera_far_plane.py -v
cmake -B build -S . && cmake --build build -j
ctest --test-dir build --output-on-failure
```

- [ ] **Step 5: Prove the conditional bites**

`cp native/src/renderer/sun_pass.cc /tmp/sp.cc`, make the scaling unconditional
again, rebuild, watch the new C++ test FAIL, `cp` back, rebuild, `diff` to prove
the restore. Report the failure output.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py native/src/renderer/sun_pass.cc \
        native/src/renderer/lens_flare_pass.cc \
        tests/unit/test_camera_far_plane.py native/tests/<the file you touched>
git commit -m "feat(render): far plane reaches the whole system; virtual distance only beyond it"
```

---

### Task 3: Apply the map when a region's set is created

**Files:**
- Create: `engine/systems/apply_map.py`
- Test: `tests/unit/test_apply_system_map.py`

**Interfaces:**

- Produces `apply_to_set(pSet, set_name) -> bool` — `True` when the set resolved
  to a region and the map was applied, `False` when it resolved to nothing.
- For each body the map names in that region: set its **radius** to the map's
  `radius_gu` and its **position** to `body.position_gu − region.anchor_gu`
  (set-local). Nothing is created, nothing is deleted, no model is swapped.
- **The star is the exception**, and it has two halves:
  - A set that already holds a `Sun` keeps it, repositioned to
    `(0,0,0) − region.anchor_gu` with the map star's radius.
  - A set with no `Sun` gets one created from the map. Belaruz and Vesuvi render
    bright directional light from a source BC never placed; their
    `overrides.star` blocks declare what it is.
- **This must run before anything render-realizes the set.**
  `_RenderState.planet_natural_scale` caches `GetRadius() / NIF_extent` once at
  load; a radius written after that cache is populated leaves the body drawn at
  its old size while every other system sees the new one.
- A body in the set that the map does not name is left exactly as BC placed it.

**Ruling to implement, not to revisit:** nothing is removed. §2 of the parent
spec allows for a map relocating a body out of its original set, but no map
declares one — every ambiguous case was resolved by demoting the body to a moon
within its own region. Do not build a removal path.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_body_takes_the_maps_radius_and_set_local_position():
    """Ona 1's planet is 110 GU at 538 GU in BC, and 2,200 GU at ~6,000 GU
    here -- the same object, re-authored around the region's anchor."""
    pSet = _fake_set_with_planet("Ona 1", radius=110.0, at=(0.0, 538.0, 0.0))
    assert apply_map.apply_to_set(pSet, "Ona1") is True
    body = pSet.GetObject("Ona 1")
    m, r = resolve.for_set("Ona1")
    expected = tuple(a - b for a, b in zip(m.body("Ona 1").position_gu, r.anchor_gu))
    assert body.GetRadius() == pytest.approx(m.body("Ona 1").radius_gu)
    assert _loc(body) == pytest.approx(expected)


def test_a_set_that_is_not_a_region_is_untouched():
    pSet = _fake_set_with_planet("Whatever", radius=110.0, at=(0.0, 538.0, 0.0))
    assert apply_map.apply_to_set(pSet, "QuickBattle") is False
    assert pSet.GetObject("Whatever").GetRadius() == pytest.approx(110.0)


def test_an_existing_sun_is_moved_to_the_maps_star():
    pSet = _fake_set_with_sun(at=(70000.0, 0.0, 0.0), radius=4000.0)
    apply_map.apply_to_set(pSet, "Ona1")
    m, r = resolve.for_set("Ona1")
    star = m.body("Ona")
    assert _loc(_only_sun(pSet)) == pytest.approx(tuple(-c for c in r.anchor_gu))
    assert _only_sun(pSet).GetRadius() == pytest.approx(star.radius_gu)


def test_a_set_with_no_sun_gets_one():
    """Belaruz and Vesuvi author no Sun_Create and still light their scenes."""
    pSet = _fake_set_with_planet("Belaruz 2", radius=120.0, at=(0.0, 500.0, 0.0))
    apply_map.apply_to_set(pSet, "Belaruz2")
    sun = _only_sun(pSet)
    assert sun is not None
    assert sun.GetRadius() == pytest.approx(load("belaruz").body("Belaruz").radius_gu)


def test_a_body_the_map_does_not_name_is_left_alone():
    pSet = _fake_set_with_planet("Ona 1", radius=110.0, at=(0.0, 538.0, 0.0))
    _add_planet(pSet, "Mystery Rock", radius=40.0, at=(10.0, 20.0, 30.0))
    apply_map.apply_to_set(pSet, "Ona1")
    rock = pSet.GetObject("Mystery Rock")
    assert rock.GetRadius() == pytest.approx(40.0)
    assert _loc(rock) == pytest.approx((10.0, 20.0, 30.0))
```

Build the fake sets from the real `engine.appc` classes (`SetClass`, `Planet`,
`Sun`), not hand-written doubles — a double that drifts from the real surface is
a defect this project has hit before.

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement** per the Interfaces block.

- [ ] **Step 4: Run the tests, then `uv run pytest tests/unit/ -q`.**

- [ ] **Step 5: Commit**

```bash
git add engine/systems/apply_map.py tests/unit/test_apply_system_map.py
git commit -m "feat(systems): a region's bodies take the map's radius and position"
```

---

### Task 4: System residency

**Files:**
- Create: `engine/systems/residency.py`
- Modify: `engine/appc/warp.py`
- Test: `tests/unit/test_system_residency.py`

**Interfaces:**

- Produces `enter(set_name) -> str | None` — resolves the set, and if it belongs
  to a system that is not the current one, tears the current system down,
  creates **every** region of the new one, and returns its name. Returns `None`
  when the set belongs to no system (having torn down whatever was resident).
- Produces `current() -> str | None` and `is_resident(set_name) -> bool`.
- **"Create" means BC's own path**, the one Set Course already uses: import
  `Systems.<System>.<Region>` and run its `Initialize()`. Nothing is
  synthesized. A region created this way is indistinguishable from one the
  player warped into.
- Task 3's `apply_to_set` runs as part of creating each region, before anything
  render-realizes it.
- Teardown is the ordinary `DeleteSet` per region, after the render teardown the
  warp path already performs.
- `warp.py:_WarpDepartAction` must **not** delete a set that
  `residency.is_resident()` reports. Suppression lives on the **departure path
  only** — `g_kSetManager.DeleteSet` keeps working for every other caller, so a
  mission that deletes a set deliberately still can.

**Ruling to implement, not to revisit:** missions are included. A scripted
mission loads its whole system like any other arrival. Two consequences are
accepted: 33 campaign missions now load several sets where they loaded one, and
a player can fly out of a mission's staging area with no way back yet — the
hand-off is a later slice.

- [ ] **Step 1: Write the failing tests**

```python
def test_entering_a_region_creates_every_region_of_its_system():
    assert residency.enter("Ona2") == "Ona"
    for name in ("Ona1", "Ona2", "Ona3"):
        assert App.g_kSetManager.GetSet(name) is not None
        assert residency.is_resident(name)


def test_entering_a_second_region_of_the_same_system_changes_nothing():
    residency.enter("Ona1")
    sets_before = dict(App.g_kSetManager._sets)
    assert residency.enter("Ona3") == "Ona"
    assert dict(App.g_kSetManager._sets) == sets_before


def test_leaving_for_another_system_tears_the_old_one_down():
    residency.enter("Ona1")
    residency.enter("Vesuvi4")
    assert residency.current() == "Vesuvi"
    for name in ("Ona1", "Ona2", "Ona3"):
        assert App.g_kSetManager.GetSet(name) is None
    assert App.g_kSetManager.GetSet("Vesuvi5") is not None


def test_leaving_for_a_set_that_is_no_system_tears_down_and_builds_nothing():
    """The bridge, a QuickBattle arena, a multiplayer set. A system must never
    be left resident behind a set that is not part of it."""
    residency.enter("Ona1")
    assert residency.enter("QuickBattle") is None
    assert residency.current() is None
    assert App.g_kSetManager.GetSet("Ona1") is None


def test_the_warp_departure_path_does_not_delete_a_resident_set():
    """THE RULE THIS TASK EXISTS FOR. Today departing destroys the set you
    leave; within one system that would delete the worlds you can see."""
    residency.enter("Ona1")
    warp._WarpDepartAction(...)  # follow the real call shape
    assert App.g_kSetManager.GetSet("Ona1") is not None


def test_the_warp_departure_path_still_deletes_a_set_outside_any_system():
    residency.enter("QuickBattle")
    warp._WarpDepartAction(...)
    assert App.g_kSetManager.GetSet("QuickBattle") is None
```

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement** per the Interfaces block.

- [ ] **Step 4: Prove the suppression is load-bearing**

`cp engine/appc/warp.py /tmp/warp.py`, remove the residency check, run
`tests/unit/test_system_residency.py`, watch the departure test FAIL, `cp` back,
`diff` to prove the restore. Report the output.

- [ ] **Step 5: Run `uv run pytest tests/unit/ -q` and report the count.**
An extra set being resident changes what `iter_ships` walks, so watch for
mission and AI tests that assumed exactly one space set.

- [ ] **Step 6: Commit**

```bash
git add engine/systems/residency.py engine/appc/warp.py \
        tests/unit/test_system_residency.py
git commit -m "feat(systems): a system's regions are resident together"
```

---

### Task 5: Gather the celestial bodies

**Files:**
- Modify: `engine/host_loop.py`
- Test: `tests/host/test_celestial_gathering.py`

**Interfaces:**

- `_live_sets()`'s scope becomes **the current system** rather than the active
  set. Its existing reason survives — it stops one system's bodies bleeding into
  another's scene — the unit of scope just grows from a region to a system.
- Bodies from a region other than the player's are shifted into the player's
  frame: `render_position = body_local_position + (body_region.anchor_gu −
  player_region.anchor_gu)`. **Translation only, never rotation.**
- **The shift is applied when building render data, not by moving objects.**
  `GetWorldLocation()` must keep returning the set-local position BC and the map
  agree on, so Orbit, mission scripts and the physics step still see a body
  where its own set puts it.
- **Suns stay scoped to the player's own region.** Task 3 put every region's sun
  at the same system-space point, so drawing one is correct and drawing eight is
  waste.
- **`iter_ships` is not touched.** Only `_live_sets()` and the two body
  iterators that read it. That is what bounds the cost to a system's body count
  (~15 worst case) rather than every resident region's traffic.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_body_from_another_region_is_shifted_into_the_players_frame():
    residency.enter("Ona1")
    _put_player_in("Ona1")
    drawn = {d["name"]: d["position"] for d in host_loop._celestial_render_data()}
    m = load("ona")
    a1, a2 = m.region("Ona1").anchor_gu, m.region("Ona2").anchor_gu
    local = tuple(a - b for a, b in zip(m.body("Ona 2").position_gu, a2))
    expected = tuple(l + (x - y) for l, x, y in zip(local, a2, a1))
    assert drawn["Ona 2"] == pytest.approx(expected)


def test_the_players_own_body_is_not_shifted():
    residency.enter("Ona1")
    _put_player_in("Ona1")
    drawn = {d["name"]: d["position"] for d in host_loop._celestial_render_data()}
    m = load("ona")
    a1 = m.region("Ona1").anchor_gu
    local = tuple(a - b for a, b in zip(m.body("Ona 1").position_gu, a1))
    assert drawn["Ona 1"] == pytest.approx(local)


def test_shifting_does_not_move_the_object():
    """Orbit, targeting range and the physics step all read GetWorldLocation.
    Only the picture is assembled across regions."""
    residency.enter("Ona1")
    before = _loc(App.g_kSetManager.GetSet("Ona2").GetObject("Ona 2"))
    host_loop._celestial_render_data()
    assert _loc(App.g_kSetManager.GetSet("Ona2").GetObject("Ona 2")) == before


def test_exactly_one_sun_is_drawn():
    residency.enter("Ona1")
    _put_player_in("Ona1")
    assert len(list(host_loop._iter_suns())) == 1


def test_a_set_outside_any_system_draws_only_its_own_bodies():
    """QuickBattle and the bridge must behave exactly as today."""
    _put_player_in("QuickBattle")
    assert host_loop._celestial_render_data() == []
```

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement** per the Interfaces block.

- [ ] **Step 4: Prove the shift is guarded**

`cp engine/host_loop.py /tmp/hl.py`, drop the anchor difference so bodies use
their raw set-local position, run the test file, watch it FAIL, `cp` back,
`diff`. Report the output.

- [ ] **Step 5: `uv run pytest tests/host/ tests/unit/ -q`, report both counts.**

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/host/test_celestial_gathering.py
git commit -m "feat(render): draw every region's bodies, shifted into the player's frame"
```

---

### Task 6: A developer mission that puts the player in a system

**Why.** Without it there is no way to look at any of the above. Five tasks of
headless tests prove the arithmetic; this is the one that makes the result
visible, which is the point of the slice.

**Files:**
- Create: `engine/dev_missions/system_preview.py`
- Test: `tests/unit/test_dev_system_preview.py`

**Interfaces:**

- A developer mission, discoverable from the existing dev mission picker,
  following the conventions in `engine/dev_missions/combat_stress.py` — read it
  first and match its shape rather than inventing one.
- Drops the player at the `Player Start` of a chosen region, with residency
  entered so the whole system is present.
- The region is chosen by `DAUNTLESS_SYSTEM_REGION`, defaulting to **`Ona1`** —
  three regions, one planet each, no moons, no nebula, and the clearest test of
  whether the sky reads correctly.
- Gated behind `--developer` like every other dev mission. Production behaviour
  must be byte-identical without the flag.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_preview_enters_the_region_and_its_whole_system():
    mission = system_preview.Mission()
    mission.start()
    assert residency.current() == "Ona"
    assert all(residency.is_resident(n) for n in ("Ona1", "Ona2", "Ona3"))


def test_the_region_is_selectable_by_environment():
    with _env(DAUNTLESS_SYSTEM_REGION="Vesuvi5"):
        system_preview.Mission().start()
    assert residency.current() == "Vesuvi"


def test_an_unknown_region_falls_back_rather_than_crashing():
    with _env(DAUNTLESS_SYSTEM_REGION="Nonsense9"):
        system_preview.Mission().start()
    assert residency.current() == "Ona"
```

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement**, matching `combat_stress.py`'s structure.

- [ ] **Step 4: Gate** — `scripts/check_tests.sh`. Expect
`OK — no new failures. 1 known failure(s) still baselined.` Report its exact
output, and confirm `git status --porcelain engine/systems/maps` is empty.

- [ ] **Step 5: Report what a live run would show**, from the map data, so the
user knows what to look for before running it: the bearing and apparent size of
every body visible from Ona 1, and which direction the star should be in.

- [ ] **Step 6: Commit**

```bash
git add engine/dev_missions/system_preview.py tests/unit/test_dev_system_preview.py
git commit -m "feat(dev): System Preview mission — stand in a region and see its system"
```

---

## Self-review

**Spec coverage.** Far plane and the two conditional passes → Task 2. Resolution
→ Task 1. Map application including the star's two halves → Task 3. Residency,
BC's own creation path, and `DeleteSet` suppression on the departure path only →
Task 4. Celestial gathering, the shift, suns scoped to one region, `iter_ships`
untouched → Task 5. **Deliberately not covered**, per the spec: the hand-off,
the dash, distance-based streaming, and clouds — `SystemMap.clouds` stays
unread, and is superseded anyway by the radial-profile design.

**Type consistency.** `for_set` returns `(SystemMap, Region)` in Tasks 1, 3 and
5. `residency.enter` returns the system name or `None` in Tasks 4 and 6.
`apply_to_set` returns `bool` in Tasks 3 and 4. Anchors are 3-tuples of GU
throughout, and the shift is always `body_region.anchor_gu −
player_region.anchor_gu`, in that order, in both the spec and Task 5.

**Ordering.** Task 2 is independent and could run at any point. Tasks 1 → 3 → 4
→ 5 are a chain: resolution feeds map application, which runs inside residency,
which is what gives the gathering more than one set to gather from. Task 6 needs
all of them.

**The risk this plan carries.** Task 4 makes several space sets resident at
once, which has never been true in this engine. `iter_ships` walks every set, so
simulation already handles it, but nothing has ever exercised it — expect Task
4's Step 5 to surface mission or AI tests that quietly assumed one space set.
That is a discovery, not a defect, and it belongs in the ledger rather than
being worked around.
