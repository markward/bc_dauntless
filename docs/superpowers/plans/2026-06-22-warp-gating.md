# Warp Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block engaging warp when the SDK's `WarpPressed` would refuse it (impulse off, warp engine damaged/off, in a nebula, in an asteroid field, near Starbase 12), surfacing the authentic Helm `CantWarp*` line / subtitle, then warping only when clear.

**Architecture:** A point-in-time `warp_gate(ship)` mirroring `WarpPressed`'s check order, called by `on_warp_engage` before `execute_warp`. The spatial checks read real geometry objects (new `MetaNebula` / `AsteroidField`) that the destination system's `_S.py` already creates; the starbase check ray-tests the model's "Inside Visibility" points via the existing `ray_trace_mesh`.

**Tech Stack:** Python engine (`engine/appc/`), pytest, the existing `_dauntless_host.ray_trace_mesh` binding (no C++ changes), crew-speech for dialogue.

## Global Constraints

- Never edit anything under `sdk/Build/scripts/` (SDK is ground truth). Run tests with `uv run pytest`.
- Point-in-time gating ONLY (no per-tick membership / events). Mirrors `WarpPressed`.
- `warp_gate` and every predicate NEVER raise — an un-evaluable/erroring check returns "not blocking" (False), so a gate bug can never wedge warp shut. `speak_deny` failures degrade to a silent block.
- Gate order is exactly `WarpPressed`'s: impulse-off → warp-disabled (CantWarp1) → warp-off (CantWarp5) → nebula (CantWarp2) → asteroid field (CantWarp4) → starbase (CantWarp3). First failure wins.
- Deny line keys are verbatim: `"EngineeringNeedPowerToEngines"` (impulse off, XO), `"CantWarp1"`, `"CantWarp5"`, `"CantWarp2"`, `"CantWarp4"`, `"CantWarp3"`. No new strings.
- No C++/shader changes. No new user-facing strings.
- Starbase check is live-only (needs renderer + starbase instance); headless / no host hook ⇒ that check passes (don't block what can't be evaluated).

**Key existing signatures (verified, consume as-is):**
- `engine/appc/sets.py`: `SetClass.AddObjectToSet(obj, id)`, `.GetObject(id)`, `.GetClassObjectList(class_type)` (isinstance-filters `_objects.values()`), `.GetName()`, `App.g_kSetManager.GetSet(name)`.
- Root `App.py`: `class Nebula(ObjectClass)`, `class AsteroidField(ObjectClass)`, `CT_NEBULA = Nebula`, `CT_ASTEROID_FIELD = AsteroidField`, `CT_POSITION_ORIENTATION_PROPERTY = PositionOrientationProperty`, `ShipClass_GetObject(set, name)`, `ObjectClass_GetObject(set, name)`.
- Placement pattern (`engine/appc/placement.py:99`, `engine/appc/lights.py:97`): create obj → `SetName` → `g_kSetManager.GetSet(set_name).AddObjectToSet(obj, name)` → return.
- `engine/appc/ai.py:1137` `CharacterAction_Create(character, action_type, detail, set_name, flag, database, priority)`; `CharacterAction.AT_SAY_LINE = 12`; `.Play()` routes AT_SAY_LINE to crew speech (voice + subtitle).
- `engine/appc/characters.py:644` `CharacterClass_GetObject(pSet, name)` (auto-vivifies; never None).
- `engine/appc/actions.py:552` `SubtitleAction_Create(database, string_id)`; `.SetDuration(s)`; used inside a `TGSequence_Create()` then `.Play()`.
- `engine/appc/subsystems.py`: `WarpEngineSubsystem.IsDisabled()`, `.IsOn()`; impulse `GetPowerPercentageWanted()`. Ship accessors `GetImpulseEngineSubsystem()`, `GetWarpEngineSubsystem()`, `GetContainingSet()`, `GetWorldLocation()`, `GetWorldRotation()`.
- `host.ray_trace_mesh(instance_id:int, origin:(x,y,z), direction:(x,y,z), max_dist:float) -> ((px,py,pz),(nx,ny,nz),t) | None` (`native/src/host/host_bindings.cc:2112`). `host` = `_dauntless_host` module (`_h` in `run()`); `controller.session.ship_instances: dict[ShipClass,int]`.
- `sdk/Build/scripts/MissionLib.py:1807` `GetPositionOrientationFromProperty(pObject, sName) -> (pos, fwd, up) | (None,None,None)` (works against our engine via `GetPropertySet().GetPropertiesByType(CT_POSITION_ORIENTATION_PROPERTY)`). Starbase "Inside Visibility 1/2" exist in `sdk/.../ships/Hardpoints/fedstarbase.py`.
- `engine/appc/warp.py`: `execute_warp(button, event=None)`, `configure_warp_hooks(...)`. `engine/host_loop.py:3222` `on_warp_engage(button)`.

