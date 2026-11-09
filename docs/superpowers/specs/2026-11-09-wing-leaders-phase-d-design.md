# Wing leaders — Phase D: wings working together

Date: 2026-11-09. Builds on the programme spec (§6 "Locations are relative to
groups") and Phases A–C. Read Phase A §2/§11 (brain, tree), Phase B §6
(`WingMoveTo`, withdraw), and Phase C §3 and §11 (slots, build rulings).
Branch `feat/wing-leaders-d`, cut from the end of `feat/wing-leaders-c`. As
with Phase C, Mark asked for this phase to be built without his spec approval.
Every choice he didn't make is marked **(call)** and listed in §10.

## 1. What Phase D delivers

Up to Phase C every wing decides alone. Phase D lets the wings on one side
see each other and act together. It adds three items from the programme table:

- **#3 Reinforce.** A wing that isn't fighting goes to help a friendly wing
  that is losing.
- **#4 Hold a location relative to groups.** No map points are used. Every
  location is recomputed from where the groups are now:
  - **flank:** an idle wing swings onto the side of an enemy cluster that a
    friendly wing is already fighting, so the enemy is caught between two
    wings;
  - **screen:** a healthy idle wing puts itself between a weak friendly wing
    and the enemies closing on it.
- **#12 Bait and feint.** A wing that is fighting pulls back toward an idle
  friendly wing (the **lure** point), so the enemy that chases it runs into
  both wings. When the trap closes it turns and fights.

## 2. Facts this design rests on (verified 2026-11-09)

- **A side.** In Quick Battle all of one side's wings target the same enemy
  group (`wings_qb`), and combat_stress builds both sides' wings the same way.
  "Same side" is made explicit: `Wing.side`, a string that consumers set
  (`wings_qb`: "friendly" / "enemy"; combat_stress: its side names). Default:
  `str(id(enemy_group))`.
- **Distances.** QB places a side's groups side by side
  (`quickbattle/placement.py`, `MARGIN_GU` 2 GU between hulls, rows), so a
  side's wings start within a few hundred GU of each other. combat_stress
  rings its wings 371 GU across. Leash is 200 GU and engage 350 GU (Phase A
  §7).
- **Targets beyond reach.** `plans.target_priorities` keeps a primary only
  when it is within leash of the anchor. With nothing in reach it falls back
  to the nearest enemy at 3.0. A wing going to another wing's fight needs a
  primary outside its own reach (§4).
- **Who moves the wing.** The commander runs the stock tree and the followers
  stay with it (rejoin, leash), so changing the wing's primary moves the
  whole wing: the commander's stock attack intercepts its target. A branch
  that moves every non-player member (withdraw) also moves the commander,
  because the commander's tree is wrapped like everyone else's.

## 3. Allies: what a wing knows about its side

The brain publishes a small **status** for each led wing at the end of its
tick. The other wings on the side read it at their next tick, so it is at
most one brain period (1 s) old.

`WingStatus` lives in pure `engine/wings/allies.py`:

| Field | Meaning |
|---|---|
| `wing_id`, `side` | identity |
| `anchor` | the commander's position |
| `strength_frac` | live strength / armed strength |
| `ours`, `theirs` | `side_strength` within `engage_gu` of the anchor (members / enemies) |
| `enemy_centroid` | centroid of the enemies within `engage_gu`, or None |
| `engaged` | at least one enemy within `engage_gu` |
| `decision` | the current decision |

Rules:
- A leaderless wing, or one whose command is away, publishes **no** status.
  Allies don't count on it.
- `allies.side_allies(wing)` returns the other led wings on the same side, as
  their last statuses.
- Decisions get them as `Context.allies` (a tuple of `WingStatus`), and they
  stay pure.

**In trouble** (pure: `allies.in_trouble(status)`). An ally is in trouble
when it is engaged and either:
- `ours < reinforce_odds × theirs` (dial, default **1.0**); or
- its decision is `protect` or `withdraw`.

## 4. Reinforce (#3)

**`reinforce`.**
- **Score 1.25** when all of these hold **(call)**:
  - our wing is **not engaged**, or ours ≥ `reinforce_spare_odds` (dial,
    default **2.5**) × theirs (we can spare the help);
  - at least one ally is in trouble;
  - that ally's anchor is within `reinforce_range_gu` (dial, default
    **1500 GU**) of ours.
- Reinforce sits below protect (1.5) and withdraw (2.5): a wing looks after
  its own first. It sits above swarm (1.0) and disable (1.3 > 1.25 —
  **(call)**: finishing a dangerous ship in reach beats leaving to help).
- **Choice.**
  - The ally is the one in trouble with the worst `ours / theirs`; ties go to
    the nearest.
  - `primary` is the enemy nearest that ally's anchor among the enemies
    within `engage_gu` of it.
  - `secondaries` are the next two such enemies by the same order.
  - `Choice.far = True`: `plans.target_priorities` keeps this primary and
    these secondaries even though they are beyond leash (§2).
