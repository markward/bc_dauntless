# CharacterClass reimplementation — SP2: the AnimationQueue

**Date:** 2026-07-21
**Status:** design approved, awaiting spec review
**Depends on:** SP1 (owner skeleton + state model), merged to main `c865c0da`.
**Scope:** the second sub-project of the CharacterClass reimplementation (see
`project-characterclass-reimplementation` memory and the SP1 spec for the overall roadmap).

---

## 1. Motivation

SP2 is the heart of the effort and the first **player-visible** payoff. Today:

- `CharacterClass.Breathe/MoveTo/TurnTowards/TurnBack/GlanceAt/GlanceAway/PlayAnimation/PlayAnimationFile/LookAtMe`
  are `pass` stubs — a script calling `pChar.MoveTo(...)` directly does **nothing**.
- Character animation flows through a *second* door: the SDK builds a `CharacterAction(character,
  AT_TURN, …)` and `engine/appc/ai.py:CharacterAction.Play()` dispatches `AT_*` verbs straight into
  the host controllers.
- The actual queue is `engine/bridge_character_anim.py:BridgeCharacterAnimController` — a
  **priority-preempting** queue keyed off `request_*` verbs, using *priority* preemption, **not**
  BC's `CAT_*` categories, `Classify` conflict-resolution, or `Special4/6` chaining.

BC has **one** door: both `CharacterAction` verbs and direct `pChar.MoveTo(...)` calls go through the
`CharacterClass` methods, which compose the `<location>+action` key, resolve the SDK animation
builder, and enqueue a `CAT_*` record via `SetCurrentAnimation`; `UpdateAnimationQueue` drives
playback with `Classify` conflict resolution and `Special4/6` chaining.

SP2 makes `CharacterClass` own that faithful queue and collapses the two doors into one.

## 2. Evidence sources (ranked)

Per `project-evidence-tiers-sdk-swig-re`:

0. **Tier-0 `CharacterClass.md`** (recompiled + gameplay-tested) — authoritative for the queue
   methods: §4.8 (`SetCurrentAnimation`, `ClearAnimationsOfType`, `ClearAnimations`,
   `ReleaseCurrentAnimation`, `OnAnimRelease`, `UpdateAnimationQueue`, `Special4/6`, `ShouldPlayNow`,
   `PreparePlay`), §4.9 (predicates), §4.10 (the high-level action methods + the `PlayAnimation`
   mode table).
1. **Sibling RE repo** — `docs/gameplay/bridge-character-system.md` for the surrounding TG animation
   layer (§4 name→Python-function mechanism, §4.3 interruptability/UI interlock, §4.4 the
   `<location>+action` key grammar, §5 `TGAnimBlender`/exclusivity, §6.2b `TGSequence` scheduling,
   §6.4 `DoCrewReactions` engine-driven hit reactions), and `stbc_constants.csv` for `CAT_*` values.

**Classify gap — RESOLVED.** The exact conditions inside `Classify1`(`0x0066C9E0`) /
`Classify2`(`0x0066C860`) were relayed to the RE project and answered (Mark, 2026-07-21): a **single
referee** driven by categories, with names as a tiebreaker in two match-ups. The full rules are in
§5; the original question and its answer are in Appendix A.

## 3. Architecture decision — "own + demote to clip-player"

`CharacterClass` **owns** the `CAT_*` record queue (the brain: records, conflict resolution,
chaining, the per-frame driver, interruptability). `BridgeCharacterAnimController` is **demoted to a
clip-player** (the hands): its proven playback half is kept, its queuing/preemption layer is removed
and superseded by the `CharacterClass` queue. There is **one** queue and **one** door.

`AT_WATCH_ME`/`AT_LOOK_AT_ME` stay on the **separate** camera-watch subsystem
(`engine/bridge_camera_watch.py`) — in BC that is the `ZoomCameraObjectClass`, legitimately not the
animation queue (sibling §7.2). SP2 does not touch it.

## 4. Design

### 4.1 Queue data model (in `CharacterClass`)