---

### Task 1: Gate framework + subsystem gates + deny feedback + wiring

The `warp_gate` skeleton with the three subsystem checks live and the three spatial predicates present but returning `False` (filled in Tasks 2-4). Wire `on_warp_engage` to gate before warping.

**Files:**
- Create: `engine/appc/warp_gates.py`
- Modify: `engine/host_loop.py` (`on_warp_engage`, ~line 3222)
- Test: `tests/unit/test_warp_gates.py`

**Interfaces:**
- Produces: `GateResult` (attrs `allowed: bool`, `deny_line: str|None`, `silent: bool`); `warp_gate(ship) -> GateResult`; predicate helpers `_impulse_off(ship)`, `_warp_disabled(ship)`, `_warp_off(ship)`, `_in_nebula(ship)`, `_in_asteroid_field(ship)`, `_near_starbase(ship)` (last three return `False` for now); `speak_deny(ship, line_key) -> None`; `configure_gate_hooks(ray_collide=None)` (used in Task 4).
- Consumes: ship subsystem accessors; `CharacterAction_Create`, `CharacterClass_GetObject`, `SubtitleAction_Create`, `TGSequence_Create`, `g_kLocalizationManager`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_warp_gates.py
from engine.appc import warp_gates as wg


class _Sub:
    def __init__(self, disabled=False, on=True, power=1.0):
        self._d, self._on, self._p = disabled, on, power
    def IsDisabled(self): return 1 if self._d else 0
    def IsOn(self): return 1 if self._on else 0
    def GetPowerPercentageWanted(self): return self._p


class _Ship:
    def __init__(self, impulse=None, warp=None):
        self._imp, self._warp = impulse, warp
    def GetImpulseEngineSubsystem(self): return self._imp
    def GetWarpEngineSubsystem(self): return self._warp
    def GetContainingSet(self): return None


def test_all_clear_allows():
    r = wg.warp_gate(_Ship(_Sub(), _Sub()))
    assert r.allowed is True and r.deny_line is None


def test_impulse_off_blocks_with_xo_line():
    r = wg.warp_gate(_Ship(_Sub(power=0.0), _Sub()))
    assert r.allowed is False
    assert r.deny_line == "EngineeringNeedPowerToEngines"


def test_warp_disabled_blocks_cantwarp1():
    r = wg.warp_gate(_Ship(_Sub(), _Sub(disabled=True)))
    assert (r.allowed, r.deny_line) == (False, "CantWarp1")


def test_warp_off_blocks_cantwarp5():
    r = wg.warp_gate(_Ship(_Sub(), _Sub(on=False)))
    assert (r.allowed, r.deny_line) == (False, "CantWarp5")


def test_no_warp_subsystem_blocks_silently():
    r = wg.warp_gate(_Ship(_Sub(), None))
    assert r.allowed is False and r.deny_line is None and r.silent is True


def test_no_ship_blocks_silently():
    r = wg.warp_gate(None)
    assert r.allowed is False and r.silent is True


def test_order_impulse_before_warp():
    # both impulse-off and warp-disabled -> impulse (XO) line wins
    r = wg.warp_gate(_Ship(_Sub(power=0.0), _Sub(disabled=True)))
    assert r.deny_line == "EngineeringNeedPowerToEngines"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_warp_gates.py -v`
Expected: FAIL (`engine.appc.warp_gates` missing).

- [ ] **Step 3: Implement `engine/appc/warp_gates.py`**

```python
"""Warp gating — point-in-time checks mirroring SDK WarpPressed.

warp_gate(ship) runs the same checks in the same order as
sdk/Build/scripts/Bridge/HelmMenuHandlers.py:WarpPressed and returns a
GateResult. on_warp_engage calls it before execute_warp; a denial speaks the
authentic CantWarp*/XO line (Helm AT_SAY_LINE, else subtitle). Nothing here
ever raises — an un-evaluable check is treated as not-blocking.

Spec: docs/superpowers/specs/2026-06-22-warp-gating-design.md
"""

# Host-supplied segment-vs-mesh test for the starbase check (Task 4).
# fn(starbase_ship, from_xyz_point, to_xyz_point) -> bool (True if the segment
# hits the starbase mesh). None => starbase check can't run (don't block).
_ray_collide_hook = None


