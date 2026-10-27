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

## ✅ Fixed 2026-08-21: skipping left the officers stuck standing

Skipping while Picard/Saffi were on their feet left them standing forever. BC's
skip path does **not** walk anyone back to a chair — `UndockCutscene(TRUE)`
appends `PutEveryoneInSeats` (`E1M1.py:2569`), which hard-teleports them:

```python
g_pSaffi.SetLocation("DBCommander")
g_pPicard.SetLocation("DBGuest")
```

`CharacterClass.SetLocation` (`engine/appc/characters.py:978`) is a pure data
write, and station placement reached the renderer exactly **once** per bridge
load (`host_loop._realize_character_instance`, guarded by `_render_instance`).
The only other runtime re-pose was the `AT_MOVE` walk controller. So the SDK
considered them seated and the renderer never heard about it. Verified
headlessly: `PutEveryoneInSeats` itself runs clean and the locations *do* change
(`DBL1M` → `DBCommander`/`DBGuest`) — nothing turned that into a pose.

Fixed with `host_loop._sync_bridge_character_station`, a per-frame pull sync
alongside `_sync_bridge_character_visibility`: a realized bridge character whose
`GetLocation()` differs from the `_placed_location` tag is re-captured through
`capture_placement` and snapped onto that station's placement clip
(`_restation_character` → `load_instance_clip` + `set_instance_rest_pose`), then
re-breathed at the destination. It runs **before** the visibility sync, because
a teleport into the turbolift (`SetLocation("DBL1M")`) hides via `SetPosition`'s
`SetHidden(1)` and must take effect on the same frame.

