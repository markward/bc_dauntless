# Mission View, Camera & Input Locks — SDK-Faithful Reimplementation (Pull Model)

**Date:** 2026-07-05
**Status:** Approved design, pending implementation plan
**Supersedes:** the abandoned branch `feat/mission-view-camera-input-locks` (11 commits, live-regressed, never merged)

## Problem

E1M1 and E1M2 call ~30 engine functions that control the player's view (bridge vs
tactical/exterior), the camera, and input locks. On `main` almost all of them are
silent no-ops — either `_LoudStub` fallthroughs or flag writes nothing reads.
The missions run without errors but scripted sequences play wrong: input locks
leak, cutscenes have no letterbox, the camera never turns to the viewscreen,
missions cannot hold the player on the bridge, and `IsBridgeVisible()` lies.

### Audit of no-ops on main (ground truth for scope)

| SDK call | Route | Status on main | E1M1/E1M2 usage |
|---|---|---|---|
| `TopWindow.AllowKeyboardInput(0/1)` | `MissionLib.RemoveControl/ReturnControl` | Flag consumed only by SDK `ET_KEYBOARD` dispatch ([engine/appc/input.py:244](../../../engine/appc/input.py)); every natively-polled input (helm, SPACE, camera keys, F-keys, alert keys, fire, tractor/cloak) bypasses it | 4 lock/unlock pairs in E1M1, 6 in E1M2 |
| `TopWindow.AllowMouseInput(0/1)` | same | Flag stored, consumed nowhere — crew/station/menu clicks all work while "locked" | same call sites |
| `TopWindow.StartCutscene(fTimeToComeIn, fCoveredArea, bHideReticle)` | `MissionLib.StartCutscene` | Sets `_cutscene_active` only; all args discarded; no letterbox, no reticle hide | 5× E1M1, 7× E1M2 |
| `TopWindow.EndCutscene(fTime)` | `MissionLib.EndCutscene` | Clears flag; no fade-out; view-restore half is dead (see Force*) | 7× E1M1, 9× E1M2 |
| `TopWindow.AbortCutscene()` | E1M1.py:956 (early Starbase 12 arrival) | Flag clear only | 1× E1M1 |
| `TopWindow.FadeOut/FadeIn/AbortFade` | mission sequences | Flags only, nothing renders | several |
| `TopWindow.ForceBridgeVisible / ForceTacticalVisible / ToggleBridgeAndTactical` | `MissionLib.EndCutscene`, `Actions.CameraScriptActions.ChangeRenderedSet` | Flags flip but nothing reads them; rendered view owned by `_ViewModeController` ([engine/host_loop.py:1638](../../../engine/host_loop.py)) which never syncs | E1M1 crew-intro DryDock/bridge swaps; every EndCutscene |
| `ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL` handler registration | E1M1.py:858, E1M2.py:1155 | Never fires — SPACE toggles directly in host_loop with no event dispatch; missions cannot hold the player on the bridge | both missions register `TacticalToggleHandler` |
| `TopWindow.IsBridgeVisible()` | mission conditionals (E1M1.py:1198/1667/1679) | Returns the unread flag — lies as soon as the player presses SPACE | E1M1 tactical-view info box + warp suggestion |
| `SetManager.GetRenderedSet()` bridge semantics | `MissionLib.EndCutscene` restore conditional | Never reports the bridge set | every EndCutscene |
| `ZoomCameraObjectClass.LookForward()` | `MissionLib.LookForward`, `MissionLib.ViewscreenOn` | `_LoudStub` no-op ([engine/appc/bridge_set.py:145](../../../engine/appc/bridge_set.py)) | E1M1 Picard walk-on + character select (direct, `bWaitForSweep=1`); ~4 E1M1 + ~9 E1M2 hails (via ViewscreenOn) |
| `STTopLevelMenu_GetOpenMenu` + menu drop | `BridgeHandlers.DropMenusTurnBack` inside `MissionLib.LookForward` | Doesn't exist | every LookForward |
| `TacticalControlWindow.SetVisible/SetNotVisible` | Start/EndCutscene HUD handling | Flag not consumed by CEF tactical HUD | every cutscene |
| `SubtitleWindow.SetPositionForMode(SM_*)` | Start/EndCutscene | No-op — subtitles don't ride above the letterbox bar | every cutscene |
| Reticle hide (`bHideReticle`) | StartCutscene | No gate on the reticle passes | every cutscene |
| Root-window `ET_KEYBOARD` handlers | E1M1 opening-sequence skip key | Host never synthesizes root-window key events | E1M1 |
| `ET_CHARACTER_MENU`-style menu locks | E1M2 `SetCharWindowLock` | No dispatch seam — menus can't be locked | E1M2 tutorial |
| Alert-key interception | E1M2 tutorial | Alert keys apply directly; no event chain to intercept | E1M2 tutorial |