def configure_gate_hooks(ray_collide=None):
    global _ray_collide_hook
    _ray_collide_hook = ray_collide


class GateResult:
    __slots__ = ("allowed", "deny_line", "silent")

    def __init__(self, allowed, deny_line=None, silent=False):
        self.allowed = allowed
        self.deny_line = deny_line
        self.silent = silent


def _safe(fn, ship):
    """Evaluate a predicate, treating any error as 'not blocking'."""
    try:
        return bool(fn(ship))
    except Exception:
        return False


def _impulse_off(ship):
    imp = ship.GetImpulseEngineSubsystem()
    return imp is not None and imp.GetPowerPercentageWanted() == 0.0


def _warp_disabled(ship):
    warp = ship.GetWarpEngineSubsystem()
    return warp is not None and bool(warp.IsDisabled())


def _warp_off(ship):
    warp = ship.GetWarpEngineSubsystem()
    return warp is not None and not warp.IsOn()


def _in_nebula(ship):
    return False  # Task 2


def _in_asteroid_field(ship):
    return False  # Task 3


def _near_starbase(ship):
    return False  # Task 4


def warp_gate(ship):
    """Return a GateResult for whether `ship` may warp, in WarpPressed order."""
    if ship is None:
        return GateResult(False, None, silent=True)
    # Impulse subsystem missing -> SDK CallNextHandler (proceed; not a block).
    if ship.GetImpulseEngineSubsystem() is None:
        pass
    elif _safe(_impulse_off, ship):
        return GateResult(False, "EngineeringNeedPowerToEngines")
    # Warp subsystem missing -> SDK silent return.
    if ship.GetWarpEngineSubsystem() is None:
        return GateResult(False, None, silent=True)
    if _safe(_warp_disabled, ship):
        return GateResult(False, "CantWarp1")
    if _safe(_warp_off, ship):
        return GateResult(False, "CantWarp5")
    if _safe(_in_nebula, ship):
        return GateResult(False, "CantWarp2")
    if _safe(_in_asteroid_field, ship):
        return GateResult(False, "CantWarp4")
    if _safe(_near_starbase, ship):
        return GateResult(False, "CantWarp3")
    return GateResult(True, None)


def speak_deny(ship, line_key):
    """Speak the deny line via the Helm officer (AT_SAY_LINE), falling back to a
    3s subtitle. Mirrors WarpPressed's dual path; never raises."""
    import App
    try:
        bridge = App.g_kSetManager.GetSet("bridge")
        helm = App.CharacterClass_GetObject(bridge, "Helm") if bridge else None
        if helm is not None:
            App.CharacterAction_Create(
                helm, App.CharacterAction.AT_SAY_LINE, line_key, None, 1).Play()
            return
    except Exception:
        pass
    try:
        db = App.g_kLocalizationManager.Load("data/TGL/Bridge Crew General.tgl")
        if db:
            seq = App.TGSequence_Create()
            sub = App.SubtitleAction_Create(db, line_key)
            sub.SetDuration(3.0)
            seq.AddAction(sub)
            seq.Play()
            App.g_kLocalizationManager.Unload(db)
    except Exception:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_warp_gates.py -v`
Expected: PASS.

- [ ] **Step 5: Wire `on_warp_engage` to gate before warping**

In `engine/host_loop.py`, replace `on_warp_engage` (~line 3222):

```python
        def on_warp_engage(button):
            from engine.appc import warp as _w
            from engine.appc import warp_gates as _wg
            import App
            player = App.Game_GetCurrentPlayer()
            if player is None and controller.session is not None:
                player = controller.session.player
            result = _wg.warp_gate(player)
            if not result.allowed:
                if result.deny_line is not None:
                    _wg.speak_deny(player, result.deny_line)
                return
            _w.execute_warp(button)
```

- [ ] **Step 6: Add an integration test (gate suppresses warp)**

```python
# tests/integration/test_warp_gating_integration.py
import App
from engine.appc import warp, warp_gates
from engine.appc.sets import SetClass_Create


def _dest_module(name, set_name):
    import types, sys
    mod = types.ModuleType(name)
    def Initialize():
        s = SetClass_Create(); App.g_kSetManager.AddSet(s, set_name)
        wp = App.Waypoint_Create("Player Start", set_name, None)
        wp.SetTranslateXYZ(1.0, 0.0, 0.0); wp.Update(0)
    mod.Initialize = Initialize
    sys.modules[name] = mod


