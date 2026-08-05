# Developer Toggles: Force Damaged / Disabled Light States (design)

**Date:** 2026-08-05
**Status:** approved (Mark), spec for review
**Area:** Developer Options panel + the subsystem glow-state classifier.

## Goal

Two developer-only toggles that force every subsystem's **visual** glow state so
the author can preview the emitter light behaviour without taking damage in
combat:

- **Set Systems Damaged** → lights **flicker** (glow state DISABLED).
- **Set Systems Disabled** → lights **off / dead** (glow state DESTROYED).

Mutually exclusive; toggling either off (or the other on) returns to the real
per-subsystem state. Dev-mode only; production byte-identical.

## Why hooking `glow_state` is the whole feature

`engine/appc/subsystem_glow.py:glow_state(sub)` is the single point that maps a
subsystem to `HEALTHY` / `DISABLED` / `DESTROYED`. It is **purely visual** — the
only readers are `light_emitters.resolve_emitter_intensity` (DISABLED→flicker,
DESTROYED→off) and the `ShipGlowController` glow volumes. **No gameplay reads
it.** So a forced override there is a pure visual preview: it does *not* disable
any real system (combat/AI/collision untouched), and it drives **both** the cast
lights and the emissive glow volumes together — the real flicker / blow-out
animations, coherently.

## Design — mirrors the `dev_combat_cheats` seam exactly

### `engine/dev_light_preview.py` (new)

A tiny flag module, same shape as `dev_combat_cheats.py` (imports only
`dev_mode`; the seam neither side of which imports the other's consumer):

```python
from engine import dev_mode
from engine.appc import subsystem_glow   # for the DISABLED/DESTROYED constants

# None | subsystem_glow.DISABLED | subsystem_glow.DESTROYED
_forced_state = None

def set_systems_damaged(on: bool) -> None:
    """Damaged = flicker = glow DISABLED. Mutually exclusive with 'disabled'."""
    global _forced_state
    _forced_state = subsystem_glow.DISABLED if on else None

def set_systems_disabled(on: bool) -> None:
    """Disabled = off/dead = glow DESTROYED. Mutually exclusive with 'damaged'."""
    global _forced_state
    _forced_state = subsystem_glow.DESTROYED if on else None

def forced_glow_state():
    """The forced state string, or None when not dev-enabled / not set.
    ANDed with dev_mode so production can never be affected."""
    return _forced_state if dev_mode.is_enabled() else None

def systems_damaged_active() -> bool:
    return forced_glow_state() == subsystem_glow.DISABLED

def systems_disabled_active() -> bool:
    return forced_glow_state() == subsystem_glow.DESTROYED

def reset() -> None:      # tests only
    global _forced_state
    _forced_state = None
```

**Import-cycle note:** `dev_light_preview` imports `subsystem_glow` for the
constants; `subsystem_glow` must therefore NOT import `dev_light_preview` at
module top (that would cycle). `glow_state` does a **lazy import** inside the
function (cheap — `sys.modules` cache; glow_state is already doing per-call
work). Confirm no cycle: `dev_mode` must not import `subsystem_glow`
(it doesn't).

### `subsystem_glow.glow_state` — the two-line hook

```python
def glow_state(sub) -> str:
    from engine import dev_light_preview          # lazy: avoids an import cycle
    forced = dev_light_preview.forced_glow_state()
    if forced is not None:
        return forced                             # dev preview: all subs forced
    if sub is None:
        return HEALTHY
    if sub.IsDestroyed():
        return DESTROYED
    if sub.IsDisabled():
        return DISABLED
    return HEALTHY
```

Production (dev off): `forced_glow_state()` returns `None` → falls straight
through to today's classification → **byte-identical**.

### Developer Options panel — a new "Lighting" tab

`engine/ui/developer_options_panel.py`:
- `_tabs` gains `("lighting", "Lighting")`.
- Local mirrors `_systems_damaged`, `_systems_disabled` synced from
  `dev_light_preview.systems_damaged_active()` / `systems_disabled_active()` in
  `__init__` and `open()`.
- `render_payload` snapshot + `settings` gain `systems_damaged`,
  `systems_disabled`.
- `dispatch_event`: `toggle:systems_damaged` and `toggle:systems_disabled`,
  each `set_*` then re-sync BOTH local mirrors from the active getters (because
  the setters are mutually exclusive — turning one on clears the other, and the
  panel must reflect that).
- `_focusables`: when `_selected_tab == "lighting"`, add
  `("ctrl", "systems_damaged")`, `("ctrl", "systems_disabled")`.

`native/assets/ui-cef/js/developer_options.js`:
- `_doFocusableList`: add the two lighting controls when
  `selected_tab === 'lighting'`.
- New `_doRenderLightingBody(state, focusables)` — two `_doToggleRow`s
  ("Set Systems Damaged" → `systems_damaged`, "Set Systems Disabled" →
  `systems_disabled`).
- `setDeveloperOptions`: render the lighting body when
  `selected_tab === 'lighting'`.

## Non-goals

- No gameplay effect: real IsDisabled/IsDestroyed are never written; this only
  overrides the visual classification.
- Not persisted across launches; not reset on panel close (matches the combat
  cheats). `reset()` is test-only.
- Player-ship-only scoping is NOT done — the forced state is global (all
  subsystems of all ships), per Mark. A wreck's already-destroyed subs stay
  destroyed regardless (DESTROYED already, and forced only overrides upward
  visually).

## Global constraints

- **Dev-mode gated** at the getter (`forced_glow_state()` ANDs `dev_mode.is_enabled()`)
  — defense-in-depth, so production is byte-identical even if a flag were set.
- **Mutually exclusive** via a single `_forced_state` variable.
- CEF is mouse-only for the toggles (keyboard focus nav already exists in the
  panel's `handle_input`, reused).
- No renderer/C++ change; no persistence.
- Gate: `scripts/check_tests.sh`.

## Testing

- **`dev_light_preview`:** damaged/disabled setters are mutually exclusive;
  `forced_glow_state()` returns None when dev disabled (patch `dev_mode`),
  the forced constant when enabled; `reset()` clears.
- **`glow_state`:** with a forced state + dev enabled, returns the forced state
  for any sub (incl. a healthy one and `None`); with dev disabled OR no forced
  state, returns the real classification (healthy/disabled/destroyed) —
  byte-identical to today.
- **Panel:** `toggle:systems_damaged` sets DISABLED and clears disabled;
  `toggle:systems_disabled` sets DESTROYED and clears damaged; both reflected in
  the payload; the Lighting tab appears in `tabs`; focusables include the two
  controls when the lighting tab is selected; production path (dev off) unaffected.
- **JS:** the lighting body/ focusable list include the two toggle keys and
  their dispatch strings (`developer-options/toggle:systems_damaged`,
  `.../toggle:systems_disabled`).
- Full gate green (1 known baseline).
