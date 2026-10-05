# Sensor model — roadmap

Status: approved in brainstorming with Mark, 2026-10-03. Each sub-project gets its own
spec → plan → subagent-driven execution. This document holds the **standing decisions**
so later sub-projects do not re-ask them.

## Why

Today one predicate, `sensor_detection.can_detect`, decides both whether a contact is
listed and whether it is identified, at the same range — so nothing is ever
listed-but-unknown passively. BC has two tiers (the SDK implies them, the reverse-
engineering recovers them), missions depend on the gap between them (E2M2: ships on
sensors but unidentified until scanned), and rocks and nebulae need a richer answer than
"listed or not".

## Evidence

| Fact | Tier | Source |
|---|---|---|
| Effective range = `BaseSensorRange × NormalPowerPercentage × ConditionPercentage`, 0 if disabled/off | RE'd | `STBC-Reverse-Engineering-1/docs/gameplay/sensor-subsystem.md` (re-audited 2026-07-14), `GetSensorRange` @0x00567190 |
| `IsObjectNear` = within **half** range, `IsObjectFar` = within full range; pure distance (+ probes), no nebula term | RE'd | same, @0x00567440 / @0x00567640 |
| `GetIdentificationTime` returns a hard-coded **4.0 s**; no setter exists | RE'd | same, @0x005671C0 |
| A contact in the near band and not yet known is identified after the 4.0 s dwell | RE'd | same, global contact manager @0x0098C000 |
| The contact sweep runs every **1.0 s**, player ship only | RE'd | same, `HandlePeriodicScanEvent`, interval at 0x008E50F4 |
| NEAR/FAR proximity events fire on entering AND leaving (bit at event+0x19) | RE'd | same |
| `IsObjectVisible`: power gate → absolute cloak → same set → nebula jam (bool) → over-boost >1.2 sees all → `IsObjectFar` → probes → (if not jammed) `IsObjectKnown` | RE'd | same, @0x005671D0 |
| `ForceObjectIdentified` immediate; `IdentifyObject` deferred; `ScanAllObjects` spaces actions by the identification time | RE'd | same |
| Unknown colour is mid grey; E1M2 teaches "grey = unknown" | SDK | `LoadInterface.py:140`, `E1M2.py:4357` |
| Proximity handlers read the ship from `GetSource()`; identify handlers from `GetDestination()` | SDK | E2M2:934, E2M6:910, E8M1:2232; HelmMenuHandlers:499, ScienceMenuHandlers:244 |
| E8M1 uses FAR as "detected something in the nebula", before the Kessok is seen | SDK | `E8M1.py:2221-2269` |

**Not recovered:** the "Unknown …" caption text (`ShowUnknownName` body unreconstructed);
whether BC's *target list* follows `IsObjectVisible` (which keeps known contacts) or the
far band. No tested-tier measurement of any of it exists (stbc-oracle bible silent; the
stbc-reference MCP was unreachable 2026-10-03).

## Standing decisions

1. **Two tiers, BC's way.** Detected = listed, grey, "Unknown N", restricted information.
   Identified = real name, `IsObjectKnown`, `ET_SENSORS_SHIP_IDENTIFIED`. Identification
   needs the near band plus a dwell, or a scan.
2. **The list follows sensor range, as today.** Out of range ⇒ not listed, not targetable,
   lock drops. *Mark's recollection of BC; the RE doc's `IsObjectVisible` keeps known
   contacts, but nothing shows the list uses it.* Recorded gap. Memory lives only inside
   `IsObjectVisible` for the SDK callers that ask it directly.
3. **Identity survives leaving range.** Forgotten only when the ship leaves the set (the
   player leaving wipes everything) or after a lost track (decision 9).
4. **Unknown contacts are labelled "Unknown 1", "Unknown 2", …** — a number held per
   contact until identified, so the SDK's label-keyed button de-duplication never merges
   two unknowns.
5. **No name leaks.** Science's Scan Object button for an unknown contact carries the same
   placeholder and is renamed in place on identification.