def test_blocked_warp_does_not_load_destination(monkeypatch):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    App.Game_SetCurrentPlayer(player)
    _dest_module("FakeSys.Blocked", "BlockedDst")

    btn = App.STWarpButton_CreateW("Warp"); App.SortedRegionMenu_SetWarpButton(btn)
    btn.SetDestination("FakeSys.Blocked")

    # Force a block: warp engine disabled.
    monkeypatch.setattr(warp_gates, "_warp_disabled", lambda s: True)
    spoken = []
    monkeypatch.setattr(warp_gates, "speak_deny",
                        lambda ship, key: spoken.append(key))

    # Drive the same call on_warp_engage makes.
    result = warp_gates.warp_gate(player)
    assert result.allowed is False
    # execute_warp must NOT run when blocked: emulate on_warp_engage.
    if result.allowed:
        warp.execute_warp(btn)
    else:
        warp_gates.speak_deny(player, result.deny_line)

    assert App.g_kSetManager.GetSet("BlockedDst") is None   # never loaded
    assert App.g_kSetManager.GetSet("Src") is src           # still home
    assert spoken == ["CantWarp1"]
```

- [ ] **Step 7: Run tests + host import**

Run: `uv run pytest tests/unit/test_warp_gates.py tests/integration/test_warp_gating_integration.py -q`
Expected: PASS.
Run: `PYTHONPATH=build/python uv run python -c "import engine.host_loop"`
Expected: no error.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/warp_gates.py engine/host_loop.py tests/unit/test_warp_gates.py tests/integration/test_warp_gating_integration.py
git commit -m "feat(warp): gate framework + subsystem/power gates + deny dialogue"
```

---

### Task 2: Nebula geometry + nebula gate

Make `MetaNebula_Create` build a real `Nebula` (point-in-sphere `IsObjectInNebula`) registered as `CT_NEBULA`, add `SetClass.GetNebula`, and fill `_in_nebula`.

**Files:**
- Create: `engine/appc/nebula.py`
- Modify: root `App.py` (export nebula factories + `Nebula` class), `engine/appc/sets.py` (`GetNebula`), `engine/appc/warp_gates.py` (`_in_nebula`)
- Test: `tests/unit/test_nebula.py`, extend `tests/unit/test_warp_gates.py`

**Interfaces:**
- Produces: `MetaNebula(Nebula)` with `AddNebulaSphere(x,y,z,r)`, `IsObjectInNebula(obj) -> int`, `GetNebulaSpheres() -> list`, `SetupDamage(hull, shields)` (stored, unused), `SetName`/`GetName`; `MetaNebula_Create(r,g,b,visibility,sensor_density,internal_tex,external_tex)`; `Nebula_Cast(obj)`. `SetClass.GetNebula() -> Nebula|None`. `_in_nebula(ship)` real.
- Consumes: existing `Nebula(ObjectClass)` base in `App.py`; `obj.GetWorldLocation()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_nebula.py
import App
from engine.appc.sets import SetClass_Create


def _obj_at(x, y, z):
    o = App.ShipClass_Create(); o.SetName("o")
    o.SetTranslateXYZ(x, y, z); o.Update(0)
    return o


def test_point_in_sphere_membership():
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "i.tga", "e.tga")
    neb.AddNebulaSphere(0.0, 0.0, 0.0, 100.0)
    assert neb.IsObjectInNebula(_obj_at(10.0, 0.0, 0.0))   # inside
    assert not neb.IsObjectInNebula(_obj_at(200.0, 0.0, 0.0))  # outside


def test_multi_sphere():
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "i.tga", "e.tga")
    neb.AddNebulaSphere(0.0, 0.0, 0.0, 50.0)
    neb.AddNebulaSphere(500.0, 0.0, 0.0, 50.0)
    assert neb.IsObjectInNebula(_obj_at(490.0, 0.0, 0.0))   # inside 2nd
    assert not neb.IsObjectInNebula(_obj_at(250.0, 0.0, 0.0))  # between


def test_get_nebula_and_class_list():
    App.g_kSetManager._sets.clear()
    s = SetClass_Create(); App.g_kSetManager.AddSet(s, "N")
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "i.tga", "e.tga")
    s.AddObjectToSet(neb, "neb")
    assert s.GetNebula() is neb
    assert neb in s.GetClassObjectList(App.CT_NEBULA)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_nebula.py -v`
Expected: FAIL (`MetaNebula_Create` is a stub / `GetNebula` missing).

- [ ] **Step 3: Implement `engine/appc/nebula.py`**

