# Ship Running Lights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mod ships' `BlinkingLightProperty` running lights load onto the ship and render as small additive navigation lights that blink, fade with cloak, track power-plant state and go out on death.

**Architecture:** Python gets real property classes (so mod hardpoints register their lights) and a pure `running_lights` module that turns a ship's property set into body-frame light specs and a per-frame brightness level. The host loop sends each ship's lights to C++ once at spawn and one level per ship per frame. C++ keeps a per-instance store, resolves positions through the hull's current transform, computes the blink from game time, and draws additive depth-tested sprites in the space phase.

**Tech Stack:** Python 3.11 (pytest), C++17 / OpenGL 4.1 core (GLSL 410), pybind11, gtest.

**Spec:** `docs/superpowers/specs/2026-10-14-ship-running-lights-design.md` — read it first. §2 (what BC does) and §3 (deliberate departures) explain why the behaviour differs from the binary on purpose.

## Global Constraints

- Work in the worktree `.claude/worktrees/running-lights` on branch `feat/running-lights`. Never `cd` to the main checkout.
- **Banned git:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit paths only. To mutate a file temporarily, back it up with `cp` and restore with `cp`, then `diff` to prove the restore.
- Build: `cmake --build build -j` (the worktree's `build/` is already configured, Debug, against uv Python 3.11). Never run cmake from `native/`; never change `CMAKE_BUILD_TYPE`; never create another build tree.
- Run Python tests with `unset VIRTUAL_ENV; uv run pytest <path> -q -p no:cacheprovider`.
- Run native tests with `ctest --test-dir build -R <regex> --output-on-failure` after a build.
- GLSL is `#version 410 core`. Shader errors are RUNTIME errors: a shader change is only proven by a test that constructs the `Pipeline`.
- Units: everything spatial is GU (1 GU = 175 m). Never name a variable `*_m`.
- Rotation convention: column-vector, right-handed. Body → world is `t + R·p` with uniform scale divided out (the `resolve_attached_dynamic_lights` rule).
- Never capture a path at import; never spell `game`/`sdk` as a path segment (`tests/unit/test_path_indirection.py`).
- Commit after every task with a message ending in:
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`
- Dial start values (spec §4.5): `size_gu_per_radius = 0.02`, `min_px = 1.5`, `intensity = 4.0`.
- Blink ramps are `0.1 × duration` (BC's key spacing). Static = `duration <= 0`.
- Running lights are ON by default in production.

## Review Focus

1. **Instance id recycled after a ship dies** → the new occupant of that id must not inherit the old ship's lights. Owned by Task 6 (native `erase` on `destroy_instance`) and Task 7 (`ship_running_lights.pop` in the removal path); both add a test.
2. **Mission swap** → no lights survive into the next mission. Native `reset_frame_state` runs only at init/shutdown, NOT on a swap; a swap is covered because session teardown destroys every ship instance and Task 6's `destroy_instance` hook erases its lights. Task 6 tests the destroy purge; Task 7 tests that `MissionSession` teardown clears its dict.
3. **Hardpoint omits `SetTextureName` / `SetColor`** (stock Kessok "Strobe") → defaults apply, nothing raises. Owned by Task 1.
4. **Degenerate timing** (Period 0, negative Period, Duration ≥ Period) → always-on, never NaN. Owned by Task 3.
5. **A lit ship with no power subsystem and no cloaking subsystem** (stations, odd mods) → level 1, no exception. Owned by Task 2 and Task 7.

---

### Task 1: Property classes and class-tag registration

**Files:**
- Modify: `engine/appc/properties.py` (add classes after `ObjectEmitterProperty`, ~line 217; add `_Create`/`_Cast` after `ObjectEmitterProperty_Cast`, ~line 1002)
- Modify: `App.py` (import block ~line 288-316; `_CT_CLASS_FOR_TAG` ~line 416)
- Test: `tests/unit/test_blinking_light_property.py` (create)

**Interfaces:**
- Produces: `engine.appc.properties.EffectEmitterProperty`, `SmokeEmitterProperty`, `SparkEmitterProperty`, `ExplodeEmitterProperty`, `BlinkingLightProperty`; `App.<Name>_Create(name)` and `App.<Name>_Cast(obj)` for all five; `BlinkingLightProperty.GetColor() -> App.TGColorA`, `GetRadius/GetPeriod/GetDuration() -> float`, `GetTextureName() -> str | None`; `App.CT_BLINKING_LIGHT_PROPERTY` (and the other four tags) resolvable by `TGModelPropertySet.GetPropertiesByType`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_blinking_light_property.py`:

```python
"""BlinkingLightProperty + the EffectEmitter family (running-lights spec §4.1).

Before this, App.BlinkingLightProperty_Create fell through to a _NamedStub whose
GetName() is itself a stub hashed by identity, so RegisterLocalTemplate keyed
each light under a key nobody could find and every mod running light was
silently dropped by FindByName.
"""
import importlib
import sys
from pathlib import Path

import pytest

import App
import tools.mission_harness as mh
from engine import mods
from engine.appc.math import TGPoint3
from engine.appc.properties import (
    BlinkingLightProperty, EffectEmitterProperty, ExplodeEmitterProperty,
    PositionOrientationProperty, SmokeEmitterProperty, SparkEmitterProperty,
    TGModelPropertySet,
)


def test_defaults_match_the_binary_constructor():
    # FUN_0067B590: Radius 0.1, Period 3.0, Duration 1.0, no texture.
    p = App.BlinkingLightProperty_Create("Strobe")
    assert isinstance(p, BlinkingLightProperty)
    assert p.GetName() == "Strobe"
    assert p.GetRadius() == pytest.approx(0.1)
    assert p.GetPeriod() == pytest.approx(3.0)
    assert p.GetDuration() == pytest.approx(1.0)
    assert p.GetTextureName() is None
    c = p.GetColor()
    assert (c.r, c.g, c.b, c.a) == (1.0, 1.0, 1.0, 1.0)


def test_setters_round_trip_like_a_mod_hardpoint():
    p = App.BlinkingLightProperty_Create("Bridge Blinker")
    pos = TGPoint3(); pos.SetXYZ(-0.000447, 0.578326, 0.280537)
    p.SetPosition(pos)
    fwd = TGPoint3(); fwd.SetXYZ(0, 1, 0)
    up = TGPoint3(); up.SetXYZ(0, 0, 1)
    right = TGPoint3(); right.SetXYZ(1, 0, 0)
    p.SetOrientation(fwd, up, right)
    col = App.TGColorA(); col.SetRGBA(1.0, 1.0, 0.501961, 1.0)
    p.SetColor(col)
    p.SetRadius(1.5); p.SetPeriod(3.0); p.SetDuration(1.0)
    p.SetTextureName("scripts/Custom/NanoFXv2/SpecialFX/Gfx/Blinker/Blank.tga")

    got = p.GetPosition()
    assert (round(got.x, 6), round(got.y, 6), round(got.z, 6)) == (-0.000447, 0.578326, 0.280537)
    c = p.GetColor()
    assert (c.r, c.g, round(c.b, 6), c.a) == (1.0, 1.0, 0.501961, 1.0)
    assert (p.GetRadius(), p.GetPeriod(), p.GetDuration()) == (1.5, 3.0, 1.0)
    assert p.GetTextureName().endswith("Blank.tga")
    # Mutating the caller's colour after SetColor must not change the property.
    col.SetRGBA(0, 0, 0, 0)
    assert p.GetColor().r == 1.0


def test_get_color_returns_a_copy():
    p = App.BlinkingLightProperty_Create("x")
    p.GetColor().SetRGBA(0, 0, 0, 0)
    assert p.GetColor().r == 1.0


def test_effect_emitter_family_is_placement_only():
    for create, cls in (
        (App.SmokeEmitterProperty_Create, SmokeEmitterProperty),
        (App.SparkEmitterProperty_Create, SparkEmitterProperty),
        (App.ExplodeEmitterProperty_Create, ExplodeEmitterProperty),
        (App.EffectEmitterProperty_Create, EffectEmitterProperty),
    ):
        p = create("SmokeEmitter2")
        assert isinstance(p, cls)
        assert isinstance(p, EffectEmitterProperty)
        assert isinstance(p, PositionOrientationProperty)
        pos = TGPoint3(); pos.SetXYZ(204.452, 179.076, 113.168)
        p.SetPosition(pos)
        assert p.GetPosition().x == pytest.approx(204.452)


def test_blinking_light_is_an_effect_emitter():
    assert issubclass(BlinkingLightProperty, EffectEmitterProperty)


def test_cast_accepts_own_class_and_rejects_others():
    light = App.BlinkingLightProperty_Create("a")
    smoke = App.SmokeEmitterProperty_Create("b")
    assert App.BlinkingLightProperty_Cast(light) is light
    assert App.BlinkingLightProperty_Cast(smoke) is None
    assert App.BlinkingLightProperty_Cast(None) is None
    assert App.EffectEmitterProperty_Cast(light) is light
    assert App.SmokeEmitterProperty_Cast(smoke) is smoke
    assert App.SparkEmitterProperty_Cast(smoke) is None
    assert App.ExplodeEmitterProperty_Cast(smoke) is None


def test_get_properties_by_type_finds_lights_by_ct_tag():
    pset = TGModelPropertySet()
    light = App.BlinkingLightProperty_Create("a")
    smoke = App.SmokeEmitterProperty_Create("b")
    pset.AddToSet("Scene Root", light)
    pset.AddToSet("Scene Root", smoke)
    assert list(pset.GetPropertiesByType(App.CT_BLINKING_LIGHT_PROPERTY)) == [light]
    assert list(pset.GetPropertiesByType(App.CT_SMOKE_EMITTER_PROPERTY)) == [smoke]
    assert list(pset.GetPropertiesByType(App.CT_SPARK_EMITTER_PROPERTY)) == []
    assert list(pset.GetPropertiesByType(App.CT_EXPLODE_EMITTER_PROPERTY)) == []
    assert set(pset.GetPropertiesByType(App.CT_EFFECT_EMITTER_PROPERTY)) == {light, smoke}


def test_named_template_survives_find_by_name():
    App.g_kModelPropertyManager.ClearLocalTemplates()
    light = App.BlinkingLightProperty_Create("Bridge Blinker")
    App.g_kModelPropertyManager.RegisterLocalTemplate(light)
    found = App.g_kModelPropertyManager.FindByName(
        "Bridge Blinker", App.TGModelPropertyManager.LOCAL_TEMPLATES)
    assert found is light
    App.g_kModelPropertyManager.ClearLocalTemplates()


_LC_HP = "LC Intrepid Pack/scripts/ships/Hardpoints/LCintrepidHP.py"


def test_real_lc_intrepid_hardpoint_puts_19_lights_on_the_ship():
    """The regression: 0 before this change (FindByName returned None)."""
    root = Path(mods.mods_root(argv=[], env={}))
    if not (root / _LC_HP).is_file():
        pytest.skip("LC Intrepid Pack not installed under the mods root")
    mods.configure(mods.build_index(root))
    mh.setup_sdk()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    sys.modules.pop("ships.Hardpoints.LCintrepidHP", None)
    hp = importlib.import_module("ships.Hardpoints.LCintrepidHP")
    assert hp.__spec__.origin.endswith("LCintrepidHP.py")
    pset = TGModelPropertySet()
    hp.LoadPropertySet(pset)
    lights = list(pset.GetPropertiesByType(App.CT_BLINKING_LIGHT_PROPERTY))
    assert len(lights) == 19
    statics = [l for l in lights if l.GetDuration() == 0.0]
    blinkers = [l for l in lights if l.GetDuration() == 1.0]
    assert len(statics) + len(blinkers) == 19
    assert all(l.GetPeriod() == 3.0 for l in lights)
    App.g_kModelPropertyManager.ClearLocalTemplates()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_blinking_light_property.py -q -p no:cacheprovider`
Expected: FAIL at import with `ImportError: cannot import name 'BlinkingLightProperty'`.

- [ ] **Step 3: Implement the classes**

In `engine/appc/properties.py`, directly after the `ObjectEmitterProperty` class (before `class EngineGlowProperty`), add:

```python
class EffectEmitterProperty(PositionOrientationProperty):
    """Base of BC's effect emitter points (SDK App.py:9872, CT 0x8141).

    No surface of its own: position and orientation, inherited. The Smoke /
    Spark / Explode subclasses are bridge-interior damage-effect spawn points
    (EBridgeProperties.py, dbridgeproperties.py); they are placement-only until
    bridge damage effects are built (running-lights spec, sub-project B).
    """


class SmokeEmitterProperty(EffectEmitterProperty):
    """CT 0x8142 — SDK App.py:9889."""


class SparkEmitterProperty(EffectEmitterProperty):
    """CT 0x8143 — SDK App.py:9906."""


class ExplodeEmitterProperty(EffectEmitterProperty):
    """CT 0x8144 — SDK App.py:9923."""


class BlinkingLightProperty(EffectEmitterProperty):
    """A ship running light (CT 0x8145, SDK App.py:9940-9968).

    Defaults match the binary's constructor (FUN_0067B590): Radius 0.1,
    Period 3.0, Duration 1.0, no texture. Colour is stored as an RGBA tuple
    and handed out as a fresh TGColorA, so callers may mutate either side
    without touching the property. How the lights render, and why it departs
    from BC, is docs/superpowers/specs/2026-10-14-ship-running-lights-design.md.
    """

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._color = (1.0, 1.0, 1.0, 1.0)
        self._radius = 0.1
        self._period = 3.0
        self._duration = 1.0
        self._texture_name = None

    def SetColor(self, color) -> None:
        self._color = (float(color.r), float(color.g),
                       float(color.b), float(color.a))

    def GetColor(self):
        import App
        return App.TGColorA(*self._color)

    def SetRadius(self, value) -> None:
        self._radius = float(value)

    def GetRadius(self) -> float:
        return self._radius

    def SetPeriod(self, value) -> None:
        self._period = float(value)

    def GetPeriod(self) -> float:
        return self._period

    def SetDuration(self, value) -> None:
        self._duration = float(value)

    def GetDuration(self) -> float:
        return self._duration

    def SetTextureName(self, name) -> None:
        self._texture_name = None if name is None else str(name)

    def GetTextureName(self):
        return self._texture_name
```

After `ObjectEmitterProperty_Cast` (end of that function), add:

```python
def EffectEmitterProperty_Create(name):    return EffectEmitterProperty(name)
def SmokeEmitterProperty_Create(name):     return SmokeEmitterProperty(name)
def SparkEmitterProperty_Create(name):     return SparkEmitterProperty(name)
def ExplodeEmitterProperty_Create(name):   return ExplodeEmitterProperty(name)
def BlinkingLightProperty_Create(name):    return BlinkingLightProperty(name)


def _strict_cast(obj, cls):
    """obj if it is a `cls`, else None (stubs included) — the
    ObjectEmitterProperty_Cast contract, for the EffectEmitter family."""
    if obj is None:
        return None
    import App
    if isinstance(obj, App._NamedStub):
        return None
    return obj if isinstance(obj, cls) else None


def EffectEmitterProperty_Cast(obj):   return _strict_cast(obj, EffectEmitterProperty)
def SmokeEmitterProperty_Cast(obj):    return _strict_cast(obj, SmokeEmitterProperty)
def SparkEmitterProperty_Cast(obj):    return _strict_cast(obj, SparkEmitterProperty)
def ExplodeEmitterProperty_Cast(obj):  return _strict_cast(obj, ExplodeEmitterProperty)
def BlinkingLightProperty_Cast(obj):   return _strict_cast(obj, BlinkingLightProperty)
```

In `App.py`, extend the `from engine.appc.properties import (...)` block: add the five class names after `ObjectEmitterProperty,` and the ten functions after `ObjectEmitterProperty_Create, ObjectEmitterProperty_Cast,`:

```python
    EffectEmitterProperty, SmokeEmitterProperty, SparkEmitterProperty,
    ExplodeEmitterProperty, BlinkingLightProperty,
```
```python
    EffectEmitterProperty_Create, EffectEmitterProperty_Cast,
    SmokeEmitterProperty_Create, SmokeEmitterProperty_Cast,
    SparkEmitterProperty_Create, SparkEmitterProperty_Cast,
    ExplodeEmitterProperty_Create, ExplodeEmitterProperty_Cast,
    BlinkingLightProperty_Create, BlinkingLightProperty_Cast,
```

In `_CT_CLASS_FOR_TAG`, after the `("CT_OBJECT_EMITTER_PROPERTY", ObjectEmitterProperty),` row, add:

```python
    ("CT_EFFECT_EMITTER_PROPERTY",       EffectEmitterProperty),
    ("CT_SMOKE_EMITTER_PROPERTY",        SmokeEmitterProperty),
    ("CT_SPARK_EMITTER_PROPERTY",        SparkEmitterProperty),
    ("CT_EXPLODE_EMITTER_PROPERTY",      ExplodeEmitterProperty),
    ("CT_BLINKING_LIGHT_PROPERTY",       BlinkingLightProperty),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_blinking_light_property.py tests/unit/test_object_emitter_property.py tests/unit/test_constant_surface.py -q -p no:cacheprovider`
Expected: all PASS. If `test_constant_surface.py` objects to the new table rows, read its failure: the CT values come from `MODULE_CONSTANTS` and must not be hand-typed.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/properties.py App.py tests/unit/test_blinking_light_property.py
git commit -m "feat(properties): BlinkingLightProperty + EffectEmitter family, CT tags registered

Mod running lights now survive RegisterLocalTemplate/FindByName: the real
LC Intrepid hardpoint puts 19 lights on the ship (0 before).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `running_lights` module — specs, phase, level; dial store

**Files:**
- Create: `engine/appc/running_lights.py`
- Create: `engine/appc/running_light_dials.py`
- Test: `tests/unit/test_running_lights.py` (create)

**Interfaces:**
- Consumes: Task 1's `BlinkingLightProperty` and `App.CT_BLINKING_LIGHT_PROPERTY`; `engine.appc.subsystem_glow.glow_state(sub)` returning `HEALTHY`/`DISABLED`/`DESTROYED`; `engine.appc.light_emitters.emitter_flicker(now, phase) -> float`.
- Produces:
  - `RunningLightSpec(pos: tuple[float,float,float], rgb: tuple[float,float,float], size: float, period: float, duration: float)` with `.as_tuple() -> tuple[9 floats]` in the order `(px, py, pz, r, g, b, size, period, duration)`.
  - `lights_for(ship) -> list[RunningLightSpec]`
  - `phase_for(ship) -> float` (seconds, in [0, 1000))
  - `level_for(ship, cloak_frac: float, now: float, phase: float) -> float` in [0, 1]
  - `running_light_dials.DEFAULTS`, `current() -> dict`, `reset()`, `register()` (dial group "running lights").

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_running_lights.py`:

```python
"""engine.appc.running_lights (running-lights spec §4.2)."""
import pytest

import App
from engine.appc import running_lights, running_light_dials
from engine.appc.light_emitters import emitter_flicker
from engine.appc.math import TGPoint3
from engine.appc.properties import TGModelPropertySet


def _light(name, pos, rgba, radius=1.5, period=3.0, duration=1.0):
    p = App.BlinkingLightProperty_Create(name)
    pt = TGPoint3(); pt.SetXYZ(*pos)
    p.SetPosition(pt)
    c = App.TGColorA(); c.SetRGBA(*rgba)
    p.SetColor(c)
    p.SetRadius(radius); p.SetPeriod(period); p.SetDuration(duration)
    return p


class _Sub:
    def __init__(self, disabled=False, destroyed=False):
        self._dis, self._des = disabled, destroyed
    def IsDisabled(self): return 1 if self._dis else 0
    def IsDestroyed(self): return 1 if self._des else 0


class _Ship:
    def __init__(self, props=(), name="USS Voyager", power=None,
                 dying=False, dead=False):
        self._pset = TGModelPropertySet()
        for p in props:
            self._pset.AddToSet("Scene Root", p)
        self._name, self._power = name, power
        self._dying, self._dead = dying, dead
    def GetPropertySet(self): return self._pset
    def GetName(self): return self._name
    def GetPowerSubsystem(self): return self._power
    def IsDying(self): return 1 if self._dying else 0
    def IsDead(self): return 1 if self._dead else 0


def test_lights_for_reads_static_and_blinker_in_property_order():
    red = _light("Port Static", (-0.5, 0.1, 0.0), (1, 0, 0, 1), radius=1.0, duration=0.0)
    white = _light("Bridge Blinker", (0.0, 0.58, 0.28), (1, 1, 0.5, 0.25))
    ship = _Ship([red, App.SmokeEmitterProperty_Create("not a light"), white])
    specs = running_lights.lights_for(ship)
    assert [s.duration for s in specs] == [0.0, 1.0]
    assert specs[0].pos == pytest.approx((-0.5, 0.1, 0.0))
    assert specs[0].rgb == (1.0, 0.0, 0.0)
    assert specs[1].rgb == pytest.approx((1.0, 1.0, 0.5))   # alpha dropped
    assert specs[1].size == 1.5 and specs[1].period == 3.0
    assert specs[1].as_tuple() == pytest.approx(
        (0.0, 0.58, 0.28, 1.0, 1.0, 0.5, 1.5, 3.0, 1.0))


def test_lights_for_unlit_ship_is_empty():
    assert running_lights.lights_for(_Ship()) == []


def test_lights_for_skips_a_light_with_no_position():
    p = App.BlinkingLightProperty_Create("unplaced")   # SetPosition never called
    assert running_lights.lights_for(_Ship([p])) == []


def test_lights_for_ship_without_property_set_is_empty():
    class _Bare:
        def GetPropertySet(self): return None
    assert running_lights.lights_for(_Bare()) == []


def test_phase_is_stable_per_name_and_differs_across_names():
    a1 = running_lights.phase_for(_Ship(name="USS Voyager"))
    a2 = running_lights.phase_for(_Ship(name="USS Voyager"))
    b = running_lights.phase_for(_Ship(name="USS Defiant"))
    assert a1 == a2
    assert a1 != b
    assert 0.0 <= a1 < 1000.0 and 0.0 <= b < 1000.0


def test_level_healthy_uncloaked_is_one():
    ship = _Ship(power=_Sub())
    assert running_lights.level_for(ship, 0.0, 10.0, 3.0) == 1.0


def test_level_with_no_power_subsystem_is_one():
    assert running_lights.level_for(_Ship(power=None), 0.0, 10.0, 3.0) == 1.0


def test_level_disabled_power_flickers_like_the_emitters():
    ship = _Ship(power=_Sub(disabled=True))
    got = running_lights.level_for(ship, 0.0, 12.5, 7.0)
    assert got == pytest.approx(emitter_flicker(12.5, 7.0))


def test_level_destroyed_power_is_zero():
    assert running_lights.level_for(_Ship(power=_Sub(destroyed=True)), 0.0, 1.0, 0.0) == 0.0


@pytest.mark.parametrize("frac,expected", [(0.0, 1.0), (0.5, 0.5), (1.0, 0.0),
                                           (-0.2, 1.0), (1.7, 0.0)])
def test_level_fades_with_cloak(frac, expected):
    assert running_lights.level_for(_Ship(power=_Sub()), frac, 1.0, 0.0) == pytest.approx(expected)


@pytest.mark.parametrize("dying,dead", [(True, False), (False, True)])
def test_level_is_zero_once_the_ship_dies(dying, dead):
    ship = _Ship(power=_Sub(), dying=dying, dead=dead)
    assert running_lights.level_for(ship, 0.0, 1.0, 0.0) == 0.0


def test_forced_dev_glow_preview_drives_the_lights(monkeypatch):
    from engine import dev_light_preview
    from engine.appc import subsystem_glow
    monkeypatch.setattr(dev_light_preview, "forced_glow_state",
                        lambda: subsystem_glow.DESTROYED)
    assert running_lights.level_for(_Ship(power=_Sub()), 0.0, 1.0, 0.0) == 0.0


def test_dials_defaults_and_reset():
    running_light_dials.reset()
    assert running_light_dials.current() == {
        "size_gu_per_radius": 0.02, "min_px": 1.5, "intensity": 4.0}


def test_dials_step_clamps_at_minimum():
    running_light_dials.reset()
    for _ in range(200):
        running_light_dials._step("min_px", -1)
    assert running_light_dials.current()["min_px"] == pytest.approx(0.5)
    running_light_dials.reset()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_running_lights.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'running_lights'`.

- [ ] **Step 3: Implement**

Create `engine/appc/running_lights.py`:

```python
"""Ship running lights: BlinkingLightProperty -> render specs + per-frame level.

Pure (no host calls). The host loop sends `lights_for` once per ship at spawn
and `level_for` every frame; the C++ RunningLightPass does placement and blink.
Spec: docs/superpowers/specs/2026-10-14-ship-running-lights-design.md. Read its
§3 before "fixing" any behaviour here back toward BC: BC's own timing is a
~9 Hz flicker and its statics are invisible, and both departures are rulings.
"""
import zlib
from dataclasses import dataclass


@dataclass(frozen=True)
class RunningLightSpec:
    pos: tuple        # body frame, GU, unscaled (emitter-light convention)
    rgb: tuple        # colour alpha is dropped, as BC does
    size: float       # the property's Radius; scaled by the size dial in C++
    period: float
    duration: float   # <= 0 means a static (always-on) light

    def as_tuple(self) -> tuple:
        return (self.pos[0], self.pos[1], self.pos[2],
                self.rgb[0], self.rgb[1], self.rgb[2],
                self.size, self.period, self.duration)


def lights_for(ship) -> list:
    """The ship's running lights in property-set order. A light that was never
    placed (no SetPosition) is skipped rather than drawn at the hull origin."""
    import App
    get_set = getattr(ship, "GetPropertySet", None)
    pset = get_set() if get_set is not None else None
    if pset is None:
        return []
    out = []
    for prop in pset.GetPropertiesByType(App.CT_BLINKING_LIGHT_PROPERTY):
        pos = prop.GetPosition()
        if pos is None:
            continue
        c = prop.GetColor()
        out.append(RunningLightSpec(
            pos=(float(pos.x), float(pos.y), float(pos.z)),
            rgb=(float(c.r), float(c.g), float(c.b)),
            size=float(prop.GetRadius()),
            period=float(prop.GetPeriod()),
            duration=float(prop.GetDuration())))
    return out


def phase_for(ship) -> float:
    """Seconds in [0, 1000), stable per ship name. One ship's blinkers share
    it (they flash together); the C++ side takes it modulo each period."""
    name = str(ship.GetName() or "")
    return (zlib.crc32(name.encode("utf-8")) / 2.0 ** 32) * 1000.0


def level_for(ship, cloak_frac: float, now: float, phase: float) -> float:
    """Brightness in [0, 1]: alive x power-plant state x (1 - cloak)."""
    if ship.IsDying() or ship.IsDead():
        return 0.0
    from engine.appc import subsystem_glow
    from engine.appc.light_emitters import emitter_flicker
    get_power = getattr(ship, "GetPowerSubsystem", None)
    power = get_power() if get_power is not None else None
    state = subsystem_glow.glow_state(power)
    if state == subsystem_glow.DESTROYED:
        return 0.0
    level = emitter_flicker(now, phase) if state == subsystem_glow.DISABLED else 1.0
    frac = min(1.0, max(0.0, float(cloak_frac)))
    return level * (1.0 - frac)
```

Create `engine/appc/running_light_dials.py`:

```python
"""Running-light look dials (running-lights spec §4.5).

Play-test values calibrated from Mark's reference screenshot, not recovered BC
numbers (BC never visibly drew these lights). Read at use: the host loop
pushes current() to native every frame there are lights. Tuned live with the
shared / L O keys once Developer Options -> Diagnostics -> "Dial keys"
selects "running lights" (engine/dev_dial_groups.py). Not persisted.
"""
DEFAULTS: dict = {
    "size_gu_per_radius": 0.02,   # Radius 1.5 => 0.03 GU ~ 5 m
    "min_px": 1.5,                # smallest on-screen diameter
    "intensity": 4.0,             # HDR multiplier; above the bloom threshold
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {"size_gu_per_radius": 0.002, "min_px": 0.25, "intensity": 0.25}
_MIN = {"size_gu_per_radius": 0.001, "min_px": 0.5, "intensity": 0.25}

_dials: dict = dict(DEFAULTS)


def reset() -> None:
    global _dials
    _dials = dict(DEFAULTS)


def current() -> dict:
    return dict(_dials)


def _step(name: str, direction: int) -> None:
    v = _dials[name] + (_STEP[name] if direction > 0 else -_STEP[name])
    _dials[name] = max(_MIN[name], round(v, 4))


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("running lights", DIAL_ORDER, current, _step)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_running_lights.py -q -p no:cacheprovider`
Expected: all PASS. If `test_forced_dev_glow_preview_drives_the_lights` fails because `glow_state` imports `dev_light_preview` by a different name, read `engine/appc/subsystem_glow.py:139-153` and patch the attribute it actually calls.

- [ ] **Step 5: Add the dial-module reset to the test-isolation fixture**

`running_light_dials._dials` is module state. In `tests/conftest.py`'s `_reset_leakable_engine_globals`, next to the other dial resets (search for `sensor_dials.reset()`), add:

```python
    try:
        from engine.appc import running_light_dials as _rl_dials
        _rl_dials.reset()
    except Exception:
        pass
```

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_running_lights.py -q -p no:cacheprovider` — still PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/running_lights.py engine/appc/running_light_dials.py tests/unit/test_running_lights.py tests/conftest.py
git commit -m "feat(running-lights): specs, per-ship phase and level from power/cloak/death

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Native blink curve and size clamp

**Files:**
- Create: `native/src/renderer/include/renderer/running_light_math.h`
- Create: `native/src/renderer/running_light_math.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `running_light_math.cc` to the renderer sources list beside `hull_discharge_pass.cc`, ~line 208)
- Create test: `native/tests/renderer/running_light_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt` (add `running_light_test.cc` to `renderer_tests` sources beside `dynamic_lights_test.cc`)

**Interfaces:**
- Produces (namespace `renderer`):
  - `float running_light_blink_alpha(float t, float period, float duration, float phase);`
  - `float running_light_world_size(float size, float size_gu_per_radius, float min_px, float distance, float proj11, int viewport_h);` — returns the sprite DIAMETER in GU.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/running_light_test.cc`:

```cpp
// Running lights: blink curve + size clamp (running-lights spec §4.4).
#include <gtest/gtest.h>

#include <cmath>
#include <limits>

#include "renderer/running_light_math.h"

using renderer::running_light_blink_alpha;
using renderer::running_light_world_size;

TEST(RunningLightBlink, StaticIsAlwaysOn) {
    for (float t : {0.0f, 0.3f, 1.7f, 2.9f, 100.0f})
        EXPECT_FLOAT_EQ(running_light_blink_alpha(t, 3.0f, 0.0f, 0.0f), 1.0f);
}

TEST(RunningLightBlink, DegenerateTimingIsAlwaysOnNeverNaN) {
    const float cases[][2] = {{0.0f, 1.0f}, {-3.0f, 1.0f}, {3.0f, 3.0f}, {3.0f, 5.0f},
                              {std::numeric_limits<float>::quiet_NaN(), 1.0f}};
    for (const auto& c : cases) {
        const float a = running_light_blink_alpha(1.25f, c[0], c[1], 0.0f);
        EXPECT_FALSE(std::isnan(a));
        EXPECT_FLOAT_EQ(a, 1.0f);
    }
}

TEST(RunningLightBlink, OnForDurationOffForRestWithTenPercentRamps) {
    // Period 3, Duration 1: ramp up over [0, 0.1], hold to 0.9, ramp down to 1.0.
    EXPECT_FLOAT_EQ(running_light_blink_alpha(0.0f,  3.0f, 1.0f, 0.0f), 0.0f);
    EXPECT_NEAR    (running_light_blink_alpha(0.05f, 3.0f, 1.0f, 0.0f), 0.5f, 1e-4f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(0.5f,  3.0f, 1.0f, 0.0f), 1.0f);
    EXPECT_NEAR    (running_light_blink_alpha(0.95f, 3.0f, 1.0f, 0.0f), 0.5f, 1e-4f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(1.5f,  3.0f, 1.0f, 0.0f), 0.0f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(2.99f, 3.0f, 1.0f, 0.0f), 0.0f);
    // Next period repeats.
    EXPECT_FLOAT_EQ(running_light_blink_alpha(3.5f,  3.0f, 1.0f, 0.0f), 1.0f);
}

TEST(RunningLightBlink, PhaseShiftsTheWindow) {
    // Phase 1.0 s: game time 2.5 reads as 3.5 -> 0.5 into the next period: on.
    EXPECT_FLOAT_EQ(running_light_blink_alpha(2.5f, 3.0f, 1.0f, 1.0f), 1.0f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(0.5f, 3.0f, 1.0f, 1.0f), 0.0f);
}

TEST(RunningLightBlink, LargePhaseAndTimeStayInRange) {
    const float a = running_light_blink_alpha(100000.25f, 3.0f, 1.0f, 999.0f);
    EXPECT_GE(a, 0.0f);
    EXPECT_LE(a, 1.0f);
}

TEST(RunningLightSize, WorldSizeWinsUpClose) {
    // proj11 = 1/tan(30 deg) for a 60 deg vertical fov; 1080 px tall.
    const float proj11 = 1.0f / std::tan(0.5236f);
    const float d = running_light_world_size(1.5f, 0.02f, 1.5f, 1.0f, proj11, 1080);
    EXPECT_NEAR(d, 0.03f, 1e-6f);
}

TEST(RunningLightSize, MinPixelFloorWinsFarAway) {
    const float proj11 = 1.0f / std::tan(0.5236f);
    const float dist = 500.0f;
    const float per_px = 2.0f * dist / (proj11 * 1080.0f);
    const float d = running_light_world_size(1.5f, 0.02f, 1.5f, dist, proj11, 1080);
    EXPECT_NEAR(d, 1.5f * per_px, 1e-4f);
    EXPECT_GT(d, 0.03f);
}

TEST(RunningLightSize, DegenerateViewportFallsBackToWorldSize) {
    EXPECT_NEAR(running_light_world_size(1.0f, 0.02f, 1.5f, 10.0f, 0.0f, 0), 0.02f, 1e-6f);
}
```

Add `running_light_test.cc` to `renderer_tests` in `native/tests/renderer/CMakeLists.txt`.

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `renderer/running_light_math.h: No such file or directory`.

- [ ] **Step 3: Implement**

Create `native/src/renderer/include/renderer/running_light_math.h`:

```cpp
// native/src/renderer/include/renderer/running_light_math.h
#pragma once

namespace renderer {

/// Blink alpha in [0,1] for a ship running light at game time `t` (seconds).
/// duration <= 0, period <= 0, non-finite inputs, or duration >= period => 1
/// (always on). Otherwise the light is on for `duration` seconds out of every
/// `period`, with linear ramps of 0.1*duration at each end (BC's alpha-key
/// spacing, on the mod authors' timescale -- spec §3 explains why BC's own
/// D/P^2 loop is not reproduced).
float running_light_blink_alpha(float t, float period, float duration, float phase);

/// Sprite DIAMETER in GU: max(size * size_gu_per_radius, min_px pixels at
/// `distance`). proj11 = proj[1][1] (1 / tan(fov_y/2)). A degenerate viewport
/// or projection returns the world size alone.
float running_light_world_size(float size, float size_gu_per_radius, float min_px,
                               float distance, float proj11, int viewport_h);

}  // namespace renderer
```

Create `native/src/renderer/running_light_math.cc`:

```cpp
// native/src/renderer/running_light_math.cc
#include "renderer/running_light_math.h"

#include <algorithm>
#include <cmath>

namespace renderer {

float running_light_blink_alpha(float t, float period, float duration, float phase) {
    if (!std::isfinite(period) || !std::isfinite(duration) ||
        !std::isfinite(t) || !std::isfinite(phase))
        return 1.0f;
    if (duration <= 0.0f || period <= 0.0f || duration >= period) return 1.0f;
    float u = std::fmod(static_cast<double>(t) + static_cast<double>(phase),
                        static_cast<double>(period));
    if (u < 0.0f) u += period;
    const float r = 0.1f * duration;
    if (u >= duration) return 0.0f;
    if (u < r) return u / r;
    if (u > duration - r) return (duration - u) / r;
    return 1.0f;
}

float running_light_world_size(float size, float size_gu_per_radius, float min_px,
                               float distance, float proj11, int viewport_h) {
    const float world = std::max(0.0f, size) * size_gu_per_radius;
    if (proj11 <= 0.0f || viewport_h <= 0 || distance <= 0.0f) return world;
    const float per_px = 2.0f * distance / (proj11 * static_cast<float>(viewport_h));
    return std::max(world, min_px * per_px);
}

}  // namespace renderer
```

Add `running_light_math.cc` to the renderer sources in `native/src/renderer/CMakeLists.txt`.

- [ ] **Step 4: Run to verify it passes**

Run: `cmake --build build -j 2>&1 | tail -3 && ctest --test-dir build -R "RunningLight" --output-on-failure`
Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/running_light_math.h native/src/renderer/running_light_math.cc native/src/renderer/CMakeLists.txt native/tests/renderer/running_light_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): running-light blink curve and pixel-floored size

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Native store and sprite builder

**Files:**
- Create: `native/src/renderer/include/renderer/running_light_store.h`
- Create: `native/src/renderer/running_light_store.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `running_light_store.cc`)
- Modify test: `native/tests/renderer/running_light_test.cc` (append)

**Interfaces:**
- Consumes: Task 3's `running_light_blink_alpha`, `running_light_world_size`; `scenegraph::World::get(InstanceId) -> const Instance*` and `Instance::world` (glm::mat4).
- Produces (namespace `renderer`):

```cpp
struct RunningLight { glm::vec3 body_pos{0}; glm::vec3 rgb{1}; float size = 0.1f, period = 3.0f, duration = 1.0f; };
struct RunningLightDials { float size_gu_per_radius = 0.02f, min_px = 1.5f, intensity = 4.0f; };
struct RunningLightSprite { glm::vec3 world_pos{0}; float half_size = 0.0f; glm::vec3 color{0}; };
constexpr std::size_t kMaxRunningLightSprites = 4096;
class RunningLightStore {
public:
    void set(scenegraph::InstanceId id, std::vector<RunningLight> lights, float phase); // empty => erase
    void set_levels(const std::vector<std::pair<scenegraph::InstanceId, float>>& levels);
    void erase(scenegraph::InstanceId id);
    void clear();
    std::size_t size() const noexcept;
    float level(scenegraph::InstanceId id) const noexcept;   // 0 when absent or unlisted
    std::vector<RunningLightSprite> build_sprites(const scenegraph::World& world, float game_time,
        const RunningLightDials& dials, const glm::vec3& cam_eye, float proj11, int viewport_h) const;
};
```

- [ ] **Step 1: Write the failing tests** — append to `native/tests/renderer/running_light_test.cc`:

```cpp
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <scenegraph/world.h>

#include "renderer/running_light_store.h"

using renderer::RunningLight;
using renderer::RunningLightDials;
using renderer::RunningLightStore;

namespace {

// T * R * S with R = 90 deg about +Z (body +X -> world +Y), uniform scale s.
glm::mat4 rl_world(const glm::vec3& t, float s) {
    glm::mat4 m = glm::translate(glm::mat4(1.0f), t);
    m = glm::rotate(m, glm::radians(90.0f), glm::vec3(0, 0, 1));
    return glm::scale(m, glm::vec3(s));
}

RunningLight static_light(glm::vec3 body, glm::vec3 rgb) {
    RunningLight l; l.body_pos = body; l.rgb = rgb;
    l.size = 1.5f; l.period = 3.0f; l.duration = 0.0f;
    return l;
}

}  // namespace

TEST(RunningLightStore, UnlistedOrAbsentLevelIsZero) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    RunningLightStore s;
    s.set(a, {static_light({1, 0, 0}, {1, 0, 0})}, 0.0f);
    EXPECT_FLOAT_EQ(s.level(a), 0.0f);           // no levels pushed yet
    s.set_levels({{a, 0.75f}});
    EXPECT_FLOAT_EQ(s.level(a), 0.75f);
    s.set_levels({});                            // unlisted this frame
    EXPECT_FLOAT_EQ(s.level(a), 0.0f);
}