Replace the interim single `_current_anim` tuple (from SP1) and populate the SP1 `_anim_queue` slot.
Mirror BC's `+0x15C..+0x174` idiomatically:

- `AnimRec` — a small object/namedtuple `{play, flags, category, name}` where `play` is the resolved
  thing the clip-player can run (a clip list / SDK sequence handle), `flags` the `CS_*` word to apply
  while playing, `category` a `CAT_*` code, `name` the owned target name (or `None`).
- The queue owner holds: `current: AnimRec | None`, `pending: list[AnimRec]` (FIFO), and derives
  `count`. No literal freelist/slab (pure-Python).

### 4.2 `SetCurrentAnimation(anim, category, flags, name)` — enqueue with conflict resolution

Faithful to tier-0 §4.8:
1. Build the record `{play=anim, flags, category, name}`.
2. Classify the new record against the **current** animation (`Classify1`): stop-existing (0/1) →
   stop the current's live playback; reject-new (2/1) → stop `anim`, drop the record, return.
3. For each **queued** record, classify the new against it (`Classify2`): 0/1 → stop that queued
   record's playback; 2/1 → reject the new record and return.
4. Append the surviving record at the tail; bump count.

The conflict model (`Classify1`/`Classify2`) is the single RE-confirmed referee of §5.

### 4.3 `UpdateAnimationQueue()` — the per-frame driver

Faithful to tier-0 §4.8. Called once per character per frame from the host loop:
1. `ReleaseCurrentAnimation(0)`. If an animation is still current, or the queue is empty, return.
2. Pop the head record → it becomes the candidate current.
3. Dispatch by category:
   - `CAT_TURN_BACK (4)` → `Special4`; if it declines, stop the record's playback.
   - `CAT_GLANCE_BACK (6)` → `Special6`; if it declines, stop the record's playback.
   - otherwise → resolve the play object; if `ShouldPlayNow` → `PreparePlay` + play (via the
     clip-player), else stop.
4. Set `current` to the record. If this character is the current tooltip owner and `CS_UI_DISABLED
   (0x8)` is set, fire `BridgeHandlers.DropCharacterToolTips` (via the existing bridge seam).

### 4.4 Release + per-category cleanup

- `ReleaseCurrentAnimation(param)` (tier-0 §4.8): if `current` is `None`, return; if the current's
  live playback has completed (ask the clip-player `is_clip_active`), run `OnAnimRelease` then clear
  `current`. The `param` variant matches a supplied record's play-object.
- `OnAnimRelease(rec)` (tier-0 §4.8): category `6` (glance-away) → free `_glance_name` (`+0xa4`),
  clear `CS_GLANCING (0x2)`; category `4` (turn-back) → free `_target_name` (`+0xa0`), clear
  `CS_TURNED (0x4)`.
- `ClearAnimationsOfType(cat)` — skip/stop every record (current + queued) of that category
  (tier-0: a marking/skip pass, not an unlink). `ClearExtraAnimations()` = clear categories
  `0,1,5,6` (the interruptable set). `ClearAnimations()` — full drain + reset (also frees
  `_location_name`/`_target_name`, clears the speak queue in SP3, resets position table in SP4;
  SP2 does the queue-drain + name-buffer half).

### 4.5 Predicates (tier-0 §4.9) — re-expressed against the queue

- `IsAnimating` — queue non-empty, else `ReleaseCurrentAnimation(0)` and whether the current's live
  playback is still active.
- `IsGoingToAnimate` — something is queued (`count != 0` / pending non-empty).
- `IsAnimatingInterruptable` — after release, current (if any) **and** every queued record are in
  `{0,1,5,6}`.
- `IsAnimatingNonInterruptable` — after release, current is `2` **or** any queued record is `2`.

### 4.6 High-level action methods become real (tier-0 §4.10)

