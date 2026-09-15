# Manual Aim (H key "mouse pick fire") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BC's "Manual Aim" — press `H` in the tactical view and the player's weapons aim at the hull point under the mouse cursor, reverting to the locked subsystem / ship centre whenever the cursor is off the target.

**Architecture:** The SDK already owns the UI/state chain (`H → ET_INPUT_TOGGLE_PICK_FIRE → TacticalControlHandlers.TogglePickFire → "Manual Aim" button ↔ TacticalControlWindow.SetMousePickFire`). We add the C++-only half in `engine/manual_aim.py`: each sim tick, if the flag is on and the view is exterior, unproject the cursor through the gameplay camera, `ray_trace_mesh` against the **targeted** ship's hull, and store the hit as a target-local offset on the player (`ShipClass.set_manual_target_offset` / `UseTargetOffsetTG`). The phaser tick, the drawn beam, and the torpedo/pulse fire path all read that offset. Felix's button gets a real `SetAutoChoose`, and an engine-side twin of the SDK's stubbed `DropOutOfManualFireMode` drops the mode on the bridge.

**Tech Stack:** Python 3 engine shim (`engine/`), SDK Python 1.5 scripts (never edited), CEF JS/CSS for the crew-menu row, pytest. **No C++ change and no rebuild** — the key poller reads GLFW code 72 from `input_map`, and `ray_trace_mesh` / `cursor_pos` are already exported.

**Spec:** `docs/superpowers/specs/2026-09-15-manual-aim-pick-fire-design.md` — read it first; it lists the five assumptions this plan builds on and the SDK evidence for every rule.

## Global Constraints

- **Never edit SDK files** under the configured SDK root. Shims live in `engine/`.
- **Never grep `def <Name>(` to decide whether Appc surface exists** (SWIG binds at module level). Read `docs/stub_heatmap.md` before asserting any SDK call is a no-op.
- **Shared checkout:** follow CLAUDE.md § "Shared checkout — NEVER run destructive git" to the letter. Stage with explicit pathspecs only; back up/restore temporary mutations by `cp`, never by git.
- **Column-vector, right-handed rotations:** body→world is `R · v` (`v.MultMatrixLeft(R)`); world→body is `combat._body_frame_delta`. World-forward is `GetCol(1)`. Never `GetRow`.
- **Units:** everything spatial is game units (GU). No `*_m` / `*_mps` names.
- **Render-side code never mutates game state.** `manual_aim.note_camera` stores data only; `manual_aim.update` (sim side) is the only mutation.
- **Test gate:** finish with `scripts/check_tests.sh`; any failure not in `tests/known_failures.txt` is yours.
- **Snake_case for engine-internal methods** on `ShipClass` (`set_manual_target_offset`, `is_using_target_offset`) so they are visibly not Appc surface; `UseTargetOffsetTG` / `GetTargetOffsetTG` keep their SWIG names.
- Commit after every task with the attribution line from the session: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

## File structure

| File | Responsibility |
|---|---|
| `engine/manual_aim.py` (new) | Cursor→ray unproject, per-tick pick/revert, camera note, toggle-handler registration, drop-mode rule |
| `engine/appc/ships.py` | `ShipClass` target-offset state: `UseTargetOffsetTG`, `set_manual_target_offset`, `is_using_target_offset`, `GetTargetOffsetTG` branch, clear on `SetTarget` |
| `engine/appc/weapon_subsystems.py` | `WeaponSystem._live_held_offset()` — torpedoes/pulse fired mid-hold follow the live offset |
| `engine/host_loop.py` | `_phaser_aim_point()` shared by the damage tick and the drawn beam; sim-side `manual_aim.update`; render-side `manual_aim.note_camera`; `TogglePickFire` registration on TCW reset; H row in `_poll_fire_keys` / `_owned_glfw_keys` |
| `engine/host_io.py` | `cursor_pos()` façade wrapper |
| `engine/input_map.py` | `manual_aim` remappable action, default `H` |
| `engine/appc/characters.py` | `STButton.SetAutoChoose` stores state; `IsAutoChoose()` |
| `engine/ui/crew_menu_panel.py` | Click on an auto-choose button flips chosen before activation; `chosen` in row payload |
| `native/assets/ui-cef/js/crew_menus.js`, `native/assets/ui-cef/css/crew_menus.css` | Render chosen rows |
| `engine/appc/top_window.py` | Call `manual_aim.drop_mode()` at cutscene start and when a view flip lands on the bridge |
| `tests/unit/test_manual_aim.py` (new) | All new behaviour; plus small additions to `tests/unit/test_input_map.py`, `tests/unit/test_crew_menu_panel.py` |
| `CLAUDE.md` | One key-reference row |

---

### Task 1: ShipClass target-offset state

**Files:**
- Modify: `engine/appc/ships.py` (init fields near line 64; `SetTarget` ~line 1538; `GetTargetOffsetTG` ~line 1608)
- Test: `tests/unit/test_manual_aim.py` (create)

**Interfaces:**
- Produces: `ShipClass.UseTargetOffsetTG(v) -> None` (SWIG name; `0` clears the manual offset), `ShipClass.set_manual_target_offset(offset: TGPoint3) -> None` (stores a copy, sets use=1), `ShipClass.is_using_target_offset() -> bool`, `ShipClass.GetTargetOffsetTG() -> TGPoint3` (manual offset while in use, else locked subsystem local position, else zero).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_manual_aim.py
"""Manual Aim (BC "mouse pick fire", H key).

Spec: docs/superpowers/specs/2026-09-15-manual-aim-pick-fire-design.md
"""
import math

from engine.appc.math import TGPoint3


# ── Task 1: ShipClass target-offset state ────────────────────────────────────

def _ship_with_locked_subsystem():
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShipSubsystem
    ship = ShipClass()
    sub = ShipSubsystem("Warp Core")
    sub._position = TGPoint3(0.5, -2.0, 1.5)
    ship.SetTargetSubsystem(sub)
    return ship


def test_manual_offset_overrides_the_subsystem_offset_while_in_use():
    ship = _ship_with_locked_subsystem()
    ship.set_manual_target_offset(TGPoint3(3.0, 4.0, 5.0))

    assert ship.is_using_target_offset() is True
    o = ship.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (3.0, 4.0, 5.0)


def test_get_target_offset_returns_a_copy_not_the_stored_point():
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    ship.set_manual_target_offset(TGPoint3(1.0, 2.0, 3.0))
    o = ship.GetTargetOffsetTG()
    o.x = 99.0
    assert ship.GetTargetOffsetTG().x == 1.0


def test_use_target_offset_zero_reverts_to_the_locked_subsystem():
    """E3M1.FixTargeting: UseTargetOffsetTG(0) == 'fix the targeted
    location to match the targeted subsystem'."""
    ship = _ship_with_locked_subsystem()
    ship.set_manual_target_offset(TGPoint3(3.0, 4.0, 5.0))

    ship.UseTargetOffsetTG(0)

    assert ship.is_using_target_offset() is False
    o = ship.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (0.5, -2.0, 1.5)


def test_use_target_offset_one_without_a_stored_offset_is_not_in_use():
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    ship.UseTargetOffsetTG(1)
    assert ship.is_using_target_offset() is False
    o = ship.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (0.0, 0.0, 0.0)


def test_changing_target_clears_the_manual_offset():
    """The offset is target-local; it cannot survive a retarget."""
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    a = ShipClass()
    b = ShipClass()
    ship.SetTarget(a)
    ship.set_manual_target_offset(TGPoint3(1.0, 1.0, 1.0))

    ship.SetTarget(a)                       # same object: keeps it
    assert ship.is_using_target_offset() is True
    ship.SetTarget(b)                       # different object: clears
    assert ship.is_using_target_offset() is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_manual_aim.py -v`
Expected: 5 FAIL with `AttributeError: 'ShipClass' object has no attribute 'set_manual_target_offset'` (and `UseTargetOffsetTG`).

- [ ] **Step 3: Implement**

In `engine/appc/ships.py`, next to `self._target_subsystem = None` in `__init__` (line ~65) add:

```python
        # Manual Aim (BC "mouse pick fire", H key): a target-LOCAL, unscaled
        # aim point picked off the target's hull under the cursor each tick
        # by engine.manual_aim.update. While _use_target_offset is set,
        # GetTargetOffsetTG() hands this back instead of the locked
        # subsystem's position -- E3M1.FixTargeting's UseTargetOffsetTG(0) is
        # the documented way back ("fix the targeted location to match the
        # targeted subsystem"). Spec: docs/superpowers/specs/
        # 2026-09-15-manual-aim-pick-fire-design.md
        self._manual_target_offset = None
        self._use_target_offset = False
```

In `SetTarget`, inside the existing `if self._target is not old_target:` block (the one that fires `ET_TARGET_WAS_CHANGED`), add as its FIRST statements:

```python
            # The manual aim offset is expressed in the OLD target's frame.
            self._manual_target_offset = None
            self._use_target_offset = False
