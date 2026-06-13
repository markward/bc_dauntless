# Bridge Crew Population — Design

**Date:** 2026-06-13
**Status:** Approved (design); implementation pending
**Feature line:** crew-menu cluster → crew speech (`SpeakLine`/`SayLine`, merged `00a119a`) → menu-interaction ack (`feat/crew-menu-ack-speech`) → **crew population** (this slice).
**Branch:** `feat/bridge-crew-population` (stacked on `feat/crew-menu-ack-speech`).
**Builds on:** `docs/superpowers/specs/2026-06-13-crew-menu-acknowledgement-speech-design.md`.

## Goal

Make the crew acknowledgement (and `CharacterInteraction`/`CharacterAction` speech) produce **real voice + subtitle** instead of the placeholder `"Aye, Captain."` fallback, by populating the five bridge officers with their real SDK names and localization databases.

Today nothing creates bridge crew: our `LoadBridge.Load` shim builds an empty bridge set, so `resolve_character("Tactical")` auto-vivifies an **empty** `CharacterClass` (no database, no name) and `acknowledge` always hits the text-only fallback with `wav=None` — `_play_voice` is never reached. (Root-caused during smoke-testing of the ack branch.)

## Decisions (resolved during brainstorming)

1. **Approach:** run the SDK's own per-officer creation + configuration (`CreateCharacter` then `ConfigureForXxx`), **guarded per officer**, letting our shims absorb the rendering/animation setters as no-ops. Not a throwaway dauntless helper.
2. **Forward-compatibility:** structure the population as the `ConfigureCharacters` stage of a future **full** SDK bridge `Load` (the deferred "option 3": `CreateBridgeModel` + `ConfigureCharacters` + `PreloadAnimations`). This slice does the character step; the hook is shaped so option 3 extends it.
3. **Verification-first:** the downstream audio path (Voice category gain, wav file resolution/decode) is **unverified**. The plan front-loads a live-build audio check on one officer before hardening all five.

## Key SDK facts established

- Each officer module (`Bridge/Characters/{Felix,Kiska,Saffi,Miguel,Brex}.py`) exposes **`CreateCharacter(pSet)`** — idempotent (`if pSet.GetObject("Tactical") != None: return it`) — which does `g_kModelManager.LoadModel(bodyNIF, "Bip01")` + `LoadModel(headNIF, None)`, `CharacterClass_Create(bodyNIF, headNIF)`, `ReplaceBodyAndHead(...)`, `SetCharacterName("Felix")`, `AddObjectToSet(pFelix, "Tactical")`, `GetLight("ambientlight1").AddIlluminatedObject(pFelix)`, `Set{Size,Gender,Standing,RandomAnimationChance,BlinkChance,AudioMode}(...)`, **`SetDatabase("data/TGL/Bridge Crew General.tgl")`**, and `LoadSounds()`.
- The bridge module's **`ConfigureCharacters(pSet)`** (`GalaxyBridge.py:128`) casts `GetObject("Tactical")` etc. (assumes already created) and calls each officer's `ConfigureForGalaxy(pChar)` — which only adds animations/facial images (inert in our shim).
- Officer ↔ set-name mapping (GalaxyBridge): Felix→`Tactical`, Kiska→`Helm`, Saffi→`XO`, Miguel→`Science`, Brex→`Engineer`.
- **No officer sets a `YesSir` key** → `acknowledge`/`CharacterInteraction` use the SirN branch: line `"<CharacterName>Sir<1–5>"` (e.g. `"FelixSir3"`) from the character's database.
- `SetDatabase` is called with a **path string**; `game/data/TGL/Bridge Crew General.tgl` exists (66 KB).

## Components

### 1. Crew-population hook in `LoadBridge.Load` (`LoadBridge.py`)

After the bridge set exists and the game is live (same guard as `CreateCharacterMenus`), populate the requested bridge's officers, mirroring the SDK create→configure order:

- For each officer module of the requested bridge (default `GalaxyBridge`: the five above), call `Bridge.Characters.<Name>.CreateCharacter(pBridgeSet)` then run the bridge module's `ConfigureCharacters(pBridgeSet)`.
- **Each officer's create+configure wrapped in try/except** with `logging.exception` (same discipline as `CreateCharacterMenus`) — one officer failing must not abort the others or block menu/mission load.
- Idempotent: `CreateCharacter` self-guards on the existing object, and a module-level `_crew_populated` flag (reset in `reset_sdk_globals`, like `_menus_created`) prevents rework per bridge load.
- Runs alongside / just before `CreateCharacterMenus` in `Load`. The officer-module list is per-bridge; this slice targets the `GalaxyBridge` set, structured so other bridges (and the full option-3 `Load`) slot in.

### 2. `CharacterClass.SetDatabase` loads the TGL (shim fix) — `engine/appc/characters.py`

`SetDatabase(value)`:
- If `value` is a `str` (the SDK norm — a TGL path), resolve it via `App.g_kLocalizationManager.Load(value)` and store the resulting **DB object**.
- If `value` is already a DB object (or anything non-str), store as-is (back-compat).
- `GetDatabase()` returns the stored DB object.

