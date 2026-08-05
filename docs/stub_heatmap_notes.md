# Stub heatmap — persistent notes

`docs/stub_heatmap.md` is **generated** (`tools/stub_heatmap.py` overwrites it on
every refresh). The generator round-trips exactly one human-authored cell —
`markedResolvedOn`, and only when it parses as a date. Anything else typed into
that column is silently dropped on the next regeneration (the header's "Skipped
N malformed annotation row(s)" is the only trace).

So investigation notes about an open stub go **here**, keyed by `owner / attr`.

---

## App / ET_PLAYER_TORPEDO_TYPE_CHANGED

_Recovered 2026-08-05 from `git show f855271b:docs/stub_heatmap.md` — it had been
written into the `markedResolvedOn` cell and was destroyed by the 2026-07-26
regeneration._

LIVE GAP: BC fires this when the player changes torpedo type;
`TacticalCharacterHandlers.PlayerTorpChanged` speaks the officer callout
(`LoadingPhoton` / `LoadingQuantum`, or `PhotonsOnlyDaunt` for a 1-type Galaxy).
Undefined in `events.py` and never dispatched — our CEF switch drives
`weapon_config` directly and bypasses it, so the switch **works** but the officer
stays silent. Wiring it = define the event + dispatch on `cycle_torpedo_type` +
register the two SDK `PlayerTorpChanged` handlers. Not the torpedo count/fire
bug (fixed 2026-07-17).

## ShipClass / TurnTowardDifference

Identified 2026-08-05 as the next resolution target. The only missing member of
the `TurnToward*` family (`TurnTowardLocation`, `TurnTowardDirection`,
`TurnTowardOrientation`, `TurnDirectionsToDirections` are all implemented in
`engine/appc/ships.py`). Arg is a **world-space axis-angle vector** (turn axis ×
radians remaining); return is the **ETA in seconds** for that turn.

Sole SDK caller `AI/PlainAI/ManeuverLoop.py:126`, which is the script module for
`AI/Player/Defense`, `AI/Player/DefenseNoTarget`, `QuickBattle/QuickBattleAI`,
`AI/Compound/Parts/NoSensorsEvasive`, and `E3M1/KlingonManeuverAI`. Stubbed, it
degrades silently and **never completes**: `fRadiansSoFar` only accumulates
*observed* rotation, so with no turn commanded `fTurnLeft` never drops below
`fFinishAngleThreshold` and `Update` returns `US_ACTIVE` forever; `fTime / 2.0`
also collapses to `0.0` (`_Stub.__truediv__`) so it re-polls every tick.