```python
"""MetaNebula — point-in-sphere nebula volume (gating geometry only).

Mirrors the SDK App.MetaNebula_Create + AddNebulaSphere + IsObjectInNebula
surface. Rendering and environmental damage are out of scope; this exists so
WarpPressed-style gating (and GetClassObjectList(CT_NEBULA)) works.
"""
from App import Nebula


class MetaNebula(Nebula):
    def __init__(self, r=0.0, g=0.0, b=0.0, visibility=0.0, sensor_density=0.0,
                 internal_tex="", external_tex=""):
        super().__init__()
        self._rgb = (r, g, b)
        self._visibility = visibility
        self._sensor_density = sensor_density
        self._internal_tex = internal_tex
        self._external_tex = external_tex
        self._spheres = []          # list of (x, y, z, radius)
        self._damage = (0.0, 0.0)   # (hull, shields) — stored, unused

    def AddNebulaSphere(self, x, y, z, radius):
        self._spheres.append((float(x), float(y), float(z), float(radius)))

    def GetNebulaSpheres(self):
        return list(self._spheres)

    def SetupDamage(self, hull, shields):
        self._damage = (float(hull), float(shields))

    def IsObjectInNebula(self, obj):
        loc = obj.GetWorldLocation()
        px, py, pz = loc.x, loc.y, loc.z
        for (cx, cy, cz, rad) in self._spheres:
            dx, dy, dz = px - cx, py - cy, pz - cz
            if dx * dx + dy * dy + dz * dz <= rad * rad:
                return 1
        return 0


def MetaNebula_Create(r=0.0, g=0.0, b=0.0, visibility=0.0, sensor_density=0.0,
                      internal_tex="", external_tex=""):
    return MetaNebula(r, g, b, visibility, sensor_density,
                      internal_tex, external_tex)


def Nebula_Cast(obj):
    return obj if isinstance(obj, Nebula) else None
```

- [ ] **Step 4: Export from `App.py` + add `SetClass.GetNebula`**

In root `App.py`, add:

```python
from engine.appc.nebula import MetaNebula, MetaNebula_Create, Nebula_Cast
```

In `engine/appc/sets.py`, add to `SetClass` (near `GetClassObjectList`):

```python
    def GetNebula(self):
        """First CT_NEBULA object in this set, or None (SDK SetClass_GetNebula)."""
        from App import Nebula
        for obj in self._objects.values():
            if isinstance(obj, Nebula):
                return obj
        return None
```

- [ ] **Step 5: Fill `_in_nebula` in `warp_gates.py`**

```python
def _in_nebula(ship):
    pSet = ship.GetContainingSet()
    if pSet is None:
        return False
    neb = pSet.GetNebula()
    return neb is not None and bool(neb.IsObjectInNebula(ship))
```

- [ ] **Step 6: Extend the gate test**

```python
# tests/unit/test_warp_gates.py  (add)
def test_nebula_gate_blocks_cantwarp2(monkeypatch):
    from engine.appc import warp_gates as wg
    monkeypatch.setattr(wg, "_in_nebula", lambda s: True)
    r = wg.warp_gate(_Ship(_Sub(), _Sub()))
    assert (r.allowed, r.deny_line) == (False, "CantWarp2")
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/unit/test_nebula.py tests/unit/test_warp_gates.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/nebula.py App.py engine/appc/sets.py engine/appc/warp_gates.py tests/unit/test_nebula.py tests/unit/test_warp_gates.py
git commit -m "feat(warp): MetaNebula point-in-sphere + nebula warp gate (CantWarp2)"
```

---

### Task 3: Asteroid field geometry + asteroid gate

Make `AsteroidFieldPlacement_Create` materialize a real `AsteroidField` (point-in-sphere `IsShipInside`) registered as `CT_ASTEROID_FIELD`, and fill `_in_asteroid_field`.

**Files:**
- Create: `engine/appc/asteroid_field.py`
- Modify: root `App.py` (exports), `engine/appc/warp_gates.py` (`_in_asteroid_field`)
- Test: `tests/unit/test_asteroid_field.py`, extend `tests/unit/test_warp_gates.py`

**Interfaces:**
- Produces: `AsteroidField(<App.AsteroidField base>)` with `SetFieldRadius(r)`, `GetFieldRadius()`, `IsShipInside(ship) -> int`, plus accepted-no-op setters `SetNumTilesPerAxis`, `SetNumAsteroidsPerTile`, `SetAsteroidSizeFactor`, `ConfigField`, `UpdateNodeOnly`; `AsteroidFieldPlacement_Create(name, set_name, parent=None) -> AsteroidField`; `AsteroidField_Cast(obj)`. `_in_asteroid_field(ship)` real.
- Consumes: placement pattern; `obj.GetWorldLocation()`, `SetTranslateXYZ`, `AlignToVectors`, `Update` (inherited from ObjectClass).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_asteroid_field.py
import App
from engine.appc.sets import SetClass_Create


