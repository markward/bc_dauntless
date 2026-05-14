# Weapon firing pipeline (PR 2a of 2)

**Status:** design
**Date:** 2026-05-14
**Predecessor:** [2026-05-13-weapon-emitter-scaffolding-design.md](2026-05-13-weapon-emitter-scaffolding-design.md) (PR 1, merged)

## Context

PR 1 landed per-emitter charge/reload state and the property → runtime data path. Each `PhaserBank` / `PulseWeapon` / `TractorBeam` knows its `MaxCharge`, `MinFiringCharge`, `NormalDischargeRate`, `RechargeRate`, and current `ChargeLevel`. Each `TorpedoTube` knows `ImmediateDelay`, `ReloadDelay`, `MaxReady`, `NumReady`, and `LastFireTime`. None of these fields are read yet — they're inert.

PR 2a turns them into a firing signal that runs through BC's actual input → event → handler chain, gated on weapon power (which is itself gated on alert level). Result: right-click in red alert plays a torpedo SFX, debug panel shows "FIRE", and the next tube's `_num_ready` decrements. Nothing visible in 3D yet — projectile rendering and collision are PR 2b.

## Goals

1. Holding right-click on the player ship at RED alert fires a torpedo (audibly + state-visible).
2. Holding left-click at RED alert fires the next phaser bank for as long as the trigger is held and the bank has charge.
3. Releasing the button stops firing on energy emitters.
4. AI ships under their existing `AI.Preprocessors.AlertLevel(RED_ALERT)` setup fire on the same gating logic.
5. Mission scripts that call `g_kKeyboardBinding.BindKey(...)` to remap keys continue to work without modification — the binding pipeline is real, not a shim shortcut.

## Non-goals (deferred to PR 2b)

- Projectile entities (torpedo body in space, phaser beam geometry).
- Renderer passes for projectiles / beams.
- Collision detection.
- Damage application via `ShipClass.DamageSystem`.
- `WeaponHitEvent` broadcast.
- Friendly-fire handlers.
- AI ship targeting verification.

PR 2a's firing state is observable through `IsFiring()`, `GetChargeLevel()`, `GetNumReady()`, the debug-panel "Weapons" row, and the SFX trigger. Anything that flies through space is PR 2b.

## End-to-end data flow

```
GLFW mouse-button event (right-click down)
  ↓ host_window callback updates pressed-state buffer
Python host_loop frame()
  ↓ host.mouse_button_pressed(MOUSE_BUTTON_RIGHT) → True (rising edge)
g_kInputManager.OnKeyDown(WC_RBUTTON)
  ↓ synthesises a TGKeyboardEvent(unicode=WC_RBUTTON, state=KS_KEYDOWN)
  ↓ posts to g_kEventManager broadcast
g_kKeyboardBinding receives keyboard event, looks up binding
  ↓ DefaultKeyboardBinding.RegisterBindings registered:
  ↓   (WC_RBUTTON, KS_KEYDOWN) → (ET_INPUT_FIRE_SECONDARY, GET_BOOL_EVENT, 1)
  ↓ creates TGEvent(ET_INPUT_FIRE_SECONDARY, bool=True), dest=g_pkTacticalControlWindow
g_kEventManager.AddEvent(evt)
  ↓ TacticalControlWindow.ProcessEvent dispatches to registered handler
TacticalInterfaceHandlers.FireSecondaryWeapons(pTCW, evt)
  ↓ resolves player ship + group
FireWeapons(pShip, bFiring=1, WG_SECONDARY)
  ↓
pShip.GetWeaponSystemGroup(WG_SECONDARY).StartFiring(target, offset)
  ↓ NEW gating: if not group.IsOn(): return early
  ↓ Sequential cursor: pick next eligible emitter from _next_emitter_index
emitter.Fire(target, offset)
  ↓ NEW gating: TorpedoTube → if _num_ready <= 0: return
  ↓                EnergyWeapon → if _charge_level < _min_firing_charge: return
  ↓ on accept: _firing = True; record _target; _num_ready-- (torps);
  ↓            _last_fire_time = now (torps); SFX trigger
TGSoundManager.PlaySound(self.GetProperty().GetFireSound())
```