```

Replace the body of `GetTargetOffsetTG` (keep its docstring, append the two sentences below to it) with:

```python
    def GetTargetOffsetTG(self) -> TGPoint3:
        """...existing docstring...

        While Manual Aim has a hull pick live (is_using_target_offset()),
        the cursor-picked target-local point wins over the subsystem lock."""
        if self._use_target_offset and self._manual_target_offset is not None:
            m = self._manual_target_offset
            return TGPoint3(m.x, m.y, m.z)
        sub = self._target_subsystem
        pos = sub.GetPositionTG() if (sub is not None and hasattr(sub, "GetPositionTG")) else None
        if isinstance(pos, TGPoint3):
            return TGPoint3(pos.x, pos.y, pos.z)
        return TGPoint3(0.0, 0.0, 0.0)

    # ── Manual Aim (mouse pick fire) ─────────────────────────────────────
    def UseTargetOffsetTG(self, v) -> None:
        """SWIG ShipClass.UseTargetOffsetTG (App.py:5519). Only SDK caller is
        E3M1.FixTargeting(…, 0). 0 drops the manual offset so the next
        GetTargetOffsetTG reads the subsystem lock again; 1 merely re-arms
        an offset that is already stored (no offset => nothing in use)."""
        self._use_target_offset = bool(int(v))
        if not self._use_target_offset:
            self._manual_target_offset = None

    def set_manual_target_offset(self, offset: TGPoint3) -> None:
        """Engine-internal (not Appc surface): store the cursor pick as a
        target-local, unscaled point and put it in use."""
        self._manual_target_offset = TGPoint3(offset.x, offset.y, offset.z)
        self._use_target_offset = True

    def is_using_target_offset(self) -> bool:
        return bool(self._use_target_offset and self._manual_target_offset is not None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_manual_aim.py tests/unit/test_pulse_aimed_launch.py -v`
Expected: all PASS (the two pre-existing `GetTargetOffsetTG` tests in `test_pulse_aimed_launch.py` must still pass).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ships.py tests/unit/test_manual_aim.py
git commit -m "feat(ships): manual target offset state for Manual Aim (UseTargetOffsetTG)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Weapon systems read the offset live while Manual Aim is on

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` — `WeaponSystem` (class at ~line 991; `_held_offset` reads at ~line 1339 in `update_weapons` and ~line 2191 in `_HeldFireWeaponSystem.update_weapons`)
- Test: `tests/unit/test_manual_aim.py`

**Interfaces:**
- Consumes: `ShipClass.is_using_target_offset()`, `ShipClass.GetTargetOffsetTG()` (Task 1).
- Produces: `WeaponSystem._live_held_offset() -> TGPoint3 | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_manual_aim.py`:

```python
# ── Task 2: weapon systems read the live offset ──────────────────────────────

def test_weapon_system_uses_the_ships_live_offset_while_manual_aim_is_on():
    """StartFiring captures the offset ONCE (_held_offset); with the cursor
    moving every frame, a torpedo fired mid-hold must read the ship's
    CURRENT offset, not the one captured at keydown."""
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import TorpedoSystem
    ship = ShipClass()
    sys_ = TorpedoSystem("Torpedoes")
    sys_.SetParentShip(ship)

    sys_._held_offset = TGPoint3(0.0, 0.0, 0.0)          # captured at keydown
    assert sys_._live_held_offset() is sys_._held_offset  # off: held wins

    ship.set_manual_target_offset(TGPoint3(2.0, 0.0, 7.0))
    live = sys_._live_held_offset()
    assert (live.x, live.y, live.z) == (2.0, 0.0, 7.0)

    ship.UseTargetOffsetTG(0)
    assert sys_._live_held_offset() is sys_._held_offset


def test_live_offset_tolerates_a_parent_without_the_manual_aim_api():
    """Legacy fakes / no parent: fall back to _held_offset, never raise."""
    from engine.appc.subsystems import TorpedoSystem
    sys_ = TorpedoSystem("Torpedoes")
    sys_._held_offset = "held"
    assert sys_._live_held_offset() == "held"
    class _Bare: pass
    sys_.SetParentShip(_Bare())
    assert sys_._live_held_offset() == "held"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_manual_aim.py -k live_offset -v`
Expected: FAIL `AttributeError: ... has no attribute '_live_held_offset'`.

- [ ] **Step 3: Implement**

In `engine/appc/weapon_subsystems.py`, inside `class WeaponSystem(PoweredSubsystem)` right after the `StopFiring` method that clears `self._held_offset = None` (~line 1233), add:

```python
    def _live_held_offset(self):
        """The aim offset for THIS tick.

        BC's StartFiring captures the offset once (Weapon+0x90..+0x98); with
        Manual Aim the player's offset is re-picked off the hull every tick
        (engine.manual_aim.update), so a torpedo/pulse fired mid-hold must
        follow the cursor, not the keydown-time point. Only ShipClass
        parents that report is_using_target_offset() switch; anything else
        (AI ships, legacy fakes, no parent) keeps _held_offset."""
        ship = self.GetParentShip()
        probe = getattr(type(ship), "is_using_target_offset", None) if ship is not None else None
        if callable(probe) and ship.is_using_target_offset():
            return ship.GetTargetOffsetTG()
        return getattr(self, "_held_offset", None)
```

Then replace the two reads:

- ~line 1339 (`WeaponSystem.update_weapons`): `offset = getattr(self, "_held_offset", None)` → `offset = self._live_held_offset()`
- ~line 2191 (`_HeldFireWeaponSystem.update_weapons`): `fired = self._engage_beam(target, self._held_offset, ship)` → `fired = self._engage_beam(target, self._live_held_offset(), ship)`

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_manual_aim.py tests/unit/test_pulse_aimed_launch.py tests/unit/test_weapons_disabled_blocks_fire.py tests/unit/test_phaser_fire_sfx_edge_trigger.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/weapon_subsystems.py tests/unit/test_manual_aim.py
git commit -m "feat(weapons): read the manual aim offset live while it is in use

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: One phaser aim-point helper for the damage tick and the drawn beam

**Files:**
- Modify: `engine/host_loop.py` — the damage tick inside `_advance_combat` (`target_sub = (ship.GetTargetSubsystem() …` at ~line 954) and `_beam_descriptor_pair` (~line 1665)
- Test: `tests/unit/test_manual_aim.py`

**Interfaces:**
- Consumes: Task 1 ship API.
- Produces: `host_loop._phaser_aim_point(ship, target) -> tuple[TGPoint3, subsystem | None]` — the world point the firing `ship`'s phasers aim at on `target`, and the locked subsystem when that is what the point came from (else `None`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_manual_aim.py`:

```python
# ── Task 3: phaser aim point ─────────────────────────────────────────────────

def _galaxy_target_at(x, y, z):
    from engine.appc.ships import ShipClass_Create
    t = ShipClass_Create("Galaxy")
    t.SetTranslateXYZ(x, y, z)
    return t


def test_phaser_aim_point_is_the_locked_subsystem_when_no_manual_offset():
    from engine.host_loop import _phaser_aim_point
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShipSubsystem
    ship = ShipClass()
    target = _galaxy_target_at(0.0, 100.0, 0.0)
    sub = ShipSubsystem("Bridge")
    sub._position = TGPoint3(0.0, 0.0, 4.0)
    sub.SetParentShip(target)
    ship.SetTarget(target)
    ship.SetTargetSubsystem(sub)

    point, from_sub = _phaser_aim_point(ship, target)

    assert from_sub is sub
    expect = sub.GetWorldLocation()
    assert (point.x, point.y, point.z) == (expect.x, expect.y, expect.z)


def test_phaser_aim_point_is_target_centre_with_no_lock():
    from engine.host_loop import _phaser_aim_point
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    target = _galaxy_target_at(0.0, 100.0, 0.0)
    point, from_sub = _phaser_aim_point(ship, target)
    assert from_sub is None
    assert (point.x, point.y, point.z) == (0.0, 100.0, 0.0)


def test_phaser_aim_point_uses_the_manual_offset_rotated_and_scaled():
    """Manual offset is target-local & unscaled: world = pos + R·(o·scale).
    Yaw the target 90° about Z so a body +X offset lands on world +Y."""
    from engine.host_loop import _phaser_aim_point
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShipSubsystem
    from engine.appc.math import TGMatrix3
    ship = ShipClass()
    target = _galaxy_target_at(0.0, 100.0, 0.0)
    rot = TGMatrix3()
    rot.MakeZRotation(math.pi / 2.0)
    target.SetMatrixRotation(rot)               # copied into the transform store
    sub = ShipSubsystem("Bridge")
    sub._position = TGPoint3(0.0, 0.0, 4.0)
    sub.SetParentShip(target)
    ship.SetTarget(target)
    ship.SetTargetSubsystem(sub)
    ship.set_manual_target_offset(TGPoint3(2.0, 0.0, 0.0))

    point, from_sub = _phaser_aim_point(ship, target)

    assert from_sub is None                       # cursor pick, not the lock
    scale = float(target.GetScale())
    assert abs(point.x - 0.0) < 1e-6
    assert abs(point.y - (100.0 + 2.0 * scale)) < 1e-6
    assert abs(point.z - 0.0) < 1e-6


def test_advance_combat_routes_phaser_damage_at_the_manual_offset(monkeypatch):
    """End-to-end through the damage tick: the fallback point handed to
    combat._resolve_hit_point is the manual offset's world position."""
    from engine import host_loop
    import engine.appc.combat as combat_mod
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import PhaserSystem, PhaserBank
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sys_ = PhaserSystem("Phasers")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    b = PhaserBank("Bank0")
    b._max_charge = 5.0; b._charge_level = 5.0; b._min_firing_charge = 3.0
    b._max_damage = 1.0; b._max_damage_distance = 1000.0
    b._max_condition = 100.0; b._condition = 100.0; b._disabled_percentage = 0.25
    sys_.AddChildSubsystem(b)
    ship.SetPhaserSystem(sys_)
    target = _galaxy_target_at(0.0, 100.0, 0.0)
    ship.SetTarget(target)
    ship.set_manual_target_offset(TGPoint3(0.0, 0.0, 5.0))
    sys_.StartFiring(target=target, offset=ship.GetTargetOffsetTG())
    assert b.IsFiring() == 1

    seen = []
    real = combat_mod._resolve_hit_point
    def spy(*a, **kw):
        seen.append(kw["fallback_point"])
        return real(*a, **kw)
    monkeypatch.setattr(combat_mod, "_resolve_hit_point", spy)
    monkeypatch.setattr(combat_mod, "apply_hit", lambda *a, **kw: None)

    host_loop._advance_combat([ship, target], dt=1.0 / 60, ship_instances=None)

    assert seen, "damage tick never resolved a hit point"
    fp = seen[0]
    scale = float(target.GetScale())
    assert abs(fp.x) < 1e-6 and abs(fp.y - 100.0) < 1e-6
    assert abs(fp.z - 5.0 * scale) < 1e-6
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_manual_aim.py -k phaser_aim -v`
Expected: 3 FAIL `ImportError: cannot import name '_phaser_aim_point'`; the `_advance_combat` test FAILs on the `fp.z` assertion (tick still aims at centre / subsystem).

- [ ] **Step 3: Implement**

In `engine/host_loop.py`, add above `_advance_combat` (~line 843):

```python
def _phaser_aim_point(ship, target):
    """World point the firing `ship`'s phasers aim at on `target`, plus the
    locked subsystem when the point IS that subsystem (else None).

    Priority is BC's ShipClass target offset: Manual Aim's cursor pick
    (ship.is_using_target_offset(), target-local & unscaled -> pos +
    R·(offset·scale), the same transform _resolve_torpedo_aim_point applies),
    else the locked subsystem's world position, else the target's centre.
    ONE helper for both consumers -- the damage tick and the drawn beam --
    so they can never disagree about where the beam lands."""
    probe = getattr(type(ship), "is_using_target_offset", None)
    if callable(probe) and ship.is_using_target_offset():
        pos = target.GetWorldLocation()
        o = ship.GetTargetOffsetTG()
        scale = float(target.GetScale()) if hasattr(target, "GetScale") else 1.0
        o = TGPoint3(o.x * scale, o.y * scale, o.z * scale)
        rot = target.GetWorldRotation() if hasattr(target, "GetWorldRotation") else None
        if isinstance(rot, TGMatrix3):
            o.MultMatrixLeft(rot)
        return TGPoint3(pos.x + o.x, pos.y + o.y, pos.z + o.z), None
    target_sub = ship.GetTargetSubsystem() if hasattr(ship, "GetTargetSubsystem") else None
    if target_sub is not None and hasattr(target_sub, "GetWorldLocation"):
        return target_sub.GetWorldLocation(), target_sub
    return target.GetWorldLocation(), None
```

Check `TGMatrix3` is imported at the top of `host_loop.py` (`from engine.appc.math import TGPoint3, TGMatrix3` — add `TGMatrix3` to the existing import if absent).

Replace in the damage tick (~line 954):

```python
                target_sub = (ship.GetTargetSubsystem()
                              if hasattr(ship, "GetTargetSubsystem") else None)
                if target_sub is not None and hasattr(target_sub, "GetWorldLocation"):
                    target_pos = target_sub.GetWorldLocation()
                else:
                    target_pos = target.GetWorldLocation()
                    target_sub = None
```
with
```python
                target_pos, target_sub = _phaser_aim_point(ship, target)
```

Replace in `_beam_descriptor_pair` (~line 1665) the identical five-line block with the same one-liner.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_manual_aim.py tests/unit/test_weapons_disabled_blocks_fire.py tests/unit/test_tractor_beam_render_data.py tests/unit/test_phaser_damage_falloff.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_manual_aim.py
git commit -m "feat(combat): phaser tick and drawn beam aim at the manual offset via one helper

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `engine/manual_aim.py` — cursor ray (inverse of the SPV projection)

**Files:**
- Create: `engine/manual_aim.py`
- Test: `tests/unit/test_manual_aim.py`

**Interfaces:**
- Produces: `AimCamera(eye, target, up, fov_y_rad, near, far)` (same duck interface as `engine.ui.reticle_text._ReticleCam`: `eye()`, `up()` methods; `target`, `fov_y_rad`, `near`, `far` attributes), `cursor_ray(cursor_xy, viewport, cam) -> tuple[tuple3, tuple3] | None` (world origin, unit direction; `None` on a degenerate viewport/camera).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_manual_aim.py`:

```python
# ── Task 4: cursor ray ───────────────────────────────────────────────────────

def _dist_point_to_ray(p, origin, d):
    v = (p[0] - origin[0], p[1] - origin[1], p[2] - origin[2])
    t = v[0] * d[0] + v[1] * d[1] + v[2] * d[2]
    c = (origin[0] + d[0] * t, origin[1] + d[1] * t, origin[2] + d[2] * t)
    return math.sqrt(sum((p[i] - c[i]) ** 2 for i in range(3)))


def test_cursor_ray_inverts_project_for_off_centre_points():
    """Round trip: project a world point with the SPV projection the reticle
    uses, feed the pixel back through cursor_ray, and the ray must pass
    through the point (this is what makes the pick land where the cursor
    is drawn). Off-axis camera so no axis-aligned shortcut passes."""
    from engine.manual_aim import AimCamera, cursor_ray
    from engine.ui.ship_property_viewer import project
    cam = AimCamera(eye=(10.0, -50.0, 20.0), target=(0.0, 100.0, 0.0),
                    up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(60.0),
                    near=1.0, far=5000.0)
    viewport = (1600, 900)
    for world in ((0.0, 100.0, 0.0), (30.0, 140.0, -12.0), (-25.0, 80.0, 18.0)):
        sx, sy, _d, visible = project(world, cam, viewport)
        assert visible
        origin, direction = cursor_ray((sx, sy), viewport, cam)
        assert origin == cam.eye()
        assert abs(math.sqrt(sum(c * c for c in direction)) - 1.0) < 1e-9
        assert _dist_point_to_ray(world, origin, direction) < 1e-6


def test_cursor_ray_centre_pixel_is_the_camera_forward():
    from engine.manual_aim import AimCamera, cursor_ray
    cam = AimCamera(eye=(0.0, 0.0, 0.0), target=(0.0, 100.0, 0.0),
                    up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(45.0),
                    near=1.0, far=5000.0)
    _o, d = cursor_ray((400.0, 300.0), (800, 600), cam)
    assert abs(d[0]) < 1e-9 and abs(d[1] - 1.0) < 1e-9 and abs(d[2]) < 1e-9


def test_cursor_ray_rejects_degenerate_inputs():
    from engine.manual_aim import AimCamera, cursor_ray
    cam = AimCamera(eye=(0.0, 0.0, 0.0), target=(0.0, 100.0, 0.0),
                    up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(45.0),
                    near=1.0, far=5000.0)
    assert cursor_ray((1.0, 1.0), (0, 600), cam) is None
    same = AimCamera(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, 0.0),
                     up=(0.0, 0.0, 1.0), fov_y_rad=1.0, near=1.0, far=10.0)
    assert cursor_ray((1.0, 1.0), (800, 600), same) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_manual_aim.py -k cursor_ray -v`
Expected: FAIL `ModuleNotFoundError: No module named 'engine.manual_aim'`.

- [ ] **Step 3: Implement**

Create `engine/manual_aim.py`:

```python
"""Manual Aim -- BC's "mouse pick fire" (H key / Felix's "Manual Aim" button).

The SDK owns the toggle chain (DefaultKeyboardBinding.py:154 WC_H ->
ET_INPUT_TOGGLE_PICK_FIRE -> TacticalControlHandlers.TogglePickFire ->
TacticalControlWindow.SetMousePickFire). This module is the C++-only half
the SDK never sees: each sim tick, while the flag is on and the view is
exterior, unproject the cursor through the gameplay camera, trace it against
the TARGETED ship's hull, and store the hit on the player as a target-local
offset (ShipClass.set_manual_target_offset). Off the hull -> revert to the
subsystem lock (UseTargetOffsetTG(0), E3M1.FixTargeting's rule).

Spec + the five stated assumptions: docs/superpowers/specs/
2026-09-15-manual-aim-pick-fire-design.md
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

Vec3 = Tuple[float, float, float]


class AimCamera:
    """Gameplay camera params, duck-compatible with the interface
    engine.ui.ship_property_viewer.project expects (eye()/up() methods,
    target/fov_y_rad/near/far attributes) -- the SAME shape the reticle text
    projects with, so the pick lands where the cursor is drawn."""

    def __init__(self, eye: Vec3, target: Vec3, up: Vec3,
                 fov_y_rad: float, near: float, far: float):
        self._eye = (float(eye[0]), float(eye[1]), float(eye[2]))
        self.target = (float(target[0]), float(target[1]), float(target[2]))
        self._up = (float(up[0]), float(up[1]), float(up[2]))
        self.fov_y_rad = float(fov_y_rad)
        self.near = float(near)
        self.far = float(far)

    def eye(self) -> Vec3:
        return self._eye

    def up(self) -> Vec3:
        return self._up


def _sub(a, b):   return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-12 else None


def cursor_ray(cursor_xy, viewport, cam) -> Optional[Tuple[Vec3, Vec3]]:
    """(origin, unit direction) in world space for a cursor pixel.

    Exact inverse of ship_property_viewer.project (_look_at + _perspective):
    pixel -> NDC (top-left origin, y flipped) -> view-space direction at unit
    depth (x = ndc_x·tan(fov/2)·aspect, y = ndc_y·tan(fov/2), z = -1) ->
    world via the camera basis (right s = f×up, true up u = s×f, forward f).
    `cursor_xy` and `viewport` must be in the SAME pixel space (host_loop
    passes framebuffer pixels for both). None when the viewport or the
    camera basis is degenerate."""
    w, h = viewport
    if w <= 0 or h <= 0:
        return None
    eye = cam.eye()
    f = _norm(_sub(cam.target, eye))
    if f is None:
        return None
    s = _norm(_cross(f, cam.up()))
    if s is None:
        return None
    u = _cross(s, f)
    aspect = float(w) / float(h)
    tan_half = math.tan(cam.fov_y_rad / 2.0)
    ndc_x = 2.0 * float(cursor_xy[0]) / float(w) - 1.0
    ndc_y = 1.0 - 2.0 * float(cursor_xy[1]) / float(h)
    vx = ndc_x * tan_half * aspect
    vy = ndc_y * tan_half
    d = _norm((s[0] * vx + u[0] * vy + f[0],
               s[1] * vx + u[1] * vy + f[1],
               s[2] * vx + u[2] * vy + f[2]))
    if d is None:
        return None
    return eye, d
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_manual_aim.py -k cursor_ray -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/manual_aim.py tests/unit/test_manual_aim.py
git commit -m "feat(manual-aim): cursor ray as the exact inverse of the SPV projection

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Per-tick pick / revert (`manual_aim.update`) + `host_io.cursor_pos`

**Files:**
- Modify: `engine/manual_aim.py`, `engine/host_io.py` (add `cursor_pos` wrapper + `_REQUIRED_BINDINGS` entry)
- Test: `tests/unit/test_manual_aim.py`

**Interfaces:**
- Consumes: Task 1 ship API; `combat._body_frame_delta(ship, hit_point: TGPoint3) -> (dx, dy, dz)`; `host_io.ray_trace_mesh(iid, origin, direction, max_dist) -> ((px,py,pz), (nx,ny,nz), t) | None`.
- Produces: `manual_aim.note_camera(eye, target, up, fov_y_rad, near, far) -> None`, `manual_aim.last_camera() -> AimCamera | None`, `manual_aim.reset() -> None`, `manual_aim.update(*, player, tcw, ship_instances, is_exterior, cursor_fb=None, viewport_fb=None, cam=None, ray_trace=None) -> bool` (True while a hull pick is live this tick), `host_io.cursor_pos() -> tuple[float, float] | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_manual_aim.py`:

```python
# ── Task 5: per-tick pick / revert ───────────────────────────────────────────

class _Tcw:
    def __init__(self, on): self._on = on
    def GetMousePickFire(self): return 1 if self._on else 0


def _aim_fixture():
    """Player at origin looking +Y (camera = chase, behind the player), a
    Galaxy 100 GU ahead, cursor at screen centre, camera noted."""
    from engine import manual_aim
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShipSubsystem
    manual_aim.reset()
    player = ShipClass()
    target = _galaxy_target_at(0.0, 100.0, 0.0)
    sub = ShipSubsystem("Bridge")
    sub._position = TGPoint3(0.0, 0.0, 4.0)
    sub.SetParentShip(target)
    player.SetTarget(target)
    player.SetTargetSubsystem(sub)
    cam = manual_aim.AimCamera(eye=(0.0, -20.0, 5.0), target=(0.0, 100.0, 0.0),
                               up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(45.0),
                               near=1.0, far=5000.0)
    return manual_aim, player, target, cam


def test_update_stores_the_hull_hit_as_a_target_local_unscaled_offset():
    manual_aim, player, target, cam = _aim_fixture()
    traced = []
    def ray_trace(iid, origin, direction, max_dist):
        traced.append((iid, origin, direction, max_dist))
        return ((0.0, 90.0, 5.0), (0.0, -1.0, 0.0), 90.0)   # hull hit, world

    live = manual_aim.update(player=player, tcw=_Tcw(True),
                             ship_instances={target: 7}, is_exterior=True,
                             cursor_fb=(400.0, 300.0), viewport_fb=(800, 600),
                             cam=cam, ray_trace=ray_trace)

    assert live is True
    assert traced[0][0] == 7                       # traced the TARGET's hull
    assert traced[0][1] == cam.eye()
    assert traced[0][3] == cam.far
    assert player.is_using_target_offset()
    o = player.GetTargetOffsetTG()
    scale = float(target.GetScale())
    assert abs(o.x - 0.0) < 1e-6
    assert abs(o.y - (-10.0 / scale)) < 1e-6         # 90 - 100, unscaled
    assert abs(o.z - (5.0 / scale)) < 1e-6


def test_update_reverts_to_the_subsystem_when_the_cursor_leaves_the_hull():
    manual_aim, player, target, cam = _aim_fixture()
    kw = dict(player=player, tcw=_Tcw(True), ship_instances={target: 7},
              is_exterior=True, cursor_fb=(400.0, 300.0),
              viewport_fb=(800, 600), cam=cam)
    manual_aim.update(ray_trace=lambda *a: ((0.0, 90.0, 5.0), (0.0, -1.0, 0.0), 90.0), **kw)
    assert player.is_using_target_offset()

    live = manual_aim.update(ray_trace=lambda *a: None, **kw)   # miss

    assert live is False
    assert player.is_using_target_offset() is False
    o = player.GetTargetOffsetTG()
    assert (o.x, o.y, o.z) == (0.0, 0.0, 4.0)      # back on the lock


def test_update_is_inert_when_the_flag_is_off_or_the_view_is_not_exterior():
    manual_aim, player, target, cam = _aim_fixture()
    calls = []
    hit = lambda *a: (calls.append(a) or ((0.0, 90.0, 5.0), (0.0, -1.0, 0.0), 90.0))
    base = dict(player=player, ship_instances={target: 7},
                cursor_fb=(400.0, 300.0), viewport_fb=(800, 600), cam=cam,
                ray_trace=hit)
    assert manual_aim.update(tcw=_Tcw(False), is_exterior=True, **base) is False
    assert manual_aim.update(tcw=_Tcw(True), is_exterior=False, **base) is False
    assert calls == []                              # never traced
    assert player.is_using_target_offset() is False


def test_update_drops_a_live_offset_when_the_flag_turns_off():
    manual_aim, player, target, cam = _aim_fixture()
    player.set_manual_target_offset(TGPoint3(1.0, 1.0, 1.0))
    manual_aim.update(player=player, tcw=_Tcw(False), ship_instances={target: 7},
                      is_exterior=True, cursor_fb=(0.0, 0.0), viewport_fb=(800, 600),
                      cam=cam, ray_trace=lambda *a: None)
    assert player.is_using_target_offset() is False


def test_update_only_picks_the_targeted_ship_never_a_bystander():
    """Assumption 2 in the spec: no retarget on hover. A hit on another
    ship's instance is not even attempted -- only the target's iid is traced."""
    manual_aim, player, target, cam = _aim_fixture()
    other = _galaxy_target_at(0.0, 60.0, 0.0)
    traced = []
    def ray_trace(iid, *a):
        traced.append(iid)
        return None
    manual_aim.update(player=player, tcw=_Tcw(True),
                      ship_instances={target: 7, other: 8}, is_exterior=True,
                      cursor_fb=(400.0, 300.0), viewport_fb=(800, 600),
                      cam=cam, ray_trace=ray_trace)
    assert traced == [7]
    assert player.GetTarget() is target


def test_update_with_no_target_or_no_instance_reverts_without_tracing():
    manual_aim, player, target, cam = _aim_fixture()
    player.set_manual_target_offset(TGPoint3(1.0, 1.0, 1.0))
    traced = []
    manual_aim.update(player=player, tcw=_Tcw(True), ship_instances={},
                      is_exterior=True, cursor_fb=(400.0, 300.0),
                      viewport_fb=(800, 600), cam=cam,
                      ray_trace=lambda *a: traced.append(a))
    assert traced == [] and player.is_using_target_offset() is False
    player.SetTarget(None)
    assert manual_aim.update(player=player, tcw=_Tcw(True), ship_instances={target: 7},
                             is_exterior=True, cursor_fb=(400.0, 300.0),
                             viewport_fb=(800, 600), cam=cam,
                             ray_trace=lambda *a: traced.append(a)) is False
    assert traced == []


def test_note_camera_is_data_only_and_read_by_update_by_default():
    manual_aim, player, target, cam = _aim_fixture()
    assert manual_aim.last_camera() is None
    manual_aim.note_camera(cam.eye(), cam.target, cam.up(), cam.fov_y_rad, cam.near, cam.far)
    noted = manual_aim.last_camera()
    assert noted.eye() == cam.eye() and noted.far == cam.far
    assert player.is_using_target_offset() is False           # no mutation
    seen = []
    manual_aim.update(player=player, tcw=_Tcw(True), ship_instances={target: 7},
                      is_exterior=True, cursor_fb=(400.0, 300.0),
                      viewport_fb=(800, 600),
                      ray_trace=lambda iid, o, d, m: seen.append(o) or None)
    assert seen == [cam.eye()]                                 # used the noted cam


def test_host_io_cursor_pos_is_none_headless(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.cursor_pos() is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_manual_aim.py -k "update or note_camera or cursor_pos" -v`
Expected: FAIL `AttributeError: module 'engine.manual_aim' has no attribute 'reset'` / `'update'`; `host_io.cursor_pos` AttributeError.

- [ ] **Step 3: Implement**

`engine/host_io.py`: add `"cursor_pos"` to `_REQUIRED_BINDINGS` (the manifest test `tests/unit/test_host_io_binding_manifest.py` enforces this), and after `framebuffer_size()` add:

```python
def cursor_pos() -> Optional[Tuple[float, float]]:
    """Cursor in FRAMEBUFFER (physical) pixels -- renderer/window.cc:173-182.
    None when headless (no window to have a cursor in)."""
    if _h is None:
        return None
    return _h.cursor_pos()
```

`engine/manual_aim.py`: append:

```python
# ── Per-tick pick (sim side) ────────────────────────────────────────────────
# The gameplay camera is only known on the RENDER side of the frame
# (host_loop's r.set_camera call); note_camera parks it here -- data only,
# no game-state mutation on the render side -- and the next sim tick's
# update() reads it (one frame of camera lag, invisible at 60 Hz).
_last_cam: Optional[AimCamera] = None


def note_camera(eye, target, up, fov_y_rad, near, far) -> None:
    global _last_cam
    _last_cam = AimCamera(eye, target, up, fov_y_rad, near, far)


def last_camera() -> Optional[AimCamera]:
    return _last_cam


def reset() -> None:
    """Mission swap / tests: forget the noted camera."""
    global _last_cam
    _last_cam = None


def _revert(player) -> bool:
    if player.is_using_target_offset():
        player.UseTargetOffsetTG(0)
    return False


def update(*, player, tcw, ship_instances, is_exterior: bool,
           cursor_fb=None, viewport_fb=None, cam=None, ray_trace=None) -> bool:
    """One sim tick of Manual Aim. The ONLY game-state mutation in this
    module: sets or clears the player's manual target offset.

    Returns True while a hull pick is live. Every other path -- flag off,
    bridge view, no target / dead target, target has no render instance,
    cursor off the hull -- reverts to UseTargetOffsetTG(0) (assumption 3:
    revert immediately, never hold the last hit).

    Only the CURRENT target's hull is traced (assumption 2: no retarget on
    hover). The hit is stored target-local and UNSCALED, the same frame the
    SDK's own offset producers use (pSubsystem.GetPosition()), so
    _resolve_torpedo_aim_point / _phaser_aim_point's pos + R·(o·scale) lands
    back on the picked point."""
    from engine import host_io
    from engine.appc import combat
    from engine.appc.math import TGPoint3

    if player is None:
        return False
    probe = getattr(type(player), "is_using_target_offset", None)
    if not callable(probe):
        return False
    if not is_exterior or tcw is None or not tcw.GetMousePickFire():
        return _revert(player)
    target = player.GetTarget()
    if target is None or (hasattr(target, "IsDead") and target.IsDead()):
        return _revert(player)
    iid = ship_instances.get(target) if ship_instances is not None else None
    if iid is None:
        return _revert(player)
    if cam is None:
        cam = _last_cam
    if cursor_fb is None:
        cursor_fb = host_io.cursor_pos()
    if viewport_fb is None:
        viewport_fb = host_io.framebuffer_size()
    if cam is None or cursor_fb is None:
        return _revert(player)
    ray = cursor_ray(cursor_fb, viewport_fb, cam)
    if ray is None:
        return _revert(player)
    origin, direction = ray
    if ray_trace is None:
        ray_trace = host_io.ray_trace_mesh
    try:
        hit = ray_trace(iid, origin, direction, cam.far)
    except Exception:
        # A native trace error must not kill the sim tick; treat as a miss.
        hit = None
    if hit is None:
        return _revert(player)
    (px, py, pz), _normal, _t = hit
    dx, dy, dz = combat._body_frame_delta(target, TGPoint3(px, py, pz))
    scale = float(target.GetScale()) if hasattr(target, "GetScale") else 1.0
    if scale <= 1e-9:
        scale = 1.0
    player.set_manual_target_offset(TGPoint3(dx / scale, dy / scale, dz / scale))
    return True
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_manual_aim.py tests/unit/test_host_io_binding_manifest.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/manual_aim.py engine/host_io.py tests/unit/test_manual_aim.py
git commit -m "feat(manual-aim): per-tick hull pick with immediate revert off the hull

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Wire `update` / `note_camera` into the host loop

**Files:**
- Modify: `engine/host_loop.py` — sim block next to `_poll_fire_keys(_h, input_map)` (~line 8814); render block right after the exterior `r.set_camera(eye=eye, target=target, up=up_vec, fov_y_rad=director.fov_y_rad, near=1.0, far=5000.0)` (~line 9346); mission-swap reset (the TCW reset block ~line 3783 where `_TCW._instance = None`)
- Test: `tests/unit/test_manual_aim.py` (a source-level guard, since the loop body is not unit-callable)

**Interfaces:**
- Consumes: `manual_aim.update(...)`, `manual_aim.note_camera(...)`, `manual_aim.reset()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_manual_aim.py`:

```python
# ── Task 6: host-loop wiring (source-level guard; the loop body is not
#    unit-callable). Ordering is the point: the pick is a SIM-side mutation
#    that runs next to the key pollers, and the camera note is RENDER-side
#    data only, after r.set_camera.

def _host_loop_src():
    import inspect
    from engine import host_loop
    return inspect.getsource(host_loop)


def test_host_loop_runs_manual_aim_update_in_the_sim_block():
    src = _host_loop_src()
    i_poll = src.index("_poll_fire_keys(_h, input_map)")
    i_upd = src.index("manual_aim.update(")
    i_weap = src.index("_advance_weapons(_ships_this_tick, TICK_DT)")
    assert i_poll < i_upd < i_weap, "update must run after the key pollers and before the weapon tick"
    body = src[i_upd: src.index(")", i_upd) + 1]
    assert "is_exterior=view_mode.is_exterior" in body
    assert "tcw=" in body and "player=player" in body


def test_host_loop_notes_the_camera_after_the_exterior_set_camera():
    src = _host_loop_src()
    anchor = "r.set_camera(eye=eye, target=target, up=up_vec,\n                             fov_y_rad=director.fov_y_rad,\n                             near=1.0, far=5000.0)"
    i_cam = src.index(anchor)
    i_note = src.index("manual_aim.note_camera(eye, target, up_vec, director.fov_y_rad, 1.0, 5000.0)")
    assert i_cam < i_note < i_cam + 600


def test_host_loop_resets_manual_aim_on_tcw_reset():
    src = _host_loop_src()
    i_tcw = src.index("_TCW._instance = None")
    i_reset = src.index("manual_aim.reset()")
    assert i_tcw < i_reset < i_tcw + 400
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_manual_aim.py -k host_loop -v`
Expected: 3 FAIL with `ValueError: substring not found`.

- [ ] **Step 3: Implement**

In `engine/host_loop.py`:

1. Add to the module imports (near `from engine.ui.reticle_text import build_reticle_text, _ReticleCam`): `from engine import manual_aim`.

2. Sim block — immediately after `_poll_skip_dialogue(_h, input_map)` and before the `_ships_this_tick = list(_all_ships_for_tick())` comment block, add:

```python
                # Manual Aim (H): re-pick the cursor's hull point on the
                # player's target, or revert to the subsystem lock. Sim side
                # on purpose -- it mutates the player's target offset, which
                # the weapon tick below and the phaser tick in
                # _advance_combat both read this same frame.
                manual_aim.update(
                    player=player,
                    tcw=TacticalControlWindow.GetInstance(),
                    ship_instances=(session.ship_instances if session is not None else None),
                    is_exterior=view_mode.is_exterior,
                )
```
Confirm `TacticalControlWindow` is importable at that point (host_loop imports it lazily elsewhere as `from engine.appc.windows import TacticalControlWindow as _TCW`; add a module-level `from engine.appc.windows import TacticalControlWindow` if there is none — check the top of the file first and reuse whatever name already exists).

3. Render block — directly after the exterior `r.set_camera(eye=eye, target=target, up=up_vec, fov_y_rad=director.fov_y_rad, near=1.0, far=5000.0)` call (the one followed by `_note_camera_eye(eye)`), add:

```python
                # Manual Aim reads this camera on the NEXT sim tick to
                # unproject the cursor. Data only -- no mutation here.
                manual_aim.note_camera(eye, target, up_vec, director.fov_y_rad, 1.0, 5000.0)
```

4. TCW reset block — right after `_TCW._instance = None` add:

```python
        # Manual Aim: the noted camera belongs to the outgoing mission.
        manual_aim.reset()
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_manual_aim.py -v && uv run python -c "import engine.host_loop"`
Expected: all PASS; import succeeds (no circular import — `engine.manual_aim` imports nothing from `host_loop`).

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_manual_aim.py
git commit -m "feat(manual-aim): drive the per-tick pick from the host loop

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The H key — remappable action, poller row, and `TogglePickFire` registration

**Files:**
- Modify: `engine/input_map.py` (`ACTIONS`), `engine/host_loop.py` (`_poll_fire_keys` ~line 520, `_owned_glfw_keys` ~line 603, TCW reset block ~line 3810), `engine/manual_aim.py` (`register_toggle_handler`)
- Test: `tests/unit/test_manual_aim.py`, `tests/unit/test_input_map.py`

**Interfaces:**
- Consumes: `App.WC_H` (already 104 — `engine/appc/input.py` defines every letter), `App.ET_INPUT_TOGGLE_PICK_FIRE` (already a real int), SDK `TacticalControlHandlers.TogglePickFire`.
- Produces: `input_map` action id `"manual_aim"` (label "Manual Aim (toggle)", category "Weapons", default "H"); `manual_aim.register_toggle_handler(tcw) -> None`.

Why registration is needed: BC's C++ calls `TacticalControlHandlers.Initialize(pWindow)`, the **only** SDK site that binds `ET_INPUT_TOGGLE_PICK_FIRE → TogglePickFire`. Our engine calls `TacticalInterfaceHandlers.Initialize` (fire/turn/camera) but never `TacticalControlHandlers.Initialize`. We must NOT call the whole `Initialize` — it also registers a second `FirePrimaryWeapons/…` trio on the same TCW and would double-dispatch every fire key. Register just the toggle.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_input_map.py`:

```python
def test_manual_aim_default_h_and_unique():
    m = InputMap()
    assert m.name("manual_aim") == "H"
    assert m.code("manual_aim") == GLFW_KEYS["H"]
    # H must not be the default of any other action.
    assert [a for a in ACTIONS if a[3] == "H"] == [("manual_aim", "Manual Aim (toggle)", "Weapons", "H")]
```

Append to `tests/unit/test_manual_aim.py`:

```python
# ── Task 7: the H key ────────────────────────────────────────────────────────

def _tcw_with_tactical_menu():
    """Minimal Felix menu with the 'Manual Aim' button, registered on a fresh
    TCW -- the shape Bridge.TacticalMenuHandlers.CreateMenus produces live
    (see tests/unit/test_cutscene_menu_drop.py::_wired_officer)."""
    import App
    from engine.appc.windows import TacticalControlWindow
    from engine.appc.characters import STTopLevelMenu_CreateW
    TacticalControlWindow._instance = None
    tcw = TacticalControlWindow.GetInstance()
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    menu = STTopLevelMenu_CreateW(db.GetString("Tactical"))
    btn = App.STButton_CreateW(db.GetString("Manual Aim"))
    btn.SetAutoChoose(1)
    btn.SetChosen(0)
    btn.SetChoosable(1)
    menu.AddChild(btn)
    tcw.SetTacticalMenu(menu)
    App.g_kLocalizationManager.Unload(db)
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    return tcw, btn


def test_h_keydown_toggles_mouse_pick_fire_end_to_end(monkeypatch):
    """OnKeyDown(WC_H) -> DefaultKeyboardBinding (WC_H -> ET_INPUT_TOGGLE_
    PICK_FIRE) -> SDK TacticalControlHandlers.TogglePickFire on the TCW ->
    button chosen + SetMousePickFire(1). Second press turns it off."""
    import App
    from engine.appc.input import register_input_handlers
    from engine import manual_aim
    import Bridge.TacticalMenuHandlers as T
    monkeypatch.setattr(T, "UpdateOrders", lambda *a, **k: None)  # needs the full order panes
    register_input_handlers(App.g_kEventManager)
    tcw, btn = _tcw_with_tactical_menu()
    App.TopWindow_GetTopWindow().ForceTacticalVisible()
    manual_aim.register_toggle_handler(tcw)
    import KeyConfig, DefaultKeyboardBinding
    KeyConfig.MapScancodes()
    DefaultKeyboardBinding.Initialize()

    App.g_kInputManager.OnKeyDown(App.WC_H)
    assert tcw.GetMousePickFire() == 1
    assert btn.IsChosen() == 1

    App.g_kInputManager.OnKeyDown(App.WC_H)
    assert tcw.GetMousePickFire() == 0
    assert btn.IsChosen() == 0


def test_register_toggle_handler_is_idempotent(monkeypatch):
    """TCW reset runs once per mission (re)load; a double registration
    would toggle twice per press and never turn the mode on."""
    import App
    from engine.appc.input import register_input_handlers
    from engine import manual_aim
    import Bridge.TacticalMenuHandlers as T
    monkeypatch.setattr(T, "UpdateOrders", lambda *a, **k: None)
    register_input_handlers(App.g_kEventManager)
    tcw, btn = _tcw_with_tactical_menu()
    App.TopWindow_GetTopWindow().ForceTacticalVisible()
    manual_aim.register_toggle_handler(tcw)
    manual_aim.register_toggle_handler(tcw)
    import KeyConfig, DefaultKeyboardBinding
    KeyConfig.MapScancodes()
    DefaultKeyboardBinding.Initialize()
    App.g_kInputManager.OnKeyDown(App.WC_H)
    assert tcw.GetMousePickFire() == 1


def test_fire_key_poller_forwards_h_as_wc_h(monkeypatch):
    """_poll_fire_keys owns the H row (edge-detected like F/X/G) and
    _owned_glfw_keys lists it so the raw poller never double-delivers."""
    from engine import host_loop, host_io, input_map as im
    import App
    imap = im.InputMap()
    down = {imap.code("manual_aim"): True}
    monkeypatch.setattr(host_io, "key_state", lambda k: down.get(k, False))
    monkeypatch.setattr(host_loop, "_modifier_state", lambda h: (False, False, False))
    host_loop._fn_key_prev.clear()
    got = []
    monkeypatch.setattr(App.g_kInputManager, "OnKeyDown", lambda wc: got.append(wc))
    monkeypatch.setattr(App.g_kInputManager, "OnKeyUp", lambda wc: None)

    host_loop._poll_fire_keys(None, imap)

    assert App.WC_H in got
    assert imap.code("manual_aim") in host_loop._owned_glfw_keys(imap)


def test_host_loop_registers_the_toggle_on_tcw_reset():
    src = _host_loop_src()
    i_init = src.index("TacticalInterfaceHandlers.Initialize(_fresh_tcw)")
    i_reg = src.index("manual_aim.register_toggle_handler(_fresh_tcw)")
    assert i_init < i_reg < i_init + 900
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_input_map.py -k manual_aim tests/unit/test_manual_aim.py -k "h_key or toggle_handler or poller or registers" -v`
Expected: `KeyError: 'manual_aim'`; `AttributeError: module 'engine.manual_aim' has no attribute 'register_toggle_handler'`; poller test fails on `App.WC_H in got`; source guard fails.

- [ ] **Step 3: Implement**

`engine/input_map.py` — in `ACTIONS`, after the `fire_tertiary` row add:

```python
    ("manual_aim",           "Manual Aim (toggle)",      "Weapons",  "H"),
```

`engine/host_loop.py`:

- `_poll_fire_keys`: add a fourth row to the table:
```python
    _poll_key_table((
        (input_map.code("fire_primary"),   App.WC_F),
        (input_map.code("fire_secondary"), App.WC_X),
        (input_map.code("fire_tertiary"),  App.WC_G),
        # Manual Aim toggle: WC_H -> ET_INPUT_TOGGLE_PICK_FIRE
        # (DefaultKeyboardBinding.py:154) -> TacticalControlHandlers.
        # TogglePickFire, registered on the TCW by manual_aim.
        # register_toggle_handler. Binding path (not raw) on purpose: this
        # key's ET_INPUT_* consumer is live and wanted.
        (input_map.code("manual_aim"),     App.WC_H),
    ), suppress=suppress)
```
- `_owned_glfw_keys`: add `"manual_aim"` to the tuple of action ids (`"fire_primary", "fire_secondary", "fire_tertiary", "manual_aim",`).
- TCW reset block: right after the `try: import TacticalInterfaceHandlers; TacticalInterfaceHandlers.Initialize(_fresh_tcw) except …` statement, add:
```python
        # Manual Aim's H toggle. BC's C++ binds it through
        # TacticalControlHandlers.Initialize, which we never call (its fire
        # trio would double-dispatch F/X/G on this same TCW).
        manual_aim.register_toggle_handler(_fresh_tcw)
```

`engine/manual_aim.py` — append:

```python
# ── SDK toggle handler ──────────────────────────────────────────────────────
_TOGGLE_HANDLER = "TacticalControlHandlers.TogglePickFire"


def register_toggle_handler(tcw) -> None:
    """Bind ET_INPUT_TOGGLE_PICK_FIRE -> SDK TacticalControlHandlers.
    TogglePickFire on the TacticalControlWindow.

    BC's engine does this via TacticalControlHandlers.Initialize(pWindow)
    (:35). We register ONLY the toggle: Initialize also binds a second
    FirePrimary/Secondary/TertiaryWeapons trio, and TacticalInterface
    Handlers.Initialize already owns those on our single TCW. Idempotent --
    the TCW singleton is rebuilt per mission load, but a defensive second
    call must not stack a second handler (two toggles per press == never on)."""
    import App
    import TacticalControlHandlers  # noqa: F401 -- SDK module; the handler is resolved by name
    et = int(App.ET_INPUT_TOGGLE_PICK_FIRE)
    if getattr(tcw, "_manual_aim_toggle_registered", False):
        return
    tcw.AddPythonFuncHandlerForInstance(et, _TOGGLE_HANDLER)
    tcw._manual_aim_toggle_registered = True
```

If `TGEventHandlerObject.AddPythonFuncHandlerForInstance` already de-duplicates an identical `(event, name)` pair (check `engine/appc/events.py`), keep the flag anyway — it documents the intent and costs nothing.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_input_map.py tests/unit/test_manual_aim.py tests/unit/test_fire_key_input_chain.py tests/unit/test_keyboard_binding.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/input_map.py engine/host_loop.py engine/manual_aim.py tests/unit/test_input_map.py tests/unit/test_manual_aim.py
git commit -m "feat(input): H toggles Manual Aim through the SDK binding chain

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Felix's "Manual Aim" button — real `SetAutoChoose` + chosen state in the crew menu

**Files:**
- Modify: `engine/appc/characters.py` (`STButton.__init__`, `SetAutoChoose` ~line 118), `engine/ui/crew_menu_panel.py` (`_snapshot_node` ~line 157; click dispatch ~line 246), `native/assets/ui-cef/js/crew_menus.js` (row builder ~line 93), `native/assets/ui-cef/css/crew_menus.css`
- Test: `tests/unit/test_crew_menu_panel.py`, `tests/unit/test_manual_aim.py`

**Interfaces:**
- Produces: `STButton.SetAutoChoose(v=1)`, `STButton.IsAutoChoose() -> int`; crew-menu row payload key `"chosen": bool`; CSS class `crew-menu__row--chosen`.

Why: `Bridge/TacticalMenuHandlers.py:362-366` creates the button with `SetAutoChoose(1)` / `SetChoosable(1)`, and its `.Fire` handler (`:1025`) reads `IsChosen()` *after* the click ("If Manual Aim is now Off…"). Our `SetAutoChoose` is a `pass`, so a click never flips the state and `UpdateManualAim` never sees a change. Side effect (accepted, spec §Dauntless design): "Phasers Only" and "Target At Will" start toggling too; their consumers (`CheckFiring`, `CheckSubsystemTargeting`) are inert.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_crew_menu_panel.py`:

```python
_chosen_seen = []


def _record_chosen(dest, event):
    _chosen_seen.append(dest.GetButtonW("All Stop").IsChosen())


def test_click_on_auto_choose_button_flips_chosen_before_its_event():
    """BC order: an AutoChoose button toggles IsChosen() and THEN sends its
    activation event -- TacticalMenuHandlers.Fire reads the new state."""
    _chosen_seen.clear()
    helm, btn = _build_helm_with_button()
    btn.SetAutoChoose(1)
    helm.AddPythonFuncHandlerForInstance(App.ET_ALL_STOP, __name__ + "._record_chosen")
    panel = CrewMenuPanel()
    panel.render_payload()
    wid = ensure_widget_id(btn)
    panel.dispatch_event(f"click:{wid}")
    assert btn.IsChosen() == 1 and _chosen_seen == [1]
    panel.dispatch_event(f"click:{wid}")
    assert btn.IsChosen() == 0 and _chosen_seen == [1, 0]


def test_click_on_plain_button_never_touches_chosen():
    helm, btn = _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    panel.dispatch_event(f"click:{ensure_widget_id(btn)}")
    assert btn.IsChosen() == 0


def test_payload_carries_chosen_and_reemits_when_it_flips():
    helm, btn = _build_helm_with_button()
    panel = CrewMenuPanel()
    data = json.loads(panel.render_payload()[len("setCrewMenus("):-2])
    assert data["menus"][0]["children"][0]["chosen"] is False
    btn.SetChosen(1)
    assert panel.render_payload() is not None       # diff-gate re-emits
```

Append to `tests/unit/test_manual_aim.py`:

```python
# ── Task 8: Felix's button ───────────────────────────────────────────────────

def test_clicking_manual_aim_in_felixs_menu_sets_mouse_pick_fire(monkeypatch):
    """The SDK path with no keyboard: crew-menu click -> ET_FIRE at the
    Tactical menu -> Bridge.TacticalMenuHandlers.Fire -> UpdateManualAim ->
    SetMousePickFire(IsChosen())."""
    import App
    import json
    from engine.ui.crew_menu_panel import CrewMenuPanel
    from engine.appc.tg_ui.widgets import ensure_widget_id
    import Bridge.TacticalMenuHandlers as T
    from engine.core.game import Game, _set_current_game
    from engine.appc.ships import ShipClass
    monkeypatch.setattr(T, "UpdateOrders", lambda *a, **k: None)
    monkeypatch.setattr(T, "UpdateOrderMenus", lambda *a, **k: None)
    monkeypatch.setattr(T, "CheckFiring", lambda *a, **k: None)
    # TacticalMenuHandlers.Fire returns early with no current player.
    game = Game()
    game.SetPlayer(ShipClass())
    _set_current_game(game)
    tcw, btn = _tcw_with_tactical_menu()
    menu = tcw.GetTacticalMenu()
    evt = App.TGIntEvent_Create()
    evt.SetEventType(App.ET_FIRE)
    evt.SetDestination(menu)
    btn.SetActivationEvent(evt)
    menu.AddPythonFuncHandlerForInstance(App.ET_FIRE, "Bridge.TacticalMenuHandlers.Fire")
    tcw.AddMenuToList(menu)
    panel = CrewMenuPanel()
    panel.render_payload()

    panel.dispatch_event(f"click:{ensure_widget_id(btn)}")
    assert tcw.GetMousePickFire() == 1
    data = json.loads(panel.render_payload()[len("setCrewMenus("):-2])
    assert data["menus"][0]["children"][0]["chosen"] is True

    panel.dispatch_event(f"click:{ensure_widget_id(btn)}")
    assert tcw.GetMousePickFire() == 0
    _set_current_game(None)
```

(`tests/conftest.py`'s autouse `_reset_leakable_engine_globals` also resets the
current game between tests; the explicit `_set_current_game(None)` keeps this
test self-contained if it is ever run in isolation.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_crew_menu_panel.py -k "chosen" tests/unit/test_manual_aim.py -k felix -v`
Expected: FAIL — `IsChosen() == 0` after click; `KeyError: 'chosen'`; `GetMousePickFire() == 0`.

- [ ] **Step 3: Implement**

`engine/appc/characters.py` — in `STButton.__init__` add `self._auto_choose = False`; replace `def SetAutoChoose(self, *args) -> None: pass` with:

```python
    def SetAutoChoose(self, value=1) -> None:
        # BC: a click on an AutoChoose button flips IsChosen() BEFORE the
        # activation event fires -- Bridge.TacticalMenuHandlers.Fire reads
        # the NEW state ("If Manual Aim is now Off..."). The flip itself
        # lives at the click site (engine/ui/crew_menu_panel.py) so a scripted
        # SendActivationEvent never toggles.
        self._auto_choose = bool(value)

    def IsAutoChoose(self) -> int:
        return 1 if self._auto_choose else 0
```

`engine/ui/crew_menu_panel.py`:
- `_snapshot_node`: after `"visible": bool(widget.IsVisible()),` add `"chosen": bool(widget.IsChosen()) if isinstance(widget, STButton) else False,` (STButton is already imported there; `STMenu` has no IsChosen).
- click dispatch: immediately before `widget.SendActivationEvent()` in the `isinstance(widget, STButton)` branch add:
```python
                if widget.IsAutoChoose():
                    widget.SetChosen(not widget.IsChosen())
```

`native/assets/ui-cef/js/crew_menus.js` — in `appendCrewRows`, extend the className expression:
```js
    row.className = "crew-menu__row" + (node.enabled ? "" : " disabled") +
                    (hasChildren ? "" : " crew-menu__row--leaf") +
                    (node.chosen ? " crew-menu__row--chosen" : "");
```
and after the label is appended:
```js
    if (node.chosen) {
      const check = document.createElement("span");
      check.className = "crew-menu__check";
      check.textContent = "✓";
      row.appendChild(check);
    }
```

`native/assets/ui-cef/css/crew_menus.css` — after the `.crew-menu__row.disabled:hover` rule add:
```css
/* AutoChoose buttons (Manual Aim, Phasers Only, Target At Will): BC draws a
   chosen button in its highlighted colour; we tint the row and add a check. */
.crew-menu__row--chosen { background: rgba(216, 94, 86, 0.28); }
.crew-menu__check { margin-left: auto; padding-left: 12px; opacity: 0.9; }
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_crew_menu_panel.py tests/unit/test_manual_aim.py tests/unit/test_cutscene_menu_drop.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py engine/ui/crew_menu_panel.py native/assets/ui-cef/js/crew_menus.js native/assets/ui-cef/css/crew_menus.css tests/unit/test_crew_menu_panel.py tests/unit/test_manual_aim.py
git commit -m "feat(crew-menu): AutoChoose buttons toggle on click; rows show chosen state

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Drop Manual Aim on the bridge (engine twin of the stubbed `DropOutOfManualFireMode`)

**Files:**
- Modify: `engine/manual_aim.py` (`drop_mode`), `engine/appc/top_window.py` (`StartCutscene` ~line 97, `ForceBridgeVisible` ~line 159, `ToggleBridgeAndTactical` ~line 203)
- Test: `tests/unit/test_manual_aim.py`

**Interfaces:**
- Produces: `manual_aim.drop_mode() -> None`.

Why: `BridgeHandlers.DropOutOfManualFireMode` (`:1061`) — **only when `IsBridgeVisible()`** — clears the flag and resyncs the button. It runs from the bridge window's `GotFocus` (`:336`, i.e. every tactical→bridge flip) and from `DropMenusTurnBack` at cutscene start (`:1052`). `BridgeHandlers` is a stubbed module here (see `tests/unit/test_cutscene_menu_drop.py`), so neither call happens.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_manual_aim.py`:

```python
# ── Task 9: drop on the bridge ───────────────────────────────────────────────

def _armed_manual_aim():
    import App
    tcw, btn = _tcw_with_tactical_menu()
    btn.SetChosen(1)
    tcw.SetMousePickFire(1)
    return App.TopWindow_GetTopWindow(), tcw, btn


def test_drop_mode_clears_flag_and_button_only_when_bridge_visible():
    from engine import manual_aim
    top, tcw, btn = _armed_manual_aim()
    top.ForceTacticalVisible()
    manual_aim.drop_mode()
    assert tcw.GetMousePickFire() == 1 and btn.IsChosen() == 1    # tactical: untouched
    top._bridge_visible, top._tactical_visible = True, False       # flip flags silently
    manual_aim.drop_mode()
    assert tcw.GetMousePickFire() == 0 and btn.IsChosen() == 0


def test_drop_mode_survives_a_tcw_without_a_tactical_menu():
    from engine import manual_aim
    from engine.appc.windows import TacticalControlWindow
    import App
    TacticalControlWindow._instance = None
    tcw = TacticalControlWindow.GetInstance()
    tcw.SetMousePickFire(1)
    App.TopWindow_GetTopWindow().ForceBridgeVisible()
    manual_aim.drop_mode()                       # must not raise (GetTacticalMenu() is None)
    assert tcw.GetMousePickFire() == 0


def test_flipping_to_the_bridge_drops_manual_aim():
    """BridgeHandlers.GotFocus (:336) -> DropOutOfManualFireMode on every
    tactical -> bridge flip; the reverse flip leaves it alone."""
    top, tcw, btn = _armed_manual_aim()
    top.ForceTacticalVisible()
    top.ToggleBridgeAndTactical()                # -> bridge
    assert top.IsBridgeVisible() and tcw.GetMousePickFire() == 0 and btn.IsChosen() == 0
    btn.SetChosen(1); tcw.SetMousePickFire(1)
    top.ToggleBridgeAndTactical()                # -> tactical
    assert tcw.GetMousePickFire() == 1
    top.ForceBridgeVisible()
    assert tcw.GetMousePickFire() == 0


def test_cutscene_start_on_the_bridge_drops_manual_aim():
    top, tcw, btn = _armed_manual_aim()
    top.ForceBridgeVisible()
    btn.SetChosen(1); tcw.SetMousePickFire(1)
    top.StartCutscene(1.0, 0.125, 1)
    assert tcw.GetMousePickFire() == 0 and btn.IsChosen() == 0
    top.EndCutscene(1.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_manual_aim.py -k "drop_mode or flipping or cutscene_start" -v`
Expected: FAIL `AttributeError: module 'engine.manual_aim' has no attribute 'drop_mode'`; the flip/cutscene tests fail on `GetMousePickFire() == 0`.

- [ ] **Step 3: Implement**

`engine/manual_aim.py` — append:

```python
# ── Drop rule (BridgeHandlers.DropOutOfManualFireMode twin) ─────────────────

def drop_mode() -> None:
    """Leave Manual Aim when the BRIDGE is visible: clear the TCW flag and
    resync Felix's button (Bridge.TacticalMenuHandlers.ResetPickFireButton).

    Twin of the SDK's BridgeHandlers.DropOutOfManualFireMode (:1061), which
    our harness stubs along with the rest of BridgeHandlers. BC calls it
    from the bridge window's GotFocus (:336) and at cutscene start (:1052);
    _TopWindow calls this from the same two moments. Tactical view: no-op,
    exactly like the SDK's IsBridgeVisible() gate."""
    import App
    from engine.appc.windows import TacticalControlWindow
    top = App.TopWindow_GetTopWindow()
    if not top.IsBridgeVisible():
        return
    tcw = TacticalControlWindow.GetInstance()
    tcw.SetMousePickFire(0)
    # ResetPickFireButton dereferences GetTacticalMenu() with no None guard
    # (the crash that got BridgeHandlers stubbed) -- guard it here instead
    # of swallowing.
    if tcw.GetTacticalMenu() is not None:
        import Bridge.TacticalMenuHandlers as T
        T.ResetPickFireButton()
