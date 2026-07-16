# WC_* Modifier-Chord Keyboard Families — Design

**Date:** 2026-07-16
**Status:** Approved (brainstormed with Mark; approach A + dev-gated debug chords)

## Problem

The stub heatmap's #1 numeric-coercion entry is `engine/appc/input.py:123` (7,820 hits,
46/47 runs) with `:179` close behind (1,472). Root cause: ~120 `App.WC_ALT_*`, `WC_CTRL_*`,
and `WC_CAPS_*` constants are undefined, so each resolves to a `_NamedStub` whose `int()` is
0. Every modifier binding then registers under dead slot `(0, key_state)`, last-write-wins —
the known WC-collapse bug class (`project_keyboard_wc_constants_collapse`).

**Dead features today:**

| Chord | SDK binding | Feature |
|---|---|---|
| ALT+1–8 | `ET_MANAGE_POWER` (int 0–7, KS_NORMAL) | Power-management presets |
| CTRL+1–4 | `ET_MANEUVER` (int 1–4, KS_NORMAL) | Evasive/attack maneuvers |
| CTRL+D | `ET_INPUT_SELF_DESTRUCT` | Self-destruct |
| CTRL+T | `ET_INPUT_CLEAR_TARGET` | Clear target |
| CTRL+I | `ET_INPUT_INTERCEPT` | Intercept order |
| Shift+K/R/G | `ET_INPUT_DEBUG_{KILL_TARGET,QUICK_REPAIR,GOD_MODE}` | Debug cheats |
| CTRL+Q | `ET_INPUT_DEBUG_LOAD_QUANTUMS` | Debug quantum reload |
| ALT+T / ALT+C | `ET_OTHER_{BEAM,CLOAK}_TOGGLE_CLICKED` | Tractor / cloak toggle — work today only via bespoke bypass pollers (`host_loop.py:330,362`) outside the WC pipeline |

Binding sources: `sdk/Build/scripts/DefaultKeyboardBinding.py:42-43,150-173`. Registration:
`sdk/Build/scripts/KeyConfig.py:178-295` (plus the localized Default{UK,German,French,
Italian,Spanish}KeyboardBinding/Config twins).

## Key evidence

- `KeyConfig.MapScancodes` registers `WC_CAPS_A..Z` with `modifier=KY_SHIFT` — the SDK's own
  statement that **CAPS_x = the capital character (Shift+x), not CapsLock state**.
- The ALT-number / CTRL-number chords bind under **`KS_NORMAL`** (character-input state,
  `engine/appc/events.py:117`), not `KS_KEYDOWN`. Binding lookup is keyed
  `(wc_code, key_state)`, so a poller that only emits KEYDOWN/KEYUP never matches them.
- Downstream handlers already exist: `EngineerMenuHandlers.py:145` (ManagePower on TopWindow),
  `TacticalMenuHandlers.py:397` (Maneuver on the tactical ST menu). Our root `App.py` defines
  `ET_MANAGE_POWER`/`ET_MANEUVER` (1067/1068); **`ET_INPUT_SELF_DESTRUCT` is missing**.
- `engine/appc/input.py:29-32` deliberately left the modifier families as stubs "until a
  consumer lands"; base codes span ≤ 0x1FF (VK ≤ 0xFE + synth band 0x100–0x117).

## Design

### 1. Constant table (`engine/appc/input.py`)

Modifier bands OR'd onto the base code — collision-free by construction since base codes
stay below 0x200:

```
WC_ALT_<X>  = 0x200 | WC_<X>
WC_CTRL_<X> = 0x400 | WC_<X>
WC_CAPS_<X> = 0x800 | WC_<X>     # semantics: Shift+X (per KeyConfig KY_SHIFT registration)
```

One loop per family over letters A–Z, digits 0–9, and F1–F12 — covers every name KeyConfig
and the localized layouts reference. `_def_key` already mirrors each WC_ name to KY_, and
App.py's module `__getattr__` WC_/KY_ fallback surfaces them. Update the `input.py:29-32`
"intentionally absent" comment to describe the bands.

### 2. Generic modifier-chord poller (`engine/host_loop.py`)

New `_poll_modifier_chords()` alongside `_poll_key_table`:

- Lazily build a table of `(modifier, glfw_base_key, wc_chord_code)` from the same
  letters/digits/F-keys enumeration (base-name → GLFW via `host.keys.KEY_*`).