`_placed_location` is written by every path that poses a character — the realize
path and `BridgeCharacterWalkController._settle` — so a just-settled walk (which
holds its *own* clip's last frame, not the placement clip) is never re-snapped.
That claim in `_settle` is load-bearing and pinned by
`tests/unit/test_bridge_character_walk.py::test_settle_claims_the_destination_station`.

This was never E1M1-specific: ~30 SDK sites re-station by bare `SetLocation`
(`E7M1:2616`, `E4M4:953/1513`, `E3M2:1060`, `Ep2Cutscene:47`, …), mostly cutscene
teleports into and out of the turbolift. All of them were inert; all are now live.

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

### Modifier-code labels — CLOSED 2026-08-16

`GetDisplayStringFromUnicode` used to look up only the bare-int key, so a code
registered *exclusively* under a `(wc_code, modifier)` tuple (`WC_CAPS_S`,
`WC_ALT_F`, …) returned `""` instead of its label. Task 3 deferred this as
"unreachable by any live call site"; that stopped being true the moment
`OnChordDown` → `_emit` → `_dispatch_raw_keyboard` began handing chord codes to
SDK handlers, which read them back with `pEvent.GetUnicode()`.

**Fixed** — the lookup now falls back to the tuple entry, so `WC_CAPS_S`
resolves to BC's `"S"`. That is half of the Shift+S fix below; the label is
what makes the comparison against `"s"` fail for the right reason.

⚠️ The fallback breaks on the **first** matching tuple, and `WC_ALT_S` is
registered twice under different modifiers (`KeyConfig.py:319` `KY_ALT`,
`:568` `KY_ALTGR`). All 111 multi-registered `WC_*` codes in the real table
were enumerated and every duplicate pair agrees on its label, so the pick is
correct today — **by data coincidence, not by construction.** An SDK-table
change introducing a genuinely ambiguous pair would silently take the first
registration with no signal.

### Shift+key must not re-emit the bare code

BC registers the shifted variant of every letter as a separate WC code with its
own label (`UKConfig.py:70` `WC_S` → `"s"`; `:196` `WC_CAPS_S` → `"S"`, under
`KY_SHIFT`). `_poll_raw_keyboard` therefore suppresses on **Shift** as well as
ALT/CTRL — the chord poller owns shifted presses and emits `WC_CAPS_*`. Without
that, Shift+S emitted the bare `WC_S`, whose label `"s"` matched the skip key.

Note the docstring's "the chord poller already owns shifted presses" is only
true for the A–Z / 0–9 / F1–F12 subset `MODIFIER_CHORDS` is built from.
`_raw_key_pairs` also carries bare punctuation (`WC_OPEN_BRACKET`, `WC_MINUS`,
…) which has no owning chord, so BC's shifted-punctuation labels (`"{"`, `":"`)
can never be produced here. Not a new hole — ALT/CTRL already suppressed that
same set — but shifted punctuation is now silent rather than wrong.

### ⚠️ `TGSequence.Stop()`'s dispatch is inverted — a real latent bug

Found while fixing the skip's dialogue bleed; **deliberately not fixed**, because
the task that found it was scoped to `Abort()`.

```python
# engine/appc/actions.py — TGSequence.Stop()
if hasattr(action, "Stop") and not isinstance(action, TGSequence):
    action.Stop()
else:
    action.Abort()
```

`TGSequence` is the **only** class in the tree with a real `Stop()`, and it is
explicitly excluded. Every other class relies on `TGObject.__getattr__`, which
vends a truthy `_Stub` for undefined attributes — so `hasattr(action, "Stop")`
is `True` for a leaf child and the call lands on a stub no-op. Verified:

```
hasattr(ca, 'Stop')        = True
ca.Stop resolves to        = <engine.core.ids._Stub object>
ids.implements(ca, 'Stop') = False
CharacterAction.Abort invocations during a real TGSequence.Stop(): 0
```

Consequence: **`Stop()` never stops a playing `TGSoundAction`'s audio.** Only
nested sequences ever reach the `Abort()` branch. The fix is
`ids.implements(action, "Stop")` — never `hasattr` for engine surface.

⚠️ `tests/unit/test_actions.py::test_stop_never_reaches_character_action_abort`
currently **pins this bug as though it were desired behaviour**. Its docstring
explains the situation, but the test *name* asserts the defect is correct. When
`Stop()` is fixed that test must be **rewritten, not repaired**.

### ⚠️ Speech-bus ownership is inferred, not owned

`CharacterAction.Abort()` gates its audio cut on `self._playing and
self._speaking` so an action that does not own the single-channel speech bus
cannot cut it — the case that motivated it is `AT_SAY_LINE_AFTER_TURN` still
*turning*, which has not spoken yet (`ai.py` — `_speak` is the turn's
`on_complete`) yet would otherwise silence whoever is actually speaking.

Both flags are load-bearing. `_speaking` is not cleared on natural completion,
so a finished action carries it `True` forever, and `TGActionManager.KillActions()`
aborts long-finished registrations by design (`RegisterAction` appends and never
prunes; the SDK registers bare `CharacterAction`s directly —
`MissionLib.py:3972, 3976, 4015`). `_playing` is the only thing stopping a
stale action from cutting a live line.

**Known limitation, reproduced not theorised:** a line that finished speaking
and was then preempted by *another* line before anyone aborted the stale first
one is not covered — `_speaking` is stale and `_playing` is still true. It needs
two colliding speech sources plus a skip, and it is a strict subset of the
pre-fix behaviour (which cut unconditionally), so it is not a regression.

**Recommended follow-up:** replace both flags with a bus ownership token —
capture a monotonic line id in `_do_play`, gate on
`bus().current_token() == self._token`. That subsumes `_playing` and
`_speaking` and closes the limitation above in one mechanism.

### Minor, recorded so they are not rediscovered

- `engine/host_loop.py` — the comment on the `reset_sdk_globals()` dev-flag call
  names `MissionController._drain_pending_swap` / `MissionController.load_quickbattle`.
  **There is no `MissionController` class.** The real owners are
  `HostController._drain_pending_swap` and `_MissionLoader.load_quickbattle`
  (`_init_mission` is correct). Comment-only.
- The raw dispatch ignores the `AllowKeyboardInput(0)` lockout that
  `_OnKeyboardEvent_Dispatch` honours. This is **required** for this feature —
  E1M1's intro runs with control removed — but it now applies to every key and
  every `ET_KEYBOARD` handler rather than to four small tables.
- Aborting a mid-turn `AT_SAY_LINE_AFTER_TURN` leaves the officer swivelled with
  no turn-back (`Skip()` turns back; `Abort()` does not). Matches pre-fix
  behaviour, but the skip makes it easy to trigger.