- **Ends.** The score drops to 0 once **any** of these holds, and the normal
  decisions take over:
  - we arrive: our anchor is within `leash_gu` of the ally's anchor (the
    enemies are now in our reach, so swarm and the rest pick them up);
  - the ally is no longer in trouble;
  - the ally has no status (it died or lost command);
  - `reinforce_max_s` (dial, default **90 s**) passes. That ally is then
    "done" for `reinforce_cooldown_s` (dial, default **60 s**).
- **Latch.** While `ctx.current == "reinforce"`, the "not engaged / can
  spare" gate is **not** re-checked. Enemies near the ally become "near us"
  as we arrive, and re-checking would stop us short. The target ally is held
  (`wing.reinforce_ally`) and only the end conditions apply.
- **Moving.** Nothing new: the wing moves because its commander's stock tree
  intercepts the far primary (§2). Rejoin stays on as normal, so the
  followers come along.

## 5. Hold a relative location (#4)

A new wing branch, **`hold`**, at tree priority 4, between withdraw (3) and
guard. It is `Conditional[ConditionWing(ship, "hold")] ->
AvoidObstacles(WingMoveTo)`, the same shape as withdraw. While a hold
decision is current:
- every non-player member, **the commander included**, gets a move point in a
  small formation around the hold point;
- no guards, fallers, attack slots or rejoin are used (all off, as under
  withdraw);
- the reserve stays held but moves with the formation.

**Formation.**
- Points sit on a ring of radius `hold_spread_gu` (dial, default **30 GU**)
  about the hold point, at evenly spaced angles in the plane perpendicular to
  the line from the hold point to the enemy centroid. The commander takes the
  centre.
- Members are assigned with `attack.assign_slots`, with incumbency (Phase C
  I2) while the hold point moves less than `hold_spread_gu` in a tick.
- `WingMoveTo` needs no change: these are `move_point`s.

**Target writes.** Normal `target_priorities` for screen and flank: anything
that enters reach is still the wing's target, and the stock branch fires on
it once the hold ends.

### Screen
- **Score 1.15** when all of these hold **(call)**:
  - we are not engaged and our `strength_frac` ≥ 0.6;
  - an ally is weak: `strength_frac` < 0.5, or its decision is `withdraw`;
  - enemies are closing on that ally: the centroid of the enemies within
    `screen_watch_gu` (dial, default **700 GU**) of the ally's anchor is
    farther than `engage_gu` from it, so they haven't reached it yet.
- **Hold point:** `ally_anchor + unit(enemy_centroid − ally_anchor) ×
  min(screen_gu, 0.5 × gap)`, where `screen_gu` is a dial (default
  **150 GU**) and gap is the distance between the two.
- **Ends** when either:
  - an enemy comes within `engage_gu` of **our anchor** — we have met them
    where we chose, and normal decisions fight;
  - the ally is no longer weak, or no enemies are closing on it.

### Flank
- **Score 1.1** when all of these hold **(call)**:
  - we are not engaged;
  - an ally is engaged but **not** in trouble (a fair fight we can tip);
  - the ally's anchor is within `reinforce_range_gu` of ours.
- **Hold point:** `C + unit(perp) × flank_gu`, where:
  - C is the ally's `enemy_centroid`;
  - perp is the component of `(our_anchor − C)` perpendicular to
    `(ally_anchor − C)`, so we arrive on our own side of the enemy's flank;
  - `flank_gu` is a dial, default **250 GU**.
  - If perp is shorter than 1 GU (we are dead behind the ally), use any unit
    vector perpendicular to `(ally_anchor − C)`.
- **Ends** when either:
  - our anchor is within `leash_gu` of the hold point, or an enemy is within
    `engage_gu` of our anchor (we're in; swarm takes it);
  - the ally is no longer engaged.
- **Latch.** As with reinforce, "not engaged" is not re-checked while flank
  is current. The **arrival** end condition covers that case.

## 6. Bait and feint (#12)

**`feint`** uses the `hold` branch with a **lure** point, and does not fire,
like withdraw.
- **Score 1.2** when all of these hold **(call)**:
  - we are engaged;
  - our `strength_frac` ≥ 0.5 (a feint, not a rout);
  - some ally F is **not engaged**, F's `strength_frac` ≥ 0.6, and F's anchor
    is within `feint_range_gu` of ours (dial, default **800 GU**) but farther
    than `engage_gu`;
  - the enemy near us is beatable by both wings: `theirs ≤ (ours + F.ours) ×
    feint_odds`, with `feint_odds` a dial, default **1.0**;
  - this wing has not feinted within `feint_cooldown_s` (dial, default
    **180 s**).
- **Lure point:** `F_anchor + unit(our_anchor − F_anchor) × feint_stop_gu`
  (dial, default **100 GU**): we run to just short of F, and an enemy
  chasing us ends up within F's engage range.
- **Target writes:** `{}` while feinting (as withdraw): nobody turns back
  early.
- **Ends — "turn and fight"** — when any of these holds:
  - our anchor is within `feint_stop_gu + 50` of F's anchor;
  - the enemies we were fighting come within `engage_gu` of F's anchor (the
    trap is sprung);
  - no enemy is within `engage_gu` of our anchor for 10 s (they didn't
    follow);
  - `feint_max_s` (dial, default **45 s**) passes;
  - F becomes engaged elsewhere, or has no status.
  Once it ends, the feint goes on cooldown and the normal decisions fight.
