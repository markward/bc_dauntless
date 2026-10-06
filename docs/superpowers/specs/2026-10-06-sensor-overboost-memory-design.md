# Sensor model sub-project 3 — over-boost and sensor memory — design

Status: design approved by Mark 2026-10-06 (brainstorming). Roadmap and standing
decisions: `2026-10-03-sensor-model-roadmap.md` (this sub-project overturns decision 2).
Sub-projects 1 (`b1e1e05a`) and 2 (`0f3db1e7`) are merged and live-verified.
Sub-project 4 (probes) follows and plugs into the reach step defined here.

## Goal

Give the target list, radar, weapons and AI the two answers BC's
`SensorSubsystem::IsObjectVisible` gives and ours does not:

1. **Sensor memory** — an identified contact stays listed, named and targetable after it
   leaves sensor range, unless a nebula jams it.
2. **Over-boost** — sensors above 120% normal power, with no nebula involved, see every
   ship in the set (listed as Unknown: identification still needs the near band).

…while keeping one detection rule (`sensor_detection.can_detect`) that every consumer
shares, and making the SDK's own `IsObjectVisible` callers get that same answer.

## Evidence

| Fact | Tier | Source |
|---|---|---|
| `IsObjectVisible` returns TRUE when the float at `this+0x98` > 1.2 and the nebula flag is clear, **before** `IsObjectFar`. Compare `FLD [ESI+0x98]` @`0x00567294`, `FCOMP [0x0089054c]` @`0x0056729A`, `JNZ` on `AH&0x41` (fallthrough = strictly greater); early return `0x005672AB–B4`; `CALL 0x00567640` (IsObjectFar) @`0x005672C0` | RE'd (raw disassembly) | RE project answer to Mark, 2026-10-06 |
| Constant `0x0089054c` = `9A 99 99 3F` = 1.2f | RE'd | same |
| `+0x98` = NormalPowerPercentage = `received / (normal × dt)`; SWIG getter `0x0060E960` | RE'd + clean-room reference | `sensor-subsystem.md`; stbc-reference `spec/PoweredSubsystem.md` §2 (`m_loadRatio`) |
| It can exceed 1.2: slider cap 1.25 (`0x0088BEC0`), `wanted = normal × pct × dt` | RE'd | `power-system.md`; stbc-reference `PoweredSubsystem.md` §2 |
| Nebula flag = owner **or** target inside any `CT_NEBULA` (`0x800E`) in the set (`0x00599290` called on owner @`0x00567256`, then on target @`0x00567277`). Set gate: owner `+0x20` ≠ target `+0x20` → FALSE @`0x00567229` | RE'd (raw disassembly) | RE project answer, 2026-10-06 |
| Final step: not jammed ⇒ `IsObjectKnown(target)` (memory) | RE'd (decompile) | `decompiled_fresh/05_game_mission.c:23259` (`0x005671D0`) |
| **The target list and radar call `IsObjectVisible`**: STTargetMenu periodic refresh `0x00538D86`, RadarScope_Update `0x005443D7`, MapWindow ×3 (`0x004FED5F`, `0x00501564`, `0x00501793`/`0x0050181B`) | RE'd (xrefs) | RE project answer, 2026-10-06 |
| So do AI and weapons: AI OptimizedSelectTarget filter `0x00489A14`, `ShipClass::IsValidTarget` `0x005AE128`, weapon target-list rebuild `0x005857FA` | RE'd (xrefs) | same |
| No tactical target-cycling key calls it | RE'd | same |
| `IsObjectNear` is distance + probes, no boost term — over-boost lists, it does not identify | RE'd | `sensor-subsystem.md` |
| No SDK script sets sensor power above 1.0; missions read boost through `MissionLib.IsBoosted` (E2M2 :1934/:2012, E7M6, E8M1) | SDK | grep, 2026-10-06 |

The stbc-reference MCP has only the method roster for `SensorSubsystem` (no
`IsObjectVisible` body); no tested-tier measurement exists.

## Decisions (Mark, 2026-10-06)

- **D1 — Over-boost is BC's rule** (not a range multiplier, which was considered and
  dropped once the RE showed the list uses `IsObjectVisible`).
- **D2 — Sensor memory is BC's rule.** Roadmap decision 2 ("out of range ⇒ not listed")
  is overturned: it was recorded as recollection with a gap note, and the xrefs close the
  gap the other way.
