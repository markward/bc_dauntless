# Torpedo event probe — who posts ET_TORPEDO_FIRED, and what does it carry?

Status: PENDING
Author: Claude session (TorpedoTube recreation brainstorm)
Created: 2026-07-12
Closed:  —

## Goal

Determine, by direct observation inside the running original game, **which
object is the Source and which is the Destination of `ET_TORPEDO_FIRED`**, what
triggers it, and what its numeric event ID is — plus the same for
`ET_TORPEDO_RELOAD`, `ET_WEAPON_FIRED`, `ET_CANT_FIRE` and
`ET_TORPEDO_START_HOMING`.

## Background

We are reimplementing `App.TorpedoTube` for Dauntless. Two of the three evidence
tiers we have disagree, and the third is silent:

- **RE'd binary** (`docs/original_game_reference/gameplay/combat-and-damage.md:793-810`):
  the tube's `Fire` (`FUN_0057C9E0`) posts **`ET_WEAPON_FIRED`**, with an explicit
  annotation *"NB: NOT `ET_TORPEDO_FIRED`"*. `ReloadTorpedo` (`FUN_0057D8A0`)
  posts the reload event.
- **SDK scripts**: `Conditions/ConditionTorpsReady.py:140-141,169,182` and
  `Maelstrom/Episode7/Episode7.py:37,88-115` both consume `ET_TORPEDO_FIRED`,
  treating the **Torpedo projectile as Source** and the **TorpedoTube as
  Destination**.
- **Nobody has RE'd the torpedo *projectile* path**, which is the most likely
  place `ET_TORPEDO_FIRED` is actually posted.

So we know the event exists and we know what listeners expect of it, but we do
**not** know what posts it or under what conditions. Guessing is not safe:
`Episode7.TorpedoFired` destroys the event's `GetDestination()` subsystem outright
(`MissionLib.SetConditionPercentage(pLauncher, 0)`) on a 10% roll. If we post the
event with the wrong Destination, we destroy the wrong subsystem.

This probe replaces inference with observation.

## Specific questions

- **Q12-1** — What is the numeric value of `ET_TORPEDO_FIRED`,
  `ET_TORPEDO_RELOAD`, `ET_WEAPON_FIRED`, `ET_CANT_FIRE`,
  `ET_TORPEDO_START_HOMING`? (We need real integers for our `App.py`; today they
  are undefined and fall through to a stub.)
- **Q12-2** — Does `ET_TORPEDO_FIRED` fire for an **ordinary photon torpedo**, or
  only for special ammo (Phased Plasma)? I.e. is the ammo-type filter in the
  engine or in `Episode7`'s handler?
- **Q12-3** — What is `GetSource()` on `ET_TORPEDO_FIRED`? (Expected: the
  `Torpedo` projectile. Confirm.)
- **Q12-4** — What is `GetDestination()`? (Expected: the `TorpedoTube`. **This is
  the load-bearing one** — Episode 7 destroys this object.)
- **Q12-5** — Cardinality and ordering: one `ET_TORPEDO_FIRED` per torpedo, or per
  tube, or per volley? Does it arrive before or after `ET_WEAPON_FIRED` for the
  same shot?
- **Q12-6** — Source/Destination of `ET_TORPEDO_RELOAD`, and the measured game-time
  gap between a tube's fire and its reload (validates our `ReloadDelay` model —
  Galaxy tubes should show ~40 s).

## Probe

`tools/probes/q12_torpedo_events.py`

**This one is different from every previous probe.** q01–q11 are one-shot
`execfile()` scripts. q12 is **event-driven**, so it must be **imported**, not
`execfile`'d: `AddBroadcastPythonFuncHandler` takes a `"module.FunctionName"`
string that the engine resolves *by importing that module*. Functions defined via
`execfile()` land in the REPL namespace and are not importable, so the engine
could never call them. `game/` is on `sys.path`, so a plain `import` works and the
handler strings resolve.

## How to run

### On the dev machine (already done — the probe is committed)

```bash
uv run python tools/probes/push.py q12      # copies q12_torpedo_events.py into game/
```

### On the Windows BC machine

**Step 1 — get the probe into the game folder.**

```
git pull
uv run python tools/probes/push.py q12
```
Confirm `game\q12_torpedo_events.py` now exists.

**Step 2 — launch BC with the dev console.**

```
cd game
stbc.exe -TestMode
```

**Step 3 — start a battle FIRST, before arming the probe.**

The probe needs a live player ship to own its event handlers. In the game UI:

1. Start a **Quick Battle**.
2. Pick the **Galaxy** as the player ship (it has 6 torpedo tubes,
   `MaxReady=1`, `ReloadDelay=40.0`, `ImmediateDelay=0.25` — a known baseline
   from `sdk/Build/scripts/ships/Hardpoints/galaxy.py:28-30`).
3. Pick any single enemy.
4. Let the battle load until you are flying.

**Step 4 — arm the probe.** Open the console and type these two lines exactly:

```python
import q12_torpedo_events
q12_torpedo_events.Install()
```

You should see the five constant values printed, then five `armed …` lines. If
you instead see `FATAL -- no player/episode object`, you skipped Step 3 — start
the battle, then re-run `Install()`.

**Copy the printed constant values into the report** — that alone answers Q12-1
even if everything else fails.

**Step 5 — generate the events.** Back in the game:

1. Press **Tab** to acquire the target.
2. Fire **torpedoes** (not phasers) — **at least 6 shots**. Fire them in a burst
   so tubes empty.
3. **Hold fire for ~45 seconds** so a full tube reload completes (Galaxy
   `ReloadDelay` is 40 s).
4. Fire **2 more torpedoes**.
5. Optional but useful: fire once with **no torpedoes ready** (immediately after
   emptying a tube) — that should generate `ET_CANT_FIRE`.

**Step 6 — dump.** Back in the console:

```python
q12_torpedo_events.Dump()
```

It prints `q12 done -- N events captured` and writes `game\BCProbe_q12.cfg`.

> **If N is 0:** the probe armed but nothing fired. Either you fired phasers
> instead of torpedoes, or handler registration silently failed. Re-check the
> `armed …` lines from Step 4 and try again.

**Step 7 — collect and commit.**

```
uv run python tools/probes/collect.py q12
git add tools/probes/results/q12_torpedo_events.txt
git commit -m "probe: q12 torpedo event results"
git push
```

## Expected output

`[BCProbe_q12]` should contain, in order:

- an `environment` block,
- an `event constant values` block — the five integers (Q12-1),
- a `player torpedo config` block — the ship, the tube count, and per-tube
  `maxready / numready / immediate / reload / lastfire` (this independently
  cross-checks the hardpoint values and the RE'd `last_fire_time = -1000.0`
  initialiser),
- a `captured events` block — one line per event, e.g.:

```
e000 = ET_WEAPON_FIRED | t=12.317 frame=741 type=8388732 ammo=Photon Torpedo | SRC TorpedoTube(name='Forward Torpedo 1' ready=0) objid=... | DST ShipClass(name='Galaxy') objid=...
e001 = ET_TORPEDO_FIRED | t=12.317 frame=741 type=... ammo=Photon Torpedo | SRC Torpedo(parent=... target=...) objid=... | DST TorpedoTube(name='Forward Torpedo 1' ready=0) objid=...
e002 = ET_TORPEDO_RELOAD | t=52.334 frame=3143 type=... ammo=Photon Torpedo | SRC ... | DST TorpedoTube(name='Forward Torpedo 1' ready=1) objid=...
```

The `SRC`/`DST` fields are built by attempting **every relevant SWIG cast**
(`Torpedo_Cast`, `TorpedoTube_Cast`, `TorpedoSystem_Cast`, `ShipSubsystem_Cast`,
`ShipClass_Cast`) and reporting which succeeded — so we are not guessing at
types, we are asking the engine.

## Analysis

Read the result file directly; no script needed.

- **Q12-1** — read straight off the `event constant values` block.
- **Q12-2** — if any `ET_TORPEDO_FIRED` line shows `ammo=Photon Torpedo`, the
  event is **universal** and Episode 7's plasma filter lives in the handler. If
  `ET_TORPEDO_FIRED` never appears while `ET_WEAPON_FIRED` does, the event is
  ammo-gated (or posted somewhere we have not reached) — a very different answer.
- **Q12-3 / Q12-4** — read `SRC` / `DST` on the `ET_TORPEDO_FIRED` lines.
- **Q12-5** — compare `frame=` and ordering between `ET_TORPEDO_FIRED` and
  `ET_WEAPON_FIRED` for the same shot; count events per volley.
- **Q12-6** — subtract the `t=` of a tube's `ET_WEAPON_FIRED` from the `t=` of the
  next `ET_TORPEDO_RELOAD` naming the **same tube**. Expect ~40 s on a Galaxy.

## Cleanup

Delete `game\q12_torpedo_events.py` and `game\BCProbe_q12.cfg`. The probe scrubs
its own cfg keys after writing (`_flush()`), so `Options.cfg` is not polluted. It
makes **no** modification to `App.py` or any game file — nothing else to revert.

## Findings

(To be filled in when the probe runs.)
