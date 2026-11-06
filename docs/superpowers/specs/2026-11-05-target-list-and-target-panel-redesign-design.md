# Target list and target panel redesign

**Status:** design approved in mockup by Mark, 2026-11-05. Built and live-verified by Mark 2026-11-06 (one fix from the live check: locking a single subsystem closes the open family).
**Lands after:** `ws/motion-phase6-a1` (see §8). Build on `main` once that branch is merged.
**Mockup (the reference for every visual detail):**
`.superpowers/brainstorm/28763-1793886627/content/target-panel-v54-family-shortcuts.html`
(gitignored, on Mark's machine). It runs the game's own `target_list.js`,
`ship_display.js` and their CSS, with mockup data. Open it through the
brainstorm server, or read it as source. Earlier steps (v2 to v53) sit beside it.

Who decided what: **(Mark)** marks a decision Mark made in the mockup
session; **(my call)** marks one I made that he saw and did not object to;
anything unmarked is description of the existing game.

## 1. Why

In a busy fight the left column has to answer two questions fast: *which
ship do I want?* and *which part of it do I want?* Today both live in one
list. Expanding a ship's row pushes every other ship down, and only one
ship can be expanded at a time, so picking a subsystem means scrolling a
list that keeps changing length.

The redesign splits the two questions:

- the **target list** becomes a compact way to find and pick ships
  (filter by side, sort, distance at a glance), and never expands;
- the **target panel** (the target `ShipDisplay`, `ship-target`, above the
  list) becomes the one place for everything about the targeted ship,
  including choosing and seeing its subsystems.

## 2. Goals, non-goals, anti-goals

**Goals**

- Find a ship quickly in a long list: filter out sides you don't care
  about, sort the rest, see distance and health without opening anything.
- Pick a subsystem in one or two clicks, from a fixed-size control that
  shows the whole ship's state at a glance.
- Always show where the locked subsystem is on the ship.
- Work for any stock ship, not just the Akira: tested in the mockup on the
  Akira (8 families) and the Warbird (10 families, cloak, disruptor beam,
  disruptor cannons).

**Non-goals**

- No change to what can be targeted or locked. The engine rules
  (`target_list_view.dispatch_event`, non-targetable group headers, the
  sensor tiers' "Unknown N") are unchanged; this is presentation.
- No change to the player's own `ShipDisplay` (`ship-player`), the radar,
  or the weapons display, **except** that the player panel's damage icons
  get the same new glyphs (§6) and the same placement fix (§4.2) (Mark:
  one shared change for both panels).
- No "who is targeting me" view. Phase 6 builds a seam for it (§8); not
  this work.

**Anti-goals** (would make this a failure even if it works)

- UI shudder: things that appear and disappear and move the layout under
  the cursor. Mark rejected a disappearing name bar for exactly this
  (§5.4).
- A subsystem lock that silently fails or clears. Every click that looks
  like it locks must lock.
- A per-frame cost that shows up in the frame profiler at 64 ships. The
  list re-sorts live and the panel reads every subsystem's state (§7).

## 3. Target list

Spec of the current list: `2026-05-11-target-list-from-scene-design.md`,
`2026-06-02-target-list-health-bars-design.md`; code
`native/assets/ui-cef/js/target_list.js`, `css/target_list.css`,
`engine/ui/target_list_view.py`.

### 3.1 Filter tabs (Mark)

A strip of three equal tabs directly under the "Targets" header, inside
the panel's 4px left edge. Each toggles the visibility of one affiliation:

| Tab | Shows | Lucide icon |
|---|---|---|
| 1 | Friendlies (`FRIENDLY`) | `shield` |
| 2 | Neutrals (`NEUTRAL`) | `satellite-dish` |
| 3 | Enemies (`ENEMY`) | `locate-fixed` |

- All three start **on** (my call).
- On: the side's row tint (`rgba(.., 0.35)` / neutral `0.30`), a 2px
  underline in the side's radar colour, bright icon. Off: dark grey
  `rgba(40,40,40,0.6)`, faint icon; hover brightens the icon a little
  (my call).
- `UNKNOWN` contacts ("Unknown N") have no tab and **always show** (my call).
- Hidden rows drop out of the list; the list closes up.

### 3.2 Sort (Mark)

A strip of three radio buttons pinned at the **bottom** of the list, under
the scrolling body, so it stays visible when the list scrolls:

| Button | Order | Lucide icon |
|---|---|---|
| Name | A to Z by displayed label | `id-card` |
| Distance | closest first | `radar` |
| Health | weakest first | `heart-pulse` |

- **Name is the default** (Mark). (Today's list is unsorted: contact order.)
- Exactly one is active; clicking the active one does nothing.
- Active: the header's salmon gradient with a black icon, so "one of three"
  reads differently from the colour-coded filters (my call).
- **Re-sorts live** as distance and health change (Mark). Note the list
  updates at its existing cadence (2 Hz, see
  `docs/reference/engine/perf-cadences-and-latency.md`), so "live" means
  each list update, not each frame.
- Health = hull first, then shields, then name. A target with no shields
  (an asteroid) counts as 0 shields (my call).
- Ties always fall back to name, so the order is stable (my call).

### 3.3 Rows (Mark)

- **No chevron and no expanding** in the list. The chevron and its 22px
  slot go, so names sit flush left. Subsystems move to the panel (§4).
- **Distance** in each row, between the name and the bars, right-aligned
  against the bars so the numbers form a column (alignment is my call),
  formatted like the old panel readout: `29.62 km`, 11px, dim
  (`--bc-row-text-dim`), tabular numbers. Use the same value the panel
  and reticle used (`_range_and_speed_to`: distance to the target's
  bounding sphere, converted at the display boundary via `engine.units`).
  The contact record already holds it (`Contact.surface_gu`).
- **Stacked bars:** shields directly on top of hull, no gap, each 4px
  (half the old 8px), 32px wide. A target with no shields shows the hull
  bar alone at the full 8px.
- Row tints, chosen/hover states, markers (`protect`, `target`) unchanged.

## 4. Target panel

Spec of the current panel: `2026-05-28-ship-display-panel-design.md`;
code `native/assets/ui-cef/panels/ship_display/`, `engine/ui/ship_display_panel.py`.

Top to bottom: header (ship name), ship icon with shield arcs, hull bar,
then the subsystem area. The title is the targeted ship's name.

### 4.1 Speed and range (Mark)

- **Speed** moves to the top-right corner of the ship icon, 11px dim with
  a soft shadow, above the shield arcs.
- **Range** leaves the panel (it is in the list now). The old row under
  the hull bar (`ship-display__target-extras`) is gone.

### 4.2 Locked-subsystem marker (Mark)

Whenever a subsystem is locked, its glyph is drawn on the ship icon at its
hardpoint `SetPosition2D`, **at all times**, whatever its health, inside
**gold corner brackets** (`rgb(255,210,90)`), **no backing**.

- Glyph colour follows the BC state rules of §5.2: healthy uses the plain
  label colour; damaged / disabled / destroyed use BC's colours. Mark
  reviewed the faint disabled-grey marker and accepted it.
- Sits above the shield arcs, below the speed text.
- The existing BC damage icons for other subsystems keep their rule (shown
  only once damaged); unchanged by this work.

**Placement fix (needed by the marker, and fixes a live bug from the
code).** `Position2D` is in BC's 128px ship-icon frame. Today
`ship_display.js` maps `x/128`, `y/120` across the **whole silhouette
stack**, about 204px wide, while the ship image is drawn
`object-fit: contain` as a centred square about 120px wide. So damage
icons land off the ship (Port Warp at x=4 sits about 36px left of its
nacelle). The mockup places against the drawn image box:

```
side = min(stack.width, stack.height)
left = (stack.width  - side) / 2 + x / 128 * side
top  = (stack.height - side) / 2 + y / 128 * side
```

and the hull dots then land on the Akira's and Warbird's hulls, cannons at
x = 0 and 128 included. Apply the same mapping to the existing damage
icons, **in both panels**, player and target (Mark). ⚠️ The y divisor (128 vs today's 120) is the mockup's assumption
from the 128×128 ship icons; check it against BC's `DamageIcon` placement
before fixing the existing icons (§9).

### 4.3 Family buttons (Mark)

The ship's **top-level subsystems** ("families": Sensor Array, Impulse
Engines, Phasers, Warp Core...) are square buttons in a grid, with a glyph
and no text. These are exactly today's top-level rows of the target list's
subsystem tree (the same filter: hull excluded, a non-targetable
subsystem shown only as a group header over targetable members; see
`STTargetMenu._add_subsystem_row`).

- **Columns from the family count:** 6 or fewer → 6 columns; 7 or 8 → 8
  columns; more than 8 → 6 columns (Mark). Akira (8) = one row of 8;
  Warbird (10) = 6 + 4.
- Square (`aspect-ratio: 1`), 3px gaps, 8px sides, grey
  `rgba(40,40,40,0.6)`.
- Glyph colour by BC state (§5.2), taken from **the family's own subsystem
  condition**, not its members' (Mark). A family can therefore look healthy
  while one of its members is hurt; the member blocks show that once the
  family is open. **Disabled fills the whole button with
  BC's disabled grey and the glyph turns black** (Mark). Disabled wins over
  the open tint (my call).
- **Open** family (its members are showing): the enemy row tint
  `rgba(216,43,43,0.35)` behind the glyph (my call; the affiliation tint
  of the target).
- **Holds the lock** (itself, or one of its members): the same gold corner
  brackets as the ship marker (Mark).
- No `title=` tooltips: they show nothing in the game's off-screen CEF view.
  The name bar (§4.4) is the family buttons' hover text. The filter and sort
  buttons (§3) have no name bar, so they use the page-drawn `[data-tip]`
  tooltip from `configuration_panel.css` (my call).

**Clicks** (Mark):

| Click | On a family with 2+ members | On a family with exactly 1 remaining member | On a single subsystem (Sensor Array, Shield Generator, Warp Core...) |
|---|---|---|---|
| single | open it (close any other); click again to close | lock that member and open the family; click again to unlock | lock it and close any open family; click again to unlock (also closes) |
| double | open it and lock its **first remaining member** | same as single (lock) | lock it and close any open family |

- Double-click = two clicks on the same button within **350 ms**, detected
  by the page, not the browser's `dblclick` (each click redraws the
  buttons, and the browser's event is unreliable when the node under the
  mouse is replaced). Mark accepted the side effect: two fast clicks can
  no longer open-then-close a family.
- "First remaining member" skips destroyed members (they are not listed,
  §4.5). Warbird Disruptor Cannons with Port Cannon 1 destroyed → Port
  Cannon 2.
- One family open at a time.
- **A family that is itself lockable** (e.g. `cardstarbase.py`'s "Torpedoes",
  `SetTargetable(1)` with tubes under it; the current list lets you lock that
  row): a single click locks the family itself and opens it, like a family
  of one; a double-click still locks its first member (my call). This is
  what the payload's "lockable" flag is for.
- Unlocking sends the existing "set target, no subsystem" event
  (`target/<ship>`); no new event needed.

### 4.4 Name bar (Mark)

A full-width bar under the buttons, same grey as the buttons, one grid gap
(3px) below them, **text centred**, 12px.

- Text priority: the hovered button's name, else the open family, else
  the locked subsystem.
- **Empty (no text) when nothing is locked and no button is hovered**, but
  the bar always stays, at a fixed height, so nothing moves (Mark: a
  disappearing bar caused "too much UI shudder").
- ⚠️ Consequence, still open (§9): a family open with nothing locked shows
  an empty bar.

### 4.5 Member blocks (Mark)

When a family is open, its members are blocks in a grid under the name bar.

- **Columns from the member count:** 1 member → 1 column (full width),
  2 → 2, 3 or more → 3.
- Grey block (`rgba(40,40,40,0.6)`), 3px gaps, name inside, **left-aligned**
  (centred was tried and rejected), 11px, `text-wrap: balance` so a
  two-line name keeps its number with it ("Forward / Torp 1"; Chromium
  114+, the CEF build is Chromium 144).
- **No health bar.** Health is a **3px left edge in the BC state colour**:
  none (transparent, space kept) when healthy, lime when damaged (Mark).
- **Disabled fills the whole block with BC's disabled grey and the name
  turns black** (Mark).
- **Destroyed members drop off the grid** (Mark). The column count uses
  the remaining members, so a family can reflow mid-fight. This matches
  the existing list: `_keep` in `engine/ui/target_list_view.py` delists a
  destroyed leaf, and drops a family once every member is destroyed, so
  its **button disappears** and the family grid can reflow (8 columns → 6).
- **A locked member that is destroyed:** existing code handles it.
  `reconcile_subsystem_lock` (same file) runs every tick, hands the lock to
  the next surviving member of the same family, and clears it once the whole
  family is gone. So the destroyed-orange ship marker is rarely seen.
- **Locked:** the enemy tint behind it and a **full-width 2px white
  underline**, drawn as a pseudo-element so it runs under the left edge
  and never changes the block's height (Mark: white underline instead of
  corner brackets).
- Click a block to lock it; click the locked block to unlock it.
- Opening and closing a family moves what is below (Mark: acceptable).

### 4.6 Height and minimising

- **The panel sizes to its content** (Mark). Its height changes with no
  target, an "Unknown N" target, a cloaked target (its subsystems are not
  targetable, so no buttons), and between a one-row and a two-row family
  grid; the list below moves when you switch targets. Accepted.
- **Minimising hides the whole body**, subsystem picking included (Mark:
  accepted). No subsystem can be picked from the panel until it is opened.

### 4.7 Short screens

The panel never shrinks (`flex: 0 0 auto`), and the target list is the
part that gives way and scrolls. The panel is now about 190px taller with
a family open, so on a short window the list loses rows first (seen in the
mockup at 520px tall). Not decided (§9).

## 5. Colour and state rules

### 5.1 What is BC's and what is ours

Checked against the SDK (`LoadInterface.py:143-153`):

- BC's damage display has **three** colours: destroyed
  `g_kDamageDisplayDestroyedColor` (1.00, 0.25, 0), damaged
  `g_kDamageDisplayDamagedColor` (0.72, 1.00, 0), disabled
  `g_kDamageDisplayDisabledColor` (0.6, 0.6, 0.6). **No healthy colour**:
  BC does not draw a healthy subsystem's icon.
- BC's subsystem health-bar fill `g_kSubsystemFillColor` (183.6, 255, 0)
  is the **same lime** as "damaged", used for the hull gauge
  (`Tactical/Interface/ShipDisplay.py:37-50`).
- Ours, not BC's: the label off-white `--bc-label-text` (235, 225, 255),
  the hull-bar green (50, 210, 80), the shield-arc colours.

### 5.2 The rules this design uses (Mark)

- State ladder, BC's (`ship_display_panel._row_state`): destroyed
  (condition 0), else disabled (at or below `SetDisabledPercentage` ×
  max), else damaged (below max), else healthy.
- **Healthy is unmarked** (Mark, following BC): no left edge on blocks;
  a button glyph keeps the buttons' plain resting colour
  `rgba(235,225,255,0.75)`, bright on hover.
- Damaged: lime. Disabled: grey fill, black glyph/name. Destroyed: orange
  (seen only on the ship marker, since destroyed members drop off).
- Gold `rgb(255,210,90)` = the lock (brackets). Mark: the amber/gold
  closeness is fine.

## 6. Icons

All subsystem glyphs **replace** BC's `DamageIcons` SVGs outright (Mark:
"imagine we replaced the svg altogether"), in the family buttons, the
lock marker, and the damage icons of **both** ship panels (Mark). Lucide, ISC licence, version used in the mockup 1.69.0;
add a Lucide entry to the existing third-party notice.