- **D3 — Approach 1:** a reach step inside `can_detect`; `IsObjectVisible` delegates to
  `can_detect`. Rejected: boost/memory in the perception layer only (forks list from
  weapons); `can_detect` calling `IsObjectVisible` (inverts the layering).

## The rule

`can_detect(observer, target, …)` becomes **not hidden ∧ reached**, evaluated in order:

1. **Power** — `effective_sensor_range(observer) ≤ 0` ⇒ False. Unchanged. Because this
   precedes everything, dead or switched-off sensors also forget every remembered
   contact and lose the boost (BC's step 1).
2. **Cloak** — unchanged (`ENHANCED_SENSOR_CONTEST` off ⇒ cloaked is False; on ⇒ range
   shrinks to the cloak bubble).
3. **Hidden** — unchanged from sub-project 2: a major rock on the line of sight
   (`sensor_occlusion.blocked`, under `ENHANCED_SENSOR_CONTEST`), or the target at the
   dense nebula core (concealment ≥ `LOCK_BREAK_T` with hysteresis, under
   `apply_concealment`) ⇒ False.
4. **Reach** — True if ANY branch holds:
   - **range**: centre distance ≤ effective range after the nebula shrink — exactly
     today's test, including a caller-supplied cross-set `dist_sq_gu`;
   - **over-boost**: same set ∧ target not fully cloaked ∧
     `observer sensors.GetNormalPowerPercentage() > overboost_threshold` ∧ not jammed;
   - **memory**: same set ∧ target not fully cloaked ∧
     `observer sensors.IsObjectKnown(target)` ∧ not jammed;
   - *(sub-project 4 adds: a probe of the observer reaches the target.)*

"Same set" and "not fully cloaked" guard only the two new branches, because BC's set and
absolute-cloak gates precede them. The range branch is untouched, so the cloak bubble and
cross-set torpedo guidance behave exactly as before.

**Jammed** — `sensor_detection.jammed(observer, target)`: either ship is inside a
`MetaNebula` in the observer's set (`contact_index.nebulae_in(set)`,
`MetaNebula.IsObjectInNebula`). This is BC's boolean, distinct from the density
`concealment_at`. The radial system-profile nebula is not a `MetaNebula` and never jams.
Evaluated only when a new branch is otherwise satisfied (in range never needs it).

**Toggle-off:** `ENHANCED_SENSOR_CONTEST` and `apply_concealment` do not switch the new
branches off — they are BC's rules, not part of the stage-4 sensing contest.

## Architecture

| Unit | One idea | Change |
|---|---|---|
| `engine/appc/sensor_detection.py` | The one detection rule | `can_detect` keeps its gates and signature; after today's range test fails it asks a new private `_beyond_range_reach(observer, target, cloaked)` (the over-boost and memory branches). No `_hidden`/`_reached` split — the hide gates already return early, so the reach step is simply "range test, else beyond-range reach". New public `jammed(observer, target)`. New public `in_reach(observer, target)` = reached ignoring the hide gates (for `is_concealed`); its range branch uses the **unshrunk** effective range (today's `is_concealed` test), takes no density sample and mutates no latch, so a ship in the dense core still counts as in reach. |
| `engine/appc/subsystems.py` `SensorSubsystem.IsObjectVisible` | SDK surface | Keeps BC's same-set gate (`can_detect`'s range branch has none — cross-set torpedoes need that), then returns `can_detect(owner, obj)` (0/1). Its private copy of the jam and over-boost logic is deleted. `IsObjectNear`/`IsObjectFar` unchanged. |
| `engine/appc/sensor_contacts.py` `is_concealed` | Lost-track clock | "Inside player sensor range" becomes `in_reach(player, obj)`. A remembered or boosted contact that a rock hides runs the 5 s clock; a lost track ends its memory, so it then drops out of reach. |
| `engine/appc/sensor_dials.py` | Tunables | `overboost_threshold` 1.2 (RE'd `0x0089054c`), step 0.01, min 0.0. |
| Roadmap | Standing decisions | Row 2 merged `0f3db1e7`; decision 2 overturned with the evidence above; new evidence rows; SP3 row; probes row becomes SP4. |

Known-ness is read from the **observer's** `SensorSubsystem.IsObjectKnown`. AI has no
identification tier (roadmap decision 6), so an AI observer's known set is empty in
practice and memory never applies to AI. AI never sets sensor power above 1.0
(`ships.py` alert-level power), so over-boost never applies to AI in practice either. Both
are symmetric by construction, not by special case.

## Behaviour changes (deliberate, pinned by tests)

1. An identified ship stays listed, named, targetable and lockable after leaving sensor
   range. It drops when jammed (either ship in a MetaNebula), fully cloaked, hidden for
   the continuity window (track lost), out of the set, or when the player's sensors are
   disabled or off.
2. Sensors at > 120% normal power, with neither ship in a MetaNebula, list every
   uncloaked ship in the set — unidentified ones as "Unknown N".
3. The SDK's direct `IsObjectVisible` callers (`TacticalInterfaceHandlers` enemy filter
   :797/:867, E3M2 debris auto-target, E1M2 asteroid button) now get occlusion, the
   nebula core and the cloak contest, identical to the list: a fully cloaked ship inside
   the cloak bubble is visible to them (BC: never), and a cloaked ship outside it is not,
   even when known. `test_sensor_bands_and_visibility.py::test_fully_cloaked_is_never_visible`
   is rewritten to that rule.
