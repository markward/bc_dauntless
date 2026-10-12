# Bridge Material Library + Five States + Editor Chrome (Slice 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-shape profiles with a Blender-style material library (objects link to shared materials holding finish, surface and scoped Emitter/Animation modifiers), add the `offline` and `special` bridge states end to end, and rebuild the Bridge Editor as a top-left bar plus a selection-only side panel with Object / Material tabs.

**Architecture:** Python owns the document (`format: 2`, with a loader that upgrades `format: 1`), the evaluation (pure functions: Σ emitters × Π animations per state, cross-faded), and all editing (a new `editing.py` of pure document operations the panel calls inside its one-undo-step `_edit`). C++ only learns the two new states: an `_emissive_s` sibling slot, the state→map choice, and "the texture-level default glow is dark at offline". The CEF UI is rebuilt around a bar (`#be-bar`) and a dock shown only while an object is selected.

**Tech Stack:** Python 3.11 / pytest; C++20 / GLSL 410 / gtest; CEF page JS (node-run tests).

**Spec:** `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` §13 (binding), with §9.7, §11.2, §11.4, §12.

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/dbridge-round7`, branch `feat/dbridge-round7`. ⛔ No `git checkout --`/`restore`/`stash`/`clean`/`reset --hard`/`add -A`/`add .`; explicit pathspecs.
- Bridge state ints everywhere (Python ↔ C++): **0 green, 1 yellow, 2 red, 3 offline, 4 special**. State names: `offline green yellow red special` (document order).
- Document `format: 2` keys exactly as spec §13.4; unknown keys REJECTED. Surface `src` ∈ `auto emission texture flat none`.
- Every value the editor writes is clamped to the schema (§12.3). Tint is V = 1 (max channel 1).
- No `<select>` anywhere in the editor (CEF OSR draws no popup).
- The game's real alert is never changed by the editor; with the editor closed, behaviour equals the game state (§12.2).
- Asset tests need `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"`. Build `cmake --build build -j` (Debug tree; never reconfigure the build type).
- Commit trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Done = `scripts/check_tests.sh` exits 0.

## Review Focus

1. **Upgrading a `format: 1` file with Mark's real data** (alcove + roof profiles, ~40 roughness overrides, light-only objects): nothing lost — Task 3 `test_upgrade_of_the_real_dbridge_shape_is_lossless_where_it_matters`.
2. **An object linked to a material whose surface is `emission` but whose texture has no emission map**: skipped with a warning, never a crash — Task 4 `test_emission_surface_without_a_map_is_skipped_with_a_warning`.
3. **Offline**: texture-level default glows go dark, but a material's emission-map glow scoped to offline still lights — Task 1 `OfflineDarkensTheDefaultButNotAMaterialGlow`.
4. **Renaming / duplicating a material used by several objects** moves or copies cleanly, and undo restores everything — Task 6 tests.
5. **Shift held while typing in a text field** must not start flying (the KeyGate masks keys then) — Task 7 `test_shift_flies_and_scroll_sets_the_speed` exercises the non-masked path; the KeyGate itself is already tested.

---

### Task 1: C++ — `_emissive_s` and the offline/special states

**Files:**
- Modify: `native/src/assets/include/assets/material.h` (StageSlot `EmissiveSpecial` after `EmissiveRed`; doc)
- Modify: `native/src/assets/src/model_build.cc` (sibling sink, probe list, probe count 7, `filename_is_emissive`, `mat_inputs`)
- Modify: `native/src/assets/src/material_build.h`, `material_build.cc` (4th emissive sink)
- Modify: `native/src/assets/src/mesh_fix.cc` (reserved `_emissive_s`)
- Modify: `tools/shape_diff/match.py` (`_RESERVED_SUFFIXES`)
- Modify: `native/src/renderer/include/renderer/bridge_pass.h`, `native/src/renderer/bridge_pass.cc`, `native/src/host/host_bindings.cc` (docstring)
- Test: `native/tests/renderer/bridge_pbr_frame_test.cc`, `native/tests/assets/cpu/model_build_test.cc`, `native/tests/assets/cpu/mesh_fix_texture_test.cc`, `tests/tools/test_shape_diff.py`

**Interfaces:**
- Produces: `assets::Material::StageSlot::EmissiveSpecial`; `renderer::kBridgeStateOffline = 3`, `renderer::kBridgeStateSpecial = 4`; `bridge_emissive_texture(mat, 3)` → the default map, `(mat, 4)` → EmissiveSpecial else default; at state 3 the texture-level default glow (`glow_src < 0`) draws nothing.

- [ ] **Step 1: Failing tests.**

`bridge_pbr_frame_test.cc` — after the existing `emissive_material` helper add a four-slot one and tests:

```cpp
assets::Material emissive_material4(int e, int y, int r, int s) {
    assets::Material m = emissive_material(e, y, r);
    m.stages[static_cast<std::size_t>(assets::Material::StageSlot::EmissiveSpecial)]
        .texture_index = s;
    return m;
}

TEST(BridgeEmissiveSelect, SpecialTakesItsOwnMapElseTheDefault) {
    EXPECT_EQ(renderer::bridge_emissive_texture(emissive_material4(4, 5, 6, 7), 4), 7);
    EXPECT_EQ(renderer::bridge_emissive_texture(emissive_material4(4, 5, 6, -1), 4), 4);
}

TEST(BridgeEmissiveSelect, OfflineTakesTheDefaultForMaterialGlows) {
    EXPECT_EQ(renderer::bridge_emissive_texture(emissive_material4(4, 5, 6, 7), 3), 4);
}

// Spec §13.1: at offline the texture-level default goes dark, but a
// material glow through the emission map still lights (reserve power).
TEST_F(BridgePbrFrame, OfflineDarkensTheDefaultButNotAMaterialGlow) {
    set_base({0, 0, 0, 1});
    set_map(assets::Material::StageSlot::Emissive, {0.5f, 0.5f, 0.5f, 1.0f});
    pass->set_alert_level(renderer::kBridgeStateOffline);
    EXPECT_LT(render_floor().r, 1e-3f);
    pass->set_glow(handle(), {{0, 0, {1.0f, 1.0f, 1.0f}, 0.0f}});
    EXPECT_NEAR(render_floor().r, 0.5f, 3e-3f);
    pass->clear_glow();
    pass->set_alert_level(0);
}
```

`model_build_test.cc` — after `InteriorEmissiveWithoutAlertVariantsLeavesThemEmpty`:

```cpp
TEST_F(ModelBuildTest, InteriorEmissiveSpecialSiblingBinds) {
    const fs::path stock = tmp_dir / "stock", mod = tmp_dir / "mod";
    for (const auto& d : {stock, mod}) fs::create_directories(d);
    write_tga_at(mod / "hull_ID.tga");
    write_tga_at(mod / "hull_ID_emissive.tga");
    write_tga_at(mod / "hull_ID_emissive_s.tga");
    auto model = assets::detail::build_model(file_with_textured_shape(),
                                             interior_mod_ctx(make_ctx(), mod, stock));
    using S = assets::Material::StageSlot;
    const auto& st = model.materials[0].stages;
    const int s = st[static_cast<size_t>(S::EmissiveSpecial)].texture_index;
    EXPECT_GE(s, 0);
    EXPECT_NE(s, st[static_cast<size_t>(S::Emissive)].texture_index);
}
```

`mesh_fix_texture_test.cc` — beside the red-emissive line: `expect_refused(fix_of(1, "panel_emissive_s.tga"), "special emissive suffix");`

`tests/tools/test_shape_diff.py` — add `"panel_emissive_s.tga"` to `test_reserved_suffix_albedo_is_refused`'s list and `("Map 22a_emissive_s.tga", "_emissive_s")` to `test_emissive_albedo_refusal_names_the_emissive_map`'s list.

- [ ] **Step 2: Build/run, watch fail** — `cmake --build build -j 2>&1 | grep error: | head` (no `EmissiveSpecial`, no `kBridgeStateOffline`), and `uv run pytest tests/tools/test_shape_diff.py -q -k "reserved or emissive_albedo"` (the `_emissive_s` cases fail).

- [ ] **Step 3: Implement.**

`material.h`: `Emissive, EmissiveYellow, EmissiveRed, EmissiveSpecial,` and the doc line: ``/// Emissive / EmissiveYellow / EmissiveRed / EmissiveSpecial: `<stem>_emissive`, `_emissive_y`, `_emissive_r`, `_emissive_s` siblings ... chosen per bridge state (spec §13.1)``.

`model_build.cc`: add `std::unordered_map<std::uint32_t, int> sibling_emissive_s_for_image;` after the `_r` sink (comment "_emissive_s" = special alert, spec §13.1); add `{"_emissive_s", &out.sibling_emissive_s_for_image, false},` after the `_emissive_r` probe; `probe_count = ctx.interior_sibling_policy ? 7 : 3`; `filename_is_emissive` also matches `"_emissive_s"`; `mat_inputs.sibling_emissive_s_for_image = &tex_result.sibling_emissive_s_for_image;`.

`material_build.h`: `const std::unordered_map<std::uint32_t, int>* sibling_emissive_s_for_image = nullptr;`. `material_build.cc`: `kEmissiveSlots[4]` adds `Material::StageSlot::EmissiveSpecial`, the loop runs `k < 4`, and `emissive_sinks[4]` adds `in.sibling_emissive_s_for_image` (update the `apply_texture_property` parameter type from `[3]` to `[4]` wherever the array is passed).

`mesh_fix.cc`: the reserved loop becomes `{"_emissive_y", "_emissive_r", "_emissive_s", "_emissive"}`.

`match.py`: `("_emissive_r", _EMISSIVE), ("_emissive_s", _EMISSIVE))`.

`bridge_pass.h` (beside `bridge_emissive_texture`):

```cpp
/// Bridge states beyond the alert levels (spec 2026-10-08-bridge-emitters §13.1):
/// 0 green, 1 yellow, 2 red, 3 offline, 4 special.
inline constexpr int kBridgeStateOffline = 3;
inline constexpr int kBridgeStateSpecial = 4;
```

and its doc comment: `special -> EmissiveSpecial else Emissive; offline -> Emissive (for a material glow through the emission map; the texture-level default is dark at offline, see draw).`

`bridge_pass.cc` `bridge_emissive_texture`: first line of the body after `slot`:
`if (alert == kBridgeStateSpecial) return slot(S::EmissiveSpecial) >= 0 ? slot(S::EmissiveSpecial) : (slot(S::Emissive) >= 0 ? slot(S::Emissive) : -1);`
In `draw_mesh`'s emissive block, after computing `id`:

```cpp
        // Spec §13.1: power offline darkens the texture-level default; a
        // material glow (glow_src >= 0) still samples the map.
        if (glow_src < 0 && emissive_alert == kBridgeStateOffline) id = 0;
```

`host_bindings.cc` `set_bridge_alert_level` docstring: `"Bridge state (0 green, 1 yellow, 2 red, 3 offline, 4 special; anything else reads as green) ..."`.

- [ ] **Step 4: Run** — `cmake --build build -j 2>&1 | tail -1 && DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" ctest --test-dir build -R "Bridge|ModelBuild|MeshFix" 2>&1 | tail -2 && uv run pytest tests/tools/test_shape_diff.py -q 2>&1 | tail -1` → all pass.

- [ ] **Step 5: Commit** — `git add` the files above; message `feat(bridge): _emissive_s sibling and the offline/special bridge states in the renderer (spec §13.1)`.

---

### Task 2: Python bridge states — offline from the power plant, a special-alert hook

**Files:** Modify `engine/bridge_lighting.py`, `engine/host_loop.py` (`_bridge_alert_level_of`); Test `tests/unit/test_bridge_lighting.py`.

