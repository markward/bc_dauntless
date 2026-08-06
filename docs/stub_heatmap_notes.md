# Stub heatmap — persistent notes

`docs/stub_heatmap.md` is **generated** (`tools/stub_heatmap.py` overwrites it on
every refresh). The generator round-trips exactly one human-authored cell —
`markedResolvedOn`, and only when it parses as a date. Anything else typed into
that column is silently dropped on the next regeneration (the header's "Skipped
N malformed annotation row(s)" is the only trace).

So investigation notes about an open stub go **here**, keyed by `owner / attr`.

---

## App / ET_PLAYER_TORPEDO_TYPE_CHANGED — RESOLVED 2026-08-06 (live-verified)

_Note recovered 2026-08-05 from `git show f855271b:docs/stub_heatmap.md` — it had
been written into the `markedResolvedOn` cell and was destroyed by the 2026-07-26
regeneration. Resolved the next day._

Was: BC fires this when the player changes torpedo type and
`TacticalCharacterHandlers.PlayerTorpChanged` speaks the callout (`LoadingPhoton` /
`LoadingQuantum` / `LoadingTorps`, or `PhotonsOnlyDaunt` for a 1-type Galaxy). The
switch worked; Felix stayed silent.

**The note's plan was wrong about the work, in an instructive way.** It said
"register the two SDK `PlayerTorpChanged` handlers" — but the SDK already
registers them itself, every bridge load: `AttachMenuToTactical`
(`Bridge/TacticalCharacterHandlers.py:59`) is called from
`Bridge/Characters/Felix.py:187`. Only the CONSTANT and the DISPATCH were missing.

**Diagnostic worth reusing:** the heatmap's `EventType | <name>` row *is*
`events._validate_event_type` logging a live SDK registration against an undefined
constant. This one read 498 hits across 103/194 runs — i.e. the SDK was
registering that handler on nearly every run and it could never fire, because an
undefined `App.ET_*` vends a fresh `_NamedStub` per access. **A high-coverage
`EventType` row therefore means the SDK side is already wired and the fix is just
"define the constant + post the event" — cheap.** Contrast a bare `App | ET_*` row
with no `EventType` twin, which only tells you something read the name.

Id `0x00800068` came from the live constant dump
(`tools/probes/results/q13_constants_battle.txt:523`), completing the measured
torpedo cluster (...65 reload, ...66 fired, ...67 ammo-consumed, ...68
type-changed) — worth checking those dumps before ever inventing an id.

Shipped in `976677b6`; dispatch + both gates live in
`weapon_subsystems.TorpedoSystem._announce_player_type_change`.

**Resolved with a MINUTE, not a date** (`2026-08-06 11:14`, the merge to main) —
`parse_resolved_date` accepts `YYYY-MM-DD HH:MM`. Use that form whenever the fix
lands the same day a run recorded the stub, because a bare date resolves to
23:59:59 and silently swallows every post-fix hit that day. Here it matters:
the 11:13 run still hit this stub 6 times, because the fix was committed on a
branch at 10:43 and the working tree was switched back to main at ~10:45 to start
unrelated work — so the live run genuinely did not contain it. With the minute
form, any hit after 11:14 is correctly flagged REGRESSED instead of hidden.

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