6. A known ship that a rock hides keeps running the lost-track clock after it leaves
   sensor range (memory keeps it in reach). `test_sensor_continuity.py::
   test_leaving_range_while_hidden_stops_the_clock` is rewritten: leaving range while
   hidden now stops the clock only when the contact is also nebula-jammed.
4. Torpedo guidance and the player's lock follow both new branches (BC:
   `IsValidTarget` and the weapon target list use `IsObjectVisible`). Weapons keep their
   own range limits.
5. Fewer `ET_TARGET_LIST_OBJECT_REMOVED` events (remembered contacts no longer fall off
   at range). The only SDK listener is `ScienceMenuHandlers` (Scan button removal): a
   remembered contact keeps its Scan button.

## Audit (plan task)

Before behaviour lands: `ScienceMenuHandlers`' removal path; every SDK and engine
consumer that assumed "out of range ⇒ off the list" (grep `ET_TARGET_LIST_OBJECT_REMOVED`,
`perceivable`, `clear_undetectable_player_lock`); E2M2's unidentified-ship beat; the
E2M2/E7M6 `IsBoosted` beats (must still fire — they read power, not the list). Findings
recorded in the plan's ledger; anything unsafe becomes a guard in
`sensor_mission_guards.py`.

## Performance

The new branches cost a set compare, a cloak read, one power read or one set-membership
read, and — only when one of those passes — a nebula membership test over the set's
MetaNebulae (usually 0–3). In-range contacts never reach the new branches. Verified by a
headless benchmark extending `test_sensor_occlusion_bench.py`'s roster with known,
out-of-range contacts and a boosted observer (CPU `process_time`, recorded budget). A
frame-profiler run is optional and only with Mark's approval of the launch.

## Testing

Unit (`tests/unit/`):
- memory: known ∧ out of range ⇒ True; unknown ∧ out of range ⇒ False; known ∧ out of
  range ∧ target in a MetaNebula ⇒ False; same with only the observer in one ⇒ False;
  known ∧ other set ⇒ False; known ∧ fully cloaked ⇒ False; known ∧ rock-blocked ⇒ False;
  sensors disabled ⇒ False.
- over-boost: NormalPowerPercentage = threshold + ε ⇒ True at any distance; exactly the
  threshold ⇒ False (strictly greater); jammed ⇒ False; cloaked ⇒ False; other set ⇒
  False; boosted reach never identifies (no `AddKnownObject`, no
  `ET_SENSORS_SHIP_IDENTIFIED`); the dial moves the threshold.
- `jammed`: observer-in / target-in / neither / profile-nebula-only ⇒ False.
- AI observer never reaches by memory.
- `IsObjectVisible(obj) == can_detect(owner, obj)` across the matrix above.
- continuity: a remembered, out-of-range contact behind a rock loses its track after the
  window; it is then out of reach and unlisted.
- range branch byte-identical: the existing `test_sensor_detection.py` matrix passes
  unchanged (including cross-set `dist_sq_gu`).

Integration (`tests/integration/`): a real mission — identify a ship, move it beyond
range ⇒ still listed by name; put it in a MetaNebula ⇒ gone; raise player sensor power to
1.25 ⇒ every ship in the set listed, the far ones Unknown.

Gate: `scripts/check_tests.sh` exit 0.

## Out of scope