**Interfaces:**
- Produces: `bridge_lighting.GREEN, YELLOW, RED, OFFLINE, SPECIAL = 0, 1, 2, 3, 4`; `ambient_scale_for_alert(state)` covers 0-4 (offline `OFFLINE_AMBIENT_SCALE = 0.4`, special = red's); `bridge_state_of(player) -> int`; `set_special_alert(on)`, `special_alert() -> bool`; `player_bridge_ambient_scale(player)` uses `bridge_state_of`.

- [ ] **Step 1: Failing tests** — append to `tests/unit/test_bridge_lighting.py`:

```python
class _Power:
    def __init__(self, disabled=False, destroyed=False):
        self._d, self._x = disabled, destroyed

    def IsDisabled(self):
        return self._d

    def IsDestroyed(self):
        return self._x


class _Player:
    def __init__(self, alert=0, power=None):
        self._a, self._p = alert, power

    def GetAlertLevel(self):
        return self._a

    def GetPowerSubsystem(self):
        return self._p


@pytest.fixture
def no_special():
    bl.set_special_alert(False)
    yield
    bl.set_special_alert(False)


def test_bridge_state_follows_the_alert_level(no_special):
    assert [bl.bridge_state_of(_Player(a, _Power())) for a in (0, 1, 2)] == [0, 1, 2]
    assert bl.bridge_state_of(None) == bl.GREEN


def test_a_dead_power_plant_is_offline_over_any_alert(no_special):
    assert bl.bridge_state_of(_Player(2, _Power(disabled=True))) == bl.OFFLINE
    assert bl.bridge_state_of(_Player(0, _Power(destroyed=True))) == bl.OFFLINE
    bl.set_special_alert(True)
    assert bl.bridge_state_of(_Player(0, _Power(disabled=True))) == bl.OFFLINE


def test_special_overrides_the_alert_levels(no_special):
    bl.set_special_alert(True)
    assert bl.special_alert() is True
    assert bl.bridge_state_of(_Player(2, _Power())) == bl.SPECIAL


def test_no_power_subsystem_reads_as_powered(no_special):
    assert bl.bridge_state_of(_Player(1, None)) == bl.YELLOW


def test_ambient_scales_cover_the_five_states():
    assert bl.ambient_scale_for_alert(bl.OFFLINE) == bl.OFFLINE_AMBIENT_SCALE
    assert bl.OFFLINE_AMBIENT_SCALE < bl.ambient_scale_for_alert(bl.RED)
    assert bl.ambient_scale_for_alert(bl.SPECIAL) == bl.ambient_scale_for_alert(bl.RED)
```

(add `import pytest` at the top if the file lacks it).

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/unit/test_bridge_lighting.py -q` → the new tests fail (no `bridge_state_of`).

- [ ] **Step 3: Implement** in `engine/bridge_lighting.py`:

```python
# Bridge states (spec 2026-10-08-bridge-emitters §13.1); the C++ pass uses the
# same ints (renderer::kBridgeStateOffline / kBridgeStateSpecial).
GREEN, YELLOW, RED, OFFLINE, SPECIAL = 0, 1, 2, 3, 4
OFFLINE_AMBIENT_SCALE = 0.4   # "dimmed" (Mark 2026-10-11); calibrate live
_ALERT_AMBIENT_SCALE = {GREEN: 1.5, YELLOW: 1.0, RED: 1.0,
                        OFFLINE: OFFLINE_AMBIENT_SCALE, SPECIAL: 1.0}
_special = [False]


def set_special_alert(on) -> None:
    """The generic special-alert hook (§13.1), e.g. a future multi-vector
    assault 'blue alert'. No in-game caller yet."""
    _special[0] = bool(on)


def special_alert() -> bool:
    return _special[0]


def bridge_state_of(player) -> int:
    """The state the player's bridge shows: offline while the power plant is
    disabled or destroyed, else special while the hook is on, else the alert
    level (0-2). No player -> green."""
    if player is None:
        return GREEN
    try:
        power = player.GetPowerSubsystem()
        if power is not None and (power.IsDisabled() or power.IsDestroyed()):
            return OFFLINE
    except Exception as e:  # noqa: BLE001 - never let a probe kill the frame
        dev_mode.log_swallowed("bridge power-state probe", e)
    if _special[0]:
        return SPECIAL
    try:
        level = int(player.GetAlertLevel())
    except Exception as e:  # noqa: BLE001
        dev_mode.log_swallowed("bridge alert probe", e)
        return GREEN
    return level if level in (GREEN, YELLOW, RED) else GREEN
```

Replace the old `_ALERT_AMBIENT_SCALE` line with the block above, and change `player_bridge_ambient_scale`'s body after its `None` check to `return ambient_scale_for_alert(bridge_state_of(player))` (drop its own try/except — `bridge_state_of` guards).

`engine/host_loop.py`: `_bridge_alert_level_of(_player)`'s body becomes `return _bridge_lighting.bridge_state_of(_player)` (keep the name; it already feeds the runtime, the probe blend, the ambient and `set_bridge_alert_level`).

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_bridge_lighting.py tests/unit/test_bridge_editor_preview.py tests/host/test_host_loop_lighting.py -q` → pass.

- [ ] **Step 5: Commit** — `engine/bridge_lighting.py engine/host_loop.py tests/unit/test_bridge_lighting.py`; message `feat(bridge): offline (power plant down) and special bridge states (spec §13.1)`.

---

### Task 3: Document `format: 2` and the `format: 1` upgrade

**Files:** Modify `engine/bridge_editor/lighting_doc.py`, `engine/bridge_editor/lighting_writer.py` (docstring only); Test `tests/unit/test_bridge_lighting_doc.py` (rewrite), `tests/unit/test_bridge_lighting_writer.py` (update fixtures to v2).

**Interfaces:**
- Produces: `ld.FORMAT = 2`; `ld.STATES = ("offline", "green", "yellow", "red", "special")`; `ld.SURFACES = ("auto", "emission", "texture", "flat", "none")`; `ld.empty_doc(source)` → `{"format": 2, "source", "materials": {}, "objects": {}}`; `ld.object_entry(doc, block, name)`; `ld.validate(doc)` (v2); `ld.upgrade(doc_v1) -> doc_v2`; `ld.load` upgrades a v1 file; `ld.match_shapes(doc, meshes)` reads `doc["objects"]`. `ld.shape_entry` is removed.

- [ ] **Step 1: Failing tests** — replace `tests/unit/test_bridge_lighting_doc.py`'s `full_doc`, the parametrized invalid list, `test_every_glow_source_validates` and `test_shape_entry_creates_once` with:

```python
def full_doc():
    return {
        "format": 2,
        "source": "data/Models/Sets/DBridge/DBridge.nif",
        "materials": {
            "alcove": {
                "roughness": 0.4, "metalness": 0.0,
                "surface": {"src": "auto", "strength": 1.0},
                "fade_s": 0.5,
                "modifiers": [
                    {"type": "emitter", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
                    {"type": "emitter", "scope": ["red"], "tint": [1, 0.1, 0.1], "level": 0.5},
                    {"type": "animation", "scope": ["red"], "shape": "square",
                     "period_s": 1.0, "min": 0.2, "duty": 0.5, "soft": 0.1, "phase": 0.0},
                ],
            }
        },
        "objects": {
            "137:wall inset slot left": {
                "block": 137, "name": "wall inset slot left", "material": "alcove",
                "lights": [{"position": [191, 0, 40], "direction": [-1, 0, 0],
                            "inner_deg": 30, "outer_deg": 60, "range": 120,
                            "intensity": 1.0}],
            }
        },
    }


OBJ = "137:wall inset slot left"


def _mod(d, i):
    return d["materials"]["alcove"]["modifiers"][i]


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.update(extra=1), "extra"),
    (lambda d: d.update(format=3), "format"),
    (lambda d: d["objects"][OBJ].update(colour=1), "colour"),
    (lambda d: d["objects"][OBJ].update(name="other"), "key"),
    (lambda d: d["objects"][OBJ].update(material="nope"), "nope"),
    (lambda d: d["objects"][OBJ]["lights"][0].update(direction=[0, 0, 0]), "direction"),
    (lambda d: d["objects"][OBJ]["lights"][0].update(inner_deg=70), "inner_deg"),
    (lambda d: d["materials"]["alcove"].update(roughness=1.5), "roughness"),
    (lambda d: d["materials"]["alcove"].update(shine=1), "shine"),
    (lambda d: d["materials"]["alcove"]["surface"].update(src="glow"), "src"),
    (lambda d: d["materials"]["alcove"]["surface"].update(strength=-1), "strength"),
    (lambda d: _mod(d, 0).update(scope=["green", "blue"]), "scope"),
    (lambda d: _mod(d, 0).update(scope=["green", "green"]), "scope"),
    (lambda d: _mod(d, 0).update(tint=[1, 1]), "tint"),
    (lambda d: _mod(d, 0).update(type="spark"), "type"),
    (lambda d: _mod(d, 2).update(shape="saw"), "shape"),
    (lambda d: _mod(d, 2).pop("period_s"), "period_s"),
    (lambda d: _mod(d, 2).update(shape="sine"), "duty"),        # duty/soft are square-only
    (lambda d: _mod(d, 2).update(phase=1.5), "phase"),
])
def test_invalid_documents_are_rejected_naming_the_fault(mutate, fragment):
    d = full_doc()
    mutate(d)
    with pytest.raises(ld.BridgeLightingError, match=fragment):
        ld.validate(d)


def test_an_empty_scope_is_a_parked_modifier():
    d = full_doc()
    _mod(d, 0)["scope"] = []
    assert ld.validate(d)


@pytest.mark.parametrize("src", ld.SURFACES)
def test_every_surface_validates(src):
    d = full_doc()
    d["materials"]["alcove"]["surface"] = {"src": src}
    assert ld.validate(d)


def test_object_entry_creates_once():
    d = ld.empty_doc("x")
    e = ld.object_entry(d, 4, "lamp")
    assert ld.object_entry(d, 4, "lamp") is e
    assert d["objects"] == {"4:lamp": {"block": 4, "name": "lamp"}}


def _v1():
    return {
        "format": 1, "source": "x",
        "profiles": {
            "alcove": {"fade_s": 0.5,
                       "green": {"tint": [1, 1, 1], "level": 1},
                       "red": {"tint": [1, 0.12, 0.08], "level": 0.5,
                               "wave": {"shape": "sine", "period_s": 2, "min": 0.2}}},
            "roof": {"fade_s": 0.5,
                     "green": {"tint": [1, 1, 1], "level": 1},
                     "yellow": {"tint": [1, 1, 1], "level": 0.6},
                     "red": {"tint": [1, 1, 1], "level": 0.6}},
        },
        "shapes": {
            "401:": {"block": 401, "name": "",
                     "emitter": {"profile": "alcove", "glow": {"src": "texture"},
                                 "light": {"position": [1, 2, 3], "direction": [0, 0, -1]}}},
            "423:": {"block": 423, "name": "",
                     "emitter": {"profile": "alcove", "glow": {"src": "texture"},
                                 "light": {"position": [4, 5, 6], "direction": [0, 0, -1]}}},
            "81:": {"block": 81, "name": "",
                    "emitter": {"profile": "roof", "glow": {"src": "emissive", "scale": 2}}},
            "133:": {"block": 133, "name": "", "material": {"roughness": 0}},
            "139:": {"block": 139, "name": "", "material": {"roughness": 0}},
            "299:": {"block": 299, "name": "",
                     "emitter": {"light": {"position": [7, 8, 9], "direction": [1, 0, 0]}}},
        },
    }


def test_upgrade_of_the_real_dbridge_shape_is_lossless_where_it_matters():
    d = ld.validate(ld.upgrade(_v1()))
    m, o = d["materials"], d["objects"]
    assert o["401:"]["material"] == o["423:"]["material"] == "alcove"
    assert m["alcove"]["surface"] == {"src": "texture"}
    assert m["alcove"]["modifiers"] == [
        {"type": "emitter", "tint": [1, 1, 1], "level": 1, "scope": ["green"]},
        {"type": "emitter", "tint": [1, 0.12, 0.08], "level": 0.5, "scope": ["red"]},
        {"type": "animation", "shape": "sine", "period_s": 2, "min": 0.2, "phase": 0.0,
         "scope": ["red"]}]
    assert o["401:"]["lights"] == [{"position": [1, 2, 3], "direction": [0, 0, -1]}]
    assert m["roof"]["surface"] == {"src": "emission", "strength": 2}
    assert [x["scope"] for x in m["roof"]["modifiers"]] == [["green"], ["yellow", "red"]]
    assert o["133:"]["material"] == o["139:"]["material"] == "material 1"
    assert m["material 1"] == {"roughness": 0}
    assert o["299:"] == {"block": 299, "name": "", "lights": [{"position": [7, 8, 9],
                                                               "direction": [1, 0, 0]}]}


def test_upgrade_gives_a_profile_shared_with_different_settings_its_own_material():
    v1 = _v1()
    v1["shapes"]["423:"]["emitter"]["phase"] = 0.5
    d = ld.upgrade(v1)
    assert d["objects"]["401:"]["material"] == "alcove"
    assert d["objects"]["423:"]["material"] == "alcove 2"


def test_load_upgrades_a_format_1_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    (tmp_path / "bridge_lighting").mkdir()
    (tmp_path / "bridge_lighting" / f"{HASH}.json").write_text(json.dumps(_v1()))
    res = ld.load(HASH, "x")
    assert res.error is None and res.doc["format"] == 2
```

Keep the file's other tests (lookup order, bad-file reporting, `match_shapes`), changing their docs to v2: `ld.empty_doc` already is; any test that wrote `"shapes"` writes `"objects"`, and `match_shapes` tests build `{"objects": {...}}`.

In `tests/unit/test_bridge_lighting_writer.py`, change every fixture document from v1 to v2 (`"materials"`/`"objects"` instead of `"profiles"`/`"shapes"`; use `ld.object_entry`); the byte-identical round-trip assertions stay.

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/unit/test_bridge_lighting_doc.py tests/unit/test_bridge_lighting_writer.py -q` → fail (format 2 unknown, no `upgrade`, no `object_entry`).

- [ ] **Step 3: Implement** in `lighting_doc.py`: rename the current `_wave`, `_profile`, `_glow`, `validate` to `_v1_wave`, `_v1_profile`, `_v1_glow`, `_validate_v1` (keep their bodies; `_validate_v1` checks `format == 1`), keep `_light`, and add:

```python
FORMAT = 2
STATES = ("offline", "green", "yellow", "red", "special")
SURFACES = ("auto", "emission", "texture", "flat", "none")
_WAVES = ("sine", "square")


def empty_doc(source) -> dict:
    return {"format": FORMAT, "source": str(source), "materials": {}, "objects": {}}


def object_entry(doc, block, name) -> dict:
    key = f"{block}:{name}"
    entry = doc["objects"].get(key)
    if entry is None:
        entry = {"block": int(block), "name": str(name)}
        doc["objects"][key] = entry
    return entry


def _scope(v, where):
    if not isinstance(v, list) or any(s not in STATES for s in v) or len(set(v)) != len(v):
        _fail(where, f"must be a list of distinct states from {', '.join(STATES)}")


def _modifier(m, where):
    if not isinstance(m, dict) or m.get("type") not in ("emitter", "animation"):
        _fail(f"{where}.type", "must be emitter or animation")
    if m["type"] == "emitter":
        _obj(m, where, {"type", "scope", "tint", "level"}, ("scope", "tint", "level"))
        _vec3(m["tint"], f"{where}.tint", lo=0)
        _num(m["level"], f"{where}.level", lo=0)
    else:
        _obj(m, where, {"type", "scope", "shape", "period_s", "min", "duty", "soft", "phase"},
             ("scope", "shape", "period_s"))
        _enum(m["shape"], f"{where}.shape", _WAVES)
        _num(m["period_s"], f"{where}.period_s", lo=0, lo_open=True)
        for k in ("duty", "soft"):
            if k in m:
                if m["shape"] != "square":
                    _fail(f"{where}.{k}", "only for square")
                _num(m[k], f"{where}.{k}", 0, 1)
        for k in ("min", "phase"):
            if k in m:
                _num(m[k], f"{where}.{k}", 0, 1)
    _scope(m["scope"], f"{where}.scope")


def _material(m, where):
    _obj(m, where, {"roughness", "metalness", "surface", "fade_s", "modifiers"})
    for ch in ("roughness", "metalness"):
        if ch in m:
            _num(m[ch], f"{where}.{ch}", 0, 1)
    if "surface" in m:
        _obj(m["surface"], f"{where}.surface", {"src", "strength"}, ("src",))
        _enum(m["surface"]["src"], f"{where}.surface.src", SURFACES)
        if "strength" in m["surface"]:
            _num(m["surface"]["strength"], f"{where}.surface.strength", lo=0)
    if "fade_s" in m:
        _num(m["fade_s"], f"{where}.fade_s", lo=0)
    if "modifiers" in m:
        if not isinstance(m["modifiers"], list):
            _fail(f"{where}.modifiers", "must be a list")
        for i, mod in enumerate(m["modifiers"]):
            _modifier(mod, f"{where}.modifiers[{i}]")


def validate(doc) -> dict:
    _obj(doc, "$", {"format", "source", "materials", "objects"},
         ("format", "materials", "objects"))
    if doc["format"] != FORMAT:
        _fail("$.format", f"must be {FORMAT}")
    if "source" in doc and not isinstance(doc["source"], str):
        _fail("$.source", "must be a string")
    if not isinstance(doc["materials"], dict):
        _fail("$.materials", "must be an object")
    for name, m in doc["materials"].items():
        _material(m, f"$.materials.{name}")
    if not isinstance(doc["objects"], dict):
        _fail("$.objects", "must be an object")
    for key, o in doc["objects"].items():
        where = f"$.objects.{key}"
        _obj(o, where, {"block", "name", "material", "lights"}, ("block", "name"))
        if isinstance(o["block"], bool) or not isinstance(o["block"], int) or o["block"] < 0:
            _fail(f"{where}.block", "must be a non-negative integer")
        if not isinstance(o["name"], str):
            _fail(f"{where}.name", "must be a string")
        if key != f"{o['block']}:{o['name']}":
            _fail(where, "key must be '<block>:<name>'")
        if "material" in o and o["material"] not in doc["materials"]:
            _fail(f"{where}.material", f"no material named {o['material']!r}")
        if "lights" in o:
            if not isinstance(o["lights"], list):
                _fail(f"{where}.lights", "must be a list")
            for i, light in enumerate(o["lights"]):
                _light(light, f"{where}.lights[{i}]")
    return doc


# ── format 1 -> 2 (spec §13.4) ───────────────────────────────────────────────

_V1_SRC = {"emissive": "emission", "texture": "texture", "flat": "flat"}
_V1_STATES = ("green", "yellow", "red")
_V1_WHITE = {s: {"tint": [1, 1, 1], "level": 1} for s in _V1_STATES}


def _merge(mods, mod, state):
    for m in mods:
        if {k: v for k, v in m.items() if k != "scope"} == mod:
            m["scope"].append(state)
            return
    mods.append(dict(mod, scope=[state]))


def _v1_modifiers(profile, phase):
    emitters, animations = [], []
    for s in _V1_STATES:
        st = profile.get(s)
        if st is None:
            continue
        _merge(emitters, {"type": "emitter", "tint": list(st["tint"]), "level": st["level"]}, s)
        w = st.get("wave")
        if w and w["shape"] != "steady":
            a = {"type": "animation", **{k: v for k, v in w.items()}, "phase": phase}
            _merge(animations, a, s)
    return emitters + animations


def upgrade(doc) -> dict:
    """A validated-shape `format: 1` document as `format: 2` (spec §13.4):
    each shape's material overrides + glow source/scale + profile (+ phase)
    form one material; identical materials are shared -- named after the
    profile when there is one (`<profile> 2`, ... on a clash), else
    `material N`; the light becomes lights[0]."""
    doc = _validate_v1(doc)
    out = empty_doc(doc.get("source", ""))
    by_sig = {}
    for key in sorted(doc["shapes"], key=lambda k: (doc["shapes"][k]["block"], k)):
        s = doc["shapes"][key]
        em = s.get("emitter", {})
        mat = {ch: v for ch, v in s.get("material", {}).items()}
        prof_name = em.get("profile")
        prof = doc["profiles"][prof_name] if prof_name else None
        glow = em.get("glow")
        if glow is not None or (prof is not None and "light" in em):
            surface = {"src": _V1_SRC[glow["src"]] if glow else "none"}
            if glow and glow.get("scale", 1) != 1:
                surface["strength"] = glow["scale"]
            mat["surface"] = surface
            if prof is not None and "fade_s" in prof:
                mat["fade_s"] = prof["fade_s"]
            mat["modifiers"] = _v1_modifiers(prof or _V1_WHITE, em.get("phase", 0.0))
        obj = {"block": s["block"], "name": s["name"]}
        if mat:
            sig = json.dumps(mat, sort_keys=True)
            name = by_sig.get(sig)
            if name is None:
                if prof_name:
                    name, n = prof_name, 2
                    while name in out["materials"]:
                        name, n = f"{prof_name} {n}", n + 1
                else:
                    n = 1
                    while f"material {n}" in out["materials"]:
                        n += 1
                    name = f"material {n}"
                by_sig[sig] = name
                out["materials"][name] = mat
            obj["material"] = name
        if "light" in em:
            obj["lights"] = [dict(em["light"])]
        if len(obj) > 2:
            out["objects"][key] = obj
    return out
```

`load`: change `doc = validate(json.loads(...))` to

```python
        raw = json.loads(path.read_text(encoding="utf-8"))
        doc = validate(upgrade(raw) if isinstance(raw, dict) and raw.get("format") == 1
                       else raw)
```

`match_shapes`: `doc["objects"]` in place of `doc["shapes"]`. Delete `shape_entry`. Module docstring: "per-object `material` link and `lights`, plus a `materials` library (spec §13); `format: 1` files are upgraded on load."

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_bridge_lighting_doc.py tests/unit/test_bridge_lighting_writer.py -q` → pass. (Consumers — lights, glow, materials, runtime, panel — break until Tasks 4–6; that is expected.)

- [ ] **Step 5: Commit** — `engine/bridge_editor/lighting_doc.py engine/bridge_editor/lighting_writer.py tests/unit/test_bridge_lighting_doc.py tests/unit/test_bridge_lighting_writer.py`; message `feat(bridge): lighting document format 2 -- material library + objects, format 1 upgraded on load (spec §13.4)`.

---

### Task 4: Evaluation — behaviour, glow, lights, finish overrides

**Files:** Create `engine/bridge_editor/behaviour.py`; rewrite `engine/bridge_editor/glow.py`, `engine/bridge_editor/lights.py`, `engine/bridge_editor/materials.py`; delete `engine/bridge_editor/profiles.py` and `tests/unit/test_bridge_profiles.py`; Tests: create `tests/unit/test_bridge_behaviour.py`; rewrite `tests/unit/test_bridge_glow.py`, `tests/unit/test_bridge_lights.py`, `tests/unit/test_bridge_materials.py`.

**Interfaces:**
- Produces `behaviour`: `STATES` (= `ld.STATES`), `state_name(i) -> str` (0 green, 1 yellow, 2 red, 3 offline, 4 special, else green), `state_index(name) -> int`, `wave_factor(anim, t) -> float`, `output(material, state, t) -> ((r, g, b), k)`, `has_emitter(material) -> bool`, `WHITE` (a material lighting every state white at 1), `DEFAULT_FADE_S = 0.5`, `StateFade(state_name)` with `.set_state(name)`, `.advance(dt)`, `.output(material, t)`.
- Produces `glow.SRC = {"emission": 0, "texture": 1, "flat": 2}`, `glow.glow_objects(doc, matched, meshes) -> ([(mesh, src, material, strength)], warnings)`, `glow.live(objs, fade, t) -> [(mesh, src, rgb, level)]`.
- Produces `lights.spots(doc, matched) -> (spots9, warnings)` (one per object light, mesh order, cap 32), `lights.live_colours(doc, matched, fade, t)`, `lights.to_linear`, `MAX_SPOTS`, `DEFAULT_INTENSITY`.
- Produces `materials.overrides(doc, matched) -> [(mesh, rough, metal)]` from each object's material.

- [ ] **Step 1: Failing tests.**

`tests/unit/test_bridge_behaviour.py`:

```python
"""Material behaviour over time (spec §13.2)."""
import math

import pytest

from engine.bridge_editor import behaviour as bh

ALCOVE = {"fade_s": 0.5, "modifiers": [
    {"type": "emitter", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
    {"type": "emitter", "scope": ["red"], "tint": [1, 0.1, 0.1], "level": 0.5},
    {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2.0, "min": 0.2,
     "phase": 0.0}]}


def test_state_names_and_indices():
    assert [bh.state_name(i) for i in range(6)] == ["green", "yellow", "red", "offline",
                                                    "special", "green"]
    assert bh.state_index("offline") == 3


def test_emitters_add_and_animations_multiply():
    m = {"modifiers": [
        {"type": "emitter", "scope": ["red"], "tint": [1, 0, 0], "level": 1},
        {"type": "emitter", "scope": ["red"], "tint": [0, 0, 1], "level": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "square", "period_s": 1, "duty": 0.5,
         "min": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "square", "period_s": 1, "duty": 0.5,
         "min": 0.5, "phase": 0.5}]}
    rgb, k = bh.output(m, "red", 0.25)          # first on (1), second off (0.5)
    assert rgb == pytest.approx((0.5, 0.0, 0.25))
    assert k == pytest.approx(0.75)


def test_out_of_scope_and_parked_modifiers_do_nothing():
    assert bh.output(ALCOVE, "yellow", 0.0) == ((0.0, 0.0, 0.0), 0.0)
    m = {"modifiers": [{"type": "emitter", "scope": [], "tint": [1, 1, 1], "level": 1}]}
    assert bh.output(m, "green", 0.0) == ((0.0, 0.0, 0.0), 0.0)


def test_the_animation_phase_shifts_the_sine():
    a = dict(ALCOVE["modifiers"][2])
    assert bh.wave_factor(a, 0.0) == pytest.approx(1.0)
    assert bh.wave_factor(dict(a, phase=0.5), 0.0) == pytest.approx(0.2)


def test_white_lights_every_state():
    for s in bh.STATES:
        assert bh.output(bh.WHITE, s, 0.0) == ((1.0, 1.0, 1.0), 1.0)


def test_fade_is_continuous_across_two_changes():
    f = bh.StateFade("red")
    f.set_state("green")
    f.advance(0.25)
    before = f.output(ALCOVE, 0.25)
    f.set_state("red")
    after = f.output(ALCOVE, 0.25)
    assert after[1] == pytest.approx(before[1])
    assert all(math.isfinite(c) for c in after[0])
    f.advance(10.0)
    assert f.output(ALCOVE, 10.25) == bh.output(ALCOVE, "red", 10.25)
```

`tests/unit/test_bridge_glow.py` (replace):

```python
"""Objects -> per-mesh glow (spec §13.2)."""
import pytest

from engine.bridge_editor import behaviour as bh, glow, lighting_doc as ld

MESHES = [{"mesh": 3, "maps": {"emissive": True}}, {"mesh": 4, "maps": {"emissive": False}}]
ROOF = {"surface": {"src": "auto", "strength": 2}, "modifiers": [
    {"type": "emitter", "scope": ["green", "red"], "tint": [0.5, 0.5, 1], "level": 0.6}]}


def _doc():
    d = ld.empty_doc("x")
    d["materials"]["roof"] = ROOF
    d["materials"]["finish only"] = {"roughness": 0}
    ld.object_entry(d, 10, "panel")["material"] = "roof"
    ld.object_entry(d, 11, "alcove")["material"] = "roof"
    ld.object_entry(d, 12, "wall")["material"] = "finish only"
    return d


MATCHED = {"10:panel": 3, "11:alcove": 4, "12:wall": 5}


def test_auto_surface_resolves_per_object():
    objs, warnings = glow.glow_objects(_doc(), MATCHED, MESHES)
    assert [(m, s, st) for m, s, _, st in objs] == [(3, 0, 2.0), (4, 1, 2.0)]
    assert warnings == []


def test_a_material_without_emitters_adds_no_glow():
    objs, _ = glow.glow_objects(_doc(), {"12:wall": 5}, MESHES)
    assert objs == []


def test_emission_surface_without_a_map_is_skipped_with_a_warning():
    d = _doc()
    d["materials"]["roof"]["surface"]["src"] = "emission"
    objs, warnings = glow.glow_objects(d, MATCHED, MESHES)
    assert [o[0] for o in objs] == [3]
    assert warnings == ["11:alcove: material 'roof' glows through an emission map but "
                        "this object's texture has none; skipped"]


def test_none_surface_adds_no_glow():
    d = _doc()
    d["materials"]["roof"]["surface"]["src"] = "none"
    assert glow.glow_objects(d, MATCHED, MESHES)[0] == []


def test_live_scales_by_strength():
    objs, _ = glow.glow_objects(_doc(), MATCHED, MESHES)
    (m, s, rgb, k), _ = glow.live(objs, bh.StateFade("red"), 0.0)
    assert (m, s) == (3, 0)
    assert rgb == pytest.approx((0.6, 0.6, 1.2))
    assert k == pytest.approx(1.2)
```

`tests/unit/test_bridge_lights.py` (replace):

```python
"""Object lights (spec §13.2)."""
import pytest

from engine.bridge_editor import behaviour as bh, lighting_doc as ld, lights


def _doc():
    d = ld.empty_doc("x")
    d["materials"]["alcove"] = {"modifiers": [
        {"type": "emitter", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
        {"type": "emitter", "scope": ["red"], "tint": [1, 0.5, 0.5], "level": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2, "min": 0.2}]}
    e = ld.object_entry(d, 5, "roof")
    e["material"] = "alcove"
    e["lights"] = [{"position": [1, 2, 3], "direction": [0, 0, -1], "intensity": 100},
                   {"position": [4, 5, 6], "direction": [0, 0, -1], "intensity": 50}]
    ld.object_entry(d, 6, "lamp")["lights"] = [
        {"position": [0, 0, 9], "direction": [0, 0, -1], "inner_deg": 10, "outer_deg": 20,
         "range": 50, "intensity": 900, "light_scale": 2}]
    return d


MATCHED = {"5:roof": 1, "6:lamp": 2}


def test_every_object_light_is_listed_in_mesh_order():
    spots, warnings = lights.spots(_doc(), MATCHED)
    assert [s[0] for s in spots] == [(1, 2, 3), (4, 5, 6), (0, 0, 9)]
    assert warnings == []


def test_no_material_is_steady_white_with_light_scale():
    spots, _ = lights.spots(_doc(), {"6:lamp": 2})
    assert spots == [((0, 0, 9), (0, 0, -1), 10, 20, 50, (1.0, 1.0, 1.0), 1800,
                      (1.0, 1.0, 1.0), (1.0, 1.0, 1.0))]


def test_capture_colours_are_steady_states_only():
    (a, b, _), _ = lights.spots(_doc(), MATCHED)
    assert a[7] == pytest.approx((1.0, 1.0, 1.0))      # green steady
    assert a[8] == (0.0, 0.0, 0.0)                       # yellow: nothing scoped


def test_live_colour_is_linear_radiance_and_off_states_are_zero():
    cols = lights.live_colours(_doc(), MATCHED, bh.StateFade("yellow"), 0.0)
    assert cols[0] == (0.0, 0.0, 0.0) and len(cols) == 3
    cols = lights.live_colours(_doc(), MATCHED, bh.StateFade("red"), 0.0)
    assert cols[0] == pytest.approx(tuple(100 * c for c in lights.to_linear((0.5, 0.25, 0.25))))


def test_more_than_32_are_reported_by_name():
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "s")["lights"] = [{"position": [0, 0, 0], "direction": [0, 0, -1]}] * 34
    spots, warnings = lights.spots(d, {"1:s": 1})
    assert len(spots) == 32
    assert warnings == ["1:s light 33: dropped (more than 32 bridge lights)",
                        "1:s light 34: dropped (more than 32 bridge lights)"]
```

`tests/unit/test_bridge_materials.py` (replace its body):

```python
from engine.bridge_editor import lighting_doc as ld, materials


def test_overrides_come_from_each_objects_material():
    d = ld.empty_doc("x")
    d["materials"]["polished"] = {"roughness": 0.1}
    d["materials"]["metal"] = {"roughness": 0.3, "metalness": 1}
    d["materials"]["glow only"] = {"surface": {"src": "auto"}}
    for b, m in ((1, "polished"), (2, "metal"), (3, "glow only")):
        ld.object_entry(d, b, "x")["material"] = m
    ld.object_entry(d, 4, "x")
    got = materials.overrides(d, {"1:x": 10, "2:x": 11, "3:x": 12, "4:x": 13})
    assert got == [(10, 0.1, -1.0), (11, 0.3, 1.0)]
```

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/unit/test_bridge_behaviour.py tests/unit/test_bridge_glow.py tests/unit/test_bridge_lights.py tests/unit/test_bridge_materials.py -q`.

- [ ] **Step 3: Implement.**

`engine/bridge_editor/behaviour.py`:

```python
"""Material behaviour over time (spec 2026-10-08-bridge-emitters §13.2). Pure.

A material's modifiers each carry a scope (bridge states). In state s the
output is (sum of emitters scoped to s) x (product of animations scoped to
s): rgb = sum(tint x level) x waves, k = sum(level) x waves (the received-
light dip, §11.2). DISPLAY space; lights convert (lights.py). State changes
cross-fade over the material's fade_s from the LIVE output."""
import math

from engine.bridge_editor import lighting_doc as ld

STATES = ld.STATES
_BY_INDEX = {0: "green", 1: "yellow", 2: "red", 3: "offline", 4: "special"}
DEFAULT_FADE_S = 0.5
MAX_FADE_CHAIN = 4
WHITE = {"modifiers": [{"type": "emitter", "scope": list(STATES), "tint": [1, 1, 1],
                        "level": 1}]}


def state_name(i) -> str:
    return _BY_INDEX.get(int(i), "green")


def state_index(name) -> int:
    return {v: k for k, v in _BY_INDEX.items()}[name]


def has_emitter(material) -> bool:
    return any(m["type"] == "emitter" for m in material.get("modifiers", ()))


def _smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def wave_factor(anim, t) -> float:
    """1 at the peak, `min` at the trough; sine peaks at phase 0; square is
    on for `duty` with `soft` rise/fall (fractions of the period)."""
    lo = float(anim.get("min", 0.0))
    x = (float(t) / float(anim["period_s"]) + float(anim.get("phase", 0.0))) % 1.0
    if anim["shape"] == "sine":
        f = 0.5 + 0.5 * math.cos(2.0 * math.pi * x)
    else:
        duty, soft = float(anim.get("duty", 0.5)), float(anim.get("soft", 0.0))
        if soft <= 0.0:
            f = 1.0 if x < duty else 0.0
        else:
            f = min(_smooth(x / soft), 1.0 - _smooth((x - duty) / soft))
    return lo + (1.0 - lo) * f


def output(material, state, t):
    rgb, k, f = [0.0, 0.0, 0.0], 0.0, 1.0
    for m in material.get("modifiers", ()):
        if state not in m["scope"]:
            continue
        if m["type"] == "emitter":
            lv = float(m["level"])
            for i in range(3):
                rgb[i] += float(m["tint"][i]) * lv
            k += lv
        else:
            f *= wave_factor(m, t)
    return tuple(c * f for c in rgb), k * f


class StateFade:
    """The state the bridge shows and the cross-fade into it. A change mid-
    fade freezes the fade in progress as the new fade's source (never a jump);
    the chain is capped at MAX_FADE_CHAIN."""

    def __init__(self, state="green"):
        self.state, self.since, self.source = state, math.inf, None

    def set_state(self, state):
        if state == self.state:
            return
        frozen = StateFade.__new__(StateFade)
        frozen.state, frozen.since, frozen.source = self.state, self.since, self.source
        node, depth = frozen, 1
        while node.source is not None:
            if depth >= MAX_FADE_CHAIN:
                node.source = None
                break
            node, depth = node.source, depth + 1
        self.state, self.since, self.source = state, 0.0, frozen

    def advance(self, dt):
        self.since += max(float(dt), 0.0)

    def output(self, material, t):
        new_rgb, new_k = output(material, self.state, t)
        fade = float(material.get("fade_s", DEFAULT_FADE_S))
        if self.source is None or fade <= 0.0 or self.since >= fade:
            return new_rgb, new_k
        old_rgb, old_k = self.source.output(material, t)
        f = self.since / fade
        return (tuple(a + (b - a) * f for a, b in zip(old_rgb, new_rgb)),
                old_k + (new_k - old_k) * f)
```

`engine/bridge_editor/glow.py` (replace):

```python
"""Objects -> per-mesh emitter glow (spec 2026-10-08-bridge-emitters §13.2):
an object glows when its material has an emitter; WHAT glows is the
material's surface resolved against the object's own texture (`auto`: its
emission map if it has one, else its own texture)."""
from engine.bridge_editor import behaviour

SRC = {"emission": 0, "texture": 1, "flat": 2}


def glow_objects(doc, matched, meshes):
    has_map = {m["mesh"]: bool((m.get("maps") or {}).get("emissive")) for m in meshes}
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        name = doc["objects"].get(key, {}).get("material")
        mat = doc["materials"].get(name) if name else None
        if mat is None or not behaviour.has_emitter(mat):
            continue
        mesh = matched[key]
        surface = mat.get("surface", {})
        src = surface.get("src", "auto")
        if src == "none":
            continue
        if src == "auto":
            src = "emission" if has_map.get(mesh) else "texture"
        if src == "emission" and not has_map.get(mesh):
            warnings.append(f"{key}: material {name!r} glows through an emission map but "
                            "this object's texture has none; skipped")
            continue
        out.append((mesh, SRC[src], mat, float(surface.get("strength", 1.0))))
    return out, warnings


def live(objs, fade, t):
    out = []
    for mesh, src, mat, strength in objs:
        rgb, k = fade.output(mat, t)
        out.append((mesh, src, tuple(c * strength for c in rgb), k * strength))
    return out
```

`engine/bridge_editor/lights.py` (replace):

```python
"""Object lights (spec 2026-10-08-bridge-emitters §13.2, §11.4). The spot
LIST is static -- every light of every matched object, mesh order, with its
green and yellow/red probe-capture colours -- so a state change or a pulse
never recaptures the probes; `live_colours` gives the radiance per frame in
the same order. A light's colour follows its object's material (steady white
without one), display -> linear by ^2.2. A capture colour is the steady
value in that state, 0 when an animation runs there."""
from engine.bridge_editor import behaviour

MAX_SPOTS = 32
DEFAULT_INTENSITY = 2000.0
GAMMA = 2.2


def to_linear(rgb):
    return tuple(max(float(c), 0.0) ** GAMMA for c in rgb)


def _intensity(light):
    return light.get("intensity", DEFAULT_INTENSITY) * light.get("light_scale", 1.0)


def _material(doc, obj):
    name = obj.get("material")
    return doc["materials"].get(name) if name else behaviour.WHITE


def _lit(doc, matched):
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        obj = doc["objects"].get(key, {})
        mat = _material(doc, obj) or behaviour.WHITE
        for i, light in enumerate(obj.get("lights", ())):
            if len(out) >= MAX_SPOTS:
                warnings.append(f"{key} light {i + 1}: dropped (more than {MAX_SPOTS} "
                                "bridge lights)")
                continue
            out.append((light, mat))
    return out, warnings


def _capture(mat, state):
    if any(m["type"] == "animation" and state in m["scope"]
           for m in mat.get("modifiers", ())):
        return (0.0, 0.0, 0.0)
    rgb, _ = behaviour.output(mat, state, 0.0)
    return to_linear(rgb)


def spots(doc, matched):
    lit, warnings = _lit(doc, matched)
    out = []
    for light, mat in lit:
        green = _capture(mat, "green")
        out.append((tuple(light["position"]), tuple(light["direction"]),
                    light.get("inner_deg", 30), light.get("outer_deg", 60),
                    light.get("range", 200), green, _intensity(light),
                    green, _capture(mat, "yellow")))
    return out, warnings


def live_colours(doc, matched, fade, t):
    lit, _ = _lit(doc, matched)
    out = []
    for light, mat in lit:
        rgb, _k = fade.output(mat, t)
        k = _intensity(light)
        out.append(tuple(c * k for c in to_linear(rgb)))
    return out
```

`engine/bridge_editor/materials.py` (replace):

```python
"""Objects -> per-mesh roughness/metalness overrides from each object's
material (spec §13.2; §9.2 source B). -1.0 = no override for a channel."""


def overrides(doc, matched):
    out = []
    for key, mesh in matched.items():
        name = doc["objects"].get(key, {}).get("material")
        mat = doc["materials"].get(name) if name else None
        if not mat or ("roughness" not in mat and "metalness" not in mat):
            continue
        out.append((int(mesh), float(mat.get("roughness", -1.0)),
                    float(mat.get("metalness", -1.0))))
    return sorted(out)
```

Delete `engine/bridge_editor/profiles.py` and `tests/unit/test_bridge_profiles.py` (`git rm`).

- [ ] **Step 4: Run** — the four test files → pass.

- [ ] **Step 5: Commit** — `git add engine/bridge_editor/behaviour.py engine/bridge_editor/glow.py engine/bridge_editor/lights.py engine/bridge_editor/materials.py tests/unit/test_bridge_behaviour.py tests/unit/test_bridge_glow.py tests/unit/test_bridge_lights.py tests/unit/test_bridge_materials.py` and `git rm engine/bridge_editor/profiles.py tests/unit/test_bridge_profiles.py`; message `feat(bridge): material behaviour -- scoped emitters add, animations multiply; object glow, lights and finish from materials (spec §13.2)`.

---

### Task 5: Runtime on materials and five states

**Files:** Modify `engine/bridge_editor/runtime.py`; Test `tests/unit/test_bridge_runtime.py`.

**Interfaces:**
- Consumes Task 4. `on_alert(level)` takes a bridge state int (0-4) → `self._fade.set_state(behaviour.state_name(level))`; `attach` seeds `behaviour.StateFade(behaviour.state_name(self._alert()))`; `push` uses `glow.glow_objects`.

- [ ] **Step 1: Failing tests** — in `tests/unit/test_bridge_runtime.py` replace `_glow_doc` with a v2 document and add an offline test:

```python
def _glow_doc(proj):
    d = ld.empty_doc("x")
    d["materials"]["p"] = {"fade_s": 1.0, "surface": {"src": "flat"}, "modifiers": [
        {"type": "emitter", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
        {"type": "emitter", "scope": ["red"], "tint": [1, 0, 0], "level": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2.0, "min": 0.0}]}
    e = ld.object_entry(d, 3, "floor")
    e["material"] = "p"
    e["lights"] = [{"position": [0, 0, 9], "direction": [0, 0, -1], "intensity": 10}]
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")


def test_offline_state_turns_an_unscoped_material_off(proj):
    _glow_doc(proj)
    io = FakeIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (0, 0, 0), alert=lambda: 3)
    rt.attach("iid")
    (_, _, rgb, level), = last(io, "set_bridge_glow")[2]
    assert level == 0.0 and rgb == (0.0, 0.0, 0.0)
```

Every other test in the file that builds a document with `ld.shape_entry(..., "material"|"emitter")` switches to v2: `d["materials"]["m"] = {"roughness": 0.25}` + `ld.object_entry(d, 3, "floor")["material"] = "m"` for material tests; lights → `object_entry(...)["lights"] = [ {...} ]`. Assertions on pushed calls stay.

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/unit/test_bridge_runtime.py -q`.

- [ ] **Step 3: Implement** in `runtime.py`: import `behaviour` instead of `profiles`; `self._fade = behaviour.StateFade()`; in `attach`, `self._fade = behaviour.StateFade(behaviour.state_name(self._alert()))`; in `push`, `glow.glow_objects(doc, self._matched, self._meshes)`; `on_alert` body `self._fade.set_state(behaviour.state_name(level))` (docstring: "a bridge state 0-4, §13.1").

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_bridge_runtime.py tests/unit/test_bridge_lighting.py tests/host/test_bridge_runtime_swap.py -q` → pass.

- [ ] **Step 5: Commit** — `engine/bridge_editor/runtime.py tests/unit/test_bridge_runtime.py`; message `feat(bridge): BridgeRuntime evaluates materials across the five states`.

---

### Task 6: Document editing operations (`editing.py`)

**Files:** Create `engine/bridge_editor/editing.py`; Test `tests/unit/test_bridge_editing.py`.

**Interfaces:**
- Produces (all mutate `doc` in place; return an error string or None where noted):
  - `link(doc, block, name, material)` (None/'' unlinks; prunes an empty object)
  - `new_material(doc, block, name) -> str` (an empty material, linked)
  - `duplicate(doc, block, name) -> str|None` (copy of the linked material as `<name> copy`, `<name> copy 2`…, linked)
  - `rename(doc, old, new) -> str|None` (error text on refusal)
  - `users(doc) -> {material: count}`
  - `set_finish(mat, ch, raw)`, `clear_finish(mat, ch)`
  - `set_surface(mat, field, raw)` (`src` in `ld.SURFACES`; `strength` ≥ 0)
  - `set_fade(mat, raw)`
  - `add_modifier(mat, kind, state)`, `remove_modifier(mat, i)`, `toggle_scope(mat, i, state)`, `set_modifier(mat, i, field, raw)`
  - `add_light(doc, block, name, position, direction)`, `remove_light(doc, block, name, i)`, `set_light(light, field, raw)`
- Constants: `MIN_PERIOD_S = 0.05`; light defaults as the panel's today.

- [ ] **Step 1: Failing tests** — `tests/unit/test_bridge_editing.py`:

```python
"""Pure document edits for the Bridge Editor (spec §13)."""
import pytest

from engine.bridge_editor import editing as ed, lighting_doc as ld


def _doc():
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "a")
    ld.object_entry(d, 2, "b")
    return d