6. **AI has no identification tier** (BC's contact layer is player-only). AI stays on the
   detection predicate; occlusion applies to it symmetrically.
7. **Occlusion is one level and binary.** A major rock (radius ≥ a dial) on the line of
   sight removes the contact. It lives in `can_detect`, so list, weapons, torpedoes and AI
   all obey it. Fields between observer and target do NOT occlude; minor and near-band
   rocks never occlude.
8. **"Unknown" from a medium is a property of where the target is.** A ship inside an
   asteroid field, or in moderate nebula, reads Unknown with restricted information
   (no subsystem targeting, AI included — symmetric with cloak). The dense nebula core
   (today's lock-break threshold) still removes the contact; the nebula range shrink stays.
9. **Continuity (Mark's rule).** Concealed < 5 s ⇒ display-only "obscured", identity kept.
   Concealed ≥ 5 s ⇒ lost track: `RemoveKnownObject`, remove its Hail and Scan buttons by
   calling Helm and Science `ExitedSet(ship)` directly (never a fake `ET_EXITED_SET`),
   re-identify later via the dwell or a scan. Applies to rock occlusion, field and nebula
   concealment alike.
10. **The player's lock drops at once** when a contact is concealed (today's
    `clear_undetectable_player_lock`, unchanged). Only the row's identity rides the window.
11. **Scans identify through fields but not through a blocking rock.**
12. **Every tunable is a dial** in a "sensors" group on the shared / L O keys
    (`engine/dev_dial_groups.py`). BC's recovered numbers are the defaults.

## Sub-projects

| # | Name | Depends on | Status |
|---|---|---|---|
| 1 | **Two tiers** — contact manager, bands, dwell, proximity events, Unknown display, `SensorSubsystem` surface | local main | ✅ merged b1e1e05a, live-verified — spec: `2026-10-03-sensor-tiers-design.md` |
| 2 | **Continuity and occlusion** — 5 s window, lost track, major-rock line of sight, field and nebula Unknown, E5M2 / Helm guards | 1 (merged b1e1e05a), rock-fields (merged) | built, unmerged (feat/sensor-continuity) — spec: `2026-10-05-sensor-continuity-occlusion-design.md` |
| later | **Probes** — BC lets a probe's sensors see for you (`AddProbe`, Science "Launch Probe", E6M4 goal) | 1 | explore after 2 |
| later | **Over-boost** — BC reveals the whole set above 120% sensor power; decide whether the list shows it | 1 | explore after 2 |

### Sub-project 2 notes, carried forward

- **Occluders:** RockClass majors only — the only rocks with a Python position and radius
  every tick (tens per set). `ProximityManager.GetLineIntersectObjects`
  (`engine/appc/planet.py`) is an exact segment-vs-sphere test already used for AI line of
  sight; `_dauntless_host.ray_trace_mesh` is available as an exact narrow phase if spheres
  prove too coarse.
- **Field membership is a point query**, not a march. Since rock-fields merged
  (2026-10-04) there is one: `engine/rocks/far_tier.field_strength_at(obj)` returns the
  strongest field `a(x)` (tile fields + the system's belt) and already drives the in-field
  dust. ⚠️ Its tile fields are those **last pushed for the VIEWED set**
  (`frames.viewing_set()`), so it answers 0 for a set nobody is viewing — fine for
  contacts in the player's set, wrong for AI-vs-AI elsewhere. Sub-project 2 must either
  accept that (stated reason) or give it a set-explicit form. Per-source evaluation is
  `far_tier.source_strength(s, p, anchor)`; belts come from
  `density.sources_for_system(system)`.
- **Re-identification audit (2026-10-03):** safe to re-fire — HelmMenuHandlers (existing
  button check), ScienceMenuHandlers (`GetButtonW` guard), E2M0, E2M1, E2M2, E2M6, E6M3,
  E3M2. **Unsafe — E5M2 `ShipIdentified` (:610)** replays dialogue and re-adds a removed
  goal on every Outpost re-identify. **Race — Helm's 1 s delayed `AddHailButton` (:568)**
  never re-checks, so a track lost inside that second still gets a button.
- **Live risk:** E2M1's Karoon drifts into the asteroids; it must keep its Hail button and
  remain scannable (decision 11).
- **Cost:** measure with the frame profiler (`docs/engine/frame-profiler.md`,
  `engine.dev_missions.combat_stress`), CPU only — GPU timing is dead on this Mac.
- **The asteroids roadmap** (`2026-09-30-modern-asteroids-roadmap.md`) already marks its
  sub-project 5 as promoted to this project (merged 2026-10-04). Rock fields now consist of
  the near band, the speck band and puffs; the volumetric haze and mid band were deleted,
  so there is no haze optical depth to reuse — consistent with decision 7 (fields do not
  occlude).

## Later / parked

- **Oracle measurements** that would close the gaps: does a known contact stay listed out
  of range; the Unknown caption; the dwell and half-range band; radar disc range
  (`docs/instrumented_experiments/2026-05-26-radar-range-calibration.md`, still pending).
- **Tuning debts already recorded:** `FALLBACK_RANGE_GU = 30000` (18 of 52 hardpoints
  author no sensor range); station cloak bubbles; the unmeasured nebula sensor-scale clamp
  (`docs/superpowers/deferred/2026-09-28-nebula-sensor-scale-unmeasured.md`).
- **Declined:** fields occluding between observer and target; minor/near-band occluders;
  partial-lock UI.
- **Fields only exist where seeded:** today Vesuvi's belt and BC tile fields. Asteroid
  sub-project 4 (profile seeding) widens where decision 8 applies.