Each replaces a `pass` stub. All compose the key from `_location_name` and resolve the SDK builder
via the existing `engine/appc/bridge_placement.py` path (the equivalent of BC's
`CallPythonAnimationFactory` — split the dotted builder path at the last `.`, call it with `self`,
take the returned sequence). Then build the record and enqueue via `SetCurrentAnimation`:

| Method | Key composed | Category / flags (tier-0) |
|--------|--------------|----------------------------|
| `Breathe` | `"%sBreathe"` (fallback bare `"Breathe"`), only if idle (not animating, nothing queued, no move/glance target) | `SetCurrentAnimation(anim, 0, 0, 0)` |
| `MoveTo(dest)` | `"%sTo%s"` | `SetFlags(0x8)`; `SetCurrentAnimation(anim, 2, 8, 0)` |
| `TurnTowards(name)` | acts only when `name=="Captain"` & active | builds a `TGSequence` of two `CharacterAction`s (tags `0x19`,`0x1A`) — plays; returns false |
| `TurnBack` | bare sequence | `SetCurrentAnimation(seq, 4, 0, 0)`; clears interruptable set first |
| `GlanceAt(name)` | `"%sGlance%s"` | clear `0,1`; `SetCurrentAnimation(anim, 5, 2, name)` |
| `GlanceAway` | bare sequence | clear `0,1`; `SetCurrentAnimation(seq, 6, 0, 0)` |
| `PlayAnimation(name, mode)` | `Make(name)` | mode table below |
| `PlayAnimationFile(file, mode)` | file → `TGAnimAction`+`TGSequence` | mode `==0`→cat 2/flags 8; else cat 1/flags 0 |
| `LookAtMe` | camera-watch seam | routes to the camera-watch subsystem (not the queue) |

**`PlayAnimation` mode table** (tier-0 §4.10 / sibling §4.3): `mode>0` → done 0, cat 1, flags 0;
`mode==0` → done `0x800`, cat 2, flags 8; `mode<0` → no done event, cat 2, flags 0.

> **Two distinct name concepts — do not conflate (clarified by the RE Appendix-B answer):**
> (1) the **record name** (`+0x0C`, the 4th `SetCurrentAnimation` arg) — used **only** by the §5
> referee, compared by content. (2) the character's **target buffers** `+0xa0` (move/back-to) and
> `+0xa4` (glance) — written at *play* time by `PreparePlay` and read by `OnAnimRelease`/`Special4/6`
> for follow-up chaining, **never** by the referee. Transcribe each method's contract exactly as
> tier-0 gives it; the earlier apparent category↔name inconsistency dissolves once these two are kept
> separate. Pin each with a test.

### 4.7 Clip-player seam — demote `BridgeCharacterAnimController`

Carve the controller down to a "hands" API the `CharacterClass` queue calls:

- `play(character, rec, on_complete)` — start the record's clips on the character's render instance.
- `is_active(character)` — is the character's clip still playing (drives `ReleaseCurrentAnimation`).
- `stop(character)` — stop/skip the current clip.
- `return_to_default(character)` — the `AT_DEFAULT`/rest-pose restore.

**Kept** (the proven playback half): `_start_clip`, `_real_duration`, `_return_to_default`,
`_process_turn`, `_body_turns_officer`, the `BridgeNodeAnimController` chair coupling, and the
per-frame `update()` that advances active clips. **Removed** (superseded by the `CharacterClass`
queue): the `_Action` priority records and `submit`/`request_*`/`is_busy` decision layer.

### 4.8 Collapse the two doors + re-point callers

- `engine/appc/ai.py:CharacterAction.Play()` — its `AT_*` branches call the new `CharacterClass`
  methods (`AT_MOVE`→`MoveTo`, `AT_TURN`/`AT_TURN_NOW`→`TurnTowards`, `AT_TURN_BACK*`→`TurnBack`,
  `AT_GLANCE_AT`→`GlanceAt`, `AT_GLANCE_AWAY`→`GlanceAway`, `AT_BREATHE`→`Breathe`,
  `AT_PLAY_ANIMATION[_FILE]`→`PlayAnimation[File]`, `AT_DEFAULT`→queue drain/return-to-default). The
  speak/camera/menu/status branches are unchanged (SP3/SP4/separate subsystems).