```

`engine/appc/top_window.py`:
- `StartCutscene`: after `_drop_open_crew_menu()` add:
```python
        # BridgeHandlers.DropMenusTurnBack also leaves Manual Aim (:1052);
        # same moment, engine-side twin (BridgeHandlers is stubbed).
        from engine import manual_aim
        manual_aim.drop_mode()
```
- `ForceBridgeVisible`: after `self._leave_cinematic_for_view()` add:
```python
        from engine import manual_aim
        manual_aim.drop_mode()
```
- `ToggleBridgeAndTactical`: after the swap add:
```python
        if self._bridge_visible:
            # Bridge window GotFocus (BridgeHandlers.py:336) drops Manual Aim.
            from engine import manual_aim
            manual_aim.drop_mode()
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_manual_aim.py tests/unit/test_cutscene_menu_drop.py tests/unit/test_top_window*.py tests/unit/test_cinematic*.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/manual_aim.py engine/appc/top_window.py tests/unit/test_manual_aim.py
git commit -m "feat(manual-aim): drop the mode on the bridge, as BridgeHandlers does in BC

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Docs + full gate

**Files:**
- Modify: `CLAUDE.md` (key reference table), `docs/superpowers/specs/2026-09-15-manual-aim-pick-fire-design.md` (status line)