| Subsystem type | Lucide icon | Note |
|---|---|---|
| Sensors (4) | `radar` | |
| Impulse family and pods (1) | `chevrons-up` | |
| Warp Engines family | `margin-horizontal` | the family button only |
| Warp pods (8) | `usb-c-port`, rotated 90° | rotation baked into the SVG |
| Torpedoes (7) | `test-tubes` | |
| Phasers and beams (2) | `laser` | includes the Warbird's Disruptor Beam |
| Disruptor cannons, pulse (9) | `loader` | Mark: close to `laser` on purpose, similar function |
| Tractors | `wand-sparkles` | Lucide's current name for `magic-wand` |
| Cloak | `eye-off` | |
| Shield Generator (5) | `shield-plus` | |
| Power (3) | `zap` | Warp Core / Power Plant |
| Fallback, any other type (6) | `boxes-linked` | e.g. mod subsystem types |
| Hull (0) | not shown | the hull is the ship-level bar |

**Mapping changes the builder must make:** `engine/ui/damage_icons.py`
maps by subsystem class today, and several classes fall to 6 (System):
engine pods are plain `ShipSubsystem`s (`ships.py`, "Pass 5"), and
`TractorBeam` and the cloak have no entry. The new mapping needs:

- an impulse pod → impulse icon, a warp pod → warp-pod icon, decided by
  the pod's parent (`EngineProperty.EP_IMPULSE` / `EP_WARP`), not its class;