- `engine/bridge_idle_gestures.py` → enqueue via `Breathe`/a random-animation enqueue on the
  character instead of `controller.submit`.
- `engine/bridge_hit_reactions.py` → push the reaction into the queue (BC's engine-driven
  `DoCrewReactions`, sibling §6.4) instead of `controller.submit`.
- `engine/bridge_character_walk.py` → drive the `AT_MOVE` clip through the clip-player seam.
- `engine/appc/characters.py:_notify_menu` → `self.TurnTowards("Captain")` instead of
  `controller.request_turn`.
- The host-loop per-frame tick calls `character.UpdateAnimationQueue()` for each active character
  (plus the clip-player `update()` for playback), replacing the controller-queue tick.

### 4.9 `SetActive` faithfulness (deferred from SP1)

Tier-0 §4.2: `SetActive(bActive)` stores the flag; if deactivating (`bActive==0`),
`ClearAnimationsOfType(0,1,5,6)`. Honor the argument (today `SetActive(*args)` ignores it and always
sets active), wire the anim-clear (now possible with the queue), and apply BC's RE'd inactive
constructor default (the piece SP1 deferred).

## 5. Conflict-resolution model — the single referee (RE-CONFIRMED, EXACT)

`Classify1` = `Classify2` run with the currently-playing animation as the "existing" record. One
referee, called `(existing, new)` at enqueue time (§4.2): first against the current animation, then
against each queued record. **Inputs: only the two `CAT_` categories, plus the two records' name
fields in exactly two cells. The flags word (`+0x04`) and object identity are ignored.**

**Verdict table** (RE project, Appendix B; rows = existing category, cols = new category):

| existing ↓ / new → | 0 BREATHE | 1 INTERRUPT | 2 NON_INT | 3 TURN | 4 TURN_BACK | 5 GLANCE | 6 GLANCE_BACK |
|---|---|---|---|---|---|---|---|
| **0 BREATHE** | reject-new | stop-old | stop-old | stop-old | stop-old | stop-old | stop-old |
| **1 INTERRUPT** | coexist | reject-new | stop-old | stop-old | coexist | coexist | coexist |
| **2 NON_INT** | coexist | coexist | coexist | coexist | coexist | coexist | coexist |
| **3 TURN** | coexist | coexist | coexist | coexist | **name\*** | coexist | coexist |
| **4 TURN_BACK** | coexist | coexist | coexist | coexist | coexist | coexist | coexist |
| **5 GLANCE** | coexist | coexist | stop-old | stop-old | stop-old | coexist | **name\*** |
| **6 GLANCE_BACK** | coexist | coexist | stop-old | stop-old | stop-old | coexist | coexist |

- **Null existing record ⇒ coexist.**
- **`name*`** (two cells only: existing `TURN 3` × new `TURN_BACK 4`; existing `GLANCE 5` × new
  `GLANCE_BACK 6`) = **coexist**, except **stop-both** when both records carry a non-null, **equal**
  name **and** the existing record is **not** the currently-playing animation. This is the sole
  current-vs-queued asymmetry (`Classify1` tolerates the same-named conflict against what's actually
  playing; `Classify2` rejects it against a waiting record). `stop-both` = stop the existing **and**
  drop the new.

**Verdict → `SetCurrentAnimation` action (§4.2):** `stop-old` → stop the existing's playback + enqueue
new; `reject-new` → drop the new (stop its just-built object); `stop-both` → stop existing + drop new;
`coexist` → enqueue new.

**Name source.** Each record's own name field (`+0x0C`), set from the **4th argument** to
`SetCurrentAnimation` (null if that arg is null), compared by content. The character's `+0xa0`/`+0xa4`
target buffers are **not** consulted by the referee — those are written later, at play time, by
`PreparePlay`, and read by other logic (§4.4/§4.6).