KEYUP path mirrors: `host.mouse_button_released(...) → OnKeyUp(WC_RBUTTON) → KeyboardBinding routes to ET_INPUT_FIRE_SECONDARY(bool=0) → FireWeapons(pShip, 0, ...) → group.StopFiring()`.

Per-frame tick (separate from input):

```python
host_loop.frame(dt):
    for ship in all_ships:
        for group in (ship.GetPhaserSystem(), ship.GetTorpedoSystem(),
                      ship.GetPulseWeaponSystem(), ship.GetTractorBeamSystem()):
            if group is None: continue
            for i in range(group.GetNumWeapons()):
                emitter = group.GetWeapon(i)
                emitter.UpdateCharge(dt)    # EnergyWeapon: fill/drain
                if isinstance(emitter, TorpedoTube):
                    emitter.UpdateReload(dt)  # increment _num_ready when reload elapses
```

## Components

### New shim classes (engine/appc/)

#### `TGKeyboardEvent(TGEvent)` — `engine/appc/events.py`

Subclass of `TGEvent`. Carries:
- `_unicode_key: int` — `WC_*` code (`WC_RBUTTON` etc.)
- `_key_state: int` — `KS_KEYDOWN` / `KS_KEYUP` / `KS_KEYREPEAT`

Methods: `GetUnicodeKey() -> int`, `SetUnicodeKey(int)`, `GetKeyState() -> int`, `SetKeyState(int)`. Constructor sets `_event_type = ET_KEYBOARD_EVENT` (new constant).

#### `TGInputManager` (`g_kInputManager`) — `engine/appc/input.py` (new module)

Tracks the `WC_*` → `KY_*` registration table populated by `RegisterUnicodeKey`. Translates host-side key/button events into `TGKeyboardEvent` posts.

```python
class TGInputManager(TGObject):
    def __init__(self):
        super().__init__()
        # {WC_code: (KY_code, database_ref, name)}
        self._registered: dict[int, tuple[int, object, str]] = {}

    def RegisterUnicodeKey(self, wc_code, ky_code, database, name) -> None:
        self._registered[int(wc_code)] = (int(ky_code), database, str(name))

    def OnKeyDown(self, wc_code: int) -> None:
        if wc_code not in self._registered:
            return
        evt = TGKeyboardEvent()
        evt.SetUnicodeKey(wc_code)
        evt.SetKeyState(KS_KEYDOWN)
        App.g_kEventManager.AddEvent(evt)

    def OnKeyUp(self, wc_code: int) -> None:
        if wc_code not in self._registered:
            return
        evt = TGKeyboardEvent()
        evt.SetUnicodeKey(wc_code)
        evt.SetKeyState(KS_KEYUP)
        App.g_kEventManager.AddEvent(evt)
```

Module-level singleton `g_kInputManager = TGInputManager()` exposed through `App.py`.

#### `KeyboardBinding` (`g_kKeyboardBinding`) — `engine/appc/input.py`

Listens for `TGKeyboardEvent`s on `g_kEventManager` broadcast. Translates `(unicode_key, key_state)` → `(event_type, value)` per registered bindings, then posts the resulting event.

```python
class KeyboardBinding(TGObject):
    GET_BOOL_EVENT = 1
    GET_INT_EVENT  = 2
    GET_FLOAT_EVENT = 3

    def __init__(self):
        super().__init__()
        # {(wc_code, key_state): (event_type, flags, value)}
        self._bindings: dict[tuple[int, int], tuple[int, int, object]] = {}

    def BindKey(self, wc_code, key_state, event_type, flags, value) -> None:
        self._bindings[(int(wc_code), int(key_state))] = (int(event_type), int(flags), value)

    def OnKeyboardEvent(self, evt: TGKeyboardEvent) -> None:
        key = (evt.GetUnicodeKey(), evt.GetKeyState())
        binding = self._bindings.get(key)
        if binding is None:
            return
        event_type, flags, value = binding
        out = _build_event(event_type, flags, value)
        out.SetDestination(App.TacticalControlWindow_GetTacticalControlWindow())
        App.g_kEventManager.AddEvent(out)
```

