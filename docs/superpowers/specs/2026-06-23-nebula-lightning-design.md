# Nebula Lightning (Thunder & God-Rays) — Design

**Date:** 2026-06-23
**Status:** Design approved, pending spec review
**Builds on:** the merged volumetric nebulae (`docs/superpowers/specs/2026-06-23-volumetric-nebulae-design.md`, `964670a9`) — this is follow-on **②** of the nebula roadmap (see `project_nebula_pockets` memory). ③ hull discharges and ④ wake remain separate.

---

## 1. Vision

A nebula should feel like a **thundercloud**: occasional **distant white light pulses** flash from somewhere in the cloud, brightening then dimming over a few seconds, lighting up both the cloud *and* the player's hull, with **crepuscular god-rays** streaming through the murk and a **rumble of thunder** following a beat later (the lightning-then-thunder gap). Mark's words: "occasional *distant* pulses of light, lasting a few seconds, getting brighter then dimmer… cast crepuscular rays through the cloud."

## 2. Scope

**In scope:** periodic distant flash pulses (transient directional lights → cloud + hull); screen-space radial **god-rays** during flashes; **delayed thunder audio**; a dedicated **Nebula Lightning** Modern VFX toggle.

**Out of scope (separate follow-ons):** ③ localised hull electrical discharges (the on-hull arcs); ④ ship wake. No drawn lightning bolts — ② is *light* pulses + shafts, not bolt geometry (bolts, if ever, belong with ③).

## 3. Decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| God-rays | **Core / designed-in from the start** | Mark wants the shafts as central, not a bolt-on |
| God-ray method | **Screen-space radial scatter** (during flashes) | Cheap (fixed-cost screen pass, only while a flash is live), dramatic, classic; decouples from the volumetric raymarch's per-step cost we fought to protect. Caveat: needs the flash roughly in-view → driver biases flash directions toward the camera |
| Audio | **Delayed thunder rumble** after the flash | The storm-distance "see it, then hear it" beat — maximum atmosphere |
| Hull lit by flash | **Yes** | The transient directional already feeds `opaque.frag`; lightning illuminating your ship in the murk is the best part, and it's nearly free |
| Toggle | Dedicated **"Nebula Lightning"** (Modern VFX, default on) | Independent of Volumetric Nebulae; purely visual/audio, no gameplay coupling |
| Cadence / intensity | Tunable **dials**, defaults proposed | Calibrate-up-then-down, like the cloud |

## 4. Architecture

A **Python flash driver** (the brain) feeds three dumb consumers it already reaches: the lighting list, a new god-ray render pass, and the audio system. All timing/randomness lives in the one testable driver.

### Components

| Unit | Location | Responsibility |
|---|---|---|
| **Thunder driver** | `engine/appc/nebula_thunder.py` (new), ticked per-frame from the host loop | State machine: while the player is in a nebula, spawn flashes on a jittered cadence; track each active flash's intensity envelope. Seeded RNG → deterministic, unit-testable. Emits `(directionals_to_add, [godray_descriptor], [audio_trigger])`. |
| **Light injection** | host-loop lighting aggregation (before `set_lighting`) | Merge each active flash's transient bright-white directional into the per-frame list → lights cloud (single-scatter) + hull (`opaque.frag`). Manages the 4-slot budget (reserves thunder slot(s)). |
| **God-ray pass** | `native/src/renderer/nebula_godray_pass.{h,cc}` + `shaders/nebula_godray.frag` (+ fullscreen vert) | Screen-space radial scatter from the flash's projected screen anchor; additive composite into HDR. Runs only when a flash is active (gated). |
| **Thunder audio** | host loop pending-trigger queue + existing audio system | Fire a delayed thunder one-shot per flash. Asset-agnostic wiring; needs a thunder SFX asset. |
| **Toggle** | Modern VFX config group (frame.cc namespace + binding + renderer.py + configuration_panel.py/.js) | "Nebula Lightning" default on; off → driver never spawns, zero cost. |

**Boundaries:** the driver knows nothing about GL or audio internals (plain descriptors out); the god-ray pass is data-in→pixels-out; light injection reuses `set_lighting`. Inert outside a nebula and behind the toggle.

## 5. The flash driver

Ticked each sim frame while the player is inside a nebula (reuses the nebula-membership signal). Manages a pool of active flashes (usually 0–1, occasionally 2 overlapping).