def test_new_material_links_and_names_in_order():
    d = _doc()
    assert ed.new_material(d, 1, "a") == "material 1"
    assert ed.new_material(d, 2, "b") == "material 2"
    assert d["objects"]["1:a"]["material"] == "material 1"
    assert d["materials"]["material 1"] == {}


def test_link_unlink_prunes_and_users_count():
    d = _doc()
    ed.new_material(d, 1, "a")
    ed.link(d, 2, "b", "material 1")
    assert ed.users(d) == {"material 1": 2}
    ed.link(d, 2, "b", "")
    assert "2:b" not in d["objects"]
    assert ed.users(d) == {"material 1": 1}


def test_duplicate_copies_and_relinks_only_this_object():
    d = _doc()
    ed.new_material(d, 1, "a")
    ed.link(d, 2, "b", "material 1")
    d["materials"]["material 1"]["roughness"] = 0.3
    assert ed.duplicate(d, 2, "b") == "material 1 copy"
    assert d["objects"]["1:a"]["material"] == "material 1"
    assert d["materials"]["material 1 copy"] == {"roughness": 0.3}
    assert ed.duplicate(d, 2, "b") == "material 1 copy copy"


def test_rename_moves_every_link_and_refuses_clashes():
    d = _doc()
    ed.new_material(d, 1, "a")
    ed.link(d, 2, "b", "material 1")
    ed.new_material(d, 3, "c")
    assert ed.rename(d, "material 1", "alcove") is None
    assert d["objects"]["1:a"]["material"] == d["objects"]["2:b"]["material"] == "alcove"
    assert "exists" in ed.rename(d, "alcove", "material 2")
    assert "empty" in ed.rename(d, "alcove", "  ")