- Modifier held-state: ALT = LEFT_ALT|RIGHT_ALT, CTRL = LEFT_CONTROL|RIGHT_CONTROL,
  CAPS = LEFT_SHIFT|RIGHT_SHIFT — same `host_io.key_state` reads as the existing chord
  pollers.
- Edge-detect at the **chord** level (modifier AND base): rising → `OnKeyDown(wc)`, falling
  → `OnKeyUp(wc)`. Skip the scan entirely when no modifier is held; emit only for chord
  codes that appear in the binding/registration tables (cheap dict probes).
- **KS_NORMAL:** on chord press emit BOTH a `KS_KEYDOWN` and a `KS_NORMAL` keyboard event.
  BC's input manager produces a character event alongside keydown; the SDK binds each chord
  under exactly one state, so exactly one binding fires. Verify the faithful rule against
  the decomp repo (`../STBC-Reverse-Engineering-1/docs/`) during implementation and adjust
  if it disagrees.
- **Base-key suppression:** while ALT or CTRL is held, the plain-key pollers
  (`_poll_key_table` users: fire keys, crew-talk keys, …) must not also emit the base WC
  code — Alt+F must not fire phasers. Gate `_poll_key_table` emission on "no ALT/CTRL held".
  Shift is NOT a suppressor for KEYDOWN-bound base keys (raw VK semantics); verify against
  the decomp, with the suppression rule as fallback.

### 3. Dev-gating the debug chords

The poller drops emission for `{WC_CAPS_K, WC_CAPS_R, WC_CAPS_G, WC_CTRL_Q}` unless
`engine.dev_mode.is_enabled()`. Constants and bindings still wire normally, so production
input is otherwise SDK-identical and telemetry stays clean.

### 4. Retire the bypass pollers

Delete `_poll_tractor_toggle` / `_poll_cloak_toggle`; `WC_ALT_T`/`WC_ALT_C` now flow
poller → binding → `ET_OTHER_BEAM_TOGGLE_CLICKED` / `ET_OTHER_CLOAK_TOGGLE_CLICKED`.
Verify the event route lands on the same toggles the bypass called directly
(`App.ToggleTractorFromInput` / `ToggleCloakFromInput`); today's live-verified toggle
behaviour must not regress.

### 5. Event plumbing gaps

- Add `ET_INPUT_SELF_DESTRUCT` to root `App.py`; sweep DefaultKeyboardBinding's chord rows
  for any other still-stubbed `ET_*` target.
- Verify dispatch end-to-end: `KeyboardBinding.OnKeyboardEvent` sets destination =
  TacticalControlWindow; ET_MANAGE_POWER's handler registers on TopWindow via
  `AddPythonFuncHandlerForInstance`, ET_MANEUVER's on the tactical ST menu. The TCW is
  recreated on every mission swap — confirm handlers re-register. If instance dispatch
  doesn't deliver, extending it is **in scope**: done means "ALT+1 visibly changes the
  power preset", not "event posted".

## Non-goals

- Controls-remap UI integration for chords (chords stay fixed and SDK-faithful; `input_map`
  keeps feeding base keys only).
- CapsLock lock-state handling (CAPS_ = Shift per SDK evidence).
- Other heatmap gaps (LoadDatabaseSoundInGroup, GetSceneNodeId, bridge damage FX,
  correctness batch) — tracked separately in the triage notes.

## Files to touch

- `engine/appc/input.py` — constant families + comment update.
- `engine/host_loop.py` — `_poll_modifier_chords`, base-suppression gate, bypass-poller
  removal, sim-block call site.
- `App.py` (root shim) — missing chord-target ET_* constants.
- `docs/stub_heatmap.md` — mark WC_* rows resolved once live-verified.

## Verification

- **pytest:** constant distinctness (bands never collide with base or each other); coverage
  (parse KeyConfig/DefaultKeyboardBinding, assert every referenced WC_ name is defined);
  BindKey lands distinct slots (no `(0, ·)` collapse); chord edge-detection with patched
  `host_io`; dev-gating on/off; base suppression while ALT/CTRL held.
- **Gate:** `scripts/check_tests.sh` (pytest + ctest, ledger-checked).
- **Live (Mark must see it run):** ALT+1–8 cycles power presets, CTRL+1–4 maneuvers, CTRL+T
  clears target, CTRL+I intercepts, Alt+T/Alt+C still toggle tractor/cloak, Shift+G god mode
  works only under `--developer`. Then a telemetry run confirming the WC_* rows and
  `input.py:123/179` vanish from the heatmap.
