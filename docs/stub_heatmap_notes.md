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

## ShipClass / TurnTowardDifference — RESOLVED 2026-08-06

The last missing member of the `TurnToward*` family (`TurnTowardLocation`,
`TurnTowardDirection`, `TurnTowardOrientation`, `TurnDirectionsToDirections` were
all already implemented in `engine/appc/ships.py`). Arg is a **world-space
axis·angle vector** (turn axis × radians remaining — `ManeuverLoop.py:121-124`
pushes a model-space axis through `MultMatrixLeft(GetWorldRotation())` before
scaling, so do **not** re-apply the ship rotation); return is the **ETA in
seconds**, which the caller halves to schedule its next update.

Sole SDK caller `AI/PlainAI/ManeuverLoop.py:126`, the script module for
`AI/Player/Defense`, `AI/Player/DefenseNoTarget`, `QuickBattle/QuickBattleAI`,
`AI/Compound/Parts/NoSensorsEvasive`, and `E3M1/KlingonManeuverAI`. Stubbed, it
degraded silently and **never completed**: `fRadiansSoFar` only accumulates
*observed* rotation, so with no turn commanded `fTurnLeft` never dropped below
`fFinishAngleThreshold` and `Update` returned `US_ACTIVE` forever, jamming its
container; `fTime / 2.0` also collapsed to `0.0` (`_Stub.__truediv__`) so it
re-polled every tick.

**Implementing it exposed a second, older bug in the shared controller.** Both
the nose and the roll reference have to be rotated by the delta (a delta about
the ship's own forward is a pure roll, which leaves forward unchanged — steering
only the nose would silently ignore it). Handing the rotated up-vector to
`TurnDirectionsToDirections` then hit a degenerate projection: any turn of ~90°
puts the current up (anti)parallel to the commanded forward, the projection onto
the plane ⊥ `primary_to` collapses to the zero vector, `Unitize()` leaves a zero
vector unchanged, and `acos(0)` injected a **spurious π/2 roll** about the target
forward — which also doubled the returned ETA and so halved the caller's update
cadence. Reachable from `TurnTowardOrientation` too, so it was fixed in the
shared controller (guard both projected lengths) rather than worked around.

### Open follow-ups from this work

1. **A finished AI turn keeps creeping.** Nothing zeroes the angular-velocity
   setpoint when an AI completes, so the last-written rate is left standing.
   Measured on a 0.25 loop: 98.9° swept at t=10 s (a fair ~9° of overshoot), still
   creeping to 117.8° by t=30 s with no AI updates at all. The rate *is* decaying
   (19° over 20 s against a 16°/s setpoint), so something damps it, just not to
   rest. Systemic — every AI that turns then finishes is affected. Held as a
   strict `xfail` in `tests/integration/test_maneuver_loop_smoke.py::
   test_maneuver_stops_turning_once_it_reports_done`; the marker fails loudly if
   it ever starts passing. Fix belongs at the AI-driver / `ship_motion` seam.
2. **`AI/Player/Defense` still will not jink**, even with this fixed: its four
   maneuvers sit under `RandomAI`, which is a separately-recorded gap (never
   dispatched). Live-verify against `QuickBattleAI` or `NoSensorsEvasive`, which
   reach `ManeuverLoop` directly.
3. Not yet live-verified in-game as of 2026-08-06.