def test_finish_surface_fade_clamp():
    m = {}
    ed.set_finish(m, "roughness", "1.7")
    ed.set_surface(m, "src", "emission")
    ed.set_surface(m, "src", "glow")              # refused: not a surface
    ed.set_surface(m, "strength", "-2")
    ed.set_fade(m, "-1")
    assert m == {"roughness": 1.0, "surface": {"src": "emission", "strength": 0.0},
                 "fade_s": 0.0}
    ed.clear_finish(m, "roughness")
    assert "roughness" not in m


def test_modifiers_add_scope_and_fields():
    m = {}
    ed.add_modifier(m, "emitter", "red")
    ed.add_modifier(m, "animation", "red")
    assert m["modifiers"] == [
        {"type": "emitter", "scope": ["red"], "tint": [1, 1, 1], "level": 1.0},
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2.0, "min": 0.0,
         "phase": 0.0}]
    ed.toggle_scope(m, 0, "green")
    ed.toggle_scope(m, 0, "red")
    assert m["modifiers"][0]["scope"] == ["green"]
    ed.set_modifier(m, 0, "tint", "0.5,0.1,0.05")
    assert m["modifiers"][0]["tint"] == pytest.approx([1.0, 0.2, 0.1])
    ed.set_modifier(m, 0, "level", "-1")
    assert m["modifiers"][0]["level"] == 0.0
    ed.set_modifier(m, 1, "shape", "square")
    assert m["modifiers"][1] == {"type": "animation", "scope": ["red"], "shape": "square",
                                 "period_s": 2.0, "min": 0.0, "phase": 0.0, "duty": 0.5,
                                 "soft": 0.0}
    ed.set_modifier(m, 1, "period_s", "0.001")
    ed.set_modifier(m, 1, "phase", "3")
    ed.set_modifier(m, 1, "shape", "sine")
    assert m["modifiers"][1] == {"type": "animation", "scope": ["red"], "shape": "sine",
                                 "period_s": 0.05, "min": 0.0, "phase": 1.0}
    ed.set_modifier(m, 1, "duty", "0.3")           # square only: ignored
    assert "duty" not in m["modifiers"][1]
    ed.remove_modifier(m, 0)
    assert len(m["modifiers"]) == 1
    d = ld.empty_doc("x")
    d["materials"]["m"] = m
    ld.validate(d)