This matches Appc semantics (where `SetDatabase(path)` associates a loaded database) and is what makes `acknowledge`/`emit`'s `HasString`/`GetFilename` work against the officer's DB. Best-effort: a failed `Load` stores `None` rather than raising.

### 3. Dependency audit + safe stubs (the "guarded" substance)

`CreateCharacter` runs Appc calls **before** `SetDatabase`; if any raise, the per-officer guard catches it but the database never gets set → no audio. So those calls must not raise. Audit and, where needed, add minimal no-op stubs:
- **`App.g_kModelManager.LoadModel(path, skeleton)`** — confirm it exists and no-ops safely (we do not render the character body/head).
- The officer module's **`LoadSounds()`** and `GalaxyBridge.LoadSounds()` (`Game_GetCurrentGame().LoadSoundInGroup(...)`) — confirm safe or guard.
- `pSet.GetLight("ambientlight1").AddIlluminatedObject(...)` — already a no-op (`engine/appc/lights.py`); our `LoadBridge.Load` already creates `"ambientlight1"`.
- The `Set{Size,Gender,…}` calls — already absorbed by `CharacterClass.__getattr__`'s `Set*` data-bag.
- `AddPositionZoom(...)` — already absorbed by the data-bag (its zoom use belongs to the deferred camera slice).

The audit's success criterion: `CreateCharacter` reaches `SetDatabase` for all five officers headlessly.

### 4. `resolve_character` / `acknowledge` resolve real data (no code change)

With officers populated, `resolve_character("Tactical")` returns the real Felix (`GetCharacterName()=="Felix"`, DB loaded). `acknowledge` then resolves `"FelixSir<N>"` → real subtitle text + wav and routes them through the bus; the `"Aye, Captain."` fallback remains only for genuinely-missing lines. No change to the ack-branch code — populating the data is what activates it.

## Data flow

```
LoadBridge.Load(bridge)  [game live]
  → for each officer of the bridge module:
        Bridge.Characters.<Name>.CreateCharacter(pBridgeSet)   [guarded]
          → CharacterClass_Create + SetCharacterName("Felix")
          → AddObjectToSet(pFelix, "Tactical")
          → SetDatabase("data/TGL/Bridge Crew General.tgl")  → loads TGL → DB object
    → pMod.ConfigureCharacters(pBridgeSet)                     [guarded]
  → CreateCharacterMenus()   (existing)

F-key / order  → resolve_character("Tactical") → real Felix (DB loaded)
              → acknowledge → "FelixSir3" → GetString/GetFilename → bus.speak(text, wav)
              → subtitle + voice
```

## Verification-first sequencing (in the plan)

The plan orders work so the **audio path is proven on one officer before the full build-out**:
1. `SetDatabase`-loads-TGL + populate a single officer (e.g. Tactical/Felix) far enough that `acknowledge` resolves a real `"FelixSir<N>"` wav.
2. **User confirms in the live build** that opening the Tactical menu plays audio (per the no-desktop rule, the user drives; I rely on logs + their report).
3. Only then: the dependency audit hardening + all five officers + reset wiring + tests.

If step 2 reveals no audio despite a resolved wav, that isolates a **second** layer (Voice-category gain / wav file resolution / decode) as a separate follow-up — caught cheaply, before investing in five officers.

## Error handling / edge cases

- **Per-officer failure**: guarded; logged; other officers and menu/mission load proceed.
- **`SetDatabase` Load failure / missing TGL**: stores `None`; `acknowledge` falls back to `"Aye, Captain."` (still visible, just no real line).
- **Mission swap**: `_crew_populated` reset in `reset_sdk_globals` so the next bridge load repopulates; `CharacterClass_GetObject` still returns the existing officers within a load.
- **Pre-game eager bridge preload**: same `Game_GetCurrentGame() is None` guard as menu creation — defer population until the mission's own `Load`.

## Testing

Headless, **focused pytest subsets only** (never the full suite — it OOMs the machine). No synthetic desktop input.

- `SetDatabase(path_str)` yields a DB object whose `HasString`/`GetFilename` work; `SetDatabase(db_obj)` stores as-is; failed load → `None`.
- After `Load` with a live game, the bridge set contains the five officers under `Tactical/Helm/XO/Science/Engineer` with real names (`Felix`/`Kiska`/`Saffi`/`Miguel`/`Brex`) and loaded DBs.
- `resolve_character("Tactical")` → character named `"Felix"`.
- `acknowledge(felix)` with the real DB resolves the `"FelixSir<N>"` text (not the fallback) when the TGL has it; speaker is `"Felix"`.
- Population is idempotent and guarded (a deliberately-broken officer module is logged, others still populate).
- **Live-build verification** (user-driven): open a station menu / issue an order → hear the officer.

## Out of scope (this slice)

- **Authentic camera zoom-to-station** — its own spec/slice (`ZoomCameraObjectClass` shim, bridge-NIF station-node extraction, animated `_BridgeCamera` zoom, talk-to→zoom wiring). Deferred.
- Character rendering / animation / lip-sync; `CreateBridgeModel`, `PreloadAnimations`, viewscreen/camera setup (the rest of the option-3 build-up).
- Fixing the audio backend if verification reveals a Voice-category / decode problem (separate follow-up).