**Practical consequence (RE).** In every reconstructed enqueue path the newcomer side of both name
pairs (a `TURN_BACK`/`GLANCE_BACK` record) is enqueued with a **null** name; the tiebreaker requires
both names non-null, so both `name*` cells collapse to plain **coexist** and **`stop-both` is
currently unreachable**. We implement it faithfully regardless (a caller could enqueue a named
turn-back/glance-back).

**Correction to the earlier draft:** the "move-toward" side of the name pairs is **`TURN` (3)**, not
`NON_INTERRUPTABLE (2)`. `MoveTo` (enqueued as cat 2) never participates in a name compare — as an
incumbent it always coexists; as a newcomer it is just a preempting category.

**Implementation.** The table is literal data (a 7×7 lookup keyed by the two category integers) plus
the null-existing and `name*` rules, wrapped in one `classify(existing, new, existing_is_current) ->
verdict`. Tests assert the table cell-for-cell (no inference remains).

## 6. Verification

- Unit tests for: queue enqueue/conflict/coexist; `UpdateAnimationQueue` dispatch incl.
  `Special4/6`; release + per-category cleanup (glance-away clears `0x2`+name, turn-back clears
  `0x4`+name); the four predicates; each action method (key composition, category/flags, idle-gate
  for `Breathe`); `SetActive` deactivate-clears-interruptable.
- The clip-player seam re-tested against the existing playback behaviors.
- **Full gate** (`scripts/check_tests.sh`) green.
- **Live in-game pass required** — SP2 is player-visible and re-homes live-verified behaviors (idle
  gestures, hit reactions, turn-to-captain, walk-on, glances). Per project practice, SP2 is **not
  done** until Mark has seen these run in-game. The plan's final task is a live-verification
  checklist, not a green-tests claim.

## 7. Out of scope

- Camera-watch internals (`AT_WATCH_ME`/`LOOK_AT_ME`) — separate subsystem, unchanged.
- Speaking/lip-sync (SP3); status widgets / position-zoom (SP4).
- `MorphBody`/`GetHeadHeight` (YAGNI, 0 call sites).
- Literal memory layout (freelist/slab) — behavioral fidelity only.

## 8. Resolved decisions

- **Own + demote to clip-player** (one queue, one door).
- **`Classify` gap RESOLVED** by the RE project — one referee with an exact 7×7 verdict table (§5,
  Appendix A + B). No inference remains; `classify()` is byte-faithful and tested cell-for-cell.
- **One SP2 plan** (not split into SP2a/SP2b); decomposed into tasks with the integration + live
  pass at the end.
- `SetActive` faithfulness lands here (deferred from SP1).

---

## Appendix A — relayed RE question (Classify1 / Classify2) — ANSWERED

**Question (relayed):**
> **CharacterClass animation-queue conflict resolution — `Classify1` (`0x0066C9E0`) and `Classify2`
> (`0x0066C860`), called from `SetCurrentAnimation` (`0x0066AEF0`).**
> The tier-0 `CharacterClass.md` reconstructs these as returning a small code (0 = stop-existing,
> 1 = stop-both-and-reject, 2 = reject-new, else = coexist) but marks the *conditions* that select
> each code as unspecified. For each of `Classify1` (new record vs. the **current** animation) and
> `Classify2` (new record vs. each **queued** record): what inputs drive the decision — the two
> records' `CAT_` categories (0–6), the flags-to-apply word (`rec+0x04`), the name string
> (`rec+0x0C`), or object identity? Which category pairings stop the existing animation, which
> reject the new one, which stop both, and which allow coexistence? Is the comparison symmetric
> between `Classify1` and `Classify2`?