TEST(RunningLightStore, EmptySetEraseAndClear) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    const auto b = world.create_instance(1);
    RunningLightStore s;
    s.set(a, {static_light({1, 0, 0}, {1, 0, 0})}, 0.0f);
    s.set(b, {static_light({1, 0, 0}, {0, 1, 0})}, 0.0f);
    EXPECT_EQ(s.size(), 2u);
    s.set(a, {}, 0.0f);
    EXPECT_EQ(s.size(), 1u);
    s.erase(b);
    EXPECT_EQ(s.size(), 0u);
    s.set(a, {static_light({1, 0, 0}, {1, 0, 0})}, 0.0f);
    s.clear();
    EXPECT_EQ(s.size(), 0u);
}

TEST(RunningLightStore, ResetLightsReplaceNotAppend) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    RunningLightStore s;
    s.set(a, {static_light({1, 0, 0}, {1, 0, 0}), static_light({2, 0, 0}, {1, 0, 0})}, 0.0f);
    s.set(a, {static_light({3, 0, 0}, {0, 0, 1})}, 0.0f);
    s.set_levels({{a, 1.0f}});
    world.set_world_transform(a, glm::mat4(1.0f));
    const auto sprites = s.build_sprites(world, 0.0f, RunningLightDials{}, {0, 0, -10}, 0.0f, 0);
    ASSERT_EQ(sprites.size(), 1u);
}