def test_lights_add_remove_and_clamp():
    d = _doc()
    ed.add_light(d, 1, "a", (1, 2, 3), (0, 0, -1))
    ed.add_light(d, 1, "a", (4, 5, 6), (0, 0, -1))
    light = d["objects"]["1:a"]["lights"][1]
    ed.set_light(light, "inner_deg", "120")
    ed.set_light(light, "outer_deg", "10")
    assert light["inner_deg"] == 10.0 and light["outer_deg"] == 10.0
    ed.remove_light(d, 1, "a", 0)
    assert d["objects"]["1:a"]["lights"][0]["position"] == [4, 5, 6]
    ed.remove_light(d, 1, "a", 0)
    assert "1:a" not in d["objects"]
```

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/unit/test_bridge_editing.py -q` → ModuleNotFoundError.

- [ ] **Step 3: Implement** `engine/bridge_editor/editing.py`:

```python
"""Pure document edits for the Bridge Editor (spec 2026-10-08-bridge-emitters
§13). Every value is clamped to the schema before it enters the document
(§12.3), so a save can never be refused for something the editor wrote."""
import copy
import math

from engine.bridge_editor import lighting_doc as ld

MIN_PERIOD_S = 0.05
LIGHT_INNER_DEG, LIGHT_OUTER_DEG, LIGHT_RANGE = 30.0, 60.0, 200.0
LIGHT_INTENSITY = 2000.0
_LIGHT_MIN_RANGE = 0.01
_WAVE_DEFAULTS = {"sine": {}, "square": {"duty": 0.5, "soft": 0.0}}


def _num(raw, lo=None, hi=None):
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _key(block, name):
    return f"{block}:{name}"


def _prune(doc, block, name):
    o = doc["objects"].get(_key(block, name))
    if o is not None and set(o) == {"block", "name"}:
        del doc["objects"][_key(block, name)]


def users(doc):
    out = {}
    for o in doc["objects"].values():
        if o.get("material"):
            out[o["material"]] = out.get(o["material"], 0) + 1
    return out


def link(doc, block, name, material):
    if material and material not in doc["materials"]:
        return
    o = ld.object_entry(doc, block, name)
    if material:
        o["material"] = material
    else:
        o.pop("material", None)
        _prune(doc, block, name)


def _free(doc, base):
    if base not in doc["materials"]:
        return base
    n = 2
    while f"{base} {n}" in doc["materials"]:
        n += 1
    return f"{base} {n}"


def new_material(doc, block, name):
    n = 1
    while f"material {n}" in doc["materials"]:
        n += 1
    mat = f"material {n}"
    doc["materials"][mat] = {}
    link(doc, block, name, mat)
    return mat


def duplicate(doc, block, name):
    cur = doc["objects"].get(_key(block, name), {}).get("material")
    if not cur:
        return None
    new = f"{cur} copy"
    while new in doc["materials"]:
        new = f"{new} copy"
    doc["materials"][new] = copy.deepcopy(doc["materials"][cur])
    link(doc, block, name, new)
    return new


def rename(doc, old, new):
    new = new.strip()
    if not new:
        return "Rename refused: empty name"
    if new == old:
        return None
    if new in doc["materials"]:
        return f"Rename refused: a material named {new!r} exists"
    doc["materials"][new] = doc["materials"].pop(old)
    for o in doc["objects"].values():
        if o.get("material") == old:
            o["material"] = new
    return None


def set_finish(mat, ch, raw):
    v = _num(raw, 0.0, 1.0)
    if ch in ("roughness", "metalness") and v is not None:
        mat[ch] = v


def clear_finish(mat, ch):
    mat.pop(ch, None)


def set_surface(mat, field, raw):
    s = mat.setdefault("surface", {"src": "auto"})
    if field == "src" and raw in ld.SURFACES:
        s["src"] = raw
    elif field == "strength":
        v = _num(raw, lo=0.0)
        if v is not None:
            s["strength"] = v


def set_fade(mat, raw):
    v = _num(raw, lo=0.0)
    if v is not None:
        mat["fade_s"] = v


def add_modifier(mat, kind, state):
    scope = [state] if state in ld.STATES else []
    if kind == "emitter":
        m = {"type": "emitter", "scope": scope, "tint": [1, 1, 1], "level": 1.0}
    elif kind == "animation":
        m = {"type": "animation", "scope": scope, "shape": "sine", "period_s": 2.0,
             "min": 0.0, "phase": 0.0}
    else:
        return
    mat.setdefault("modifiers", []).append(m)


def _mod(mat, i):
    mods = mat.get("modifiers", [])
    return mods[i] if 0 <= i < len(mods) else None


def remove_modifier(mat, i):
    if _mod(mat, i) is not None:
        del mat["modifiers"][i]


def toggle_scope(mat, i, state):
    m = _mod(mat, i)
    if m is None or state not in ld.STATES:
        return
    if state in m["scope"]:
        m["scope"].remove(state)
    else:
        m["scope"] = [s for s in ld.STATES if s in m["scope"] or s == state]


def set_modifier(mat, i, field, raw):
    m = _mod(mat, i)
    if m is None:
        return
    if m["type"] == "emitter":
        if field == "tint":
            try:
                rgb = [max(0.0, float(c)) for c in str(raw).split(",")]
            except ValueError:
                return
            if len(rgb) != 3 or not all(math.isfinite(c) for c in rgb):
                return
            top = max(rgb)
            m["tint"] = [round(c / top, 4) for c in rgb] if top > 0 else [0.0, 0.0, 0.0]
        elif field == "level":
            v = _num(raw, lo=0.0)
            if v is not None:
                m["level"] = v
        return
    if field == "shape" and raw in _WAVE_DEFAULTS:
        keep = {k: m[k] for k in ("type", "scope", "period_s", "min", "phase") if k in m}
        extra = {k: m.get(k, d) for k, d in _WAVE_DEFAULTS[raw].items()}
        m.clear()
        m.update(keep, shape=raw, **extra)
    elif field == "period_s":
        v = _num(raw, lo=MIN_PERIOD_S)
        if v is not None:
            m["period_s"] = v
    elif field in ("min", "phase") or (field in ("duty", "soft") and m["shape"] == "square"):
        v = _num(raw, 0.0, 1.0)
        if v is not None:
            m[field] = v


def add_light(doc, block, name, position, direction):
    o = ld.object_entry(doc, block, name)
    o.setdefault("lights", []).append({
        "position": list(position), "direction": list(direction),
        "inner_deg": LIGHT_INNER_DEG, "outer_deg": LIGHT_OUTER_DEG,
        "range": LIGHT_RANGE, "intensity": LIGHT_INTENSITY})


def remove_light(doc, block, name, i):
    o = doc["objects"].get(_key(block, name))
    if not o or not (0 <= i < len(o.get("lights", []))):
        return
    del o["lights"][i]
    if not o["lights"]:
        del o["lights"]
    _prune(doc, block, name)


def set_light(light, field, raw):
    v = _num(raw)
    if v is None:
        return
    if field in ("inner_deg", "outer_deg"):
        v = min(90.0, max(0.0, v))
        light[field] = v
        if field == "inner_deg" and light.get("outer_deg", 90.0) < v:
            light["outer_deg"] = v
        elif field == "outer_deg" and v < light.get("inner_deg", 0.0):
            light["inner_deg"] = v
    elif field == "range":
        light[field] = max(_LIGHT_MIN_RANGE, v)
    elif field == "intensity":
        light[field] = max(0.0, v)
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_bridge_editing.py -q` → pass.