- **(call)** F is not told anything. When the enemy arrives it is "engaged",
  and its own brain fights; its swarm picks targets in reach. If the enemy
  stops short, F may score flank or reinforce on its own.

## 7. Decision table after Phase D

| Decision | Score | Phase |
|---|---|---|
| withdraw | 2.5 | B |
| regroup | 0–2.0 | A |
| protect | 1.5 | B |
| disable | 1.3 (latched) | C |
| **reinforce** | 1.25 (latched) | D |
| focus_face | 1.2 | C |
| **feint** | 1.2 | D |
| **screen** | 1.15 | D |
| **flank** | 1.1 (latched) | D |
| envelop | 1.05 | C |
| swarm_weakest / swarm_commander | 1.0 / 0.3–1.0 | A |

- `focus_face` and `feint` tie at 1.2 and can't both apply: focus needs a
  primary in reach, so we're engaged, and feint needs us engaged too. A feint
  wins only if it is current (stickiness).
- **(call)** On a fresh tie, registration order decides: the earlier one
  wins, so focus_face beats feint. Pressing an advantage we already have
  comes before luring.

## 8. Perf

- Statuses are published once per wing tick: one `side_strength` pair (now
  memoised per Context, Phase C perf) plus a centroid.
- Allies are read from the roster: at most a handful of wings per side.
- No new per-tick App calls beyond the formation's move points. Same A/B
  rule: compare with SIG-227.

## 9. Testing

**Unit (pure).**
- `in_trouble`.
- The reinforce, screen, flank and feint scoring gates and latches.
- Hold-point geometry: screen, flank (including the dead-behind case), lure.
- The formation ring and its incumbency.
- `target_priorities` keeping a far primary when `Choice.far` is set.

**Host.**
- Statuses publish and clear (leaderless / away).
- Reinforce writes a far primary, and the wing's commander ends up within
  leash of the ally.
- The hold branch:
  - is on for every non-player member, including the commander;
  - turns off guard, fallback, attack and rejoin;
  - points form a ring.
- Feint writes `{}` and ends on its triggers.

**Behaviour (headless, generous bounds, 3 seeds, with controls).**
- (a) **Reinforce:** wing B, losing 2:5 against an enemy cluster 600 GU from
  idle wing A. A's anchor ends within leash of B's within 60 s. The control,
  with reinforce unregistered, doesn't move A.
- (b) **Flank:** A arrives on the flank: the angle at C between A's and B's
  anchors is ≥ 60°. In the control, A simply intercepts.
- (c) **Feint:** with F idle 500 GU away, the chasing enemy's centroid ends
  closer to F's anchor than in the control (feint unregistered).

## 10. Acceptance criteria for Mark's play test

1. **Reinforce.** Set up two friendly groups and an enemy force that
   overwhelms one of them. The other friendly group breaks off and comes to
   help, rather than sitting idle or flying elsewhere.
2. **Flank / screen.** When a friendly group is in an even fight, an idle
   friendly group swings round to hit the enemy from the side, not straight
   down the same line. When a friendly group is badly hurt and enemies are
   coming for it, a healthy idle group moves in between.
3. **Feint.** A friendly group that is fighting near an idle friendly group
   sometimes pulls back toward it. The chasing enemies end up fighting both
   groups.

## 11. Calls made without Mark

1. Scores:
   - reinforce 1.25 (below disable 1.3 and protect 1.5);
   - feint 1.2;
   - screen 1.15;
   - flank 1.1.
   The ties are as in §7.
2. Odds:
   - in trouble = losing on odds (< 1.0) or protecting/withdrawing;
   - we can spare help at ≥ 2.5× odds.
3. Ranges and distances:
   - help range 1500 GU;
   - feint range 800 GU, stopping 100 GU short of the ally;
   - screen 150 GU out from the weak ally;
   - flank point 250 GU off the enemy cluster;
   - formation ring 30 GU.
4. Timers:
   - reinforce: 90 s cap, 60 s cooldown per ally;
   - feint: 45 s cap, 180 s cooldown per wing.
5. Reinforce moves the wing by retargeting it (the commander's stock attack
   intercepts), not by a move branch.
6. Hold (screen, flank, feint) moves every non-player member, the commander
   included, in a 30 GU ring formation.
7. The ally receiving a feint is not told; its own brain fights when the
   enemy arrives.