Probes (sub-project 4, which adds the probe branch to reach and to the bands); a range
multiplier for boost (dropped by D1); persisting memory across set changes (BC wipes on
the player leaving the set — unchanged).

## Live check (for Mark)

`./build/dauntless --developer` from the worktree. Identify a ship, fly until it is
beyond sensor range: it stays on the list with its name. Push sensors to 125% in
Engineering: far ships appear as Unknown. Enter a nebula: remembered far ships and the
boosted ones drop. E2M2: the boosted-sensor eavesdrop still plays.

## Audit findings (Task 1)

SDK root: `/Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts`.

| Consumer | Assumes out-of-range ⇒ absent? | Verdict |
|---|---|---|
| `Bridge/ScienceMenuHandlers.py:205` `ExitedSet` (the only SDK listener of `ET_TARGET_LIST_OBJECT_REMOVED`, registered `:93`) — removes the ship's Scan Object submenu row via `pScanMenu.RemoveItemW` | yes, implicitly (it only runs when the event fires) | safe — expected per brief: if the REMOVED event never fires for a remembered out-of-range contact, its Scan button simply stays. That is BC's own behaviour once memory applies (the button is gated on identity, not range) |
| `engine/appc/target_menu.py:242` `_post_membership_changes` — the only emitter of `ET_TARGET_LIST_OBJECT_REMOVED`/`_ADDED`, diffs `listed = {c.ship for c in self._contacts if c.targetable}` each push | no — `targetable` is read straight off `Contact.targetable`, which is itself `perceivable and alive_or_wreck and IsTargetable()` (`engine/appc/perception.py:248`), and `perceivable` is `range_gu > 0.0 and can_detect(...)` (`perception.py:230`). Once `can_detect` grows the memory/over-boost branches, this membership diff follows automatically — it has no separate range check of its own | safe by construction — this is the intended propagation path for behaviour changes 1/2/5 |
| `engine/appc/sensor_detection.py:437` `clear_undetectable_player_lock` — drops the player's weapon lock when `not can_detect(player, target)`; called every tick from `engine/host_loop.py:10689` | no — gates on `can_detect` directly, the same predicate being extended | safe by construction — behaviour change 1 says the lock explicitly follows memory/reach now (a remembered contact stays lockable); this is the mechanism that makes that true, not a consumer that would misbehave |
| `engine/ui/sensors_panel.py:1-13` (radar disc) — draws a contact when its pushed record says `perceivable` | no — the module's own docstring says the disc clips to `RadarDisplay.GetRange()` (a display scale, `DEFAULT_RANGE_GU`), independent of `perceivable`'s range term; "the target list legitimately lists contacts the disc does not draw" already, today | safe — pre-existing, documented divergence; this is exactly the "radar disc clip is fine" case the brief calls out as acceptable |
| `engine/appc/sensor_contacts.py` `is_concealed` (lost-track clock) | yes, today: "inside player sensor range" gates the clock | **addressed by the architecture, not left unsafe** — the design (Architecture table, this spec) already changes its range read to the new `in_reach(player, obj)`; behaviour change 6 and its rewritten test (`test_sensor_continuity.py::test_leaving_range_while_hidden_stops_the_clock`) are part of the same plan, not a surprise this audit found uncovered |
| `AI.Preprocessors.SelectTarget.FindGoodTarget` / `AI.PlainAI.StarbaseAttack.GetTargets` / `FireScript.TargetVisible` via `engine/appc/ai_sensor_gate.py` | no — all three route through the one shared `can_detect`, same as the target list | safe — AI's own `IsObjectKnown` is empty in practice (no SDK path calls `ForceObjectIdentified` on a non-player ship, see below) and AI never raises sensor power above 1.0×, so the new branches are inert for AI observers, by the same construction the spec states, not a special case added here |
| `Maelstrom/Episode2/E2M2/E2M2.py:1930` `CheckSensorBoost`, `:2008` `CheckSensorLoop` — `MissionLib.IsBoosted(pSensors, 1.2)` | n/a (reads power, not the list) | safe — `MissionLib.IsBoosted` (`MissionLib.py:2315`) is `pSubsystem.GetNormalPowerPercentage() > fBoostLevel`, a direct power read with no dependency on `can_detect`/target-list membership. Confirmed unaffected; the beat still fires exactly as before |
| E2M2 unidentified-ships beat — `ET_SENSORS_SHIP_IDENTIFIED` handler `:567`/`ShipIdentified`, `MissionLib.IdentifyObjects(pShip)` at `:982`/`:1235` | n/a (identification tier, not reach) | safe — identification is unchanged by this sub-project ("identification still needs the near band", Goal #2); `IdentifyObjects` always targets `MissionLib.GetPlayer()`'s sensors (`MissionLib.py:2436-2445`), never an NPC's |
| `Maelstrom/Episode7/E7M6/E7M6.py:607,865,2158,2518` — all `MissionLib.IsBoosted(pPlayer.GetSensorSubsystem())` or a direct `GetNormalPowerPercentage()` read | n/a (power reads) | safe — same as E2M2; no target-list dependency |
| `Maelstrom/Episode8/E8M1/E8M1.py:2699` — `pPlayer.GetSensorSubsystem().GetNormalPowerPercentage() > 1` | n/a (power read) | safe — same reasoning |
| `MissionLib.py:2315` `IsBoosted` itself | n/a | safe — pure `GetNormalPowerPercentage()` comparison, no reach/list coupling of any kind |
| AI memory exposure — every SDK call site of `ForceObjectIdentified`/`AddKnownObject`: `MissionLib.py:2445` (`IdentifyObjects`, always `MissionLib.GetPlayer()`'s sensors), `Maelstrom/Episode3/E3M4/E3M4.py:1500`, `Maelstrom/Episode4/E4M4/E4M4.py:1077`, `Bridge/HelmMenuHandlers.py:1056` (orbit-menu planets) | — | safe, verified by inspection: all four call sites resolve `pSensors = pPlayer.GetSensorSubsystem()` before calling `ForceObjectIdentified` — none targets a non-player ship's sensors. `engine/appc/subsystems.py:1451` `ForceObjectIdentified` is confirmed **not** player-gated in our implementation either (unlike `IdentifyObject`, `:1440`, which explicitly no-ops off-player) — it calls `sensor_identification._identify_one(self, pTarget)` on whichever subsystem instance is called. No current consumer, SDK or engine, calls it on an NPC ship, so the design's "AI's known set is empty in practice" holds today. ⚠️ Noted as a latent risk, not a finding: a *future* call site that calls `someNPCShip.GetSensorSubsystem().ForceObjectIdentified(x)` would give that ship memory through the new branch; nothing currently does |

**No UNSAFE consumer found.** Every direct `can_detect`/`perceivable`/target-list consumer is either (a) one of the behaviour changes the spec explicitly plans (membership diff, weapon lock, lost-track clock — all cited in "Behaviour changes" above) or (b) structurally independent of range (power reads, radar's own display clip, identification tier). The one open item is a documentation note, not a guard: `ForceObjectIdentified` is unguarded against being called on a non-player ship, but no call site today does so.

## As built

- No deviations from the spec beyond its own amendments (`IsObjectVisible` keeps the
  same-set gate; no `_hidden`/`_reached` split; the cloak-contest change to
  `IsObjectVisible`; the continuity test rewrite) — all already written into the
  Architecture/Behaviour-changes sections above during execution, not introduced after.
- The plan's Task 5 text said "three tests" but listed four; all four were added.
- Audit (Task 1) verdict: **every consumer is safe** — the Science scan-button removal
  path, the engine's `perceivable`/target-list membership diff, the player lock-clear,
  the lost-track clock, AI's perceivable/target-visible gate, and the E2M2/E7M6/E8M1
  `IsBoosted` beats (pure power reads, no list dependency) all either already assumed the
  new behaviour by construction or are structurally independent of it. One latent,
  non-blocking risk noted, not fixed: `SensorSubsystem.ForceObjectIdentified` is not
  player-gated (unlike `IdentifyObject`), so a future call on an NPC's own sensors would
  give that AI memory through the new branch; no SDK caller does this today.
- Bench (Task 6): the beyond-range branch (memory/over-boost reach) costs **≈1.15×** the
  in-range per-call CPU cost — well inside the ≤3× budget.
- Mutation probe (Task 6 review): stubbing `_beyond_range_reach` to `False` fails all 5
  of the E2M1 integration tests, confirming they exercise the new branch and not just the
  unchanged range path.
- Deferred minors, left as-is per the plan's ledger: `test_ai_observer_never_reaches_by_memory`
  duplicates the unknown-out-of-range test; `GetNormalPowerPercentage()` is called
  unguarded beside an `implements`-guarded `IsObjectKnown` in `_beyond_range_reach`
  (harmless).
