# Wing leaders — Phase B: looking after each other

Date: 2026-11-09. Builds on the programme spec
(`2026-11-09-wing-leaders-programme-design.md`) and Phase A
(`2026-11-09-wing-leaders-phase-a-design.md`, read its §2 facts and §11 tree
first). Branch `feat/wing-leaders-b`, cut from the end of `feat/wing-leaders-a`.

**Status (2026-11-09):** built on `feat/wing-leaders-b`, Quick Battle hooks
included; headless behaviour tests in
`tests/host/test_wings_phase_b_behaviour.py`. ⚠️ **Not live-verified.**

Phase A is live-verified by Mark (2026-11-09), including his play-test changes: Developer Options toggles removed, a "Wing commanders" switch on the Quick Battle setup screen (default on), an always-on commander chevron and a focus marker in the target list, and the player's own group AI-led (the player is in no wing). Mark asked for Phase B to be specified and built without his spec approval.
Every choice below that he didn't make is marked **(call)** and listed in §10.

## 1. What Phase B delivers

Three decisions from the programme table (§6), added to the decision
registry. Phase A's code is extended, never rewritten:

- **#2 Protect.** A wingmate (or a Quick Battle protect ship on our side)
  under heavy fire: the wing turns on its attackers, and one or two guards put
  themselves physically between it and its main attacker.
- **#7 Rotate damaged ships.** A ship whose shields are failing drops back
  behind the wing until they recover, then rejoins the fight.
- **#8 Withdraw.** A badly outmatched wing pulls out together in good order,
  then comes back when the odds recover or after a time limit.

One new manoeuvre serves all three: **`WingMoveTo`**, which flies a ship to a
point that the brain recomputes each tick. Phase D's relative locations will
reuse it.

## 2. What the brain learns to see

- **Targets.** Every `ShipView` (members and enemies) gains
  `target: str | None`, the name of the ship's current target
  (`GetTarget().GetName()`), so the brain can see who is attacking whom.
  Enemy views are shared per side per period (Phase A M2), so this costs one
  read per enemy per period.
- **Damage taken.** The wing keeps, per member, a short history of strength
  (`assess.strength`) samples, one per brain tick, covering the last
  `heavy_fire_window_s` (dial, default **5.0 s**) **(call)**. The **damage
  rate** is the fraction of strength lost across the window.
- **Wing strength at arming.** `Wing.armed_strength` is the sum of member
  strengths when the wing is armed. Withdraw uses it.

## 3. Protect (#2)

**Protectees.** These are the live members, plus the Quick Battle protect
ships, plus, for the player's own group's wing, **the player's ship**
**(call)**. A friendly wing protects every ship in a Defeat "Ships Destroyed"
list, friendly or neutral (ruling 2026-11-09); an enemy wing protects the
Victory-listed (hunt) ships on its own side. Generic hook:
`Wing.protect_names: Callable[[], Iterable[str]]` (default empty); the Quick
Battle consumer supplies the protect ships.

**Under heavy fire.** A protectee is under heavy fire when either:

- its damage rate is ≥ `heavy_fire_frac` (dial, default **0.15**), or
- ≥ `heavy_fire_attackers` (dial, default **3**) enemies in reach target it
  **(call)**.

Either way it needs **at least one attacker in reach**: a damage rate with
nobody in reach targeting the protectee (rocks, a green-alert shield drop, a
fight past `engage_gu`) is never heavy fire, so Protect never displaces
Phase A's focus with nothing to turn on (final review I1, ruling 2026-11-09).

The most threatened protectee is the one with the highest damage rate, ties
broken by attacker count, then name.

**Score.** **1.5** while some protectee is under heavy fire, else 0. This beats
swarm (1.0) and loses to regroup once more than 75% of the wing has strayed.

**Choice.**

- Primary: the protectee's attacker in reach that has done the most damage.
  Approximated as the nearest attacker to the protectee **(call)**: BC's
  per-attacker damage is not visible to the brain.
- Secondaries: the next two attackers.
- `gather=False`.

**Guards (body-block).** While Protect is the decision, the brain assigns
**guards**:

- Count: `guard_count` (dial, default **1**; 2 when the wing has ≥ 6 live
  members) **(call)**.
- Who: the healthiest members (strength fraction ≥ 0.6, mean shield ≥
  `rotate_out_shield`) nearest the protectee, excluding the commander, the
  player, the protectee itself and any ship already falling back.
  `guard_count` 0 switches guards off at any wing size.
- **Incumbency:** a current guard keeps the role while it is still eligible
  and the protectee is unchanged; only vacancies go to the nearest
  (ruling 2026-11-09).
