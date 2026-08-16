# E1M1 "Press 's' to skip introduction"

BC's opening-cutscene skip. Entirely SDK-driven — `E1M1.CrewIntros` (line 1950)
builds a `TGCreditAction` banner over the subtitle window and registers
`E1M1.SkipOpeningSequence` on `g_kRootWindow` for `App.ET_KEYBOARD`; pressing
the key kills the `"CharacterIntros"` sequences and calls
`UndockCutscene(TRUE)`.

Strings come from `data/TGL/Maelstrom/Episode 1/E1M1.TGL`:
`SkipKey` = `s`, `CutsceneTextBar` = `Press 's' to skip introduction`.
The key label is resolved via `TGInputManager.GetDisplayStringFromUnicode`,
which reads the name registered by `KeyConfig.MapScancodes()`
(`UKConfig.py:70` registers `WC_S` as `"s"`).

**Status: not finished.** The chain below is wired end to end and covered by
tests, but two things gate it in a real playthrough — the prompt is still
**dev-only** (see the PlayedTutorial section) and the raw keyboard delivery has
real known divergences from BC (see **Still open**). Do not read the sections
below as "done".

## Engine surface this needs

| Surface | Where |
|---|---|
| `TGKeyboardEvent.GetUnicode` / `SetUnicode` | `engine/appc/events.py` |
| `App.ET_KEYBOARD` (**measured** `0x30002`, not invented — `tools/probes/results/q13_constants_battle.txt:459`, `tools/probes/results/ghidra_export/stbc_constants.csv:449`) | `engine/appc/events.py`, re-exported by `App.py` |
| Raw `ET_KEYBOARD` dispatch down the window chain | `engine/appc/input.py` — `_raw_keyboard_destination`, `TGInputManager._dispatch_raw_keyboard` |
| **Host forwarding of the general key stream** | `engine/host_loop.py` — `_poll_raw_keyboard` (+ `TGInputManager.OnRawKeyDown/Up`) |
| `TGInputManager.GetDisplayStringFromUnicode` | `engine/appc/input.py` |
| `TGActionManager_KillActions` (name → **list** registry) | `engine/appc/actions.py` |

## How a keystroke gets from the host to the SDK handler

Before `_poll_raw_keyboard` existed, the **only** keys the host forwarded into
`App.g_kInputManager` were mouse buttons, the crew-talk F-keys, the fire keys
and the ALT/CTRL/CAPS chords. `WC_S` was in none of them, so `_emit` never fired
for `s` and the whole chain above was dead in the actual game — pressing `s`
during the intro just pitched the ship. (A unit test entering at `OnKeyDown`
passes regardless; that is one layer *below* the gap.)

`_poll_raw_keyboard` derives its `(glfw_key, WC_code)` table from whatever the
native `keys` submodule exports that BC's `WC_*` table also names, so the next
SDK script hooking `App.ET_KEYBOARD` needs no new special case. It excludes the
GLFW codes the fire / crew-talk pollers own (they already raw-dispatch through
`_emit`, and they share the `_fn_key_prev` edge cache), and honours the same
ALT/CTRL suppress discipline.

### It forwards the RAW half only — deliberately

BC produces **both** consumers from one keypress: the binding layer turns `WC_S`
into `ET_INPUT_TURN_DOWN` (`DefaultKeyboardBinding.py:84`) *and* the raw
`ET_KEYBOARD` window event runs alongside it. We forward only the raw half
(`OnRawKeyDown`/`OnRawKeyUp` → `_emit_raw`), because dauntless drives flight,
camera and throttle host-side off `host_io.key_state`
(`engine/input_map.py`: `S` → `pitch_up`), not off the SDK binding table.
`TacticalInterfaceHandlers.Initialize` registers `TurnDown` for
`ET_INPUT_TURN_DOWN` on the TCW (`TacticalInterfaceHandlers.py:72`, re-run on
every mission load from `reset_sdk_globals`), and its `TurnShip` calls
`MissionLib.SetPlayerAI("Captain", None)` → `pPlayer.ClearAI()` before setting
an angular velocity. Emitting the binding half too would therefore clear the
player's AI mid-cutscene and add a second, fighting rotation driver.

**Revisit this if flight control ever moves onto the SDK binding path** — at
that point the raw-only restriction becomes wrong and both halves should flow.
Guarded by `tests/unit/test_raw_keyboard_poll.py::test_raw_forwarding_does_not_drive_the_sdk_turn_handlers`,
which fails the moment the poller is switched to the full `_emit` path.

