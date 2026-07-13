# Canonical probe scenarios

A standing reference for the **two pinned game states** that live-state probes
should be run in, so their dumps are reproducible and diffable — against a
previous run, against each other, and against our engine's output.

This doc exists because probes split into two kinds:

- **Static-surface probes** (e.g. q13 constant dump) read module/class state that
  is bound at `import App`. Game state is irrelevant; they don't need a scenario.
- **Live-state probes** read *instance* state — subsystem charges, per-tube reload
  timers, speeds, target offsets, hull/shield values. These values depend on ship
  class and mission progress, so a dump is only meaningful if you know **exactly**
  what state produced it. Most of the [`stub_heatmap`](../stub_heatmap.md) live
  attrs are here: `TorpedoTube.GetMaxCharge`, `ImpulseEngineSubsystem.GetCurMaxSpeed`,
  `ShipClass.GetTargetOffsetTG`, per-tube `maxready/reload`.

For live-state probes, pin one of the two scenarios below and record which one in
the probe's result file. Do not free-form the setup — an unpinned scenario makes
the numbers un-reproducible and the cross-engine diff meaningless.

## Scenario A — Galaxy vs. Galaxy QuickBattle (the baseline)

The minimal, fastest-to-reach controlled fight. Symmetric matchup so both ships
have identical authored stats — any asymmetry in a dump is a bug, not a
ship-class difference.

**Setup (operator):**

1. `stbc.exe -TestMode`.
2. **QuickBattle** → player ship **Galaxy**, single enemy **Galaxy**.
3. Fly until in space; acquire the target with **Tab** if the probe needs one.

**Why Galaxy:** it is the reference hull throughout our docs — 6 torpedo tubes,
`MaxReady=1`, `ReloadDelay=40.0`, `ImmediateDelay=0.25`
(`sdk/Build/scripts/ships/Hardpoints/galaxy.py`), `SetMaxSpeed(6.3)` (the source
of the GU↔km calibration in [`engine/units.py`](../../engine/units.py)). Its
numbers are already known, so a probe of a Galaxy is self-checking.

**Good for:** weapon/subsystem baselines, reload timing, speed/impulse curves,
target-offset geometry, damage routing on a known hull — anything where you want
a clean, symmetric, immediately-reachable state.

## Scenario B — Episode 1, Mission 1 (E1M1), full run

A scripted mission (`sdk/Build/scripts/Maelstrom/Episode1/E1M1/E1M1.py`) that
exercises the state a QuickBattle never reaches: mission triggers, scripted AI,
set transitions, dialogue/timer lifecycles, objective-driven spawns.

**Setup (operator):**

1. `stbc.exe -TestMode`.
2. Start the campaign / load **E1M1**.
3. Play the mission through, running the probe at the mission checkpoints its
   runbook names (not at arbitrary moments — checkpoints are what make two runs
   comparable).

**Good for:** anything mission-driven — event ordering across a real script,
timer/condition behaviour, set membership changes, AI container dispatch, values
that only exist once a mission has run its setup. It is the closest thing we have
to "the real game as shipped."

## Using a scenario in a probe

- State the scenario in the probe's header comment and in an early `_record`
  line (`scenario = A (Galaxy vs Galaxy QB)`), so the result file is
  self-describing.
- Keep the two scenarios' outputs in separate result files; never mix them.
- When a probe's numbers will be compared against our engine, run the *same*
  scenario headless through the harness and diff — that is the whole point of
  pinning it.

## Relationship to q13

q13 (the constant dump) is a static-surface probe, so it does **not** need a
scenario — but it deliberately dumps in **two states anyway** (boot menu vs. a
live battle) purely to *prove* the surface is state-invariant (Q13-4). That is a
one-off invariance check, not the reproducible-scenario discipline this doc is
about. Once q13 confirms invariance, no future static-surface probe needs to
think about game state at all.
