# Stub Heatmap — Scouting Pass, 2026-08-10

**What this is:** a scouting pass over `docs/stub_heatmap.md` to answer "what would
it take to plug these?" ahead of implementing. Findings are recorded **at the code
sites** wherever one exists (grep `SCOUTED 2026-08-10`); this document is the index
and holds what has no code home yet.

**Why it lives here and not in the heatmap:** `tools/stub_heatmap.py` regenerates
that file from telemetry and preserves **only** the `markedResolvedOn` column
(`parse_existing_annotations`, line 150). Any prose added to the heatmap is silently
destroyed on the next regeneration — including the triage note added on 2026-08-09,
which is already living on borrowed time.

---

## Part 1 — Three structural problems that block the risk tables

The heatmap's two most valuable tables — **Boolean-test call sites (truthiness
risk)** and **Numeric-coercion call sites (`int()==0` risk)** — are where the known
real bugs came from (`WC_*` keyboard codes, `TGUIObject.ALIGN_*`,
`EngRepairPane.REPAIR_AREA`, `STTopLevelMenu_GetOpenMenu`). They have sat unactioned,
and scouting shows why: **they identify a location but not a culprit.**

### 1.1 The attribution gap — no owner, no attribute *(the main blocker)*

`record_bool(owner_type)` in `engine/core/stub_telemetry.py` **accepts the owner and
then discards it**, storing only `_caller(3)`. `record_coercion(kind)` is worse — it
never receives an owner or attribute at all.

So a row says "something falsy-tested here" but not *which* stub, and one line can
truth-test several different names across a run. Triaging any row means opening the
file and reasoning about which name is undefined. That is slow, error-prone, and
exactly the manual archaeology this telemetry exists to remove.

**The data is already in hand.** `_Stub` carries both `_stub_owner` and `_stub_name`
(`engine/core/ids.py:43-45`), and `_Stub.__bool__` already passes the owner. Fix:

1. `_Stub.__bool__` → `record_bool(self._stub_owner, self._stub_name)`
2. key `_bool_sites` on `(owner, attr, site)`; same for `_coercion_sites` with `kind`
3. widen both tables in `tools/stub_heatmap.py`

Keep the site in the key — the same stub truth-tested from two places is two bugs
with two fixes. The counter is keyed data, so the generator must tolerate both the
old narrow key and the new wide one rather than assuming the new shape.

Recorded at `engine/core/stub_telemetry.py::record_bool` / `record_coercion`.

### 1.2 Line numbers rot; owner+attr does not

The tables key on `file:line`, and the lines have already drifted. Heatmap coercion
rank 1 points at `engine/appc/input.py:123`, which is now a constructor; the real
`int()` collapse is at `:214` (`int(wc_code)` — the `WC_*` trap). Every row's line
reference decays with each edit to the file, which compounds 1.1: no culprit *and* a
stale address. Fixing 1.1 makes the tables self-describing and edit-proof.

### 1.3 Worktree paths pollute both tables

11 of 35 truthiness rows and 4 of 14 coercion rows are
`.claude/worktrees/anim-channel-binder/...` — duplicates of real project paths from a
worktree run. They inflate the tables and split the counts for the same underlying
site. The generator should normalise or exclude paths under `.claude/worktrees/`.

---

## Part 2 — Findings with a code home *(recorded at the site)*

| Finding | Site | Severity |
|---|---|---|
| `ET_CLOAKED_COLLISION` fires for every collision involving a non-ship | `engine/appc/collisions.py:242` | **live bug** |
| `ToggleMapWindow` is an armed trap — implementing it toggles the map at every cutscene | `engine/appc/top_window.py` | latent |
| Telemetry attribution gap | `engine/core/stub_telemetry.py` | blocker |

### 2.1 `collisions.py` — live bug, and a correction to yesterday's triage

`_emit_cloaked_collision` runs on **every** collision (`collisions.py:232`) and uses
the instance form:

```python
getter = getattr(cloaked, "GetCloakingSubsystem", None)
```

That never returns `None`: `TGObject.__getattr__` vends a truthy `_Stub` for any
method the class does not define. On a planet/asteroid/station the whole guard chain
passes and the event fires — `HelmMenuHandlers.CloakedCollision` plays a "we hit a
cloaked ship" line for ramming a planet.

The fix is already written elsewhere: resolve through the **class**, as
`engine/appc/sensor_detection.py:42-56` does. Only `ShipClass` defines the real
method (`ships.py:992`).

⚠️ **Correction to the 2026-08-09 triage.** Heatmap ranks 45/46
(`Planet.GetCloakingSubsystem` and the chained `.IsTryingToCloak`, 324 hits each)
were dated `markedResolvedOn 2026-08-09` on the strength of the `sensor_detection`
fix. That attribution was **wrong** — the chained attribute is *this* loop's
signature, and this site is unfixed. **The dates have been reverted.** This is
precisely the failure mode `markedResolvedOn` is designed to prevent: a wrong date
silently disarms the regression detector for that stub.

### 2.2 `MapWindow_Cast` — an armed trap under `ToggleMapWindow`

`MissionLib.py:747-749`, immediately before `StartCutscene`, closes the tactical map
*if open*. `App.MapWindow_Cast` is absent → truthy stub → `IsWindowActive()` truthy →
the guard is always true → `ToggleMapWindow()` always fires. Harmless **only** because
our `ToggleMapWindow` is a no-op. Implement it without first implementing
`MapWindow_Cast` and a closed map will *open* on every cutscene. Live in 47/201 runs.

