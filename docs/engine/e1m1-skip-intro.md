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

## Engine surface this needs

| Surface | Where |
|---|---|
| `TGKeyboardEvent.GetUnicode` / `SetUnicode` | `engine/appc/events.py` |
| `App.ET_KEYBOARD` (real int, `0x1001`) | `engine/appc/events.py`, re-exported by `App.py` |
| Raw `ET_KEYBOARD` dispatch down the window chain | `engine/appc/input.py` — `_raw_keyboard_destination`, `TGInputManager._dispatch_raw_keyboard` |
| `TGInputManager.GetDisplayStringFromUnicode` | `engine/appc/input.py` |
| `TGActionManager_KillActions` (name → **list** registry) | `engine/appc/actions.py` |

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