`ViewscreenOn/Off` themselves (`SetRemoteCam`/`SetIsOn`/static) are already real
(comm-set viewscreen work); only their LookForward and menu-drop halves are dead.

## Requirements (user-confirmed ground truth from playing the original)

1. **`LookForward()`** eases the bridge camera to face the viewscreen.
2. **`fCoveredArea=0.125`** is the **total** covered screen area in letterbox
   view — 6.25% per bar, top and bottom.
3. **Input-lock scope:** while `RemoveControl` is active, only the pause menu
   and skip-dialogue input work. Nothing else — no clicking crew or stations,
   **and the camera is frozen too** (no mouse free-look, no keyboard camera
   keys); the view moves only when the script moves it.
4. **EndCutscene restore:** SDK-faithful conditional (tactical when the bridge
   is not the rendered set, bridge otherwise — MissionLib.py:794/801), with
   `GetRenderedSet()` reporting the bridge set while the bridge is visible.
   The user's observed "always returns to bridge" behavior falls out of this
   for E1M1/E1M2.

### Scope decisions

- **In:** view forcing + SPACE-toggle event chain, cutscene overlay
  (letterbox/fade/reticle/TCW/subtitles), keyboard+mouse locks with camera
  freeze, E1M1 root-window skip key, LookForward + menu drop, crew-menu lock
  dispatch (`ET_CHARACTER_MENU`), alert-key dispatch (`ET_SET_ALERT_LEVEL`).
- **Out (deferred to a separate pass; see memory `camera-modes-deferred`):**
  Placement/ZoomTarget/ViewscreenZoomTarget camera modes. Reference
  implementation in `622be12f` on the abandoned branch.

## Why the previous attempt failed, and the architectural answer

The abandoned branch was push-based: TopWindow flag changes pushed through a
listener (wired per mission load) into `_ViewModeController`, which synced
flags back. Five links — SPACE poll → TopWindow event chain → default handler →
view-force listener → controller → flag sync-back — each wired at a different
lifecycle point. A broken link failed silently, only live (headless: 128 green
tests; live: the E1M2 hail sequence drained mid-cutscene, never root-caused).

**This design is pull-based.** SDK calls write state onto SDK objects;
host_loop reads that state every frame. There are no listeners, no
mission-load wiring steps, and no sync-back. One frame of latency at 60 Hz is
invisible.

**Lifecycle rule (applies to every section below):** all new state lives on an
SDK object that `reset_sdk_globals()` already rebuilds, and every default
event handler is registered in that object's **constructor**, so it is reborn
with the object on every mission swap. Nothing exists whose absence fails
silently. The single exception (the root-window key prev-state dict) is
explicitly added to the reset/conftest cleanup lists.

## Design

### 1. View state — TopWindow is the single source of truth

- Remove `_ViewModeController._mode`. Each frame host_loop reads
  `top_window.bridge_flag()` and renders bridge or exterior accordingly.
  `ForceBridgeVisible()` / `ForceTacticalVisible()` are pure flag writes;
  `IsBridgeVisible()` can never disagree with the render.
- **SPACE toggle:** host detects the rising edge (when the input policy allows
  gameplay keys), builds `ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL`, dispatches via
  `TopWindow.ProcessEvent()`. The bottom-of-chain default handler that calls
  `ToggleBridgeAndTactical()` is registered **inside `_TopWindow.__init__`**
  (the branch registered it from `_ViewModeController.__init__`, orphaning it
  on singleton rebuild). Missions swallow by *not* calling
  `TGObject.CallNextHandler(pEvent)` — exactly E1M1.py:1187's shape — and the
  default runs synchronously during dispatch, because E1M1 queries
  `IsBridgeVisible()` immediately after `CallNextHandler` and expects the
  toggle to have already happened.
