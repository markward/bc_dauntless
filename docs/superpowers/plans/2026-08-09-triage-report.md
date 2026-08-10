# Open-Question Triage Report — 2026-08-09

Terminates Phase 2 of `docs/superpowers/specs/2026-08-09-open-question-reconciliation-design.md`.
Every row below was established from **code**, per the branch's evidence standard:
no status changed on the strength of a prose doc.

## Headline

Of the 6 OQs listed as open and the 2 listed as partial, **5 were already
answered** by shipped Phase-2 work and one question's premise was void. The
"open questions" list was substantially a Phase-1 planning artifact that nobody
had reconciled against the engine we actually built.

Two genuine gaps survived, and **one of them was not on the list at all** — it
surfaced only because a ✅-ticked closure turned out to be inaccurate.

## Audited items

| Item | Status | Evidence | Phase 3? |
|---|---|---|---|
| OQ-3.1 NIF/OpenMW | **superseded** | BC ships NIF v3.1; OpenMW cannot parse v3.x. Oracle dropped in `2026-05-08-nif-loader-design.md:60-63`; own parser at `native/src/nif/`. Zero OpenMW code in tree | no |
| OQ-3.2 damage geometry tagging | **resolved** | Not node-tagged — paired `*_vox.nif` with `NiBinaryVoxelData`. `docs/engine/nibinaryvoxeldata-format-v3.1.md` (84-file corpus), `native/src/voxel/`. ctest `VoxelDataHeader.*`, `VoxelVolume.*`, `SurfaceVoxelize.*` | no |
| OQ-3.3 body/head assembly | **resolved** | `graft_head_cpu()` `native/src/assets/src/model_compose.cc:206`. ctest `GraftHeadCpu.*` incl. `GraftsHeadMeshNotParentedUnderAttachNode` | no |
| OQ-8.3 `MorphBody` | **dead surface** | One occurrence outside comments: SWIG binding `App.py:4736`. Zero call sites in 1,228 SDK scripts | no |
| OQ-8.4 animation catalogue | **superseded** | Assets come from the BC install. A static manifest would be *wrong*: BC re-registers `DBCameraSitDown` to correct a typo path for a non-existent file (`GalaxyBridge.py:193`), and some paths lack extensions. `engine/appc/animation_manager.py:19`, `engine/host_loop.py:1475` | no |
| OQ-2.3 tractor force law | **partial, unpromotable** | Built + 93 tests (`engine/appc/tractor.py`). But it is a designed approximation; reference has no tractor force section (`search_reference("tractor")` → UI toggle only; force query below relevance floor at 0.20) | no |
| OQ-1.3 save format | **resolved, count corrected** | Was "39 classes"; measured 46 `__getstate__` / 46 `__setstate__` across 38 files. Substance unaffected | no |
| **OQ-2.2 set-to-set warp exit velocity** | **GENUINELY OPEN** | In-system warp is done (`ship_motion.py:252`, restores pre-warp speed, tested). Set-to-set has **no** `SetVelocity` anywhere in the set-change path; none of the 12 `test_warp_*.py` asserts arrival velocity. **Our behaviour is accidental, not chosen** | **yes** |
| **OQ-6.1 DynamicMusic** | **GENUINELY OPEN** | Maelstrom campaign drives it (`Maelstrom.py:111,265`; Episodes 1,4,6,7,8), not module-stubbed, but `g_kMusicManager` / `ET_MUSIC_DONE` / `ET_MUSIC_CONDITION_CHANGED` are all absent → silent no-op. Live telemetry: heatmap ranks 163/164, last seen 2026-08-06 | **yes** |
| **`PhaserBank.CanHit`** *(not on the OQ list)* | **LATENT GAP** | `ConditionInPhaserFiringArc.py:175` calls it in live AI (`FedAttack`, `AI/Setup`). We don't implement it → truthy `_Stub` → arc test passes unconditionally. **Latent, not observed**: absent from the heatmap, so never hit in 201 runs | **yes** |

## Phase 3 candidates, ordered

**1. `PhaserBank.CanHit` — smallest, best specified.**
The reference publishes `PhaserBank_CanHit` at `0x00619030` plus
`GetArcWidthAngles`, `GetArcHeightAngles`, the four `Arc*Angle{Min,Max}`
accessors, `GetOrientationForward/Right/Up` and `GetMaxPhaserRange` — enough to
specify it as a point-in-arc-cone-and-range test, which is geometry we already do
elsewhere. This retires the note at `engine/appc/weapon_subsystems.py:684` calling
it "unspecifiable". Headless-testable. *Note: names and addresses are identity
facts; behaviour was not asked of the reference and is not assumed.*

**2. Set-to-set warp exit velocity.**
Decide and implement deliberately rather than leaving it accidental. The
reference could not reach it — three queries returned *below-relevance-floor*,
with the likely section (`spec/ShipClass.md — Movement, docking & warp`) scoring
**0.32 against a 0.35 floor**. That is a retrieval limit, **not** evidence of
silence; re-ask when the scorer improves. Failing that, decide from gameplay and
record it as a chosen default.

**3. OQ-6.1 DynamicMusic — largest, and the only one needing a live run.**
Smaller than the OQ implies: the queue and state machine are SDK-side in
`DynamicMusic.py` (`EnqueueMusic`, `ProcessQueue`, `SwitchMusic`,
`OverrideMusic`, `StandardCombatMusic`). We supply:

- `App.g_kMusicManager` with `LoadMusic`, `UnloadMusic`, `StartMusic`,
  `StopMusic`, `PlayFanfare`
- `ET_MUSIC_DONE` (drives `MusicDone` → `ProcessQueue`) and
  `ET_MUSIC_CONDITION_CHANGED`
- a music path in `engine/audio/` with a volume ramp — `TGSound.SetVolume`
  already exists (`engine/audio/tg_sound.py:141`)

Per `spec/TGAudio.md §6` (*reviewed-not-tested*, confidence *partial*):
`StartMusic` (`0x00713D60`) registers a fade timer via TGTimerManager;
`LoadMusic` (`0x00713AD0`) reads a `Sound/StreamMusic` config toggle. BC's second
path, `TGRedbook` (CD audio via MCI), does not apply to us.

**Unresolved sub-question:** whether the fade is a true crossfade (both tracks
audible) or fade-out-then-in. The reference section does not say. Settle by ear
against the real game before committing.

## Needs Mark's live verification

- **OQ-6.1** — music playback cannot be verified headlessly. Passing tests will
  not show that music plays, let alone that transitions sound right.

## Deliberately not built

- `CloakingSubsystem_{Get,Set}CloakTime`, `_{Get,Set}ShieldDelay` — dead surface,
  zero SDK call sites. If ever needed, note the reference's object model
  (`sizeof` = `0xBC`): `g_cloakTime` (`0x8e4e1c`) and `g_shieldDelay`
  (`0x8e4e20`) are **class-static globals** — one shared cadence across all
  ships, not per-instance fields.
- `MorphBody` — dead surface.
- The 44 heatmap rows left open by the triage rule — staleness alone is not
  evidence of a fix; most carry `cov=1/201`, meaning the missions exercised
  changed rather than anything being implemented.

## What changed structurally

`tests/docs/test_doc_consistency.py` (4 tests) now machine-checks the counts that
had drifted. The audit is a one-time correction; the guards are what stop the
next drift. Proven non-vacuous: removing OQ-6.1 from the summary line while it is
unmarked fails two of them.