**Answer (RE project, via Mark, 2026-07-21):**
> There's really only one referee. `Classify1` isn't separate logic — it just runs `Classify2` with
> the character's currently-playing animation as the "existing" one. Picture a single referee
> comparing two animations: the one already there and the new one asking to play.
> **What it looks at:** only the *kind* of each animation — a category number — plus, in exactly two
> situations, the animation's *name*. It ignores the flags word (`+0x04`) and ignores which 3-D
> object is attached. Categories drive everything; the name is a tiebreaker in two cases; object
> identity and flags don't matter.
> **Four verdicts:** stop the old / reject the new / stop both / coexist.
> **Rules:** (1) Idles yield to real movement — a real animation stops an idle; two idles keep
> whichever was already playing. (2) The "heavy" movements (locomotion / turn-around) don't fight —
> they almost always coexist. (3) Light interruptable moves (glances and similar) get stopped when a
> committing movement (walk, turn) comes in. (4) Names matter only in two match-ups: "move toward X"
> vs "turn back from X", and "glance at X" vs "glance away from X" — same target ⇒ new rejected and
> old stopped, **unless** the old one is the animation currently playing, in which case they coexist.
> **Symmetric?** No — order matters, deliberately. Whoever is already there has priority: a real
> animation preempts an idle, but an idle can't preempt a real animation. `Classify1` vs `Classify2`
> are the same referee; the only practical difference is leniency — a same-named conflict is
> tolerated against the animation actually playing now, but causes a rejection against something
> still waiting in the queue.

Encoded as the model in §5.

## Appendix B — follow-up RE question (category→verdict mapping) — ANSWERED

**Answered (RE project, via Mark, 2026-07-21):** a complete 7×7 verdict table, encoded verbatim in
§5. Key results: the exact per-cell verdicts; a **null existing record ⇒ coexist**; the name
tiebreaker is only the two cells `(existing TURN 3 × new TURN_BACK 4)` and `(existing GLANCE 5 × new
GLANCE_BACK 6)`, comparing each record's own `+0x0C` name (the 4th `SetCurrentAnimation` arg), and
**stop-both is unreachable on all reconstructed paths** (the newcomer side is always enqueued
null-named). The "move-toward" name side is `TURN (3)`, **not** `NON_INTERRUPTABLE (2)` — correcting
the question's assumption. `NON_INTERRUPTABLE (2)` and `TURN_BACK (4)` incumbents never fight (always
coexist); `TURN_BACK (4)` preempts a glance but not an `INTERRUPTABLE` incumbent (a genuine
asymmetry); duplicate-reject happens only BREATHE-vs-BREATHE and INTERRUPT-vs-INTERRUPT.

**Original question (relayed):**

To eliminate the §5 category→bucket inference, a precise follow-up is relayed to the RE project:

> **Follow-up: the exact category→verdict mapping for the Classify referee, in raw `CAT_` integers
> (0–6).** We have the referee's behavioural rules; to implement it exactly rather than infer the
> category buckets, could you give the mapping in terms of the `CAT_` category integers as the
> decompiled code actually tests them?
> Categories: `0=BREATHE, 1=INTERRUPTABLE, 2=NON_INTERRUPTABLE, 3=TURN, 4=TURN_BACK, 5=GLANCE,
> 6=GLANCE_BACK`.
> 1. For `Classify2(existing_cat, new_cat)` **ignoring** the name tiebreaker: what verdict (stop-old
>    / reject-new / stop-both / coexist) results for each ordered pair of category integers 0–6? A
>    7×7 table, or the reconstructed branch logic, whatever the function actually does.
> 2. Which categories does the code treat as "idle," "heavy/don't-fight," "light/interruptable," and
>    "committing" — the exact membership tests on the category integer?
> 3. For the two name-tiebreaker match-ups: which exact category pair triggers each (move-toward =
>    which category? we enqueue `MoveTo` as `CAT_NON_INTERRUPTABLE (2)`; turn-back = `CAT_TURN_BACK
>    (4)`? glance-at = `CAT_GLANCE (5)`, glance-away = `CAT_GLANCE_BACK (6)`?), and what string does
>    each record supply as the compared name — the record's own name field (`+0x0C`) or the
>    character's `+0xa0`/`+0xa4` target-name buffer? For a move (enqueued with a **null** record
>    name in tier-0), where does the compared "X" come from?

