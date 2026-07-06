# Power Panel Redesign — Design

**Date**: 2026-07-06
**Status**: Approved (visual design locked interactively — 28 previz iterations)
**Canonical mockup**: `docs/ui_designs/06-engineer-panel.html` (v28 from the
previz session; supersedes `06-engineer-panel.html` + `07-power-transmission-grid.html`)
**Scope**: presentation + panel payload only. The EPS simulation
(`feat/power-management` branch) is untouched.

## Goal

Rebuild the Engineering power panel (`engpower`) to the dauntless design
system (LCARS-inspired: Antonio, palette tokens, translucent body) with a
redesigned information layout validated interactively with Mark. The old
`06`/`07` design-system canon is superseded; this spec + the v2 mockup are
the new canon (per `docs/ui_designs/README.md`: runtime divergence from the
canonical mockup is a fidelity bug).

## Visual structure (locked, top to bottom)

Panel: ~540 px, top-right, menu-gated (existing behaviour: shows only while
the Engineering crew menu is open). **No header bar** — chrome is the 4 px
salmon left stripe + translucent dark body (`--bc-panel-bg`) only.

1. **Slider rows** (Weapons / Engines / Sensor Array / Shields — note
   "Shields", not "Shield Gen"; no colour dots):
   grid `[100px label] [1fr track] [50px %]`. **The row IS the slider**
   (drag anywhere on the 10 px track; `cursor: ew-resize`), fill in the
   subsystem identity colour on a 25%-opacity tint track, a 3 px white
   glowing **thumb line** at the set point, and a faint 1 px hairline at the
   **80 % track position marking 100 %** (track spans 0–125 %, pre-scaled:
   `width = pct/125`). Percentage text in identity colour, tabular numerics.
2. **Tick row**: 0 % / 50 % / 100 % / 125 % positioned at their TRUE track
   fractions (0 / 40 % / 80 % / 100 %; 100 % brightened), spanning exactly
   the track column.
3. **USED bar** (28 px) and **AVAILABLE bar** (14 px), stacked with a 14 px
   gap, sharing one axis. A **damage column** (red diagonal hatch) spans the
   full height of BOTH bars at the left; the usable axis starts after it.
   - USED: stacked segments in the four groups' identity colours,
     proportional to demand.
   - AVAILABLE: three source segments — WARP CORE blue, MAIN yellow-olive,
     RESERVE red-orange — with 2 px **boundary ticks** at each segment's
     start/end, in a brightened variant of the segment colour, flush with
     the bar's bottom edge and extending **5 px above only**.
   - Segment label row below (WARP CORE / MAIN / RESERVE; no OFFLINE
     label), each label centred under its segment (widths track the
     segment widths). Narrow-segment rule: below a 40 px segment width the
     label fades out (opacity 0) rather than overflowing.
4. **Bottom row** (full panel width, no dead space):
   `MAIN battery glyph | toggle stack (centred) | RESERVE battery glyph`.
   - Battery glyphs: rounded-corner columns (fills clipped inside), MAIN
     75 px wide — **1.5×** RESERVE's 50 px — each with a small centred
     rounded **terminal bump** on top (battery iconography). Charge fill
     bottom-up in the battery colour; name + % labels centred beneath; a
     small ▼ inside the fill when that battery's net flow this interval is
     negative.
   - Toggle stack: Tractor above Cloak, 12 px apart, state text in the
     battery colour when On / disabled grey when Off.
   - **Siphon lines**: Tractor → MAIN (leftward), Cloak → RESERVE
     (rightward); line colour = battery colour; **solid + glow when On,
     dashed when Off**; lines terminate visually at the battery glyph edge
     (rendered under the opaque glyph).
5. **Conditional presence**: the Tractor row + line render only when the
   ship's hardpoints include a tractor emitter
   (`GetTractorBeamSystem()` non-null with ≥1 weapon); Cloak row + line
   only when `GetCloakingSubsystem()` is non-null. Absent rows collapse
   (the remaining toggle centres alone; neither present → the toggle
   column renders empty).

## Data contract (faithful conduit-bandwidth axis — supersedes initial "2400" contract)

All values from existing engine getters; computed in
`EngineeringPowerPanel._snapshot()` (Python), rendered verbatim by JS.

**Supersession note:** the initial contract used `D = authored_output +
main_conduit_cap + backup_conduit_cap` (~2400 Galaxy), which placed the
reserve-drain threshold at ~42% — all-125% draw appeared inside the "main"
band, not the reserve zone. The faithful axis below is taken directly from
`PowerDisplay.py:734,681-689`.