def _ship_at(x, y, z):
    s = App.ShipClass_Create(); s.SetName("s")
    s.SetTranslateXYZ(x, y, z); s.Update(0)
    return s


def test_field_radius_membership():
    App.g_kSetManager._sets.clear()
    pSet = SetClass_Create(); App.g_kSetManager.AddSet(pSet, "F")
    f = App.AsteroidFieldPlacement_Create("Asteroid Field 1", "F", None)
    f.SetTranslateXYZ(0.0, 0.0, 0.0); f.SetFieldRadius(100.0); f.Update(0)
    assert f.IsShipInside(_ship_at(50.0, 0.0, 0.0))      # inside
    assert not f.IsShipInside(_ship_at(150.0, 0.0, 0.0))  # outside
    assert f in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD)
    assert App.AsteroidField_Cast(f) is f


def test_authored_setters_are_accepted():
    f = App.AsteroidFieldPlacement_Create("AF", None, None)
    # These authored calls must not raise (they drive rendering, not gating).
    f.SetNumTilesPerAxis(3); f.SetNumAsteroidsPerTile(2)
    f.SetAsteroidSizeFactor(10.0); f.UpdateNodeOnly(); f.ConfigField()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_asteroid_field.py -v`
Expected: FAIL (`AsteroidFieldPlacement_Create` is a stub).

- [ ] **Step 3: Implement `engine/appc/asteroid_field.py`**

```python
"""AsteroidField placement — point-in-sphere field volume (gating geometry).

Mirrors the SDK App.AsteroidFieldPlacement_Create surface. The rendering setters
(tiles/asteroids/size) are accepted and ignored; only position + field radius +
IsShipInside matter for warp gating.
"""
from App import AsteroidField as _AsteroidFieldBase


class AsteroidField(_AsteroidFieldBase):
    def __init__(self):
        super().__init__()
        self._field_radius = 0.0

    def SetFieldRadius(self, r):
        self._field_radius = float(r)

    def GetFieldRadius(self):
        return self._field_radius

    def IsShipInside(self, ship):
        loc = ship.GetWorldLocation()
        c = self.GetWorldLocation()
        dx, dy, dz = loc.x - c.x, loc.y - c.y, loc.z - c.z
        r = self._field_radius
        return 1 if (dx * dx + dy * dy + dz * dz <= r * r) else 0

    # Authored render-config setters — accepted, no-op for gating.
    def SetNumTilesPerAxis(self, *a): pass
    def SetNumAsteroidsPerTile(self, *a): pass
    def SetAsteroidSizeFactor(self, *a): pass
    def ConfigField(self, *a): pass
    def UpdateNodeOnly(self, *a): pass


def AsteroidFieldPlacement_Create(name, set_name=None, parent=None):
    f = AsteroidField()
    f.SetName(name)
    import App
    s = App.g_kSetManager.GetSet(set_name) if set_name else None
    if s is not None:
        s.AddObjectToSet(f, name)
    return f


def AsteroidField_Cast(obj):
    return obj if isinstance(obj, _AsteroidFieldBase) else None
```

> Note: `App.AsteroidField` is `class AsteroidField(ObjectClass): pass` — our subclass shadows the bare base under the same `CT_ASTEROID_FIELD` isinstance, so `GetClassObjectList(CT_ASTEROID_FIELD)` finds it. Confirm `ObjectClass` provides `SetTranslateXYZ`/`AlignToVectors`/`Update`/`GetWorldLocation`; if `GetWorldLocation` isn't present on a placement, use `GetWorldLocation()`/translate accessor the other placements use (read `engine/appc/placement.py`).

- [ ] **Step 4: Export from `App.py`**

```python
from engine.appc.asteroid_field import (
    AsteroidField, AsteroidFieldPlacement_Create, AsteroidField_Cast)
```

(If `App.py` already binds a bare `AsteroidField` class, replace that name with this richer subclass — keep `CT_ASTEROID_FIELD` pointing at the class used by `isinstance` in `GetClassObjectList`. Verify `CT_ASTEROID_FIELD` resolves to the same class objects are created from.)

- [ ] **Step 5: Fill `_in_asteroid_field`**

```python
def _in_asteroid_field(ship):
    import App
    pSet = ship.GetContainingSet()
    if pSet is None:
        return False
    for obj in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD):
        field = App.AsteroidField_Cast(obj)
        if field is not None and field.IsShipInside(ship):
            return True
    return False