---

## Part 3 — Findings with no code home yet

### 3.1 `CinematicWindow_Cast` / `SetInteractive` — 197/201 runs

`MissionLib.py:783-785` (truthiness rank 13, the **highest-coverage row in the
table** — essentially every recorded run):

```python
pCinematic = App.CinematicWindow_Cast(pTop.FindMainWindow(App.MWT_CINEMATIC))
if pCinematic:
    pCinematic.SetInteractive(1)
```

Both `CinematicWindow_Cast` and `SetInteractive` are absent; `MWT_CINEMATIC` is fine
(`top_window.py:27`). The stub makes the guard pass and the call a no-op. BC's own
comment states the intent: *"Ensure that the cinematic window is set interactive. If
we were in warp during a cutscene, then the normal mechanism will not be triggered."*
So this is a **recovery path for input/interactivity after a warp-during-cutscene**.
Whether anything is currently broken depends on what `SetInteractive` gates — unknown,
and the reference has no `CinematicWindow` section. **Open question.**

### 3.2 `CharacterClass_IsCollisionAlertEnabled` — default unknown *(2,847 hits, 140/201)*

Open-table rank 5. Read once, at `HelmMenuHandlers.py:2422`:

```python
if not (App.CharacterClass_IsCollisionAlertEnabled()):
    return
```

`CharacterClass_SetCollisionAlertEnabled` exists in the SWIG binding but has **zero
call sites across all 1,228 SDK files** — nothing in Python ever sets it. The value is
therefore a pure **engine default**, and our truthy stub silently picks *enabled*, so
`CollisionAlertCheck` always runs and Helm calls out near-misses.

Reference: the entry is real — `CharacterClass_SetCollisionAlertEnabled` at
`0x005fe6c0` (*faithful*, identity fact) — but **no specification section covers its
behaviour** (best relevance 0.18, below the 0.35 floor). The default is not recoverable
from the corpus today.

Two routes when this is implemented:
- read it from a BCS save preamble, the established technique for a default nothing
  ever sets (`docs/engine/bcs-save-format.md`); or
- re-ask the reference once its retrieval improves.

Until then, **treat "enabled" as an assumption, not a finding.**

### 3.3 BC has two *process-global* collision toggles; we have per-object only

From `spec/ProximityManager.md §6.1` (*reviewed-not-tested*, confidence *partial*):

> The physical collision response chooses between two flags — a **multiplayer** one
> when a multiplayer session is in progress and a **single-player** one otherwise —
> and, if the chosen flag is clear, it **skips the pair when either object is the
> player's own ship**. Two non-player ships collide regardless; weapon impacts and
> proximity checks are not gated at all. Both are single process-wide variables, not
> fields of any manager. Constructing a multiplayer game copies the single-player
> flag over the multiplayer one, so an MP value set before session creation does not
> survive it.

We model collisions only per-object (`_collisions_enabled`, `collisions.py:54`, via
`SetCollisionsOn`). BC's mechanism is different in kind: a global that suppresses
**player-involving pairs only**. This is worth reconciling against our warp
collision-suppression work, which used a single-slot global to make the player
non-collidable — similar intent, different shape.

*Not* the same thing as §3.2: that is the bridge-crew **alert callout**, this is
physical collision **response**. Do not conflate them.

### 3.4 `TGParagraph.SetString` — the largest single row *(44,024 hits, 105/201)*

Open-table rank 1. `TGParagraph` exists (`engine/appc/tg_ui/widgets.py:320`) but has
no `SetString`; there are 93 `.SetString(` call sites in the SDK. This is the head of
the UI cluster that dominates the open table (`TGIcon.GetRight` 40,801;
`TGFrame.GetRight` 14,643; `TGPane.GetBottom` 4,256).

Note the near-miss during scouting: `MissionLib.py:2478` also calls `SetString`, but
on a **`TGStringEvent`**, and that class is already fully implemented in
`App.py:1396-1400` with `SetString`/`GetString`/`GetCString`. The MissionLib
condition-callback dispatch (`SetString("module*function")` → `GetCString()` →
`strop.split`) therefore works. **Only the text-widget `SetString` is missing.**
Checked rather than assumed — the two are unrelated despite the shared name.

### 3.5 Note on the music work (branch `fix/open-question-reconciliation`)

While scouting: that branch adds `SetCString`/`GetCString` to the base `TGEvent`
(`engine/appc/events.py`) for `ET_MUSIC_DONE`. A purpose-built `_TGStringEvent` with
exactly that surface already existed in `App.py:1396`. What was built works, but the
faithful form is `App.TGStringEvent_Create()`. Worth folding in when that branch is
revisited — not a bug, a redundancy.

---

## Suggested order when implementing

1. **§1.1 telemetry attribution** — cheap, and it makes every other row in both risk
   tables self-diagnosing. Do this first or keep paying the archaeology tax.
2. **§2.1 `collisions.py` cloaked-collision** — the only confirmed live bug found.
   Three-line fix; the correct form already exists in `sensor_detection.py`.
3. **§1.3 worktree filtering + §1.2** — small generator changes, better signal.
4. **§3.4 UI cluster** — largest hit counts, but they are HUD widgets; assess whether
   they are cosmetic before spending on them.
5. **§3.2 collision-alert default** — needs evidence we do not have yet; do not guess.