- Guard point: `protectee_pos + unit(attacker_pos − protectee_pos) ×
  min(interpose_gu, 0.5 × distance)`. `interpose_gu` is a dial, default
  **40 GU** **(call)**, recomputed every brain tick.
- A guard runs the new `"guard"` branch (§6), which does `WingMoveTo` to its
  guard point. It does not fire while it moves; see §6.

## 4. Rotate damaged ships (#7)

Rotate is a **standing rule**, like don't-chase, not a scored decision. A
damaged ship falls back under any decision except Withdraw.

- **Falls back** when its **weakest shield face** is < `rotate_out_shield`
  (dial, default **0.25**), or **once per ship** when its hull fraction is <
  `rotate_out_hull` (dial, default **0.5**), and in either case only while
  its hull fraction is ≥ `desperate_hull`. Below that, desperation (Phase A)
  is the leaderless path and the ship keeps fighting **(call)**. *Revised
  after Mark's play test 2026-11-10: the first build used the MEAN of the six
  faces and no hull trigger; one or two faces go down in a real fight, so the
  mean almost never reached 0.25 and nobody rotated.*
- **Returns** when its weakest face is ≥ `rotate_in_shield` (dial, default
  **0.6**) or after `rotate_max_s` (dial, default **30 s**) **(call)**. A
  hull fall-back ignores shields and holds the full `rotate_max_s` (hull
  does not recharge); after it the ship's hull trigger is spent, and only a
  downed face sends it back again.
- Each fall-back and return is logged under `DAUNTLESS_WINGS_LOG=1`
  (`<wing> <ship> falls back (shields|hull)`, `<wing> <ship> returns`).
- **Cap:** at most `max(1, floor(rotate_cap_frac × live members))` (dial,
  default **0.34**) ships fall back at once. The worst shields go first.
- **Never:** the commander, the player, or a guard. A member that is the
  current protectee **does** fall back; the wing still protects it, and its
  guards interpose on its current position as it retreats (ruling
  2026-11-09). Non-member protectees (the player, Quick Battle protect ships)
  are not members, so never fall back.
- `rotate_in_shield` never steps below `rotate_out_shield` (the dials clamp).
- **Fall-back point:** `anchor_pos + unit(anchor_pos − enemy_centroid) ×
  regroup_gather_gu`, i.e. behind the commander, away from the enemy.
  `enemy_centroid` is the mean position of enemies in reach. With no enemies
  in reach nobody falls back, because there is nothing to hide from.
- The ship runs the `"fallback"` branch → `WingMoveTo`.

## 5. Withdraw (#8)

**Score.** **2.5**, beating everything, when all of the following hold:

- our strength < `withdraw_odds` (dial, default **0.4**) × their strength
  (both within `engage_gu` of the anchor, as in Phase A);
- current wing strength < `withdraw_wing_frac` (dial, default **0.5**) ×
  `armed_strength`;
- the player does not command the wing (never true in Quick Battle since the player's group is AI-led; kept for the library's player-commands path);
- the wing is not in its withdraw cooldown.

Otherwise the score is 0 **(call)**.

**Effect.**

- Every non-player member runs `"withdraw"` → `WingMoveTo` to
  `own_pos + unit(own_pos − enemy_centroid) × withdraw_step_gu` (dial,
  default **300 GU**), recomputed each tick, so the whole wing keeps opening
  distance. Nobody rejoins while withdrawing (ruling 2026-11-09: with
  rejoin-with-gather the wingmates kept fighting until 100 GU from the
  commander).
- The target group is emptied, so nobody turns back to fight.

**Ends** when any of these holds; stickiness keeps it from flapping, but a
decision scoring 0 gets no stickiness bonus, so an ended Withdraw always
ends:

- no enemy is within `engage_gu` of the anchor for `withdraw_clear_s` (dial,
  default **10 s**);
- the odds recover above `withdraw_odds × 1.5`;
- `withdraw_max_s` (dial, default **60 s**) has elapsed, which stops a battle
  stalling **(call)**.

It then enters `withdraw_cooldown_s` (dial, default **120 s**), during which
Withdraw scores 0.

## 6. Tree and library additions

The Phase A tree gains two branches above rejoin. The new order is:

```
PriorityList
  1 ram       (Phase A)
  2 flee      (Phase A)
  3 withdraw  -> AvoidObstacles(WingMoveTo)      [every member]
  4 guard     -> AvoidObstacles(WingMoveTo)
  5 fallback  -> AvoidObstacles(WingMoveTo)
  6 rejoin    -> AvoidObstacles(WingRejoin)       (Phase A)
  7 <stock tree>
```

Changing `wrap_tree` to add branches is an extension, not a rewrite. Phase A's
branch indices are not part of any contract.