- **Cadence:** countdown with jitter — next flash in `interval ± jitter` (default ~`12 ± 6 s`). On fire, create a flash with a jittered peak intensity and duration.
- **Direction:** random distant direction **biased toward the view** (sampled in a cone around camera-forward, with spread) so most flashes are roughly in-frame → the screen-space god-rays have an on-screen anchor.
- **Colour:** white, faint cold-blue tint; optional nudge toward the nebula colour. Dial.
- **Envelope (brighten→dim):** fast rise (~0.2–0.4 s) + brief hold + longer decay (~1–3 s), with a subtle secondary flicker on the rise so it reads as lightning. `intensity(t)` drives both the injected light brightness and the god-ray strength.
- **Light injection + 4-slot budget:** each active flash contributes one transient directional `(dir, white·intensity)`. The renderer caps directionals at `MAX_DIR_LIGHTS = 4` and the system already uses some (sun + defaults); the driver **reserves the last slot(s)** by capping the scene's own directionals while in a nebula so 1–2 thunder slots are always free. **Pin the exact count `_aggregate_lights` emits during planning** so the sun is never starved.
- **Audio trigger:** on spawn, schedule the one-shot at `flash_time + delay`, `delay` jittered ~`0.5–2.0 s` (optionally shorter for brighter/closer flashes).
- **Outputs/tick:** `(directionals_to_add, [godray_descriptor{screen_anchor, intensity, color}], [audio_trigger{time, gain}])`. Deterministic given seed + in-nebula state.
- **Dials:** cadence interval/jitter, peak intensity, rise/decay, flicker, direction-cone width, colour, audio delay.

## 6. God-ray pass (screen-space radial scatter)

Run only while a flash is active (`intensity > 0`).

- **Anchor:** the driver projects the flash light direction to a screen-space point (where the light streams *from*) each tick and passes it in the descriptor. Off-screen / behind camera → the pass fades the effect out (no anchor → no shafts; the direction-bias keeps most flashes in-view).
- **March:** per pixel, step **toward the anchor** in screen space over N samples, accumulating the HDR colour (the bright flash-lit cloud) with a per-step decay — bright cloud near the light streaks outward along the view→light line (classic GPU-Gems crepuscular formulation: `accum += sample · weight · decay^i`, scaled by `exposure` and flash `intensity`).
- **Composite:** additive over the HDR target, premultiplied, **no feedback loop** — read from a scratch/copy and write additively, same discipline as the volumetric pass. Half-res option if heavy. Fixed cost, **only when a flash is live** → average frame pays nothing.
- **Dials:** sample count, decay, weight, exposure, overall strength (× `intensity`).

## 7. Audio

On flash spawn the driver schedules a thunder one-shot at `flash_time + delay`. The host loop holds a small **pending-trigger queue**; each fires once through the existing audio one-shot path (the same one crew speech / SFX use) when its time arrives. Volume scales with flash brightness. The **thunder SFX asset** is the one content dependency — check whether BC ships a usable storm/rumble; if not, drop in a placeholder and flag for replacement (wiring is asset-agnostic).

## 8. Toggle, integration & testing

**Toggle:** dedicated **"Nebula Lightning"** Modern VFX row, default on, independent of Volumetric Nebulae. Off → driver never spawns.

**Integration (host loop):** (1) tick the driver alongside the nebula tracker, reusing its in-nebula signal; (2) merge the driver's transient directionals before `set_lighting` (with the slot cap); (3) feed god-ray descriptors to the pass + drain the audio queue; (4) reset the driver + audio queue in `reset_sdk_globals` (mission swap).

**Testing:**
- **Driver (pytest, seeded):** spawns on cadence only in a nebula; envelope rises then decays; emits directional + god-ray descriptor + delayed audio trigger per flash; respects the slot reservation; deterministic; reset on swap.
- **God-ray pass (C++ FrameTest):** bright spot + on-screen anchor → radial streaks from it; off-screen anchor / no flash → zero output (byte-identity).
- **Audio queue (pytest):** trigger scheduled at `t+delay` fires once at the right time, not before; cleared on reset.
- **Live (Mark):** in a nebula — occasional flashes light cloud + hull, shafts fan from in-view flashes, rumble follows; tune dials; confirm framerate holds (god-rays cost only during a flash).

## 9. Key risks

- **Thunder SFX asset** — the one content unknown; placeholder acceptable, wiring asset-agnostic.
- **4-light slot budget** — pin how many directionals active sets emit so the thunder reservation never starves the sun.
- **Off-screen flashes** — directional flashes whose anchor is off-screen get no god-rays (still light + audio); mitigated by the toward-view direction bias.
- **God-ray feedback loop** — must read a scratch/copy of HDR, not read+write the bound target (mirror the volumetric pass's discipline).

## 10. Key references

- `project_nebula_pockets` memory + `2026-06-23-volumetric-nebulae-design.md` — the cloud this lights; the 4-light single-scatter already in `nebula_volumetric.frag`.
- `native/src/renderer/include/renderer/frame.h` (`Lighting`, `MaxDirectionals`) + `opaque.frag` (`MAX_DIR_LIGHTS = 4`) — the shared 4-light model the flash injects into.
- `engine/host_loop.py:_aggregate_lights` + `engine/appc/lights.py:aggregate_for_renderer` + `engine/renderer.py:set_lighting` — the per-frame lighting path the flash light rides.
- `engine/appc/nebula_runtime.py` — the in-nebula membership signal the driver reuses.
- `native/src/renderer/nebula_volumetric_pass.cc` — the scratch-target / premultiplied-composite / toggle-namespace patterns the god-ray pass mirrors.
- the engine audio system (OpenAL one-shot path used by crew speech / SFX) — for the delayed rumble.