- [ ] **Step 5: Commit** — `engine/bridge_editor/editing.py tests/unit/test_bridge_editing.py`; message `feat(bridge): pure document edits for materials, modifiers and object lights (spec §13)`.

---

### Task 7: The panel — Object / Material model, bar state, Shift fly

**Files:** Modify `engine/bridge_editor/fly_camera.py`; rewrite the editing/payload half of `engine/ui/bridge_emitters_panel.py`; Test `tests/unit/test_bridge_emitters_panel.py` (rewrite the edit/payload tests), `tests/unit/test_bridge_fly_camera.py` (speed).

**Interfaces:**
- Consumes `editing.*`, `behaviour.state_name/state_index`.
- Produces actions (after `bridge-emitters/`): bar — `state:<name>`, `preview-toggle`, `undo`, `revert`, `save`, `close`; side — `tab:object|material`, `expand:<id>`, `deselect`; object — `material-link:<name or empty>`, `material-new`, `material-duplicate`, `light-add`, `light-remove:<i>`, `light-place:<i>`, `light-aim:<i>`, `light:<i>:<field>:<v>`; material — `material-rename:<name>`, `finish:<ch>:<v>`, `finish-clear:<ch>`, `surface:<src|strength>:<v>`, `fade:<v>`, `mod-add:<emitter|animation>`, `mod-remove:<i>`, `mod:<i>:scope:<state>`, `mod:<i>:<field>:<v>`.
- Produces payload: `{visible, in_bridge, state, playing, dirty, can_save, can_undo, status, hint, hover, selected}` where `selected` is None or `{key, block, name, display_name, node_chain, textures, tab, expanded, has_emission_map, material, library: [{name, used_by}], lights: [...], material_data: {name, finish: {roughness: {value, source}, metalness: {...}}, surface: {src, strength}, fade_s, modifiers: [...]} | None}`.
- `preview_alert()` → `behaviour.state_index(self._state)` while open, else None; `preview_dt` unchanged.
- Fly: hold Shift; `FlyCamera.adjust_speed(notches)` (×1.25 per notch, clamped 0.1–16 × base); no fast/slow.
- Hit regions: `BAR_CSS_W = 560`, `BAR_CSS_H = 64` (top-left) and the dock (`DOCK_CSS_PX`, right) only while something is selected are never picks; clicking empty space deselects.

- [ ] **Step 1: Failing tests.**

`tests/unit/test_bridge_fly_camera.py` — add:

```python
def test_scroll_notches_scale_the_speed_within_bounds():
    cam = fc.FlyCamera((0, 0, 0), 0.0, 0.0)
    cam.adjust_speed(2)
    assert cam.speed == pytest.approx(fc.BASE_SPEED * 1.25 ** 2)
    cam.adjust_speed(-100)
    assert cam.speed == pytest.approx(fc.BASE_SPEED * fc.MIN_SPEED_MULT)
    cam.move(1.0, forward=1, strafe=0, lift=0)
    assert cam.eye[1] == pytest.approx(fc.BASE_SPEED * fc.MIN_SPEED_MULT)
```

