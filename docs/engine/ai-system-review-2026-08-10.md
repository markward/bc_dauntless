# AI System Review — 2026-08-10

Reviewed `engine/appc/ai.py`, `ai_driver.py` and `ai_optimized.py` against the
clean-room reference. Findings are recorded at the code sites; this is the index.

**Headline: the AI system holds up well.** Every structural claim the reference
could check came back matching. The gaps that remain are ones the reference
confirms are *not observable from script*, plus two classes it does not document
at all.

---

## Confirmed correct

### C1. Class hierarchy — exact match

`ArtificialIntelligence`'s direct descendants, from the type-conversion graph the
program registers at startup (*faithful* — extracted from registration, not
inferred from naming):

> `ConditionalAI`, `PlainAI`, `PreprocessingAI`, `PriorityListAI`, `RandomAI`,
> `SequenceAI` (6)

Ours are exactly those six. And `BuilderAI`, which is *not* a direct descendant:

> Base chain: `ArtificialIntelligence → PreprocessingAI → BuilderAI`,
> vtable `0x0088bbe0`

matching our `class BuilderAI(PreprocessingAI)`. Seven containers, right shape.

### C2. `ArtificialIntelligence` base fields

`spec/ArtificialIntelligence.md §2` (*reviewed-not-tested*): `interruptable`
`+0x23` **default 1**, `paused` `+0x22`, `hasFocus` `+0x21`, `active` `+0x20`,
unique ID `+0x24` from a post-incrementing global.

Ours: `_interruptable = True`, `_paused = False`, `_has_focus = False`, a status
field, and an id registry. Match.

### C3. Published surface — 13 of 14, and the absentee is dead

The contract publishes exactly 14 `ArtificialIntelligence_*` entries. We
implement 13. The one missing is **`LogAITree`** (`0x00603db0`), a debug dump
with **zero SDK call sites** — dead surface, correctly unimplemented.

Worth noting `ArtificialIntelligence_GetAIByID` is a *module-level* function, not
an instance method, and ours is too (`engine/appc/ai.py:1962`).

### C4. `SequenceAI` — verified field for field (2026-08-09)

Child array, current index `-1`, loops-remaining 1, loop count 1, and all three
flag bytes (`skipDormant`, `resetIfInterrupted`, `doubleCheckAllDone`) defaulting
to 0. See `docs/engine/stub-scouting-2026-08-10.md` §4.1.

### C5. `PriorityListAI` ordering — confirmed, and it needed the SDK

`spec/PriorityListAI.md §1`: the node *"runs the highest-priority runnable
child"*. That phrasing does **not** fix the numeric direction, and getting it
backwards would invert every priority tree in the game.

Settled from SDK usage. `AI/Compound/NonFedAttack.py:444-447`:

```python
pCloseRangePriorities.AddAI(pEvadeTorps_2, 1)
pCloseRangePriorities.AddAI(pFwdTorpsOrPulseReady, 2)
pCloseRangePriorities.AddAI(pRearTorpsReadySortaCloseNotInterruptable, 3)
pCloseRangePriorities.AddAI(pICOMoveAround, 4)
```

Dodging incoming torpedoes must outrank a generic move-around fallback, so
priority **1 is the most urgent**: lower int = higher priority, which is what our
ascending sort assumes. `Defend.py:102-103` repeats the pattern
(defendee-attacked 1, idle circling 2).

Same lesson as `TGUIObject.GetRight`: **the reference gave the structure, the SDK
gave the direction, and only the combination was conclusive.**

---

## Deliberately absent — confirmed unobservable

### A1. The embedded blackboard (`+0x10`..`+0x1f`)

A 37-bucket hash map of `{key, value, next}` entries holding per-node scratch
state, with `Hash`/`KeyEquals`/`InitEntry`/`FreeEntry` in its own vtable.

**We do not implement it, and should not.** None of the 14 published entries
reads or writes it — it is engine-internal scratch with nothing for the SDK to
observe. Recorded at `engine/appc/ai.py` so it is not "discovered" as a gap later.

### A2. Parent-node ID (`+0x08`)

The unique ID of the parent tree node, set by the parent's `AddAI`, 0 for a root.
We hold parent links directly instead. Its only obvious consumer is `LogAITree`,
which is itself dead surface.

---

## Limits — what the reference cannot settle

### L1. `PriorityListAI`'s run-tick is a WALL

`spec/PriorityListAI.md` records `IsInterruptable`, `AddAI(priority)`,
`RemoveAIByPriority` and the run-tick virtuals
(`0x490310` / `0x490140` / `0x4901e0` / `0x490270` / `0x4902a0` / `0x490340` /
`0x490560`) as **SEH-framed walls** — catalogued, not reconstructed. Only the
ctor and `ForEachChild` (slot 18) are byte-exact; `AllChildrenDone` (slot 17) is
behaviour-verified at ~87%.

So our `_tick_priority_list` reading — that a per-entry skip byte latches on
`US_DONE` only, never on `US_DORMANT` — **remains our own evidence, unconfirmed
by the corpus.** It is not contradicted either. Recorded at the site.

### L2. `ConditionalAI` — no document exists

`search_reference("ConditionalAI")` returns one section at relevance **0.10** (a
README coverage column). Measured silence for the class. Our evaluation-function
and condition-status wiring is unverified and unchallenged.

### L3. `PreprocessingAI` — no document, no `Update`

Confirmed 2026-08-09 and unchanged: no class specification, and the contract's
nine `PreprocessingAI_*` entries include no `Update`. The `PS_DONE` divergence in
`engine/appc/ai_optimized.py` stands as a genuine open question — the absence of a
published `Update` corroborates our comment that it was internal native code.

---

## Suggested follow-ups

1. **Nothing urgent.** No defect was found in the AI system by this review.
2. If `ConditionalAI` or the `PriorityListAI` run-tick ever get written up
   upstream, re-check L1/L2 — those are the two places our behaviour rests
   entirely on our own decompilation reading.
3. Leave A1/A2 alone. They are confirmed unobservable, and implementing them
   would be speculative surface of exactly the kind this project keeps deleting.
