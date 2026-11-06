# Motion law — how a ship's speed, course and turn rate move

Contributed by **jmanyc** (PR #14), who measured the original `stbc.exe` and
ported the law. It was then finished on main (2026-11-06). The Python
reference is `engine/appc/ship_motion.py` (`step_vector_velocity`) and
`engine/appc/ships.py` (`_steer_turn_goal`). Kernel M
(`native/src/combat/src/motion_step.cc`) flies the same law bit for bit
(the golden fights and the 40-seed differential check this).

Evidence tiers: **measured** = measured on the original through
stbc-oracle (per PR #14: the `motion_*`, `turnto`, `impulse_matrix` and
`probe_acc` runs). **Designed** = our choice, not recovered from BC.

## Linear: the law acts on the velocity vector (measured)

Each tick the velocity moves toward `forward × target speed` by
`min(MaxAccel, |gap| / tau) · dt`, with tau = 1 s (`BC_IMPULSE_TAU`). On a
straight line this is the old speed ramp. In a turn the course lags the nose
and the speed bleeds off. Turning at half impulse, the slide settles at
atan(w·tau) = 15.6-15.9°. At full impulse the cap binds: a Galaxy holds
MaxAccel / w = 1.5 / 0.28 = 5.36 GU/s (85%), with its course 32° off the
nose. The vector is stored on the ship as `_motion_vel = (vx, vy, vz, speed)`.
The AI integrator and the player's helm share it.

- **Speed orders** are fractions of the LIVE max speed (engine pods ×
  the Engines power slider). An AI Galaxy at Engines 125% reaches
  7.875 = 1.25 × 6.3 GU/s. (measured)
- **Reverse** is impulse 2 of 9, backwards (it was 1/4). (measured)
- A ship with no authored limits still snaps to its target speed. A ship
  whose live accel is 0 still closes at gap / tau. (designed, unchanged)

**The re-seed contract (designed).** The stored vector is trusted only while
`_current_speed` is bit-identical to `_motion_vel[3]`. Any code that writes
`_current_speed` directly (warp exit, a dash stop, drift, tests) breaks that
match, and the vector is re-seeded along the nose. A writer that must keep
the vector has to write both. None does today.

Code that moves a ship without the law and without writing `_current_speed`
must drop the vector instead (`ship._motion_vel = None`, through the
descriptor so kernel M's mirror drops it too), or the law resumes the
course flown before it. Every in-system warp end does
(`ShipClass._end_in_system_warp`, AI flights and dashes alike), so does a
set-to-set arrival (`warp._PlacePlayerAction`), and so do the helm's warp
burst and dash branches (`host_loop._drop_motion_vel`). The warp-in slide
writes `_current_speed = 0`, so it needs nothing.

Taking the helm from the AI (`_PlayerControl._sync_control_from_ship`)
resumes the vector's own speed, `_motion_vel[3]`, so the vector stays
trusted and a ship taken over mid-turn keeps its course lag. With no vector
standing it falls back to the velocity on the nose. Tests:
`tests/unit/test_motion_vector_reseed.py`.

## Angular: the same law on the rate vector (measured)

The turn rate moves toward its setpoint capped at MaxAngularAccel, then with
tau = 1 s. Every axis reaches 50 / 90 / 99% of the rate at 1.15 / 2.75 /
5.05 s. Before, it was a linear ramp that hit the cap at 2 s. Two or three
held turn keys are unitized as BC's `TurnShip` does (1/√2, 1/√3 per axis).
`SetTargetAngularVelocityFraction` is a fraction of the live max rate.

The law is asymptotic: below the cap each tick closes 1/60 of the gap, so a
rate easing to zero never lands on exactly zero until it underflows. A
Galaxy stopping from 0.28 rad/s is at ~3e-14 rad/s after 30 s and reaches
exact zero only after 22,123 ticks (~6 minutes). (The linear law is the
same: a speed easing onto its target closes geometrically.) Consequences:
`_integrate_rotation` runs every tick for any ship that turned in the last
~6 minutes, rotating it by a vanishing amount, and `GetAngularVelocityTG`'s
fall-back to the base field (below) rarely fires for a ship that has ever
turned. The law is left as it is.

## Turn goals (measured)

`TurnTowardLocation` / `TurnTowardOrientation` / the `TurnDirections…`
calls store a goal. It is re-planned every tick, and a point goal is
re-aimed as the ship moves. The remaining turn is the single rotation that
takes the current (forward, up) frame onto the goal frame. It is never more
than π. An about-face turns about the ship's own up axis. The plan is BC's
cubic: from rest, +A falling linearly to −A over tau = √(6θ / A), where
A = live MaxAngularAccel. A Galaxy turns 45 / 90 / 180° in 6.3 / 8.9 /
12.5 s. It peaks **past** its MaxAngularVelocity (0.37 rad/s on the
about-face, against a max of 0.28), and the plan does not cap it. This matched
within 1% on every run. Any other angular command ends the goal.
`CompleteStop` clears it too. Kernel M steers stored goals itself. A row is
handed back to Python (reason `TurnGoal`) only when the mirror cannot hold
the goal, and the golden fights assert none are.

## Acceleration is the controller's output (designed — Mark, 2026-11-06)

`GetAccelerationTG` returns what the law commanded this tick:
`(v − v0) / dt`, where v0 is the vector it stepped from (after any
re-seed). It reports zeros whenever the law does not fly the ship: immobile,
a warp flight or warp-in arrival, drift with no setpoint, engines-out drift.
The manually flown player reports its helm's value, and zeros on the helm's
warp, dash and dead-engine exits.

SDK readers (every call site in `Build/scripts`, outside `App.py`), all
feeding `GetPredictedPosition(location, velocity, acceleration, t)`:

| Reader | Use |
|---|---|
| `AI/Preprocessors.py:748` `FireScript.PredictTargetLocation` | the target's lead for weapon fire (torpedoes) |
| `AI/Preprocessors.py:1729` `AvoidObstacles.TestCourseOverride` | its OWN predicted position, for the collision check |
| `AI/PlainAI/Intercept.py:132` | the target's predicted position |
| `AI/PlainAI/Ram.py:99` | the target's predicted position |
| `AI/PlainAI/StationaryAttack.py:87` | the target's predicted position |
| `AI/PlainAI/TorpedoRun.py:143` | the target's predicted position |
| `AI/PlainAI/EvilShuttleDocking.py:96` | the target's predicted position |

Why: a before/after dv/dt turned every direct velocity write (warp drop-out,
dash stop) into a one-tick spike of v / dt. That spike fed FireScript's
`0.5·a·t²` torpedo lead and Intercept's prediction. A community
reverse-engineering comment on GitHub issue #9 says BC's impulse update
computes `accel = clamp(target − v, MaxAccel)` and integrates it. That is
community RE, not verified by us. Sideways acceleration in a turn is real:
measured up to ~1.9 GU/s² (`probe_acc`). With the old constant zero, the
AI fired 21-32% more torpedoes than the original (measured).

## `ShipClass.GetAngularVelocityTG` / `GetAngularVelocity` (designed, on a measured fact)

These now return the live controller rate, `_current_angular_velocity`:
world space from the TG call, body space for `DIRECTION_MODEL_SPACE`. They
used to return the base field, which is never written for a ship, so it read
0 in the middle of a turn. A ship with no controller rate (a drifter, a
rock) still reads the base field. The original reports the live rate
(stbc-oracle telemetry `w`): that fact is measured. Overriding these calls
on `ShipClass` to serve it, and the fall-back to the base field, are our
design. Callers:

| Caller | Wants the live rate? |
|---|---|
| SDK (`Build/scripts`) | none outside `App.py` |
| `engine/appc/camera_modes.py:_target_angular_velocity` (drop-and-watch camera) | yes, this is why the change was made |
| `engine/ui/ai_inspector_model.py` (dev AI inspector) | yes, it shows what the ship is doing |
| `engine/compat/fx_api/NanoFX_ScriptActions.py` (mod death spin kick) | yes: the kick starts from the current spin. Watch item: it then calls `SetAngularVelocity`, which writes the base field, and a ship still holding a controller rate keeps reporting that rate instead |

## Live-check list

None of this has been seen in a live game yet. Things to watch for:

- **Intercept can end its approach speeding up again.** Under the vector law
  a hostile about-faces at speed, brakes, then may pick speed up again to
  finish the approach (the intercept smoke test now checks the slowdown
  after the warp, not the final speed).
- **Shuttles are slower for the first ~10 s of each circle.** The Tau Ceti
  dry-dock shuttles (`engine/systems/shuttle_service.py`) run
  `CircleObject` at `SetCircleSpeed(0.4)` until the bearing has turned
  0.5 rad, so the lagging course does not slide them inside the band; then
  the default speed.
- **About-faces exceed MaxAngularVelocity** (0.37 rad/s against 0.28 on a
  Galaxy's 180°), as measured; it should look like a swing, not a glitch.
- **Reverse is impulse 2 of 9** (was 1/4).
- **The course lags the nose in turns** (32° at full impulse on a Galaxy)
  and the speed bleeds to 85%.
- **Taking the conn mid-turn** keeps the lag: no snap of the course onto
  the nose.

## Open questions needing BC evidence

- **Does `SetImpulse` fix its speed at order time?** We resolve the
  fraction against the live max speed (pods × Engines slider) when the
  order is given; a later slider change does not reach a standing order
  until the AI re-issues it. BC may read the slider live.
- **Engines-out drift direction.** When every pod dies, the drift
  snapshot is the commanded direction (the nose) × the current speed, not
  the stored velocity vector, so a ship turning when its engines die
  drifts along its nose rather than its course. Which BC does is unknown.

## Known gaps

- K1's native pulse-weapon lead still uses a zero target acceleration
  (`native/src/combat/src/weapon_geometry.cc:350`).
- Tractors and collisions still don't act on the one velocity vector
  (the other half of issue #9).
- A helm AI that is installed but has not yet written a setpoint leaves
  the player's previous acceleration in place.
