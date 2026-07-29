# Bridge Tactical Mode — deferred follow-ups

**Date:** 2026-07-29
**Status:** Recorded at merge time. The `feat/bridge-tactical-mode` work merged to `main`
with the core feature working (F2 shows the tactical HUD + Orders/Tactics/Maneuvers,
top-anchored, collapsible popups, working click path, orders drive the AI). The items
below were observed in live passes and deliberately deferred to a later session.

Design spec: `docs/superpowers/specs/2026-07-28-bridge-tactical-mode-f2-hud-design.md`
Plan: `docs/superpowers/plans/2026-07-28-bridge-tactical-mode.md`

---

## 1. (BIGGEST) Maneuvers/Tactics don't enable on attack orders — player weapons unpowered

**Symptom:** with a target selected and Destroy/Disable chosen, the Maneuvers and
Tactics popups stay disabled.

**Root cause (verified, NOT a panel bug):** the event→handler→enable chain works and
`UpdateOrderMenus` *does* enable the Maneuvers/Tactics children. But immediately after,
`UpdateOrders` runs the Destroy/Disable "NeedPower" acknowledgement guard
(`sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:1269-1272` Destroy, `:1288-1291`
Disable):

```python
if (not bTorpsOn and not bPhasersOn):
    g_iOrderState = -1
    UpdateOrders()          # recursive re-run with order = -1 → re-disables M/T
```

`bTorpsOn = pTorps.IsOn()` — and our weapon subsystems default to **unpowered**
(`engine/appc/subsystems.py:1092` `PoweredSubsystem._is_on = False`; comment: "a fresh
ship is unpowered until `SetAlertLevel(RED)` or a mission script turns systems on").
`TorpedoSystem`/`PhaserSystem` inherit this and nothing in `host_loop.py` powers the
bridge-tactical player's weapons, so the guard fires every click and resets the order to
`-1`, which re-disables Maneuvers/Tactics. **This is BC-faithful behavior** — you cannot
order an attack with weapons cold; Felix would say "I need power to weapons."

There is also an original SDK typo at `TacticalMenuHandlers.py:1241`
(`pPhasersOn = pPhasers.IsOn()` instead of `bPhasersOn`), so the guard is torpedo-only.
That lives in the SDK (ground truth) — do not "fix" it.

**Fix direction (needs its own investigation next session):** ensure the player's
weapons are powered when combat-appropriate — the faithful trigger is RED alert
(`SetAlertLevel(App.ALERT_RED)` powering the weapon subsystems so `IsOn()` returns 1).
Open question to answer first: **does our engine's red-alert path already power the
player's weapons?** If yes, this is largely a usage/UX matter (red-alert first) plus
maybe surfacing the "need weapons power" feedback; if no, wire red-alert → weapon power.
Do NOT blanket force-power weapons (that would break red-alert gating in combat).

## 2. Evade (OrderDefense) fatal crash — FIXED before merge

Recorded for context: clicking Evade installed `AI.Player.Defense`, which crashed on the
next tick because `AI/Player/Defense.py:214` passes `"Update()"` (with parens) to
`SetPreprocessingMethod`, and `getattr(inst, "Update()")` in the unguarded per-tick AI
driver (`engine/appc/ai_driver.py:683`) raised `AttributeError`. Fixed by normalizing a
trailing `"()"` at bind time in `engine/appc/ai.py` `PreprocessingAI.SetPreprocessingMethod`
(BC's C++ tolerated the trailing `()`; the SDK data typo is left untouched). See the
commit on this branch.

## 3. UI polish observed in live passes (to enumerate on return)

- **"Lots of issues" flagged by Mark but not yet itemized** — enumerate on return.
- **Overlap:** the top-anchored Orders/Maneuvers/Tactics panes overlap the
  `CharacterTooltipPanel` ("LT. FELIX SAVALI, TACTICAL / Awaiting Orders") which renders
  centered behind them. Needs z-order / positioning reconciliation.
- **Click-bbox height is a fixed estimate** (`_OR_H = 340` in `engine/host_loop.py`) —
  confirm it covers an expanded 7-row Tactics popup and isn't so tall it swallows clicks
  meant for the 3D view. A content-measured height would be more robust than a constant.
- **Layout vs BC exactness:** Orders left / Maneuvers+Tactics top-right now matches BC's
  gross layout; fine-tune spacing/sizing against the reference if desired.

## 4. Deferred minors from the task/final reviews (non-blocking)

- Task 1: no dedicated unit test for the `bridge_tactical_active` call-site computation
  (the expression is exercised elsewhere + live); literal `"Tactical"` duplicated vs
  `engine/ui/crew_menu_hotkeys.py:39,50`.
- Collapse popups: `_entry_key` recomputes `current_key` each tick (micro-redundant).
- `.tactical-orders.is-collapsed/.is-expanded` class hooks carry no distinct styling yet.

## 5. Known AI-side gaps that affect player orders (pre-existing, from aieditor-ai-surface-and-gaps.md)

- `RandomAI` is never ticked → Defend's no-target idle loop is inert (with a target it
  works).
- Collision-avoidance is partial → ships may clip obstacles on attack runs.