`_build_event(event_type, flags, value)` returns a `TGBoolEvent` / `TGIntEvent` / `TGFloatEvent` per the flags. PR 1's `TGEvent` already supports event types; we add minimal `TGBoolEvent(TGEvent)` with `SetBool(bool)` / `GetBool() -> int` since `FireWeapons` reads it.

Wired into the event-manager broadcast: `g_kEventManager.AddBroadcastPythonFuncHandler(ET_KEYBOARD_EVENT, g_kKeyboardBinding, "engine.appc.input.KeyboardBinding_OnKeyboardEvent")`. (Method-on-instance + module-level qualified-name resolver — matches existing pattern.)

#### `TacticalControlWindow` placeholder — `engine/appc/windows.py` (new module, small)

A `TGEventHandlerObject` subclass that input-derived events dispatch to. SDK has it as a full window class with menus, layout, focus management; for PR 2a we need only the event-handler surface so `TacticalInterfaceHandlers.RegisterHandlers(pTCW)` can install fire-event handlers on it.

```python
class TacticalControlWindow(TGEventHandlerObject):
    """Phase 1 stub — only the AddPythonFuncHandlerForInstance + ProcessEvent
    surface is needed.  Menu/layout/focus is PR 2b+ work.
    """
    _instance: "TacticalControlWindow | None" = None

    @classmethod
    def GetInstance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def CallNextHandler(self, evt):
        # SDK handlers call pObject.CallNextHandler(pEvent) for chain
        # propagation.  Without a parent window chain we no-op.
        pass
```

`App.TacticalControlWindow_GetTacticalControlWindow = TacticalControlWindow.GetInstance` in the shim.

### Constants — `engine/appc/input.py` + `App.py` re-export

| Constant | Value | Source |
|---|---|---|
| `WC_LBUTTON` | `0x01` | `App.py:13xxx` (mirror SDK ints; exact values irrelevant headlessly, but consistent) |
| `WC_RBUTTON` | `0x02` |  |
| `WC_MBUTTON` | `0x04` |  |
| `KY_LBUTTON` | `0x01` |  |
| `KY_RBUTTON` | `0x02` |  |
| `KY_MBUTTON` | `0x04` |  |
| `KS_KEYDOWN` | `0` | `App.TGKeyboardEvent.KS_*` |
| `KS_KEYUP` | `1` |  |
| `KS_KEYREPEAT` | `2` |  |
| `ET_KEYBOARD_EVENT` | (next free) | new event type for `TGKeyboardEvent` |