TEST(RunningLightStore, SpritesFollowTheHullTransformWithScaleDividedOut) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    world.set_world_transform(a, rl_world({10, 20, 30}, 2.5f));
    RunningLightStore s;
    s.set(a, {static_light({1, 0, 0}, {1, 0.5f, 0})}, 0.0f);
    s.set_levels({{a, 1.0f}});
    RunningLightDials dials;  // intensity 4
    const auto sprites = s.build_sprites(world, 0.0f, dials, {0, 0, 0}, 0.0f, 0);
    ASSERT_EQ(sprites.size(), 1u);
    EXPECT_NEAR(sprites[0].world_pos.x, 10.0f, 1e-4f);
    EXPECT_NEAR(sprites[0].world_pos.y, 21.0f, 1e-4f);   // body +X -> world +Y, unscaled
    EXPECT_NEAR(sprites[0].world_pos.z, 30.0f, 1e-4f);
    EXPECT_NEAR(sprites[0].color.r, 4.0f, 1e-5f);
    EXPECT_NEAR(sprites[0].color.g, 2.0f, 1e-5f);
    EXPECT_NEAR(sprites[0].half_size, 0.5f * 1.5f * 0.02f, 1e-6f);
}

TEST(RunningLightStore, LevelAndBlinkScaleColourAndDarkLightsAreDropped) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    world.set_world_transform(a, glm::mat4(1.0f));
    RunningLight blinker = static_light({0, 0, 0}, {1, 1, 1});
    blinker.duration = 1.0f;   // on 0.1..0.9 of each 3 s period
    RunningLightStore s;
    s.set(a, {blinker}, 0.0f);
    s.set_levels({{a, 0.5f}});
    auto on = s.build_sprites(world, 0.5f, RunningLightDials{}, {0, 0, -1}, 0.0f, 0);
    ASSERT_EQ(on.size(), 1u);
    EXPECT_NEAR(on[0].color.r, 4.0f * 0.5f, 1e-5f);
    EXPECT_TRUE(s.build_sprites(world, 2.0f, RunningLightDials{}, {0, 0, -1}, 0.0f, 0).empty());
    s.set_levels({{a, 0.0f}});
    EXPECT_TRUE(s.build_sprites(world, 0.5f, RunningLightDials{}, {0, 0, -1}, 0.0f, 0).empty());
}