- **`AI.PlainAI.WingMoveTo`** (library module, claimed single-file). Each
  update it reads `roster.member(own name).move_point` (a 3-tuple or None). It
  flies there the way SDK `AI/PlainAI/Intercept.py` flies to its destination:
  `TurnTowardLocation` plus an impulse that scales down within 20 GU of the
  point **(call)**. With no point it stops and returns ACTIVE. While the
  ship is a wing member it never returns DONE (Phase A lesson: DONE latches
  a branch dead); with no member record (the wing was reset) it returns
  DONE, as WingRejoin does. It asks for an update every 0.2 s
  (FollowObject's period), so the tree walk can sleep.
- **`Conditions.ConditionWing`** gains the kinds `"withdraw"`, `"guard"` and
  `"fallback"`. The brain pushes them like `"rejoin"`.
- **No firing during wing manoeuvres (call).** While a wing branch is active
  the stock tree's FireScript does not run, so guards, fallers and withdrawers
  hold fire. This matches BC's own `Flee`. Revisit only if play-testing shows
  guards should shoot back.
- **`Member` gains** `move_point`, `guard`, `fallback_since`, `strength_hist`.
  **`Wing` gains** `armed_strength`, `protect_names`, `withdraw_since`,
  `withdraw_cooldown_until`.

## 7. Perf

The brain does a little more per tick: a target read per enemy view, which is
shared; a strength sample per member; and a few vector sums. The Phase B A/B
uses the same rule and command as Phase A, comparing Phase B wings-on against
wings-off on the same build. `gl.ai + gl.wings` (on) must not exceed `gl.ai`
(off) beyond spread. It is also compared against SIG-225's on-side numbers, to
catch Phase B adding cost.

## 8. Testing

**Unit (pure):**

- heavy-fire detection, both triggers;
- protectee pick and its tie-breaks;
- guard selection and the guard point;
- fall-back hysteresis, cap and exclusions;
- withdraw score gates, end conditions and cooldown.

**Host:**

- `WingMoveTo` flies toward a point and stops at it;
- the new branches activate when pushed;
- a guard ends up between the protectee and the attacker after N ticks;
- a ship with shields at 0.1 moves behind the commander, and returns when its
  shields are restored to 0.7;
- a 2-ship wing against 8 enemies at 0.3 hull withdraws, opens distance, and
  stops after `withdraw_max_s`.

**Quick Battle:** a Defeat-protected friendly or neutral under fire is
protected by the friendly wings, a Victory hunt target by its enemy wing; the player (in no wing) is a protectee of their own group's
wing like any protect ship **(call)**, so your AI escorts cover you.

## 9. Acceptance criteria for Mark's play test

1. **Cover.** When one of your wing's ships (or a ship you must protect) comes
   under heavy fire, its wingmates turn on the attackers, and one moves to put
   itself between the attacker and the ship.
2. **Rotation.** An AI ship whose shields are nearly gone pulls back behind
   its commander and returns to the fight once its shields recover. Never more
   than about a third of a wing is out at once.
3. **Withdrawal.** A wing that is losing badly (well under half strength,
   heavily outnumbered) pulls back together rather than dying one by one, and
   comes back into the fight within about a minute.

## 10. Calls made without Mark

1. Heavy fire is a 15% strength loss in 5 s, or 3 or more attackers.
2. The protect score of 1.5 sits between swarm and regroup. The protect
   primary is the attacker nearest the protectee.
3. Guards: 1, or 2 in a wing of 6 or more, the healthiest and nearest to the
   protectee, holding a point 40 GU out toward the attacker.
4. Rotate out below 25% on the weakest shield face (or once below 50% hull)
   and back at 60% or after 30 s. At most a third
   of the wing falls back at once. The fall-back point is behind the commander,
   away from the enemy.
5. Withdraw needs odds under 0.4 and the wing under half its armed strength.
   It never applies to a player-led wing. It ends when the wing is clear for
   10 s, the odds recover, or 60 s pass. The cooldown is 120 s.
6. Ships hold fire while running wing manoeuvres.
7. *(Ruling 2026-11-10, Mark.)* A member rejoining a commander beyond
   `leash_gu + leash_slack_gu` in-system warps back to `regroup_gather_gu`
   off it with BC's own `InSystemWarp` (`WingRejoin._WarpBack`), then
   follows at impulse. Rejoin by FollowObject alone could never catch a
   commander as fast as the member, e.g. one that warped ahead to another
   wing's fight (Phase D reinforce, stress seed 1).
7. `WingMoveTo` slows within 20 GU of its point and never returns DONE while
   the ship is a wing member (DONE once its wing is gone). It asks for an
   update every 0.2 s, FollowObject's period.
8. The player's own group's wing treats the player's ship as a protectee, so AI escorts cover the player.
