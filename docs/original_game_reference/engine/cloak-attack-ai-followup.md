# Follow-up: proper CloakAttack AI doctrine support

**Status:** open. Interim fallback shipped (`be4b02ca`); this is the real fix.

## Problem

Cloak-capable AI ships (warbird, bird-of-prey, the Dominion craft, …) do not
attack *or* tactically cloak. BC's `QuickBattle/QuickBattleAI.py` builds every
enemy with `AI.Compound.BasicAttack.CreateAI(pShip, …, UseCloaking = 1)`, and
`BasicAttack.CreateAI` routes any ship with `GetCloakingSubsystem()` truthy to
`CloakAttackWrapper` → a `PriorityListAI`:

- prio 1 `CloakingDisabled` (ConditionalAI) → plain `BasicAttack`, ACTIVE only
  while the cloak subsystem is *disabled*;
- prio 2 `CloakAttack` (the cloak combat doctrine) — runs normally.

`CloakAttack` is a `BuilderAI` that should cloak, approach, decloak, fire, and
recloak.

## Root cause (verified, not from the cloak feature work)

Reproduced headlessly (build `BasicAttack.CreateAI(cloakship, ["Tgt"],
UseCloaking=1)`, tick `engine.appc.ai_driver.tick_ai`) and confirmed **identical
on `main`** — so this predates phases A–E (it came in with W5.T2 wiring
`GetCloakingSubsystem()` onto ships).

Equip the test ship with sensors + impulse + phasers (else `NoSensorsEvasive`
and `Intercept` fire/raise on missing subsystems and mask the real issue).

Dispatch trace (cloak vs plain), both reach `FleeAttackOrFollow` (PriorityList)
→ `SelectTarget` (prio 3, above `FollowTargetThroughWarp`; prio 1/2 =
WarpBeforeDeath / NoSensorsEvasive are dormant on a healthy ship):

- **plain (NonFedAttack):** `… → SelectTarget → PriorityList → ConditionalAI(LongRange) → FirePulseOnly → MoveIn` — descends into the attack tree, **sets the ship's target**.
- **cloak (CloakAttack):** `… → SelectTarget` … **stops**. `SelectTarget` is
  reached with `has_focus=True` and CodeAISet init done, but it **never
  propagates a target onto the ship**, so it returns its `eNoTargetPreprocessStatus
  = PS_SKIP_DORMANT`, and `_tick_preprocessing` therefore never ticks the
  contained attack subtree (`SetContainedAI(pFire)`). The ship drifts.

So the `SelectTarget` preprocessor *class* works in one tree and not the other,
with the dispatch prefix identical — the difference is how the heavier
`CloakAttack` tree drives target selection/propagation
(`SelectTarget.CallSetTargetFunctions` / `AddSetTargetTree` reaching the ship,
the per-tick re-select cadence, or a focus/CodeAISet nuance specific to this
tree). That is the thing to fix.

## Goal

`CloakAttack` runs end-to-end in `engine/appc/ai_driver.py`: cloak ships acquire
a target, and the `CloakShip`/decloak-to-fire logic engages the cloak (drawing
on the now-faithful subsystem: events, power, weapons-lockout-while-cloaked,
shields-down, sensor invisibility from phases A–E). Net behaviour: AI ships
that both **attack and tactically cloak**.

## When done

Delete the `install_cloak_attack_fallback()` call in `engine/host_loop.py` and
the `engine/appc/cloak_ai_fallback.py` module (+ its test), so cloak ships use
the real doctrine again. The faithful gameplay underneath (phases A–E) already
makes cloaking *mean* something, so this should "just work" visually once the
doctrine drives the cloak.

## Key files
- `sdk/Build/scripts/AI/Compound/CloakAttack.py` (BuilderAI tree; `BuilderCreate29` = SelectTarget, `BuilderCreate32` = FleeAttackOrFollow)
- `sdk/Build/scripts/AI/Compound/CloakAttackWrapper.py`, `BasicAttack.py`, `NonFedAttack.py`
- `sdk/Build/scripts/AI/Preprocessors.py` (`SelectTarget`)
- `engine/appc/ai_driver.py` (`_tick_preprocessing`, `_tick_priority_list`, `_tick_builder`)
- `engine/appc/cloak_ai_fallback.py` (interim shim to remove)