TEST(RunningLightStore, DestroyedInstanceIsSkipped) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    RunningLightStore s;
    s.set(a, {static_light({1, 0, 0}, {1, 0, 0})}, 0.0f);
    s.set_levels({{a, 1.0f}});
    world.destroy_instance(a);
    EXPECT_TRUE(s.build_sprites(world, 0.0f, RunningLightDials{}, {0, 0, 0}, 0.0f, 0).empty());
}

TEST(RunningLightStore, SpriteCountIsCapped) {
    scenegraph::World world;
    const auto a = world.create_instance(1);
    world.set_world_transform(a, glm::mat4(1.0f));
    std::vector<RunningLight> many(renderer::kMaxRunningLightSprites + 50,
                                   static_light({0, 0, 0}, {1, 1, 1}));
    RunningLightStore s;
    s.set(a, many, 0.0f);
    s.set_levels({{a, 1.0f}});
    EXPECT_EQ(s.build_sprites(world, 0.0f, RunningLightDials{}, {0, 0, -1}, 0.0f, 0).size(),
              renderer::kMaxRunningLightSprites);
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `renderer/running_light_store.h: No such file or directory`.

- [ ] **Step 3: Implement**

Create `native/src/renderer/include/renderer/running_light_store.h` with exactly the declarations in **Interfaces** above, plus includes `<cstddef> <utility> <vector> <glm/glm.hpp> <scenegraph/world.h>`, and a private `struct Entry { scenegraph::InstanceId id; std::vector<RunningLight> lights; float phase = 0.0f; float level = 0.0f; };` with `std::vector<Entry> entries_;` (a linear scan: tens of ships at most).

Create `native/src/renderer/running_light_store.cc`:

```cpp
// native/src/renderer/running_light_store.cc
#include "renderer/running_light_store.h"

#include "renderer/running_light_math.h"

#include <algorithm>
#include <cstdio>

namespace renderer {

void RunningLightStore::set(scenegraph::InstanceId id, std::vector<RunningLight> lights,
                            float phase) {
    if (lights.empty()) { erase(id); return; }
    for (auto& e : entries_) {
        if (e.id == id) { e.lights = std::move(lights); e.phase = phase; return; }
    }
    entries_.push_back(Entry{id, std::move(lights), phase, 0.0f});
}

void RunningLightStore::set_levels(
        const std::vector<std::pair<scenegraph::InstanceId, float>>& levels) {
    for (auto& e : entries_) e.level = 0.0f;   // unlisted this frame => dark
    for (const auto& [id, level] : levels)
        for (auto& e : entries_)
            if (e.id == id) e.level = std::clamp(level, 0.0f, 1.0f);
}

void RunningLightStore::erase(scenegraph::InstanceId id) {
    entries_.erase(std::remove_if(entries_.begin(), entries_.end(),
                                  [&](const Entry& e) { return e.id == id; }),
                   entries_.end());
}

void RunningLightStore::clear() { entries_.clear(); }

std::size_t RunningLightStore::size() const noexcept { return entries_.size(); }

float RunningLightStore::level(scenegraph::InstanceId id) const noexcept {
    for (const auto& e : entries_) if (e.id == id) return e.level;
    return 0.0f;
}

std::vector<RunningLightSprite> RunningLightStore::build_sprites(
        const scenegraph::World& world, float game_time, const RunningLightDials& dials,
        const glm::vec3& cam_eye, float proj11, int viewport_h) const {
    std::vector<RunningLightSprite> out;
    static bool warned_cap = false;
    for (const auto& e : entries_) {
        if (e.level <= 0.0f) continue;
        // By id, NOT for_each_visible_in_pass: a cloaking hull is
        // set_visible(false) while its lights must still fade out.
        const scenegraph::Instance* inst = world.get(e.id);
        if (inst == nullptr) continue;
        const glm::mat4& M = inst->world;
        const glm::mat3 RS = glm::mat3(M);
        const float s = std::max(glm::length(glm::vec3(M[0])), 1e-6f);
        const glm::vec3 t = glm::vec3(M[3]);
        for (const auto& l : e.lights) {
            const float a = e.level *
                running_light_blink_alpha(game_time, l.period, l.duration, e.phase);
            if (a <= 0.0f) continue;
            if (out.size() >= kMaxRunningLightSprites) {
                if (!warned_cap) {
                    std::fprintf(stderr, "[running_lights] sprite cap %zu reached; "
                                 "extra lights skipped\n", kMaxRunningLightSprites);
                    warned_cap = true;
                }
                return out;
            }
            RunningLightSprite sp;
            sp.world_pos = t + (RS * l.body_pos) / s;
            const float dist = glm::length(sp.world_pos - cam_eye);
            sp.half_size = 0.5f * running_light_world_size(
                l.size, dials.size_gu_per_radius, dials.min_px, dist, proj11, viewport_h);
            sp.color = l.rgb * (dials.intensity * a);
            out.push_back(sp);
        }
    }
    return out;
}

}  // namespace renderer
```

Add `running_light_store.cc` to the renderer sources.

- [ ] **Step 4: Run to verify it passes**

Run: `cmake --build build -j 2>&1 | tail -3 && ctest --test-dir build -R "RunningLight" --output-on-failure`
Expected: 15 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/running_light_store.h native/src/renderer/running_light_store.cc native/src/renderer/CMakeLists.txt native/tests/renderer/running_light_test.cc
git commit -m "feat(renderer): running-light store and hull-attached sprite builder

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Native GL pass and shaders

**Files:**
- Create: `native/src/renderer/include/renderer/running_light_pass.h`
- Create: `native/src/renderer/running_light_pass.cc`
- Create: `native/src/renderer/shaders/running_light.vert`, `native/src/renderer/shaders/running_light.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (two `embed_shader` lines beside the `hull_discharge` ones at ~92-93; add `running_light_pass.cc`)
- Modify: `native/src/renderer/include/renderer/pipeline.h` (accessor + member beside `hull_discharge_`), `native/src/renderer/pipeline.cc` (include the two embedded headers beside lines 49-50; construct beside line 153)
- Modify test: `native/tests/renderer/frame_test.cc` (append a `FrameTest`)

**Interfaces:**
- Consumes: Task 4's `RunningLightSprite`.
- Produces: `class RunningLightPass { public: void render(const scenegraph::Camera&, Pipeline&, const std::vector<RunningLightSprite>&); }`; `Pipeline::running_light_shader()`.

- [ ] **Step 1: Write the failing frame test** — append to `native/tests/renderer/frame_test.cc` (add `#include <renderer/running_light_pass.h>` beside the `hull_discharge_pass.h` include at the top):

```cpp
TEST_F(FrameTest, RunningLightDrawsAndIsDepthOccluded) {
    const int kW = 256, kH = 256;
    renderer::HdrTarget hdr;
    hdr.resize(kW, kH);

    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, -10.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.up     = glm::vec3(0.0f, 1.0f, 0.0f);
    cam.aspect = 1.0f;
    cam.near   = 0.1f;
    cam.far    = 1000.0f;

    renderer::RunningLightSprite sp;
    sp.world_pos = glm::vec3(0.0f);
    sp.half_size = 0.2f;
    sp.color     = glm::vec3(4.0f, 0.0f, 0.0f);   // HDR red

    renderer::RunningLightPass pass;

    auto centre = [&]() {
        float px[4] = {0};
        glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_FLOAT, px);
        return glm::vec3(px[0], px[1], px[2]);
    };
    auto clear_to_depth = [&](float depth) {
        hdr.bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClearDepth(depth);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glClearDepth(1.0);
    };

    // Empty list: zero GL work, target untouched.
    clear_to_depth(1.0f);
    pass.render(cam, *p, {});
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_FLOAT_EQ(centre().r, 0.0f);

    // Open scene: the sprite centre is bright red, additive HDR (> 1).
    clear_to_depth(1.0f);
    pass.render(cam, *p, {sp});
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const glm::vec3 lit = centre();
    EXPECT_GT(lit.r, 1.0f);
    EXPECT_FLOAT_EQ(lit.g, 0.0f);

    // Depth already at the near plane (a hull in front): occluded.
    clear_to_depth(0.0f);
    pass.render(cam, *p, {sp});
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_FLOAT_EQ(centre().r, 0.0f);

    // The pass must not write depth: a second sprite behind the first still draws.
    clear_to_depth(1.0f);
    renderer::RunningLightSprite behind = sp;
    behind.world_pos = glm::vec3(0.0f, 0.0f, 5.0f);
    behind.color = glm::vec3(0.0f, 4.0f, 0.0f);
    pass.render(cam, *p, {sp, behind});
    EXPECT_GT(centre().g, 0.0f);

    // GL state restored to canonical defaults.
    GLboolean depth_mask = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask);
    EXPECT_EQ(depth_mask, GL_TRUE);
    EXPECT_FALSE(glIsEnabled(GL_BLEND));
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `renderer/running_light_pass.h: No such file or directory`.

- [ ] **Step 3: Implement**

`native/src/renderer/shaders/running_light.vert`:

```glsl
#version 410 core
layout(location = 0) in vec2 a_corner;   // [-1,1] quad corner

uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_center;     // light world pos
uniform float u_half_size;  // billboard half-size (GU)

out vec2 v_uv;
void main() {
    vec3 right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 wp = u_center + (right * a_corner.x + up * a_corner.y) * u_half_size;
    v_uv = a_corner;
    gl_Position = u_proj * u_view * vec4(wp, 1.0);
}
```

`native/src/renderer/shaders/running_light.frag`:

```glsl
#version 410 core
in vec2 v_uv;
out vec4 frag;

uniform vec3 u_color;   // rgb * intensity * level * blink (premultiplied)

// One soft disc, no separate halo: with HDR on the core (above the bloom
// threshold) blooms like every other bright source; with HDR off the soft
// edge still reads as a small light (running-lights spec §4.4).
void main() {
    float r = length(v_uv);
    if (r >= 1.0) { frag = vec4(0.0); return; }
    float f = 1.0 - smoothstep(0.0, 1.0, r);
    frag = vec4(u_color * f * f, 0.0);
}
```

`native/src/renderer/include/renderer/running_light_pass.h`:

```cpp
// native/src/renderer/include/renderer/running_light_pass.h
#pragma once

#include "renderer/running_light_store.h"

#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// Ship running lights: additive camera-facing soft discs. Depth-test on (the
/// hull hides far-side lights), depth-write off, GL state restored to the
/// canonical defaults. Zero GL work for an empty list.
class RunningLightPass {
public:
    RunningLightPass() = default;
    ~RunningLightPass();
    RunningLightPass(const RunningLightPass&)            = delete;
    RunningLightPass& operator=(const RunningLightPass&) = delete;

    void render(const scenegraph::Camera& camera, Pipeline& pipeline,
                const std::vector<RunningLightSprite>& sprites);

private:
    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;
    void ensure_quad_mesh();
};

}  // namespace renderer
```

`native/src/renderer/running_light_pass.cc`:

```cpp
// native/src/renderer/running_light_pass.cc
#include "renderer/running_light_pass.h"