- [ ] **Step 1: Add the CLAUDE.md row**

In the "Key reference material" table, after the "E1M1 intro skip" row, add:

```markdown
| Manual Aim (H, "mouse pick fire") | `engine/manual_aim.py`, `docs/superpowers/specs/2026-09-15-manual-aim-pick-fire-design.md` | BC's point-to-aim: `H` → `ET_INPUT_TOGGLE_PICK_FIRE` → SDK `TacticalControlHandlers.TogglePickFire` (registered by `manual_aim.register_toggle_handler`, NOT by `TacticalControlHandlers.Initialize` — that would double-dispatch the fire keys). Per tick, sim side: cursor → `cursor_ray` (exact inverse of the SPV `project`) → `ray_trace_mesh` on the **targeted** hull only → `ShipClass.set_manual_target_offset` (target-local, **unscaled**). Off the hull ⇒ `UseTargetOffsetTG(0)` immediately. Phaser tick + drawn beam share `_phaser_aim_point`; torpedoes/pulse read the offset live via `WeaponSystem._live_held_offset`. Dropped whenever the bridge becomes visible (`manual_aim.drop_mode`, twin of the stubbed `BridgeHandlers.DropOutOfManualFireMode`). ⚠️ The C++ pick semantics are five **stated assumptions** in the spec, not RE'd behaviour. |
```

- [ ] **Step 2: Mark the spec as implemented**

Change the spec's `**Status:**` line to `**Status:** implemented by docs/superpowers/plans/2026-09-15-manual-aim-pick-fire.md; awaiting live verification (see §Live verification).`

- [ ] **Step 3: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0; every failure listed is in `tests/known_failures.txt` (currently exactly one order-dependent pytest entry). If the gate names anything else, it is a regression from this plan — fix it before committing.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-09-15-manual-aim-pick-fire-design.md docs/superpowers/plans/2026-09-15-manual-aim-pick-fire.md
git commit -m "docs: Manual Aim key-reference row and spec status

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Hand off for live verification (Mark)**

Not automatable. Report the spec's "Live verification" checklist verbatim and do not claim the feature is done until it has run in the game.