Existing `ET_INPUT_FIRE_PRIMARY/SECONDARY/TERTIARY` constants are already in `App.py` re-export ([App.py:13834-13836](sdk/Build/scripts/App.py#L13834-L13836)).

### Power state on `PoweredSubsystem` — `engine/appc/subsystems.py`

Add to `PoweredSubsystem.__init__`:
```python
self._is_on: bool = False
self._power_percentage_wanted: float = 0.0
```

Methods:
```python
def TurnOn(self) -> None:
    self._is_on = True

def TurnOff(self) -> None:
    self._is_on = False

def IsOn(self) -> int:
    return 1 if self._is_on else 0

def SetPowerPercentageWanted(self, pct: float) -> None:
    self._power_percentage_wanted = float(pct)

def GetPowerPercentageWanted(self) -> float:
    return self._power_percentage_wanted
```

### Sequential firing cursor on `WeaponSystem`

Add to `WeaponSystem.__init__`:
```python
self._next_emitter_index: int = 0
self._currently_firing: list[int] = []  # indices of emitters with _firing=True
```

Rewrite `StartFiring` / `StopFiring`:

```python
def StartFiring(self, target=None, offset=None) -> None:
    """Fire the next eligible emitter in the round-robin sequence.

    Matches the Galaxy hardpoint's SetSingleFire(1) mode — one bank per
    StartFiring call, cursor advances afterward.  No-ops cleanly when
    the group is powered off or no emitter is currently eligible.
    """
    if not self.IsOn():
        return
    n = self.GetNumWeapons()
    if n == 0:
        return
    start = self._next_emitter_index % n
    for offset_i in range(n):
        idx = (start + offset_i) % n
        emitter = self.GetWeapon(idx)
        if emitter is None:
            continue
        if emitter.CanFire():
            emitter.Fire(target, offset)
            self._currently_firing.append(idx)
            self._next_emitter_index = (idx + 1) % n
            return
    # No eligible emitter — no-op.

def StopFiring(self) -> None:
    for idx in self._currently_firing:
        emitter = self.GetWeapon(idx)
        if emitter is not None:
            emitter.StopFiring()
    self._currently_firing.clear()

def IsFiring(self) -> int:
    return 1 if self._currently_firing else 0
```

Note: `IsFiring()` was previously a bare flag on `WeaponSystem`. The flag (`_firing`) becomes per-emitter; `WeaponSystem.IsFiring()` now derives from `_currently_firing`.

### Per-emitter `Fire` / `StopFiring` / `CanFire` / `UpdateCharge` / `UpdateReload`

Energy emitter base (applied to `PhaserBank`, `PulseWeapon`, `TractorBeam`):

```python
def CanFire(self) -> int:
    return 1 if (self.IsOn() and self._charge_level >= self._min_firing_charge) else 0

def Fire(self, target=None, offset=None) -> None:
    """No-target case: PR 2b's projectile fires along emitter's local +Y
    in world space.  PR 2a only sets _firing + plays SFX.
    """
    if not self.CanFire():
        return
    self._firing = True
    self._target = target
    self._target_offset = offset
    prop = self.GetProperty()
    if prop is not None:
        sound = _resolve_fire_sound(prop)
        if sound:
            TGSoundManager.instance().PlaySound(sound)

def StopFiring(self) -> None:
    self._firing = False

def UpdateCharge(self, dt: float) -> None:
    if self._firing:
        self._charge_level = max(0.0,
            self._charge_level - self._normal_discharge_rate * dt)
        if self._charge_level <= 0.0:
            # Auto-stop when drained; group's StopFiring would also catch
            # this on the next button release.
            self._firing = False
    elif self._is_on:
        self._charge_level = min(self._max_charge,
            self._charge_level + self._recharge_rate * dt)
    # Off but not firing: charge holds (matches SDK behavior — turning
    # weapons off doesn't drain stored charge).
```

`_resolve_fire_sound(prop)` reads `prop.GetFireSound()`. PR 1 left this on the `__getattr__` catch-all; PR 2a promotes it to a typed accessor on `EnergyWeaponProperty` since we now have a consumer.

`IsOn()` on the emitter delegates to the parent group: `return self.GetParentSubsystem().IsOn() if self.GetParentSubsystem() else 0`. (The group is the powered unit; individual emitters inherit the group's on/off state.)

`TorpedoTube`:

```python
def CanFire(self) -> int:
    return 1 if (self.IsOn() and self._num_ready > 0) else 0

def Fire(self, target=None, offset=None) -> None:
    if not self.CanFire():
        return
    self._firing = True
    self._target = target
    self._target_offset = offset
    self._num_ready -= 1
    import time as _time
    self._last_fire_time = _time.monotonic()
    prop = self.GetProperty()
    if prop is not None:
        sound = _resolve_fire_sound(prop)
        if sound:
            TGSoundManager.instance().PlaySound(sound)
    # Tubes are discrete-shot — auto-stop after the launch.
    self._firing = False

def StopFiring(self) -> None:
    self._firing = False

def UpdateReload(self, dt: float) -> None:
    if self._num_ready >= self._max_ready:
        return
    import time as _time
    if _time.monotonic() - self._last_fire_time >= self._reload_delay:
        self._num_ready += 1
        self._last_fire_time = _time.monotonic()
```

(Time source: `time.monotonic()` for a real-time wall clock; if the engine has its own game-time clock to use for time scaling, swap to that — note for the implementer.)

### Alert → power policy — `ShipClass.SetAlertLevel`

Replace the current one-liner:

```python
def SetAlertLevel(self, v) -> None:
    self._alert_level = int(v)
    on = (self._alert_level == ShipClass.RED_ALERT)
    for slot in (self._phaser_system, self._torpedo_system, self._pulse_weapon_system):
        if slot is None:
            continue
        if on:
            slot.TurnOn()
            slot.SetPowerPercentageWanted(1.0)
        else:
            slot.TurnOff()
            slot.SetPowerPercentageWanted(0.0)
    # Tractor stays under manual control — toggled via the tractor UI,
    # not by alert level.  Mirrors BC behaviour.
```

Triggered by both mission-script direct calls (`pShip.SetAlertLevel(...)`) and the existing Shift+1/2/3 path in [host_loop.py:61-78](engine/host_loop.py#L61-L78).

### Per-frame tick — `engine/host_loop.py`

In the existing frame loop, after physics + AI but before render (matches measured BC tick order):

```python
_advance_weapons(_player_set_ships(), dt)
```

Where `_advance_weapons(ships, dt)` is:

```python
def _advance_weapons(ships, dt: float) -> None:
    """Per-frame charge/reload advancement for all weapon emitters.

    Walks every ship's four weapon groups and calls UpdateCharge/UpdateReload
    on each emitter.  AI ships use the same tick path — their AI scripts
    that call StartFiring rely on emitters being charged.
    """
    from engine.appc.subsystems import TorpedoTube
    for ship in ships:
        for group in (ship.GetPhaserSystem(),
                      ship.GetPulseWeaponSystem(),
                      ship.GetTractorBeamSystem(),
                      ship.GetTorpedoSystem()):
            if group is None:
                continue
            for i in range(group.GetNumWeapons()):
                emitter = group.GetWeapon(i)
                if emitter is None:
                    continue
                if hasattr(emitter, "UpdateCharge"):
                    emitter.UpdateCharge(dt)
                if isinstance(emitter, TorpedoTube):
                    emitter.UpdateReload(dt)
```

`_player_set_ships()` returns the iterator over every ship in the active `Sets` — same scope already used by other per-frame walks (e.g. position-update for engine rumble in [host_loop.py:61](engine/host_loop.py#L61)).

### Host mouse-button binding — `native/src/host/`

Add to `host_bindings.cc`:

```cpp
m.def("mouse_button_pressed",
      [](int button) -> bool {
          if (!g_window) {
              throw std::runtime_error("mouse_button_pressed: init must be called first");
          }
          return g_window->mouse_button_pressed(button);
      });

m.def("mouse_button_released",
      [](int button) -> bool { ... });
```

Plus GLFW button constants:
```cpp
keys.attr("MOUSE_BUTTON_LEFT")   = GLFW_MOUSE_BUTTON_LEFT;
keys.attr("MOUSE_BUTTON_RIGHT")  = GLFW_MOUSE_BUTTON_RIGHT;
keys.attr("MOUSE_BUTTON_MIDDLE") = GLFW_MOUSE_BUTTON_MIDDLE;
```

Mirrors the existing `key_pressed` rising-edge detection — host tracks last-frame button state, returns true only on the transition. `Window::mouse_button_pressed` / `mouse_button_released` use GLFW's per-frame poll (already in the existing input loop).

### Host_loop bootstrap

In `init_audio`'s caller block (around [host_loop.py:1417](engine/host_loop.py#L1417)), add right after `init_audio()`:

```python
# Bring up SDK-faithful input pipeline.
import App
from engine.appc.input import (
    g_kInputManager, g_kKeyboardBinding, register_input_handlers,
)
from engine.appc.windows import TacticalControlWindow

App.g_kInputManager   = g_kInputManager
App.g_kKeyboardBinding = g_kKeyboardBinding
App.TacticalControlWindow_GetTacticalControlWindow = TacticalControlWindow.GetInstance
register_input_handlers()  # wires KeyboardBinding.OnKeyboardEvent into g_kEventManager broadcast

# Real BC calls these on KeyConfig load; we invoke directly.
import DefaultKeyboardBinding
DefaultKeyboardBinding.RegisterUnicodeKeys()
DefaultKeyboardBinding.RegisterBindings()

# Install the tactical handlers onto the (newly-created) control window.
import TacticalInterfaceHandlers
TacticalInterfaceHandlers.RegisterHandlers(App.TacticalControlWindow_GetTacticalControlWindow())
```

Per-frame poll (in the frame loop):

```python
for button, wc in ((MOUSE_BUTTON_LEFT,  WC_LBUTTON),
                   (MOUSE_BUTTON_RIGHT, WC_RBUTTON),
                   (MOUSE_BUTTON_MIDDLE, WC_MBUTTON)):
    if _h.mouse_button_pressed(button):
        App.g_kInputManager.OnKeyDown(wc)
    if _h.mouse_button_released(button):
        App.g_kInputManager.OnKeyUp(wc)
```

### SFX trigger

Each `Fire()` calls `TGSoundManager.instance().PlaySound(prop.GetFireSound())`. Galaxy phasers have `SetFireSound("Galaxy Phaser")` ([galaxy.py:208](sdk/Build/scripts/ships/Hardpoints/galaxy.py#L208)); torpedoes typically rely on a default sound or have one set per-tube. If `GetFireSound()` returns `None` or empty string, no sound plays — silent fail matches BC behaviour for missing sound resources.

Sound resource names mirror BC's audio asset table. The existing `TGSoundManager` shim already supports `PlaySound(name)` for registered names; PR 2a relies on the names being registered at audio init. If a hardpoint references an unregistered sound, the call is a no-op — flag it for PR 2b polish, don't block PR 2a.

## Testing

### Unit tests

| File | Coverage |
|---|---|
| `tests/unit/test_powered_subsystem_on_off.py` | `TurnOn`/`TurnOff`/`IsOn` round-trip; `Set/GetPowerPercentageWanted`; default state. |
| `tests/unit/test_ship_alert_powers_weapons.py` | `SetAlertLevel(RED)` flips phaser/torpedo/pulse groups on; `GREEN`/`YELLOW` flips off. Tractor stays untouched. |
| `tests/unit/test_weapon_system_sequential_firing.py` | Cursor advances on each `StartFiring`. Returns to 0 after wrap. Skips off-emitters. No-eligible-emitter case is a silent no-op. |
| `tests/unit/test_energy_weapon_gating.py` | `Fire` no-ops when group off OR charge < `MinFiringCharge`. Accepts `target=None`. Sets `_firing=True` on success. SFX trigger called with property's `GetFireSound()`. |
| `tests/unit/test_energy_weapon_update_charge.py` | Charge fills at `_recharge_rate` per second when on + not firing. Drains at `_normal_discharge_rate` per second when firing. Auto-stops at zero. No movement when off. |
| `tests/unit/test_torpedo_tube_fire.py` | `Fire` no-ops at `_num_ready == 0`. Decrements on accept. Sets `_last_fire_time`. Discrete-shot (auto-stops after launch). |
| `tests/unit/test_torpedo_tube_reload.py` | `UpdateReload(dt)` increments `_num_ready` after `_reload_delay` elapses. Caps at `_max_ready`. |
| `tests/unit/test_tg_input_manager.py` | `RegisterUnicodeKey` table population. `OnKeyDown`/`OnKeyUp` post `TGKeyboardEvent` for registered keys; no-op for unregistered. |
| `tests/unit/test_keyboard_binding.py` | `BindKey` registers a mapping. `OnKeyboardEvent` resolves the binding, builds the event, dispatches via `g_kEventManager`. Unbound key state is a no-op. |

### Integration tests

| File | Coverage |
|---|---|
| `tests/integration/test_fire_secondary_chain.py` | Full chain: build a Galaxy ship at RED alert, post `OnKeyDown(WC_RBUTTON)` via `g_kInputManager`, assert: (a) `TGKeyboardEvent` flowed; (b) `KeyboardBinding` resolved it; (c) `ET_INPUT_FIRE_SECONDARY` was dispatched to TCW; (d) `FireSecondaryWeapons` handler ran; (e) one of the 6 torpedo tubes flipped `_firing=True` and decremented `_num_ready` by 1; (f) `TGSoundManager.PlaySound` was called with the tube's fire-sound name. Then `OnKeyUp` and assert nothing changes (torps are discrete). |
| `tests/integration/test_fire_primary_continuous.py` | Same Galaxy + RED, post `OnKeyDown(WC_LBUTTON)`, run the tick loop for N frames, assert the active phaser bank's `_charge_level` is draining. Then `OnKeyUp` and assert `_firing=False`. |
| `tests/integration/test_fire_gated_by_alert.py` | Same Galaxy at GREEN alert, post `OnKeyDown(WC_RBUTTON)`, assert nothing flipped — `_firing` stays False, `_num_ready` unchanged, `TGSoundManager.PlaySound` not called. |
| `tests/integration/test_sequential_firing_galaxy.py` | RED alert, post 6 right-clicks (KEYDOWN+KEYUP each), assert each one flipped a different tube's `_num_ready`. Then post a 7th — assert it cycles to tube 0 (which is still empty) and either no-ops or picks the first reloaded tube. |

### Manual verification

After this PR lands, the user should be able to:
1. Launch the game (`./build/open_stbc`).
2. Load a mission.
3. Shift+3 → RED alert.
4. Right-click → audible torpedo whoosh; debug panel "Weapons" row briefly shows "FIRE"; tube count visibly decrements.
5. Left-click+hold → audible phaser sound; charge bar in debug panel drains.
6. Release → phaser stops.
7. Shift+1 → GREEN alert; right-click → silence.

## Open questions

1. **Time source for `UpdateReload`.** Spec uses `time.monotonic()`. If the engine has a game-time clock that respects pause / time-scale (per CLAUDE.md "Game time scales 0.204"), swap to that — note for the implementer to verify and pick.
2. **Sound registration coverage.** Galaxy phasers reference `"Galaxy Phaser"`; verify it's in the registered sound table at audio init. If not, PR 2a should register at least the common phaser/torpedo sounds so the SFX trigger isn't silent.
3. **All-ship tick performance.** Walking every ship × every group × every emitter every frame — for a 30-ship mission with Galaxy-class loadouts, that's ~30 × 4 × 5 emitters = 600 method calls per frame. Should be fine, but flag if profiling shows hot.
4. **Sequential cursor persistence across spawns.** `_next_emitter_index = 0` on construction. Save/load round-trip preserves it (per the existing pickling pattern on `WeaponSystem`).

## Implementation order

1. Power state on `PoweredSubsystem` + `ShipClass.SetAlertLevel` policy. Lands with `test_powered_subsystem_on_off.py`, `test_ship_alert_powers_weapons.py`.
2. Per-emitter `Fire`/`StopFiring`/`CanFire` + `UpdateCharge`/`UpdateReload` + sequential cursor on `WeaponSystem`. Lands with `test_weapon_system_sequential_firing.py`, `test_energy_weapon_gating.py`, `test_energy_weapon_update_charge.py`, `test_torpedo_tube_fire.py`, `test_torpedo_tube_reload.py`. Promotes `GetFireSound` to a typed accessor on `EnergyWeaponProperty`.
3. `TGKeyboardEvent` + `TGInputManager` + `KeyboardBinding` + `TacticalControlWindow` placeholder. Lands with `test_tg_input_manager.py`, `test_keyboard_binding.py`.
4. Host mouse-button binding (`mouse_button_pressed` / `mouse_button_released` + GLFW constants).
5. Host_loop bootstrap (TCW singleton + DefaultKeyboardBinding + TacticalInterfaceHandlers.RegisterHandlers + per-frame mouse poll + per-frame `_advance_weapons` tick). Lands with integration tests.
6. Manual verification in the running game.

Each step independently testable.