```

- [ ] **Step 6: Extend the gate test**

```python
# tests/unit/test_warp_gates.py  (add)
def test_asteroid_gate_blocks_cantwarp4(monkeypatch):
    from engine.appc import warp_gates as wg
    monkeypatch.setattr(wg, "_in_asteroid_field", lambda s: True)
    r = wg.warp_gate(_Ship(_Sub(), _Sub()))
    assert (r.allowed, r.deny_line) == (False, "CantWarp4")
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/unit/test_asteroid_field.py tests/unit/test_warp_gates.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/asteroid_field.py App.py engine/appc/warp_gates.py tests/unit/test_asteroid_field.py tests/unit/test_warp_gates.py
git commit -m "feat(warp): AsteroidField placement + asteroid warp gate (CantWarp4)"
```

---

### Task 4: Starbase gate (inside-points + LineCollides via ray_trace_mesh)

Fill `_near_starbase` to mirror `AI.Compound.DockWithStarbase.IsInViewOfInsidePoints`: read the starbase's "Inside Visibility N" points, and for each test line-of-sight to the ship via a host-supplied ray-collide hook. Wire the hook in the host using `ray_trace_mesh`.

**Files:**
- Modify: `engine/appc/warp_gates.py` (`_near_starbase`), `engine/host_loop.py` (configure `ray_collide` hook)
- Test: extend `tests/unit/test_warp_gates.py`

**Interfaces:**
- Consumes: `configure_gate_hooks(ray_collide=fn)` (Task 1); `App.g_kSetManager.GetSet("Starbase12")`, `App.ShipClass_GetObject(set, "Starbase 12")`, `MissionLib.GetPositionOrientationFromProperty`, `obj.GetWorldRotation()`, `obj.GetWorldLocation()`, `point.MultMatrixLeft(rot)`, `point.Add(p)`; `host.ray_trace_mesh`; `controller.session.ship_instances`.
- Produces: `_near_starbase(ship)` real (live-only; returns False when the hook is unset).

- [ ] **Step 1: Write the failing test (mocked ray hook)**

```python
# tests/unit/test_warp_gates.py  (add)
def test_starbase_gate_blocks_when_inside_point_visible(monkeypatch):
    import App
    from engine.appc import warp_gates as wg
    from engine.appc.sets import SetClass_Create

    App.g_kSetManager._sets.clear()
    sb_set = SetClass_Create(); App.g_kSetManager.AddSet(sb_set, "Starbase12")
    starbase = App.ShipClass_Create(); starbase.SetName("Starbase 12")
    starbase.SetTranslateXYZ(0.0, 0.0, 0.0); starbase.Update(0)
    sb_set.AddObjectToSet(starbase, "Starbase 12")

    # Give the starbase one "Inside Visibility 1" position-orientation property.
    pos = App.PositionOrientationProperty_Create("Inside Visibility 1")
    fwd = App.TGPoint3(); fwd.SetXYZ(0.0, 1.0, 0.0)
    up = App.TGPoint3(); up.SetXYZ(0.0, 0.0, 1.0)
    pos.SetOrientation(fwd, up, fwd)
    p = App.TGPoint3(); p.SetXYZ(5.0, 0.0, 0.0); pos.SetPosition(p)
    starbase.GetPropertySet().AddProperty(pos)  # use the real add API (verify name)

    player = App.ShipClass_Create(); player.SetName("player")
    player.SetTranslateXYZ(10.0, 0.0, 0.0); player.Update(0)
    sb_set.AddObjectToSet(player, "player")

    # Hook says the segment does NOT hit the starbase -> inside point is visible
    # -> in view -> blocked.
    wg.configure_gate_hooks(ray_collide=lambda sb, a, b: False)
    assert wg._near_starbase(player) is True

    # Now the segment DOES hit the starbase -> point occluded -> not in view.
    wg.configure_gate_hooks(ray_collide=lambda sb, a, b: True)
    assert wg._near_starbase(player) is False

    # No hook -> can't evaluate -> don't block.
    wg.configure_gate_hooks(ray_collide=None)
    assert wg._near_starbase(player) is False
```

> Implementer: verify the real property-add API on the ship's property set (read `engine/appc/properties.py`); the test must add an "Inside Visibility 1" `PositionOrientationProperty` so `MissionLib.GetPositionOrientationFromProperty(starbase, "Inside Visibility 1")` returns it. If a direct add helper differs, use the real one; keep the assertions.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_warp_gates.py -k starbase -v`
Expected: FAIL (`_near_starbase` returns False unconditionally).