- tractors and the cloak → their own icons;
- a **family** icon that can differ from its members' (Warp Engines);
- every other unmapped type → the fallback.

Lucide icons are stroked outlines (`stroke="currentColor"`), BC's were
filled; the state colouring works through `currentColor` either way.

## 7. Engine side

- **The list payload** (`TargetListView.render_payload`) gains, per row:
  distance (km, from the contact record). Filter and sort state live in
  Python; the page only draws the rows it is given, in order (my call:
  matches how the list already works, and keeps the order consistent
  with keyboard target cycling, if that should follow it; see §9).
  The subsystem tree leaves the list payload.
- **The panel payload** (`ShipDisplayPanel.render_payload`, target role)
  gains: the family list with, per family and member, name, state, icon
  key, `Position2D`, lockable or not; the locked subsystem.
- **Clicks** keep the existing event protocol (`target/<ship>`,
  `target/<ship>/<subsystem>`, `.../__toggle__`), now coming from the panel.
  Filter and sort need new events (e.g. `target-list/filter/<AFF>/on|off`,
  `target-list/sort/<name|distance|health>`, as the mockup logs them).
- **Persistence:** whether filter and sort survive a mission change or a
  relaunch is not decided (§9).
- **Cost:** the panel now reads every subsystem's condition and state each
  time it builds its payload, and the list sorts on every update. After
  phase 6 these reads go through `Native*` descriptors (§8). Build the
  payloads only when something changed (the panels already compare
  snapshots), and measure with the frame profiler at 64 ships
  (`DAUNTLESS_MISSION=engine.dev_missions.combat_stress`) before calling
  it done.