(use the file's existing import alias for the module; add `import pytest` if absent). Remove any existing test that passes `fast=`/`slow=`.

`tests/unit/test_bridge_emitters_panel.py` — delete the slice-2 glow/profile tests (`test_glow_on_off_and_source` … `test_tab_and_preview_toggle_are_not_document_edits`, `test_preview_*`, `test_open_starts_on_the_players_alert`) and the old material/light tests that use `material:<ch>` / `light-add` without an index; then add:

```python
def _sel(env_rt):
    p, io, h, *_, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))          # mesh 1, block 7 "redalertpanel"
    return p, h, rt


def test_nothing_selected_hides_the_dock_payload(env_rt):
    p, io, h, *_ , rt = env_rt
    p.open()
    st = payload(p)
    assert st["selected"] is None and st["state"] == "green" and st["playing"] is True


def test_material_new_link_duplicate_and_library(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("material-new")
    sel = payload(p)["selected"]
    assert sel["material"] == "material 1"
    assert sel["library"] == [{"name": "material 1", "used_by": 1}]
    p.dispatch_event("material-duplicate")
    assert payload(p)["selected"]["material"] == "material 1 copy"
    p.dispatch_event("material-link:material 1")
    p.dispatch_event("material-rename:alcove")
    assert payload(p)["selected"]["material"] == "alcove"
    p.dispatch_event("material-link:")
    assert payload(p)["selected"]["material"] is None


def test_material_edits_need_a_linked_material_except_mod_add(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("finish:roughness:0.2")
    assert "7:redalertpanel" not in p._doc["objects"]
    p.dispatch_event("tab:material")
    p.dispatch_event("state:red")
    p.dispatch_event("mod-add:emitter")                # creates + links a material
    sel = payload(p)["selected"]
    assert sel["material"] == "material 1"
    assert sel["material_data"]["modifiers"][0]["scope"] == ["red"]   # the preview state


def test_finish_source_reports_map_material_default(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:0.8")
    fin = payload(p)["selected"]["material_data"]["finish"]
    assert fin["roughness"]["source"] == "map"           # mesh 1 has a roughness map
    assert fin["metalness"] == {"value": 0.8, "source": "material"}


def test_every_edit_is_one_undo_step(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("material-new")
    n = len(p._undo)
    p.dispatch_event("fade:0.5")                         # same as default? sets it: one step
    p.dispatch_event("fade:0.5")                         # unchanged: none
    assert len(p._undo) == n + 1
    p.dispatch_event("undo")
    assert "fade_s" not in p._doc["materials"]["material 1"]


def test_lights_are_indexed(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("light-add")
    p.dispatch_event("light-add")
    p.dispatch_event("light:1:intensity:-5")
    lights = payload(p)["selected"]["lights"]
    assert len(lights) == 2 and lights[1]["intensity"] == 0.0
    p.dispatch_event("light-remove:0")
    assert len(payload(p)["selected"]["lights"]) == 1


def test_state_and_expand_are_not_document_edits(env_rt):
    p, h, rt = _sel(env_rt)
    n = len(p._undo)
    p.dispatch_event("state:offline")
    p.dispatch_event("expand:mod:0")
    p.dispatch_event("state:purple")
    st = payload(p)
    assert st["state"] == "offline" and st["selected"]["expanded"] == ["mod:0"]
    assert p.preview_alert() == 3 and len(p._undo) == n


def test_preview_is_none_and_dt_is_the_players_when_closed(env):
    p, *_ = env
    assert p.preview_alert() is None
    assert p.preview_dt(0.02, 0.016) == 0.02


def test_open_starts_on_the_bridge_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    p = bep.BridgeEmittersPanel(pose_provider=lambda: POSE, instance_provider=lambda: "iid",
                                in_bridge_provider=lambda: True, io=FakeIO(),
                                alert_provider=lambda: 3)
    p.open()
    assert p.preview_alert() == 3


def test_deselect_and_clicking_empty_space_clear_the_selection(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("deselect")
    assert payload(p)["selected"] is None


def test_shift_flies_and_scroll_sets_the_speed(env):
    p, io, h, t, _ = env
    p.open()
    p.handle_input(h)                                   # attach + camera
    before = p._camera.speed
    h.held.add(FakeKeys.KEY_LEFT_SHIFT)
    h.scroll = 2.0
    t[0] += 0.05
    p.handle_input(h)
    assert p._camera.speed == pytest.approx(before * 1.25 ** 2)
    assert h.locked is True
    h.held.discard(FakeKeys.KEY_LEFT_SHIFT)
    p.handle_input(h)
    assert h.locked is False
```

`FakeH`/`FakeKeys` in this test file: add `KEY_LEFT_SHIFT`/`KEY_RIGHT_SHIFT` if missing, a `scroll` attribute (default 0.0) and `def consume_scroll_y(self): v, self.scroll = self.scroll, 0.0; return v`, and make `set_cursor_locked` record `self.locked`. The existing RMB-fly test becomes a Shift-fly test (hold `KEY_LEFT_SHIFT` instead of the right button).

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/unit/test_bridge_emitters_panel.py tests/unit/test_bridge_fly_camera.py -q`.

- [ ] **Step 3: Implement.**

`fly_camera.py`: docstring "Hold Shift to look and move; scroll sets the speed (Blender fly mode); W/S, A/D, Q/E." Replace `FAST_MULT`/`SLOW_MULT` with `SPEED_STEP = 1.25`, `MIN_SPEED_MULT = 0.1`, `MAX_SPEED_MULT = 16.0`; `__init__` adds `self.speed = BASE_SPEED`; add

```python
    def adjust_speed(self, notches):
        mult = (self.speed / BASE_SPEED) * SPEED_STEP ** float(notches)
        self.speed = BASE_SPEED * min(MAX_SPEED_MULT, max(MIN_SPEED_MULT, mult))
```

and `move(self, dt, forward, strafe, lift)` uses `self.speed * dt`.

`bridge_emitters_panel.py`:
- Module docstring: describe §13 (bar, Object/Material tabs, Shift fly).
- Constants: `BAR_CSS_W = 560`, `BAR_CSS_H = 64`; drop `_CHANNELS`/`_LIGHT_*`/`_WAVE_DEFAULTS`/`_EMITTER_PREFIXES` (editing.py owns defaults); `HINT = "Hold Shift: fly · WASD · Q/E · scroll: speed · click: select · Alt+click: surface behind · materials layer over the object's texture"`.
- `_reset_session`: `self._state = "green"`, `self._preview_playing = True`, `self._tab = "object"`, `self._expanded = set()`, `self._shift = False` (replacing `self._rmb`); drop `self._tab`'s old meaning.
- `open()`: `self._state = behaviour.state_name(self._alert()) if self._alert else "green"` (inside the existing try/except).
- `handle_input`: replace the RMB block with Shift:

```python
        ks = h.key_state
        shift = bool(ks(keys.KEY_LEFT_SHIFT) or ks(keys.KEY_RIGHT_SHIFT))
        if shift and not self._shift:
            h.set_cursor_locked(True)
            h.consume_mouse_delta()
        elif not shift and self._shift:
            h.set_cursor_locked(False)
        self._shift = shift
        if shift:
            dx, dy = h.consume_mouse_delta()
            self._camera.look(dx, dy)
            scroll = getattr(h, "consume_scroll_y", None)
            if scroll is not None:
                notches = scroll()
                if notches:
                    self._camera.adjust_speed(notches)
            self._camera.move(
                dt,
                forward=int(ks(keys.KEY_W)) - int(ks(keys.KEY_S)),
                strafe=int(ks(keys.KEY_D)) - int(ks(keys.KEY_A)),
                lift=int(ks(keys.KEY_E)) - int(ks(keys.KEY_Q)))
            self._push_highlight(iid)
            return
```

  and `over_dock` becomes `over_ui = (self._selected is not None and x >= fb[0] - DOCK_CSS_PX * s) or (x < BAR_CSS_W * s and y < BAR_CSS_H * s)` with `s = self._dsf(h, fb)` (use `over_ui` where `over_dock` was). `_unlock_cursor` tests `self._shift`. In `_click`, a miss (`mesh is None`) keeps `self._selected = None` (already) — and also clears `self._last_hit`.
- Dispatch: keep `close`/`save`/`revert`/`undo`; handle `state:`, `preview-toggle`, `tab:`, `expand:`, `deselect` before the no-document guard (as slice 2's ruling); everything else routes through `self._edit(...)` calling `editing` with the selected object's `(block, name)`; material actions resolve `mat = self._doc["materials"][name]` for the linked name and are ignored when none is linked, except `mod-add:` which first calls `editing.new_material`. `mod-add` passes `self._state` as the initial scope. `light-add` uses `self._last_hit` (ignored when None); `light-place:<i>` sets that light's position to `self._last_hit[0]`; `light-aim:<i>` sets its direction to `self._camera.forward()`.
- Payload as in Interfaces; `finish` source: `"map"` when the mesh's `maps[ch]`, else `"material"` when the material sets it, else `"default"` (value 1.0 / 0.0). `has_emission_map` from `maps.emissive`. `library` = sorted `[{name, used_by}]` from `editing.users`. `expanded` = sorted list.
- `preview_alert()` → `behaviour.state_index(self._state) if self._visible else None`.

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_bridge_emitters_panel.py tests/unit/test_bridge_fly_camera.py tests/unit/test_bridge_editor_preview.py tests/unit/test_host_loop_bridge_emitters_registration.py -q` → pass.

- [ ] **Step 5: Commit** — the panel, fly camera and their tests; message `feat(bridge): editor model for Object/Material tabs, five-state preview and Shift fly (spec §13.3)`.

---

### Task 8: The page — bar, selection-only dock, tabs, stacks

**Files:** Modify `native/assets/ui-cef/index.html` (the `#bridge-emitters-root` block), rewrite `native/assets/ui-cef/js/bridge_emitters.js`, `native/assets/ui-cef/css/bridge_emitters.css`; rewrite `tests/ui/test_bridge_emitters_js.py`.

**Interfaces:** consumes the Task 7 payload and action strings; `ColourWheel` from `colour_wheel.js`.

- [ ] **Step 1: Failing tests** — replace `tests/ui/test_bridge_emitters_js.py` with a harness whose fake DOM provides `bridge-emitters-root`, `be-bar`, `be-hint`, `be-dock`, `bridge-emitters-body`, `be-status`, `be-hover` (same `el()` factory; `Math` in the context) and these tests:

```python
def _state(**over):
    st = {"visible": True, "in_bridge": True, "state": "green", "playing": True,
          "dirty": False, "can_save": True, "can_undo": False, "status": "",
          "hint": "Hold Shift: fly", "hover": None, "selected": None}
    st.update(over)
    return st


def _sel(**over):
    s = {"key": "7:p", "block": 7, "name": "p", "display_name": "panel",
         "node_chain": ["Scene Root"], "textures": ["Map 19.tga"], "tab": "object",
         "expanded": [], "has_emission_map": True, "material": None,
         "library": [{"name": "alcove", "used_by": 4}], "lights": [], "material_data": None}
    s.update(over)
    return s


MAT = {"name": "alcove", "finish": {"roughness": {"value": 1.0, "source": "default"},
                                    "metalness": {"value": 0.0, "source": "default"}},
       "surface": {"src": "auto", "strength": 1.0}, "fade_s": 0.5,
       "modifiers": [{"type": "emitter", "scope": ["red"], "tint": [1, 0.1, 0.1], "level": 0.5},
                     {"type": "animation", "scope": ["red"], "shape": "square",
                      "period_s": 1, "min": 0.2, "duty": 0.5, "soft": 0.1, "phase": 0}]}


def test_the_bar_carries_the_five_states_preview_and_file_actions():
    [out] = _run([{"state": _state(state="red")}])
    bar = out["bar"]
    for s in ("offline", "green", "yellow", "red", "special"):
        assert f"bridge-emitters/state:{s}" in bar
    assert 'be-state red active' in bar
    for a in ("preview-toggle", "undo", "revert", "save", "close"):
        assert f"bridge-emitters/{a}" in bar
    assert "BRIDGE EDITOR" in bar


def test_the_dock_is_hidden_without_a_selection():
    [out] = _run([{"state": _state()}])
    assert out["dock_display"] == "none"
    [out] = _run([{"state": _state(selected=_sel())}])
    assert out["dock_display"] == "flex"


def test_object_tab_lists_the_library_and_the_emission_map_row():
    [out] = _run([{"state": _state(selected=_sel())}])
    body = out["body"]
    assert "bridge-emitters/tab:material" in body
    assert "alcove — used by 4 objects" in body and "material-link:alcove" in body
    assert "material-new" in body and "light-add" in body
    assert "Emission map" in body and "steady" in body
    assert "<select" not in body


def test_material_tab_shows_finish_surface_and_the_modifier_stack():
    sel = _sel(tab="material", material="alcove", material_data=MAT, expanded=["mod:1"])
    [out] = _run([{"state": _state(selected=sel)}])
    body = out["body"]
    assert "material-rename:" in body and "finish:roughness:" in body
    assert "surface:src:auto" in body and "surface:src:none" in body
    assert "mod-add:emitter" in body and "mod-add:animation" in body
    assert "expand:mod:0" in body and "mod:0:level:" not in body     # collapsed
    assert "mod:1:duty:" in body and "mod:1:shape:sine" in body       # expanded
    assert "mod:0:scope:red" in body and "mod-remove:0" in body
    assert "<select" not in body


def test_no_material_offers_new_on_the_material_tab():
    [out] = _run([{"state": _state(selected=_sel(tab="material"))}])
    assert "material-new" in out["body"] and "mod-add:emitter" in out["body"]


def test_hover_and_status_are_text():
    [out] = _run([{"state": _state(hover="<b>x</b>", status="<i>s</i>")}])
    assert out["hover"] == "<b>x</b>" and out["status"] == "<i>s</i>"
```

with `_run`'s output per step: `{body, bar: el('be-bar').innerHTML, hint: el('be-hint').textContent, dock_display: el('be-dock').style.display, hover, status, display}`. Keep the slice-2 "no rebuild while typing in a dock field" test, adapted to the new ids.

- [ ] **Step 2: Run, watch fail** — `uv run pytest tests/ui/test_bridge_emitters_js.py -q`.

- [ ] **Step 3: Implement.**

`index.html` — the block becomes:

```html
    <div id="bridge-emitters-root" class="dev-only" data-panel="bridge-emitters">
      <div class="be-top">
        <div class="be-bar" id="be-bar"></div>
        <div class="be-hint" id="be-hint"></div>
        <div class="be-row be-hover-row"><span id="be-hover"></span><span class="be-status" id="be-status"></span></div>
      </div>
      <div class="be-dock cp-modal" id="be-dock">
        <div class="cp-content"><div class="cp-body" id="bridge-emitters-body"></div></div>
      </div>
    </div>
```

`bridge_emitters.js` — keep `_beEsc`, `_beJs`, `_beChip`, `_beNumberRow`, `_beEditingInDock`, `_beMountWheel` (now mounting a wheel per expanded emitter: canvases `be-wheel-<i>`), and build:

```javascript
const _BE_STATES = [['offline', '⬛'], ['green', '🟩'], ['yellow', '🟨'], ['red', '🟥'],
                    ['special', '🟦']];

function _beBar(state) {
    let html = '<span class="be-title">BRIDGE EDITOR</span><span class="be-sep">|</span>';
    _BE_STATES.forEach(function (p) {
        html += '<button class="be-state ' + p[0] + (state.state === p[0] ? ' active' : '') + '"'
            + ' onclick="dauntlessEvent(\'bridge-emitters/state:' + p[0] + '\')">' + p[1] + '</button>';
    });
    html += '<span class="be-sep">|</span>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/preview-toggle\')">'
        + (state.playing ? '⏸' : '▶') + '</button><span class="be-sep">|</span>'
        + '<button' + (state.can_undo ? '' : ' disabled')
        + ' onclick="dauntlessEvent(\'bridge-emitters/undo\')">Undo</button>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/revert\')">Revert</button>'
        + '<button' + (state.can_save ? '' : ' disabled')
        + ' onclick="dauntlessEvent(\'bridge-emitters/save\')">Save' + (state.dirty ? '*' : '')
        + '</button><span class="be-sep">|</span>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/close\')">✕</button>';
    return html;
}

// One stack entry: a header row (expand toggle, title, scope squares, ×) and,
// when expanded, its fields.
function _beEntry(id, title, expanded, scope, removeAction, fields) {
    let html = '<div class="be-entry"><div class="be-entry-head">'
        + '<button class="be-caret" onclick="dauntlessEvent(\'bridge-emitters/expand:' + id + '\')">'
        + (expanded ? '▾' : '▸') + '</button><span class="be-entry-title">' + _beEsc(title) + '</span>';
    if (scope) {
        _BE_STATES.forEach(function (p) {
            html += '<button class="be-scope ' + p[0] + (scope.list.indexOf(p[0]) >= 0 ? ' on' : '') + '"'
                + ' onclick="dauntlessEvent(\'bridge-emitters/' + scope.action + p[0] + '\')">'
                + p[1] + '</button>';
        });
    }
    if (removeAction)
        html += '<button onclick="dauntlessEvent(\'bridge-emitters/' + removeAction + '\')">×</button>';
    html += '</div>';
    if (expanded) html += '<div class="be-entry-body">' + fields + '</div>';
    return html + '</div>';
}
```

Object tab (`_beObjectTab(s)`): a "Material" entry (library chips `material-link:<name>` labelled `<name> — used by N object(s)`, plus "none", **New** `material-new`, **Duplicate** `material-duplicate` when linked); when `!s.material && s.has_emission_map` a read-only row `Emission map · <first texture stem>_emissive · steady`; then each light as `_beEntry('light:' + i, 'Light ' + (i + 1), ...)` with Place/Aim buttons (`light-place:i`, `light-aim:i`) and number rows `light:i:inner_deg` / `outer_deg` / `range` / `intensity`, and remove `light-remove:i`; then an **Add light** button (`light-add`).

Material tab (`_beMaterialTab(s, state)`): with no material, a line "No material" + **New** (`material-new`) + **Add modifier** chips (`mod-add:emitter`, `mod-add:animation`). With one: rename field `#be-rename` + Rename button (`material-rename:` + value) and the library count; **Finish** entry (`finish:roughness:` / `finish:metalness:` range+number rows, disabled with "map" when `source === 'map'`, a × `finish-clear:<ch>` when `source === 'material'`); **Surface** entry (chips `surface:src:auto|emission|texture|flat|none`, labels `auto`/`emission map`/`own texture`/`flat`/`none`, and a strength row `surface:strength`); fade row (`fade`); then each modifier as `_beEntry('mod:' + i, ...)` with `scope: {list: m.scope, action: 'mod:' + i + ':scope:'}` and remove `mod-remove:i`; an emitter's fields are the wheel canvas `be-wheel-<i>` + swatch + level row (`mod:i:level`); an animation's are shape chips (`mod:i:shape:sine|square`), `period_s`, `min`, `phase`, and for square `duty`, `soft`; then **Add modifier** chips.

Tabs row at the top of the dock: two chips `tab:object` / `tab:material`.

`setBridgeEmitters(state)`: hide the root when `!state.visible` (and `_beWheels = []`); fill `be-bar` innerHTML with `_beBar(state)` (always), `be-hint` textContent with `state.hint`, `be-hover`/`be-status` textContent; `be-dock.style.display = state.selected ? 'flex' : 'none'`; rebuild the body (unless `_beEditingInDock`) with the selection readout (name, block, textures, chain), the tabs, and the active tab; then mount the wheels: for each expanded emitter `i`, `new ColourWheel(canvas, colourRgbToHs(tint), ...)` committing `mod:<i>:tint:r,g,b` on release; keep them in `_beWheels` and make `_beEditingInDock` true while any is dragging. Show the root with `display = 'block'`.

`bridge_emitters.css` — the root keeps `pointer-events: none` over the viewport; add:

```css
#bridge-emitters-root .be-top { pointer-events: auto; position: absolute; top: 8px; left: 8px;
    max-width: 560px; }
#bridge-emitters-root .be-bar { display: flex; align-items: center; gap: 4px;
    background: rgba(0, 0, 0, 0.7); padding: 4px 8px; border-radius: 4px; }
#bridge-emitters-root .be-title { letter-spacing: 1px; margin-right: 4px; }
#bridge-emitters-root .be-sep { opacity: 0.5; margin: 0 4px; }
#bridge-emitters-root .be-state, #bridge-emitters-root .be-scope { opacity: 0.45; }
#bridge-emitters-root .be-state.active, #bridge-emitters-root .be-scope.on { opacity: 1;
    outline: 1px solid #f0b060; }
#bridge-emitters-root .be-hint { font-size: 11px; opacity: 0.75; margin-top: 4px; }
#bridge-emitters-root .be-entry { border-top: 1px solid rgba(255, 255, 255, 0.15); padding: 4px 0; }
#bridge-emitters-root .be-entry-head { display: flex; align-items: center; gap: 4px; }
#bridge-emitters-root .be-entry-title { flex: 1; }
#bridge-emitters-root .be-entry-body { padding-left: 16px; }
#bridge-emitters-root .be-dock { display: none; }
```

(the `.be-dock` absolute right-docked rules from slice 2 stay; JS sets `display: flex` when selected.)

- [ ] **Step 4: Run** — `uv run pytest tests/ui -q` → pass.

- [ ] **Step 5: Commit** — `native/assets/ui-cef/index.html native/assets/ui-cef/js/bridge_emitters.js native/assets/ui-cef/css/bridge_emitters.css tests/ui/test_bridge_emitters_js.py`; message `feat(bridge): editor bar, selection-only dock, Object/Material tabs and modifier stacks (spec §13.3)`.

---

### Task 9: Convert the committed bridge files; docs; gate; live check

**Files:** `native/assets/bridge_lighting/dbcdbd4a43dc5a56.json`, `native/assets/bridge_lighting/c4fd03a51bb99bae.json` (converted through the loader + writer, never by hand); `CLAUDE.md` (Bridge editor row), the spec §10 log.

- [ ] **Step 1: Convert** (ask Mark first whether his uncommitted DBridge editor save is kept — the conversion reads the working copy):

```bash
uv run python - <<'EOF'
import json
from pathlib import Path
from engine.bridge_editor import lighting_doc as ld, lighting_writer as lw
for name in ("dbcdbd4a43dc5a56", "c4fd03a51bb99bae"):
    p = Path(f"native/assets/bridge_lighting/{name}.json")
    raw = json.loads(p.read_text())
    doc = ld.validate(ld.upgrade(raw) if raw["format"] == 1 else raw)
    lw.save(doc, p)
    print(name, sorted(doc["materials"]), len(doc["objects"]))
EOF
```

Expected: DBridge materials include `alcove`, `roof` and a handful of `material N`; EBridge `material N` only.

- [ ] **Step 2: Docs** — CLAUDE.md row: replace the sentence starting `Per-bridge data` through `previews, with a preview clock running under the editor's pause.` with `Per-bridge data \`native/assets/bridge_lighting/<fnv1a64>.json\` (format 2; format 1 upgrades on load): a material library (finish, surface, scoped Emitter/Animation modifiers) + objects (material link, lights); unknown keys REJECTED; writer deterministic + atomic. Five bridge states (offline from the power plant, green/yellow/red, special hook). Editor: top-left bar (states, preview clock, Undo/Revert/Save) + Object/Material tabs on selection; hold Shift to fly.` — then `uv run pytest tests/docs/test_doc_consistency.py -q` (row budget 1200). Spec §10: add `| G5 | 2026-10-11 | Slice 3 built (plan 2026-10-11-bridge-materials-slice-3) | built; awaiting Mark's live check | 13 |`.

- [ ] **Step 3: Gate** — `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" scripts/check_tests.sh` → `OK — no new failures`.

- [ ] **Step 4: Commit** — the two JSON files, CLAUDE.md, the spec; message `data(bridge): bridge lighting files converted to format 2 (materials + objects); docs`.

- [ ] **Step 5: Hand to Mark** (do not launch): `cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/dbridge-round7` then `./build/dauntless --developer`; check the bar's five states switch the bridge (⬛ dims the room and darkens unlit emission maps), Shift flies and scroll changes speed, the dock appears only on selection, the Object tab links materials, the Material tab's stack builds the red-bar behaviour (Emitter red scoped 🟥 + Animation sine scoped 🟥) and sharing it with the alcoves keeps each object's own surface.