- [ ] **Step 3: Implement `_near_starbase` (mirror IsInViewOfInsidePoints)**

```python
def _near_starbase(ship):
    """True if `ship` is in view of any of Starbase 12's 'Inside Visibility'
    points (mirrors AI.Compound.DockWithStarbase.IsInViewOfInsidePoints). Only
    applies inside the Starbase12 set, and only when the host ray-collide hook
    is configured (live)."""
    if _ray_collide_hook is None:
        return False
    import App
    sb_set = App.g_kSetManager.GetSet("Starbase12")
    if sb_set is None:
        return False
    cont = ship.GetContainingSet()
    if cont is None or cont.GetObjID() != sb_set.GetObjID():
        return False
    starbase = App.ShipClass_GetObject(sb_set, "Starbase 12")
    if starbase is None:
        return False
    import MissionLib
    ship_loc = ship.GetWorldLocation()
    i = 0
    while True:
        i += 1
        vPos, _fwd, _up = MissionLib.GetPositionOrientationFromProperty(
            starbase, "Inside Visibility " + str(i))
        if vPos is None:
            break
        # point -> world space
        vPos.MultMatrixLeft(starbase.GetWorldRotation())
        vPos.Add(starbase.GetWorldLocation())
        # If the segment to the ship does NOT hit the starbase, the point is
        # visible to the ship => in view => blocked.
        if not _ray_collide_hook(starbase, (vPos.x, vPos.y, vPos.z),
                                 (ship_loc.x, ship_loc.y, ship_loc.z)):
            return True
    return False
```

- [ ] **Step 4: Run the unit test**

Run: `uv run pytest tests/unit/test_warp_gates.py -k starbase -v`
Expected: PASS.

- [ ] **Step 5: Wire the host ray-collide hook**

In `engine/host_loop.py`, near the warp-hooks configuration (where `_h` and `controller` are in scope, ~line 3201), add:

```python
        from engine.appc import warp_gates as _wg
        def _starbase_ray_collide(starbase, from_pt, to_pt):
            # True if the segment from->to hits the starbase mesh.
            if _h is None or controller.session is None:
                return False
            iid = controller.session.ship_instances.get(starbase)
            if iid is None:
                return False
            import math
            dx = to_pt[0] - from_pt[0]; dy = to_pt[1] - from_pt[1]; dz = to_pt[2] - from_pt[2]
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if dist <= 1e-6:
                return False
            try:
                hit = _h.ray_trace_mesh(iid, from_pt, (dx, dy, dz), dist)
            except Exception:
                return False
            return hit is not None
        _wg.configure_gate_hooks(ray_collide=_starbase_ray_collide)
```

- [ ] **Step 6: Run the full gating suite + host import**

Run: `uv run pytest tests/ -k "warp_gat or nebula or asteroid" -q`
Expected: PASS.
Run: `PYTHONPATH=build/python uv run python -c "import engine.host_loop"`
Expected: no error.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/warp_gates.py engine/host_loop.py tests/unit/test_warp_gates.py
git commit -m "feat(warp): starbase warp gate via ray_trace_mesh inside-points (CantWarp3)"
```

---

## Final verification

- [ ] `uv run pytest tests/ -k "warp or nebula or asteroid or setting_course or crew_menu" -q` → green (modulo the documented pre-existing `test_build_sector_model_shapes`).
- [ ] `bash scripts/run_tests.sh` → green.
- [ ] **Human gate (Mark):** in `./build/dauntless`, attempt warp (a) with the warp engine damaged/off, (b) inside a nebula system, (c) inside an asteroid field, (d) near Starbase 12 — confirm the Helm officer's line/subtitle fires and no warp occurs; clear each and confirm warp works.

## Self-review notes

- **Spec coverage:** framework + ordered checks (Task 1), subsystem/power gates + dialogue (Task 1), nebula (Task 2), asteroid (Task 3), starbase incl. ray_trace_mesh + inside-points + live-only (Task 4). Out-of-scope items (event membership, WarpStop, rendering) untouched.
- **No-placeholder:** every step has concrete code; the two "verify the real API" notes (asteroid placement world-loc accessor; property-set add in the starbase test) instruct reading the real signature, not inventing one — flagged because those are the only spots the investigation didn't quote verbatim.
- **Type consistency:** `GateResult(allowed, deny_line, silent)` used uniformly; `configure_gate_hooks(ray_collide=)` defined in Task 1, consumed in Task 4; `_near_starbase` hook contract (`fn(starbase, from_xyz, to_xyz) -> bool`) matches the host wiring.