- **`GetRenderedSet()`** returns the bridge set while the bridge is visible
  (BC semantics). `MissionLib.EndCutscene`'s restore conditional and E1M1's
  `str(pBridgeSet) != str(pRenderedSet)` comparisons then work verbatim.
- **Defaults unified:** bridge visible on boot and after every mission swap.
  (Today TopWindow defaults tactical-visible while the host defaults bridge —
  they have never had to agree before.)
- `Actions.CameraScriptActions.ChangeRenderedSet` (E1M1 DryDock/bridge swaps)
  works with no special casing: `MakeRenderedSet` + `ForceBridgeVisible` are
  both real.

### 2. Input locks — one policy function, computed once per frame

New module `engine/appc/input_policy.py`:

```python
@dataclass(frozen=True)
class InputPolicy:
    gameplay_keys: bool   # helm, camera keys, fire, F-keys, alert keys, SPACE, tractor/cloak, dev keybindings
    mouse_clicks: bool    # world picks, officer/station clicks, CEF click/wheel forwarding
    mouse_look: bool      # bridge free-look and exterior orbit
    pause: bool           # always True
    skip_dialogue: bool   # always True

def compute_input_policy(keyboard_allowed, mouse_allowed, pause_open) -> InputPolicy: ...
```

- Pure function; full truth-table unit test. Keyboard lock ⇒
  `gameplay_keys=False`. Mouse lock ⇒ `mouse_clicks=False` and
  `mouse_look=False` (camera frozen per requirement 3; `RemoveControl` always
  sets both locks together).
- Host computes **one snapshot at the top of each frame's input handling** and
  passes it to every poller. Pollers consult the snapshot; the decision logic
  lives in exactly one place.
- Pause-menu exemption: while the pause menu is open under mouse lock, CEF
  click forwarding is allowed so the pause menu remains operable; world picks
  and officer clicks stay dead.
- The existing SDK-side `ET_KEYBOARD` gate in `engine/appc/input.py:244`
  stays unchanged.
- Mouse-move forwarding to CEF stays live (cursor/hover only — harmless and
  keeps CEF cursor state sane); it must not drive camera look while
  `mouse_look` is False.

### 3. Skip key — root-window keyboard synthesis

- Host synthesizes `ET_KEYBOARD` events into `g_kRootWindow`'s instance
  handler chain on key rising edges, only while at least one `ET_KEYBOARD`
  handler is registered (fast-path skip otherwise).
- **Not gated by the keyboard lock** — E1M1 registers its skip handler during
  `RemoveControl` on purpose; this is the "skip dialogue stays available"
  requirement.
- Minimal key table (ASCII A–Z, Space, Backspace, Escape, Enter), extendable.
- Prev-state dict is module-level; added to `reset_sdk_globals()` and the
  conftest autouse `_reset_leakable_engine_globals` cleanup.
- Adapted from the abandoned branch (this piece was not implicated in the
  regression).

### 4. Cutscene overlay — letterbox, fade, reticle, TCW, subtitles

- TopWindow stores the full overlay state: `_letterbox_covered` (total
  fraction; each bar is half), `_letterbox_transition_s`, `_fade_transition_s`,
  `_hide_reticle`, fade active/direction, and an `_overlay_touched` flag so
  quiescent boots emit nothing.