**Shared denominator** `D = GetMaxMainConduitCapacity() + GetBackupConduitCapacity()`
(RAW conduit-bandwidth values; Galaxy 1200+200=1400). Faithful to
`PowerDisplay.py:734` `fMaxBandwidth = GetMaxMainConduitCapacity() + GetBackupConduitCapacity()`.

**Reserve-drain threshold** `reserve_threshold = GetMainConduitCapacity() / D`
(health-scaled; ≈0.8571 healthy for Galaxy). The used bar crossing this threshold
means the ship is drawing from backup/reserve power — the live bug was this
threshold invisible on the old 2400 axis.

| Element | Formula | Note |
|---|---|---|
| Damage column (right hatch) | `(GetMaxMainConduitCapacity() − GetMainConduitCapacity()) / D` | RAW max minus health-scaled; 0 when healthy |
| AVAILABLE · WARP CORE | `GetPowerOutput() / D` | health-scaled |
| AVAILABLE · MAIN | `max(0, GetMainConduitCapacity() − GetPowerOutput()) / D` | corridor between output and conduit capacity; health-scaled |
| AVAILABLE · RESERVE | `GetBackupConduitCapacity() / D` | RAW backup band; constant width unless backup conduit also damaged |
| reserve_threshold | `GetMainConduitCapacity() / D` | ~0.8571 healthy; used bar crossing = reserve draining |
| Four pieces sum to 1.0 | warp_core + main + reserve + damage = 1.0 | |
| USED segments | per group `Σ GetNormalPowerWanted() × GetPowerPercentageWanted() / D` (same D) | SDK `PowerDisplay.Update` demand math; tractor/cloak excluded (shown by siphon lines) |
| USED overload | `used_total > 1.0` → clamp all fracs to sum to 1.0; box-shadow tint | demand exceeds total conduit bandwidth |
| Pillar fills | `GetMainBatteryPower()/limit`, `GetBackupBatteryPower()/limit` | independent of grid bands |
| Drain ▼ | net battery delta over the last interval < 0 | |
| Tractor On | `_wants_power()` firing state; Cloak On = `IsTryingToCloak()` | |

Note: available segments are now **threshold bands** — they move only with reactor
damage, NOT with battery charge. Battery charge is shown exclusively by pillar fills.
The v28 mockup's proportions are illustrative; the faithful axis corrects the reserve
threshold to 0.8571 (was visually undetectable at ~42% on the old axis).

## Interaction

- Slider drag → existing `engpower/set:<group>:<value>` action →
  `Bridge.EngineerMenuHandlers.SetPowerToSubsystem` (0 % ⇒ TurnOff etc. —
  unchanged).
- Drag-safe update rules retained (build-once DOM, skip `document.activeElement`).
- Tractor/Cloak toggle click → the same toggle actions the existing
  weapons-panel tractor toggle and cloak control fire (reuse, don't invent;
  exact action strings resolved at plan time from `weapon_config.py` and the
  cloak control path).

## Files

- Rewrite: `native/assets/ui-cef/js/engineering_power.js`,
  `native/assets/ui-cef/css/engineering_power.css`
- Modify: `engine/ui/engineering_power_panel.py` (`_snapshot` payload:
  damage/available/used/pillars/presence per the table; dispatch gains the
  two toggle actions)
- Design-system canon: replace `docs/ui_designs/06-engineer-panel.html`
  with `06-engineer-panel-v2.html` content, rewrite `06-engineer-panel.md`
  to this spec, retire `07-power-transmission-grid.{html,md}` (folded into
  06; leave a pointer stub). Update the README index.
- No engine/appc changes.

## Testing

- Unit: payload shape/formulas for every table row (damage fraction,
  segment normalization sums, overload clamp, pillar fractions, drain flag,
  tractor/cloak presence & absence collapsing); toggle-action dispatch.
- Host: existing engpower routing/menu-gating tests stay green (payload
  keys change — update in the same commit).
- Live verify: visual parity with `06-engineer-panel.html`, drag
  behaviour, siphon line states, conditional presence on a non-cloak ship
  (Galaxy: tractor only) vs a warbird (both).

## Out of scope

- Any EPS simulation change.
- Keyboard ManagePower bindings (separate follow-up, noted on the branch).
- The SDK PowerDisplay widget shims (they keep running headless untouched).