## 8. Lands after `ws/motion-phase6-a1`

That branch (phase 6, part A1) moves the subsystem stage to C++ and is
merged before this work. What it changes for us:

- `engine/appc/subsystems.py` loses the Python update paths for power,
  shields, cloak and repair. **Subsystem state becomes native-authoritative**:
  Python reads `GetCondition`, `IsDamaged`, `IsDisabled`, `IsDestroyed`
  through `Native*` descriptors (`_condition`, `_max_condition`,
  `_disabled_percentage`, `_destroyed` are `NativeField`s). Read through
  the public getters only; never cache a Python copy of a condition.
  Spec: `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md`
  ("State of record").
- `engine/host_loop.py` `_pump_contacts` (which feeds the target list)
  gains `frame_profiler` scopes (`contacts.perceive`, `contacts.push`,
  `contacts.colors`, `contacts.persist`). Rebase onto them; add any new
  list work inside a scope of its own so its cost is visible.
- The phase 6 spec plans "targeted by" counts per (set, target) and names
  "the planned 'who is targeting me' target-list UI" as a later consumer.
  Leave room for a per-row indicator; don't build it.
- No UI file (`engine/ui/`, `native/assets/ui-cef/`) is touched by the
  branch.

## 9. Open questions

1. **Empty name bar with a family open.** With nothing locked, an open
   family has no name shown. Should the bar show the open family's name?
   (Raised twice; not answered.)