#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace renderer {

namespace {
constexpr float kQuadCorners[] = {
    -1.0f, -1.0f,  +1.0f, -1.0f,  +1.0f, +1.0f,
    -1.0f, -1.0f,  +1.0f, +1.0f,  -1.0f, +1.0f,
};
}  // namespace

RunningLightPass::~RunningLightPass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void RunningLightPass::ensure_quad_mesh() {
    if (quad_vao_ != 0) return;
    glGenVertexArrays(1, &quad_vao_);
    glBindVertexArray(quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kQuadCorners), kQuadCorners, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float),
                          reinterpret_cast<void*>(0));
    glBindVertexArray(0);
}

void RunningLightPass::render(const scenegraph::Camera& camera, Pipeline& pipeline,
                              const std::vector<RunningLightSprite>& sprites) {
    if (sprites.empty()) return;
    ensure_quad_mesh();
    auto& shader = pipeline.running_light_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());

    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);
    glBindVertexArray(quad_vao_);
    for (const auto& s : sprites) {
        shader.set_vec3 ("u_center",    s.world_pos);
        shader.set_float("u_half_size", s.half_size);
        shader.set_vec3 ("u_color",     s.color);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glEnable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
}

}  // namespace renderer
```

In `native/src/renderer/CMakeLists.txt` add beside the hull_discharge lines:

```cmake
embed_shader(SHADER_RUNNING_LIGHT_VS shaders/running_light.vert running_light_vs)
embed_shader(SHADER_RUNNING_LIGHT_FS shaders/running_light.frag running_light_fs)
```

and add `running_light_pass.cc` to the sources. If the `SHADER_HULL_DISCHARGE_*` variables are referenced anywhere else in that file (e.g. a sources list), add the `SHADER_RUNNING_LIGHT_*` pair to the same place.

In `pipeline.h` add `Shader& running_light_shader() noexcept { return *running_light_; }` beside `hull_discharge_shader()` and `std::unique_ptr<Shader> running_light_;` beside `hull_discharge_`. In `pipeline.cc` add `#include "embedded_running_light_vs.h"` / `#include "embedded_running_light_fs.h"` beside lines 49-50 and, beside line 153:

```cpp
    running_light_ = std::make_unique<Shader>(shader_src::running_light_vs, shader_src::running_light_fs);
```

- [ ] **Step 4: Run to verify it passes**

Shader edits need a reconfigure to re-embed: `cmake -B build -S . > /dev/null && cmake --build build -j 2>&1 | tail -3 && ctest --test-dir build -R "RunningLight" --output-on-failure`
Expected: 16 tests PASS (the frame test constructs `Pipeline`, which compiles the new shaders).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/running_light_pass.h native/src/renderer/running_light_pass.cc native/src/renderer/shaders/running_light.vert native/src/renderer/shaders/running_light.frag native/src/renderer/CMakeLists.txt native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc native/tests/renderer/frame_test.cc
git commit -m "feat(renderer): running-light GL pass (additive, depth-tested soft discs)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Host bindings, frame wiring, renderer façade

**Files:**
- Modify: `native/src/host/host_bindings.cc` (globals near `g_hull_discharges` ~line 413; `reset_frame_state` ~line 915; `destroy_instance` binding ~line 3224; space phase after the `space.weapons` scope ~line 1820; new `m.def`s beside `set_cloak_ships` ~line 6051; pass construction/teardown beside `g_hull_discharge_pass` ~lines 1095 and the matching `.reset()`)
- Modify: `engine/renderer.py` (wrappers + `_REQUIRED_BINDINGS`)
- Test: `tests/unit/test_running_light_bindings.py` (create)

**Interfaces:**
- Consumes: Task 4 `RunningLightStore`, `RunningLightDials`; Task 5 `RunningLightPass`.
- Produces (Python, `engine.renderer`):
  - `set_running_lights(iid, lights: list[tuple[9 floats]], phase: float) -> None` (empty list removes)
  - `set_running_light_levels(levels: list[tuple[iid, float]]) -> None`
  - `set_running_light_dials(size_gu_per_radius: float, min_px: float, intensity: float) -> None`
  - `running_lights_set_enabled(enabled: bool) -> None`, `running_lights_enabled() -> bool`
  - `running_light_count() -> int` (ships currently stored; for tests and diagnostics)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_running_light_bindings.py`:

```python
"""Running-light host bindings (running-lights spec §4.3/§4.4).

The store and pass are covered by gtest; this pins the Python-visible
contract: the bindings exist, accept the documented shapes, purge on
destroy_instance and on reset, and the toggle round-trips. Needs the built
_dauntless_host; skips when it is absent (headless contexts).
"""
import pytest

_h = pytest.importorskip("_dauntless_host")
import engine.renderer as r


@pytest.fixture(autouse=True)
def _clean():
    r.running_lights_set_enabled(True)
    yield
    r.running_lights_set_enabled(True)


def _light(x=0.0):
    return (x, 0.5, 0.25, 1.0, 0.0, 0.0, 1.5, 3.0, 0.0)


def _new_instance():
    # ModelHandle is a plain uint64 and create_instance only touches the
    # scenegraph World: no GL context, no model needed.
    return _h.create_instance(1)


def test_toggle_round_trips_and_defaults_on():
    assert r.running_lights_enabled() is True
    r.running_lights_set_enabled(False)
    assert r.running_lights_enabled() is False


def test_dials_and_empty_levels_are_accepted():
    r.set_running_light_dials(0.02, 1.5, 4.0)
    r.set_running_light_levels([])


def test_destroy_instance_purges_its_lights():
    iid = _new_instance()
    r.set_running_lights(iid, [_light(), _light(1.0)], 1.0)
    assert r.running_light_count() == 1
    r.destroy_instance(iid)
    assert r.running_light_count() == 0


def test_a_recycled_id_does_not_inherit_lights():
    old = _new_instance()
    r.set_running_lights(old, [_light()], 1.0)
    r.destroy_instance(old)
    new = _new_instance()          # may reuse old's index
    assert r.running_light_count() == 0
    r.destroy_instance(new)


def test_empty_list_removes_a_ship():
    iid = _new_instance()
    r.set_running_lights(iid, [_light()], 1.0)
    r.set_running_lights(iid, [], 0.0)
    assert r.running_light_count() == 0
    r.destroy_instance(iid)
```

(Verified 2026-10-14: `_dauntless_host.create_instance(1)` and `destroy_instance` work headless from Python.)

- [ ] **Step 2: Run to verify it fails**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_running_light_bindings.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: module 'engine.renderer' has no attribute 'running_lights_set_enabled'`.

- [ ] **Step 3: Implement the native side**

In `host_bindings.cc`:

1. Includes beside `#include <renderer/hull_discharge_pass.h>`:
   ```cpp
   #include <renderer/running_light_pass.h>
   #include <renderer/running_light_store.h>
   ```
2. Globals beside `g_hull_discharges` / `g_hull_discharge_pass`:
   ```cpp
   // Ship running lights (running-lights spec §4.4). The store is per-instance
   // and Python-fed at spawn; levels arrive every frame.
   renderer::RunningLightStore                  g_running_lights;
   renderer::RunningLightDials                  g_running_light_dials;
   bool                                         g_running_lights_enabled = true;
   std::unique_ptr<renderer::RunningLightPass>  g_running_light_pass;
   ```
3. Construct beside `g_hull_discharge_pass = std::make_unique<...>()`:
   `g_running_light_pass = std::make_unique<renderer::RunningLightPass>();`
   and `g_running_light_pass.reset();` beside the matching `g_hull_discharge_pass.reset();`.
4. In `reset_frame_state()` (init/shutdown hygiene; it does NOT run on a mission swap), beside `g_hull_discharges.clear();`: `g_running_lights.clear();`
5. In the `destroy_instance` binding, inside `if (was_valid) {`: `g_running_lights.erase(id);`
6. In the space phase, immediately after the closing brace of the `space.weapons` scope:
   ```cpp
        if (g_running_lights_enabled && g_running_light_pass && g_running_lights.size() > 0) {
            DAUNTLESS_FRAME_SCOPE("space.running_lights");
            const auto sprites = g_running_lights.build_sprites(
                g_world, g_decal_game_time, g_running_light_dials,
                cam.eye, cam.proj_matrix()[1][1], vh);
            g_running_light_pass->render(cam, *g_pipeline, sprites);
        }
   ```