## ⚠️ Open follow-up: PlayedTutorial persistence

`E1M1.CrewIntros:1954` gates the whole feature on
`g_kVarManager.GetFloatVariable("global", "PlayedTutorial") == 1.0`. BC sets it
in `E1M1.SaveTheGame:2659` — *"sets the config flag that will allow them to skip
the next time through"* — so the prompt is **replay-only**.

Our `TGVarManager` is in-memory. It round-trips through savegames
(`engine/appc/save_load.py:181`) but starts empty on every launch, so a
cold-launched E1M1 never shows the prompt.

**Current stopgap:** `engine/dev_tutorial_flag.py` forces the flag to 1.0 under
`--developer`, applied from the end of `host_loop.reset_sdk_globals()`.

**When persistent-save support lands, revisit this:** persist the `"global"`
VarManager scope across launches and delete the dev force (or keep it purely as
a testing shortcut). Until then the feature is dev-only, and a production
playthrough will not show the prompt on a replay the way BC does.

## Still open

**`KeyboardBinding.FindKey`** (heatmap rank 56, same 342 hits as
`GetDisplayStringFromUnicode`) is still a stub — checked 2026-08-16:

```
$ uv run python -c "
import sys; sys.path.insert(0,'build/python')
import App
print(type(App.g_kKeyboardBinding.FindKey).__name__)
"
_Stub
```

It is the same class of gap as `GetDisplayStringFromUnicode` and blocks the
*generic* Backspace skip in `CinematicInterfaceHandlers`, but it is **out of
scope** for this plan — E1M1's skip prompt does not call it. Left unannotated
in `docs/stub_heatmap.md`.

### `SetHandled()` veto ordering is inverted

`engine/appc/input.py` posts the internal `ET_KEYBOARD_EVENT` — which
`KeyboardBinding` turns into `ET_INPUT_*` — **before** the raw `ET_KEYBOARD`
dispatch. BC's order is the reverse. `BridgeUtils.ModalKeyboardHandler`
(`sdk/Build/scripts/Bridge/BridgeUtils.py:847+`) and
`E3M1.FilteredKeyboardHandler` (`E3M1.py:1301+`) exist *solely* to call
`SetHandled()` so a key never becomes an `ET_INPUT_*` action, which requires
the window chain to run first. `SetHandled` is itself unimplemented (resolves
to `_Stub`).

Currently harmless: those handlers' comparisons against the still-stubbed
`KeyboardBinding.FindKey` all evaluate False. But this branch makes them **run
on every keystroke while structurally unable to honour their only effect**.

### Raw dispatch reaches exactly one object, and it is our choice

`_raw_keyboard_destination` delivers to **one** object, trying the root window
before the TopWindow. That ordering is a dauntless decision, not established
fidelity — the modal evidence above points the other way (BC bubbles up the
chain and lets an earlier handler veto). Handlers SDK scripts register on panes,
buttons and movie panes (`E1M2.py:4243-4247/5199`, `E8M2.py:6495`, MainMenu,
Multiplayer) are **unreachable entirely**.

### Mouse clicks emit raw keyboard events

`KeyConfig.py:646-648` registers `WC_LBUTTON` / `WC_MBUTTON` / `WC_RBUTTON` as
unicode keys, so `_poll_mouse_buttons` → `_emit` delivers an `ET_KEYBOARD` on
every click. BC sends `ET_MOUSE`. It fails safe (the click's display label is
not `"s"`), but it does mean `SkipOpeningSequence` *runs* on every mouse click
during the intro.

### Chords double-fire

`OnChordDown` calls `_emit` twice (`KS_KEYDOWN` then `KS_NORMAL`) because the
SDK binds each chord under exactly one of those states. A raw handler that does
not inspect `GetKeyState()` — and `SkipOpeningSequence` does not — therefore
runs **twice** per chord press.

### Modifier-code labels are now a reachable path

`GetDisplayStringFromUnicode` looks up only the bare-int key, so a code
registered *exclusively* under a `(wc_code, modifier)` tuple (`WC_CAPS_S`,
`WC_ALT_F`, …) returns `""` instead of its label. Task 3 deferred this as
"unreachable by any live call site". **That is no longer true**: `OnChordDown`
→ `_emit` → `_dispatch_raw_keyboard` hands chord codes to SDK handlers, which
read them back with `pEvent.GetUnicode()`. It still fails safe — an empty label
never spuriously matches a skip key — but the path is live.
