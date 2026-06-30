# Follow-up: proper CloakAttack AI doctrine support

**Status:** ✅ resolved. Interim fallback (`be4b02ca`) removed; the real
doctrine now drives. Two driver defects fixed on `feat/cloak-attack-doctrine`.

## Problem

Cloak-capable AI ships (warbird, bird-of-prey, the Dominion craft, …) did not
attack *or* tactically cloak. BC's `QuickBattle/QuickBattleAI.py` builds every
enemy with `AI.Compound.BasicAttack.CreateAI(pShip, …, UseCloaking = 1)`, and
`BasicAttack.CreateAI` routes any ship with `GetCloakingSubsystem()` truthy to
`CloakAttackWrapper` → a `PriorityListAI`:

- prio 1 `CloakingDisabled` (ConditionalAI) → plain `BasicAttack`, ACTIVE only
  while the cloak subsystem is *disabled*;
- prio 2 `CloakAttack` (the cloak combat doctrine) — runs normally.

`CloakAttack` is a `BuilderAI` that should cloak, approach, decloak, fire, and
recloak.

## Root cause (verified by headless reproduction)

> ⚠️ An earlier draft of this doc blamed `SelectTarget`'s target-propagation
> cadence / focus (`CallSetTargetFunctions` / `AddSetTargetTree` / re-select
> timing). **That was wrong.** Reproducing headlessly
> (`BasicAttack.CreateAI(cloakship, ["Tgt"], UseCloaking=1)` driven through
> `engine.core.loop.GameLoop.tick()`) pinned **two** distinct defects, neither
> in `SelectTarget`:

### Defect 1 — empty target group (the "never attacks" half)

`engine/appc/objects.py:ObjectGroup_ForceToGroup` flattened only **one** level
of list/tuple nesting. SDK compound AIs splat the targets positional through
`*lpTargets` once per routing hop, and the cloak path
(`BasicAttack → CloakAttackWrapper → BasicAttack → CloakAttack`) nests deeper
than the non-cloak path. So `ForceToGroup` received a more deeply nested arg and
stringified the inner list into a bogus name — the group ended up
`_names = ["['Tgt']"]` instead of `['Tgt']`. Then
`GetActiveObjectTupleInSet` returned `()`, `SelectTarget.FindGoodTarget()`
returned `None`, and `SelectTarget` returned its `eNoTargetPreprocessStatus`
(`PS_SKIP_DORMANT`) — so the attack subtree never ticked.

`NonFedAttack`/`FedAttack` only *looked* fine because they additionally call
`ForceCurrentTargetString(sInitialTarget)` (preset `sCurrentTarget`, which the
driver pushes onto the ship in `_ensure_select_target_initialized`); the
`CloakAttack` tree omits that call and relied entirely on the (broken)
`FindGoodTarget()` path.

**Fix:** `ObjectGroup_ForceToGroup` recurses — it returns an `ObjectGroup` found
at any depth (preserving `ObjectGroupWithInfo` identity), else flattens nested
sequences to individual leaf names.

### Defect 2 — SequenceAI never advanced (the "never cloaks" half)

The `CloakShip` preprocessor lives deep in the tree behind looping `SequenceAI`s
(`OuterSequence` / `Sequence`, both `SetLoopCount(-1)`) gated by range/timer
`ConditionalAI`s (`FarEnough_TimeNotPassed`, `TooClose_ShortTime`,
`NeedPower_OrTimeShort`). `engine/appc/ai_driver.py:_tick_sequence` only advanced
on a child reporting `US_DONE`, never **refreshed** a `ConditionalAI` child's
status (unlike `_tick_priority_list`, which calls `_refresh_conditional_status`),
and never **looped**. So `OuterSequence` stuck on its first child
(`FarEnough_TimeNotPassed`, ACTIVE for the first 15 s) and never reached the
`TooClose → … → Cloak` branch.

**Fix:** `_tick_sequence` now refreshes ConditionalAI children, advances past
`US_DONE` children, holds on `US_DORMANT` (SetSkipDormant(0) semantics), and
wraps + re-arms on `SetLoopCount(-1)` forever-loops.

## Verified behaviour

With both fixes, a fully-equipped attacker (sensors + impulse + phasers +
**power**) acquires its target on tick 0 and engages the cloak at **t ≈ 15 s**
(`IsCloaking()` true) — exactly when the approach timer expires and the sequence
reaches `NeedPower_OrTimeShort`(DONE, power ≥ 80 %) → `Cloak` / `CloakShip(1)`.
Pinned by `tests/unit/test_cloak_attack_doctrine.py` (drives the real
`GameLoop`: timers + proximity + cloak transitions).

## Done

- `install_cloak_attack_fallback()` call removed from `engine/host_loop.py`.
- `engine/appc/cloak_ai_fallback.py` and `tests/unit/test_cloak_ai_fallback.py`
  deleted. Cloak ships now use the real doctrine.

## Key files
- `engine/appc/objects.py` (`ObjectGroup_ForceToGroup` — defect 1)
- `engine/appc/ai_driver.py` (`_tick_sequence`, `_refresh_conditional_status` — defect 2)
- `sdk/Build/scripts/AI/Compound/CloakAttack.py` (BuilderAI tree; `BuilderCreate29` = SelectTarget, `BuilderCreate22` = Cloak/`CloakShip(1)`, `BuilderCreate32` = FleeAttackOrFollow)
- `sdk/Build/scripts/AI/Compound/CloakAttackWrapper.py`, `BasicAttack.py`, `NonFedAttack.py`
- `sdk/Build/scripts/AI/Preprocessors.py` (`SelectTarget`, `CloakShip`)
- `tests/unit/test_cloak_attack_doctrine.py` (end-to-end coverage)