7. Bindings beside `set_cloak_ships`:
   ```cpp
    m.def("set_running_lights",
          [](scenegraph::InstanceId id,
             const std::vector<std::array<float, 9>>& lights, float phase) {
              std::vector<renderer::RunningLight> out;
              out.reserve(lights.size());
              for (const auto& a : lights) {
                  renderer::RunningLight l;
                  l.body_pos = {a[0], a[1], a[2]};
                  l.rgb      = {a[3], a[4], a[5]};
                  l.size = a[6]; l.period = a[7]; l.duration = a[8];
                  out.push_back(l);
              }
              g_running_lights.set(id, std::move(out), phase);
          },
          py::arg("instance_id"), py::arg("lights"), py::arg("phase"),
          "Set a ship's running lights: each (px,py,pz, r,g,b, size, period, "
          "duration), body frame, unscaled GU. An empty list removes the ship.");
    m.def("set_running_light_levels",
          [](const std::vector<std::pair<scenegraph::InstanceId, float>>& levels) {
              g_running_lights.set_levels(levels);
          },
          py::arg("levels"),
          "Per-frame brightness (instance_id, level in [0,1]). Ships not listed "
          "draw dark this frame.");
    m.def("set_running_light_dials",
          [](float size_gu_per_radius, float min_px, float intensity) {
              g_running_light_dials = {size_gu_per_radius, min_px, intensity};
          },
          py::arg("size_gu_per_radius"), py::arg("min_px"), py::arg("intensity"));
    m.def("running_lights_set_enabled",
          [](bool v) { g_running_lights_enabled = v; }, py::arg("enabled"));
    m.def("running_lights_enabled", []() { return g_running_lights_enabled; });
    m.def("running_light_count",
          []() { return static_cast<int>(g_running_lights.size()); });
   ```
   (Add `#include <array>` if not already included.)

- [ ] **Step 4: Implement the façade**

In `engine/renderer.py`, beside `set_cloak_ships`:

```python
def set_running_lights(iid, lights, phase: float) -> None:
    """A ship's running lights, sent once at spawn (running-lights spec §4.3).
    `lights` is a list of 9-tuples (px,py,pz, r,g,b, size, period, duration),
    body frame, unscaled GU. An empty list removes the ship."""
    _h.set_running_lights(iid, [tuple(float(v) for v in l) for l in lights],
                          float(phase))


def set_running_light_levels(levels) -> None:
    """Per-frame (instance_id, level) brightness; unlisted ships draw dark."""
    _h.set_running_light_levels([(iid, float(lv)) for iid, lv in levels])


def set_running_light_dials(size_gu_per_radius: float, min_px: float,
                            intensity: float) -> None:
    _h.set_running_light_dials(float(size_gu_per_radius), float(min_px),
                               float(intensity))


def running_lights_set_enabled(enabled: bool) -> None:
    _h.running_lights_set_enabled(bool(enabled))


def running_lights_enabled() -> bool:
    return bool(_h.running_lights_enabled())


def running_light_count() -> int:
    return int(_h.running_light_count())
```

Add `"running_light_count"`, `"running_lights_enabled"`, `"running_lights_set_enabled"`, `"set_running_light_dials"`, `"set_running_light_levels"`, `"set_running_lights"` to `_REQUIRED_BINDINGS` (keep the set's alphabetical grouping).

- [ ] **Step 5: Build and run**

Run: `cmake --build build -j 2>&1 | tail -3 && unset VIRTUAL_ENV && uv run pytest tests/unit/test_running_light_bindings.py tests/unit/test_renderer_binding_manifest.py -q -p no:cacheprovider`
Expected: PASS (the manifest test proves the six names are declared).

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py tests/unit/test_running_light_bindings.py
git commit -m "feat(host): running-light bindings, frame wiring, purge on destroy and reset

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Host-loop wiring (spawn, per-frame levels, teardown, dial group)

**Files:**
- Modify: `engine/host_loop.py`:
  - `MissionSession`: new field beside `ship_emitters` (~line 6214); clear beside `self.ship_emitters.clear()` (~line 6265)
  - spawn: beside `session.ship_emitters[iid] = _build_ship_emitter_cache(ship)` in `realize_set_objects` (~line 6481) and `sess.ship_emitters[iid] = ...` in `_realize_session` (~line 7669)
  - removal: beside `session.ship_emitters.pop(iid, None)` (~line 6785)
  - per frame: after `_push_cloak_refraction(r, session, player)` (~line 12610)
  - boot: beside `_sensor_dials.register()` (~line 10379)
- Test: `tests/unit/test_running_lights_host_push.py` (create)

**Interfaces:**
- Consumes: Task 2 `running_lights.lights_for/phase_for/level_for`, `running_light_dials.current/register`; Task 6 `r.set_running_lights`, `r.set_running_light_levels`, `r.set_running_light_dials`.
- Produces: `engine.host_loop._register_running_lights(r, session, ship, iid) -> None`; `engine.host_loop._push_running_lights(r, session) -> None`; `MissionSession.ship_running_lights: dict[iid, float]` (iid → phase).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_running_lights_host_push.py`:

```python
"""Host-loop running-light wiring (running-lights spec §4.3)."""
import pytest

import App
from engine import host_loop
from engine.appc import running_light_dials
from engine.appc.math import TGPoint3
from engine.appc.properties import TGModelPropertySet
from engine.appc.subsystems import CloakingSubsystem


class _FakeRenderer:
    def __init__(self):
        self.lights = {}
        self.levels = None
        self.dials = None
    def set_running_lights(self, iid, lights, phase):
        self.lights[iid] = (list(lights), phase)
    def set_running_light_levels(self, levels):
        self.levels = list(levels)
    def set_running_light_dials(self, size_gu_per_radius, min_px, intensity):
        self.dials = (size_gu_per_radius, min_px, intensity)


class _Ship:
    def __init__(self, n_lights=2, name="USS Voyager", cloak=None, power=None):
        self._pset = TGModelPropertySet()
        for i in range(n_lights):
            p = App.BlinkingLightProperty_Create("L%d" % i)
            pt = TGPoint3(); pt.SetXYZ(float(i), 0.0, 0.0)
            p.SetPosition(pt)
            self._pset.AddToSet("Scene Root", p)
        self._name, self._cloak, self._power = name, cloak, power
    def GetPropertySet(self): return self._pset
    def GetName(self): return self._name
    def GetCloakingSubsystem(self): return self._cloak
    def GetPowerSubsystem(self): return self._power
    def IsDying(self): return 0
    def IsDead(self): return 0


class _Session:
    def __init__(self, mapping):
        self.ship_instances = dict(mapping)
        self.ship_running_lights = {}
        self.scope_hidden = set()


def test_register_sends_lights_once_with_phase():
    r = _FakeRenderer()
    ship = _Ship(n_lights=2)
    s = _Session({ship: 7})
    host_loop._register_running_lights(r, s, ship, 7)
    lights, phase = r.lights[7]
    assert len(lights) == 2 and len(lights[0]) == 9
    assert s.ship_running_lights == {7: phase}


def test_register_unlit_ship_sends_nothing():
    r = _FakeRenderer()
    ship = _Ship(n_lights=0)
    s = _Session({ship: 7})
    host_loop._register_running_lights(r, s, ship, 7)
    assert r.lights == {}
    assert s.ship_running_lights == {}


def test_push_sends_levels_and_dials_for_lit_ships():
    r = _FakeRenderer()
    lit, unlit = _Ship(2, name="A"), _Ship(0, name="B")
    s = _Session({lit: 1, unlit: 2})
    host_loop._register_running_lights(r, s, lit, 1)
    host_loop._register_running_lights(r, s, unlit, 2)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(1, 1.0)]
    assert r.dials == tuple(running_light_dials.current().values())


def test_push_scope_hidden_ship_is_dark():
    r = _FakeRenderer()
    ship = _Ship(2)
    s = _Session({ship: 3})
    host_loop._register_running_lights(r, s, ship, 3)
    s.scope_hidden.add(3)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(3, 0.0)]


def test_push_reads_cloak_fraction():
    c = CloakingSubsystem("Cloak")
    c.StartCloaking()
    c.Update(c._transition_duration * 0.5)
    frac = c.GetTransitionFraction()
    r = _FakeRenderer()
    ship = _Ship(2, cloak=c)
    s = _Session({ship: 4})
    host_loop._register_running_lights(r, s, ship, 4)
    host_loop._push_running_lights(r, s)
    assert r.levels[0][1] == pytest.approx(1.0 - frac)


def test_push_ship_without_cloak_or_power_subsystem_is_lit():
    r = _FakeRenderer()
    ship = _Ship(1, cloak=None, power=None)
    s = _Session({ship: 5})
    host_loop._register_running_lights(r, s, ship, 5)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(5, 1.0)]


def test_push_with_no_lit_ships_sends_nothing():
    r = _FakeRenderer()
    host_loop._push_running_lights(r, _Session({}))
    assert r.levels is None and r.dials is None


def test_push_drops_a_lit_iid_whose_ship_is_gone():
    r = _FakeRenderer()
    ship = _Ship(1)
    s = _Session({ship: 6})
    host_loop._register_running_lights(r, s, ship, 6)
    s.ship_instances.clear()        # removed without the pop (defensive)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(6, 0.0)]


def test_mission_session_teardown_clears_running_lights():
    class _R:
        def destroy_instance(self, iid):
            pass
    sess = host_loop.MissionSession(mission_name="t")
    sess.ship_running_lights[9] = 1.0
    sess.teardown(_R())
    assert sess.ship_running_lights == {}
```

Also add to `tests/unit/test_reconcile_runtime_ships.py` (it already has the
`_FakeRenderer`, `_make_set`, `_add_ship`, `_force_nif` helpers this uses):

```python
def test_reconcile_removal_drops_running_lights(monkeypatch):
    """A ship removed at runtime must not leave its running-light entry behind
    for a recycled instance id to inherit."""
    from engine import host_loop as hl
    _force_nif(monkeypatch, hl)
    App.g_kSetManager.DeleteAllSets()
    s = _make_set("S")
    App.g_kSetManager.MakeRenderedSet("S")
    drop = _add_ship(s, "drop")
    sess = hl.MissionSession(mission_name="t")
    r = _FakeRenderer()
    hl.realize_set_objects(sess, s, r)
    drop_iid = sess.ship_instances[drop]
    sess.ship_running_lights[drop_iid] = 12.5      # as if it had lights
    s.RemoveObjectFromSet("drop")
    hl._reconcile_runtime_instances(sess, r)
    assert drop_iid not in sess.ship_running_lights
    App.g_kSetManager.DeleteAllSets()
```

- [ ] **Step 2: Run to verify they fail**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_running_lights_host_push.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: module 'engine.host_loop' has no attribute '_register_running_lights'`.

- [ ] **Step 3: Implement**

Add to `engine/host_loop.py`, directly after `_push_cloak_refraction`:

```python
def _register_running_lights(r, session, ship, iid) -> None:
    """Send a ship's BlinkingLightProperty running lights to native once, at
    spawn (running-lights spec §4.3). Unlit ships send nothing."""
    from engine.appc import running_lights
    specs = running_lights.lights_for(ship)
    if not specs:
        return
    phase = running_lights.phase_for(ship)
    session.ship_running_lights[iid] = phase
    r.set_running_lights(iid, [s.as_tuple() for s in specs], phase)


def _push_running_lights(r, session) -> None:
    """Per-frame running-light brightness + dials (spec §4.3). Level folds in
    death, power-plant state and the live cloak fraction; a scope-hidden or
    vanished ship is sent 0. No lit ships => no calls at all."""
    lit = getattr(session, "ship_running_lights", None)
    if not lit:
        return
    import App  # deferred, as elsewhere in this module (sound-manager init order)
    from engine.appc import running_lights, running_light_dials
    now = App.g_kUtopiaModule.GetGameTime()
    by_iid = {iid: ship for ship, iid in session.ship_instances.items()}
    hidden = getattr(session, "scope_hidden", ())
    levels = []
    for iid, phase in lit.items():
        ship = by_iid.get(iid)
        if ship is None or iid in hidden:
            levels.append((iid, 0.0))
            continue
        frac = 0.0
        get_cloak = getattr(ship, "GetCloakingSubsystem", None)
        cloak = get_cloak() if get_cloak is not None else None
        if cloak is not None:
            frac = float(cloak.GetTransitionFraction())
        try:
            levels.append((iid, running_lights.level_for(ship, frac, now, phase)))
        except Exception as _e:
            dev_mode.log_swallowed("running light level", _e)
            levels.append((iid, 0.0))
    r.set_running_light_levels(levels)
    d = running_light_dials.current()
    r.set_running_light_dials(d["size_gu_per_radius"], d["min_px"], d["intensity"])
```

`MissionSession`: beside `ship_emitters`, add

```python
    # Running lights registered at spawn: render InstanceId -> blink phase (s).
    # Fed per frame by _push_running_lights (running-lights spec §4.3).
    ship_running_lights: dict[object, float] = field(default_factory=dict)
```

and `self.ship_running_lights.clear()` beside `self.ship_emitters.clear()`.

Spawn — at BOTH sites, immediately after the `ship_emitters` try/except block:

```python
        # Running lights (best-effort VFX); never block spawn.
        try:
            _register_running_lights(r_, session, ship, iid)
        except Exception as _e:
            dev_mode.log_swallowed("realize running lights", _e)
```

(use `sess` instead of `session` at the `_realize_session` site, matching its local name).

Removal — beside `session.ship_emitters.pop(iid, None)`: `session.ship_running_lights.pop(iid, None)`.

Per frame — after `_push_cloak_refraction(r, session, player)`:

```python
            _push_running_lights(r, session)
```

Boot — beside `_sensor_dials.register()`:

```python
                from engine.appc import running_light_dials as _rl_dials
                _rl_dials.register()
```

- [ ] **Step 4: Run to verify they pass**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_running_lights_host_push.py tests/unit/test_cloak_refraction_push.py tests/unit/test_reconcile_runtime_ships.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_running_lights_host_push.py tests/unit/test_reconcile_runtime_ships.py
git commit -m "feat(host_loop): register running lights at spawn, push levels per frame

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Developer Options toggle

**Files:**
- Modify: `engine/ui/developer_options_panel.py` (state ~line 111-135, `open()` ~line 160, snapshot + payload ~lines 190-235, toggle handler beside `toggle:normal_maps` ~line 293, `_focusables` lighting list ~line 421)
- Modify: `native/assets/ui-cef/js/developer_options.js` (lighting focusables ~line 28-36, `_doRenderLightingBody` ~line 150-170)
- Test: `tests/ui/test_developer_options_lighting_tab.py` (append)

**Interfaces:**
- Consumes: Task 6 `renderer.running_lights_enabled()`, `renderer.running_lights_set_enabled(bool)`.
- Produces: control id `running_lights` on the Lighting tab; payload key `settings.running_lights`.

- [ ] **Step 1: Write the failing tests** — append to `tests/ui/test_developer_options_lighting_tab.py` (it already has the autouse `_dev_on` fixture and the `_payload(p)` helper):

```python
def test_running_lights_row_is_on_the_lighting_tab(monkeypatch):
    import engine.renderer as renderer
    monkeypatch.setattr(renderer, "running_lights_enabled", lambda: True)
    p = DeveloperOptionsPanel()
    p.open()
    assert p.dispatch_event("tab:lighting")
    assert ("ctrl", "running_lights") in p._focusables()
    assert _payload(p)["settings"]["running_lights"] is True


def test_running_lights_toggle_flips_the_renderer(monkeypatch):
    import engine.renderer as renderer
    calls = []
    monkeypatch.setattr(renderer, "running_lights_set_enabled", calls.append)
    monkeypatch.setattr(renderer, "running_lights_enabled", lambda: True)
    p = DeveloperOptionsPanel()
    p.open()
    assert p.dispatch_event("tab:lighting")
    assert p.dispatch_event("toggle:running_lights")
    assert calls == [False]
    assert _payload(p)["settings"]["running_lights"] is False
```

`tests/unit/test_developer_options_panel.py::test_every_setting_is_in_the_render_snapshot` already guards that the new field is in the snapshot tuple.

- [ ] **Step 2: Run to verify they fail**

Run: `unset VIRTUAL_ENV; uv run pytest tests/ui/test_developer_options_lighting_tab.py tests/unit/test_developer_options_panel.py -q -p no:cacheprovider`
Expected: FAIL (`("ctrl","running_lights")` missing).

- [ ] **Step 3: Implement**

In `developer_options_panel.py`:

```python
def _running_lights_enabled() -> bool:
    """renderer.running_lights_enabled(), or True (the native default) when
    the renderer is unavailable -- this panel is constructed in headless tests."""
    try:
        return bool(renderer.running_lights_enabled())
    except Exception:
        return True
```

placed beside `_rock_specks_enabled`. Then:
- `__init__` and `open()`: `self._running_lights = _running_lights_enabled()`
- snapshot tuple: append `self._running_lights`
- payload `settings`: `"running_lights": self._running_lights,`
- handler, beside `toggle:normal_maps`:
  ```python
        if action == "toggle:running_lights":
            renderer.running_lights_set_enabled(not self._running_lights)
            self._running_lights = not self._running_lights
  ```
  (match the surrounding handler's return/flow exactly — copy the `toggle:normal_maps` branch's shape, including any `return` after it.)
- `_focusables` lighting list: add `("ctrl", "running_lights")` after `("ctrl", "systems_disabled")`.

In `developer_options.js`:
- lighting focusables: `out.push({kind: 'ctrl', target: 'running_lights'});` after `systems_disabled` (the order MUST match the Python `_focusables` list).
- `_doRenderLightingBody`: after the "Set Systems Disabled" row:
  ```js
    html += _doToggleRow('Running Lights', 'running_lights',
                         s.running_lights, isFoc('running_lights'));
  ```

- [ ] **Step 4: Run to verify they pass**

Run: `unset VIRTUAL_ENV; uv run pytest tests/ui/test_developer_options_lighting_tab.py tests/unit/test_developer_options_panel.py -q -p no:cacheprovider`
Expected: PASS. If a JS/Python focusable-order parity test exists (grep `tests/` for `developer_options.js`), run it too.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/developer_options_panel.py native/assets/ui-cef/js/developer_options.js tests/ui/test_developer_options_lighting_tab.py
git commit -m "feat(dev-options): Lighting -> Running Lights toggle

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Docs and the full gate

**Files:**
- Modify: `CLAUDE.md` (reference table — add a row after "Ship-attached dynamic lights")
- Modify: `docs/superpowers/specs/2026-10-14-ship-running-lights-design.md` (as-built corrections)

- [ ] **Step 1: Spec as-built corrections**

In the spec:
- §4.3: the calls are on `engine.renderer` (the render façade, like `set_cloak_ships`), not `host_io`. Replace `host_io.set_running_lights` / `host_io.set_running_light_levels` / `host_io.set_running_light_dials` / `host_io.set_running_lights_enabled` with `renderer.set_running_lights` / `renderer.set_running_light_levels` / `renderer.set_running_light_dials` / `renderer.running_lights_set_enabled`.
- §4.3: delete the line "Rocks are skipped (`ship_iter.iter_non_rock_ships`)." — rocks carry no BlinkingLightProperty, so `lights_for` already returns nothing for them.
- §4.4 Draw: replace "all sprites in one dynamic-VBO draw" with "one draw per sprite with per-sprite uniforms (the `hull_discharge_pass` pattern; tens to hundreds of sprites)".
- §4.4 Store: replace "`clear` is called from `reset_frame_state` (`host_bindings.cc:915`), the mission-swap reset." with "`clear` is called from `reset_frame_state` (`host_bindings.cc:915`), which runs at native init/shutdown only. A mission swap is covered by `erase`: session teardown destroys every ship instance."

- [ ] **Step 2: CLAUDE.md row**

Add after the "Ship-attached dynamic lights" row:

```markdown
| Ship running lights — `BlinkingLightProperty` | `engine/appc/running_lights.py`, `engine/appc/running_light_dials.py`, `native/src/renderer/running_light_{math,store,pass}.{h,cc}`, `docs/superpowers/specs/2026-10-14-ship-running-lights-design.md` | Mod hardpoints' nav lights (LC Intrepid 19, DCMPv2 10/ship; stock uses none). Additive depth-tested soft discs resolved through the hull's own `inst->world` (by id — they must keep fading while a cloaking hull is invisible). ⚠️ **Deliberately NOT BC**: BC's blink is a D/P² ~9 Hz flicker and its Duration-0 "Static" lights are invisible (RE'd, spec §2); we do on-for-Duration-every-Period and statics always on, per Mark. Level = alive × power-plant glow state × (1 − cloak). No halo: HDR bloom supplies the glow. Dials: "running lights" on `/ L O`. Toggle: Developer Options → Lighting → Running Lights (default on). |
```

- [ ] **Step 3: Run the full gate**

Run: `unset VIRTUAL_ENV PYTHONPATH; scripts/check_tests.sh`
Expected: final line `OK — no new failures.` Any failure it names is a regression from this branch: fix it, do not baseline it.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-10-14-ship-running-lights-design.md
git commit -m "docs: running lights in CLAUDE.md; spec as-built corrections

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Hand off for the live check**

Report to Mark: branch `feat/running-lights`, gate output, and the spec §6 checklist (Quick Battle as the LC Intrepid). Do not merge until Mark has checked it live.