- `overlay_snapshot()` returns the render-ready dict each frame; the CEF SDK
  mirror panel forwards it; JS renders two black bars + a fullscreen fade div
  with CSS transitions driven by the stored durations. (This is the abandoned
  branch's model — the part that worked; JS/CSS reused.)
- `StartCutscene(fTimeToComeIn, fCoveredArea, bHideReticle)` honors all three
  args. `EndCutscene(fTime)` animates out over `fTime`. `AbortCutscene()`
  clears instantly, no transition (E1M1 early-arrival path).
- Reticle: GL reticle pass and CEF reticle text gate on
  `top_window.reticle_hidden()` (`cutscene_active and hide_reticle`).
- Tactical HUD: `TacticalControlWindow.SetVisible/SetNotVisible` set a flag
  the CEF tactical HUD consults (StartCutscene calls `SetNotVisible(0)`,
  EndCutscene's tactical path calls `SetVisible()` — both must round-trip).
- Subtitles: `SubtitleWindow.SetPositionForMode(SM_CINEMATIC)` raises the
  subtitle strip above the bottom letterbox bar; `SM_END_CINEMATIC` /
  `SM_TACTICAL` / `SM_BRIDGE` restore it.

### 5. LookForward — ease state lives on the camera object

- `ZoomCameraObjectClass.LookForward()` becomes real: records an ease from the
  camera's current orientation to facing the viewscreen (bridge-forward),
  ~1 s smoothstep — matching `MissionLib.LookForward`'s 1-second
  `bWaitForSweep` timer — **stored on the camera object itself**. No
  module-scope request flag; mission swap destroys the object and the ease
  with it.
- The host bridge camera advances and applies the ease each frame; mouse-look
  is suppressed while easing (moot under locks, but LookForward also fires
  outside them via `ViewscreenOn`).
- Menu drop: implement `App.STTopLevelMenu_GetOpenMenu` so
  `BridgeHandlers.DropMenusTurnBack()` works. Menu-resolution failures log a
  warning — never a silent skip.

### 6. Crew-menu locks + alert keys

- `ET_CHARACTER_MENU`: every crew-menu open/close funnel (CEF click, F-keys,
  officer click, ESC-close) dispatches through the owning character's instance
  handler chain with the real open/close as a proceed-callback; the default
  handler is registered in `CharacterClass.__init__`. Missions swallow to lock
  menus (E1M2 `SetCharWindowLock`).
- `ET_SET_ALERT_LEVEL`: alert keys build a `TGIntEvent` (payload `EST_ALERT_*`)
  dispatched through the XO alert menu's chain; default handler (registered in
  `STTopLevelMenu.__init__`) translates and applies `SetAlertLevel`. E1M2's
  tutorial intercepts it.
- Two fixes over the branch: character/menu resolution failures are **logged
  loudly** instead of silently proceeding, and both key pollers consult the
  Section-2 policy snapshot.

### 7. Error handling

- Removing `_LoudStub` coverage: `LookForward`, `GetOpenMenu`, and the TCW
  visibility methods become real; anything this design intentionally leaves
  stubbed (`ToggleMapWindow`) stays a stub and is documented at the stub site.
- Every "couldn't resolve X, proceeding without lock/ease/drop" path logs at
  warning level. Silent degradation is what made these gaps invisible for
  months.

## Testing & delivery — five slices, each live-verified before the next

Each slice: TDD (RED→GREEN→REFACTOR) units + host-level tests, the full
`scripts/check_tests.sh` gate, then a **concrete live-game script** the user
runs. Merge only after the live check passes. A live failure gets
systematic-debugging treatment against that slice alone — never fixed forward
into the next slice.

| # | Slice | Live-game test script |
|---|---|---|
| 1 | View pull-model + SPACE event chain + `GetRenderedSet` bridge semantics | SPACE toggles bridge↔exterior both ways repeatedly. E1M1 tutorial beat: SPACE does nothing (held on bridge). E1M1 crew-intro: DryDock→bridge set swaps render. End any cutscene: view restores per the SDK conditional (bridge in practice). |
| 2 | Input policy + all gates + camera freeze + root-window skip key | During E1M2 debris-scan cutscene: WASD/throttle/fire/tractor/cloak/alert/F-keys dead; clicks on crew and stations dead; mouse free-look frozen; ESC opens pause (fully clickable); skip-dialogue works; E1M1 opening skip key works. After ReturnControl: everything back. |
| 3 | Letterbox + fade + reticle hide + TCW hide + subtitle reposition | E1M1 briefing: bars animate in to 12.5% total coverage, reticle hides, tactical HUD hides, subtitles sit above the bottom bar; bars animate out on EndCutscene. Fly to Starbase 12 early: AbortCutscene snaps bars away instantly. E1M2 later cutscenes (`bHideReticle=FALSE`): reticle stays. |
| 4 | LookForward ease + `GetOpenMenu` menu drop | E1M1 Picard walk-on and character-select: camera sweeps to viewscreen over ~1 s. Every E1M2 Soams/Liu hail: camera turns to viewscreen; if a crew menu is open it drops first. |
| 5 | Crew-menu + alert-key dispatch | E1M2 tutorial: locked officer menus don't open; alert keys are intercepted by the tutorial handler; after the tutorial both behave normally. |

## Non-goals

- Placement/ZoomTarget/ViewscreenZoomTarget camera modes (deferred pass).
- Map window (`ToggleMapWindow` stays a documented stub).
- Any change to production combat/render paths beyond the gates described.