2. **Icons with two meanings across the two panels:** `radar` = sensors
   (panel) and distance sort (list); a shield = Shield Generator
   (`shield-plus`) and the Friendlies tab (`shield`). Keep or change?
3. **Hiding the current target's side.** Today its row vanishes while the
   panel keeps showing it. Clear the target, keep its row, or leave it?
4. **Short screens** (§4.7): should the member area scroll instead of the
   list?
5. **Keyboard target cycling** (`CycleTarget`): should it follow the
   list's filter and sort?
6. **Persistence** of filter and sort state.
7. **The y divisor** of the `Position2D` mapping (§4.2): 128 or 120.
   Check before fixing the existing damage icons.

## 10. Left to the builder

- Markup, class names, and how the panel's subsystem area is split into
  files.
- How filter/sort state is stored and passed.
- Where the Lucide SVGs live (they replace `native/assets/ui-cef/icons/damage/*.svg`
  or sit beside them) and how the icon key reaches the page.
- Test changes. Existing tests that assert today's behaviour and will need
  updating include `tests/ui/test_target_list_caret.py`,
  `tests/integration/test_target_list_subsystems.py`,
  `tests/integration/test_target_list_sdk_integration.py`,
  `tests/integration/test_ship_display_sdk_integration.py`,
  `tests/host/test_ship_display_damage_descriptors.py`,
  `tests/unit/test_damage_icons.py`. Run only focused tests during the
  work (CLAUDE.md, "Test gate").

## 11. Not verified

- Nothing here has run in CEF; the mockup is desktop Chrome 156. The
  layout, `text-wrap: balance`, and the 350 ms double-click need a live
  check in game, with a real mouse.
- Subsystem row **order** comes from the ship's subsystem iteration; the
  mockup guessed the Warbird's order after the weapons.
- The damage-icon misplacement (§4.2) follows from the code; not seen in
  play.
