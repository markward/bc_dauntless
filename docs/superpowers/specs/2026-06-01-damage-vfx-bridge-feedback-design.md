# Damage VFX + Bridge-View Feedback — Design

**Status:** drafted, awaiting user review
**Date:** 2026-06-01
**Author:** Mark Ward (with Claude)
**Roadmap:** [`2026-06-01-combat-damage-pipeline-design.md`](./2026-06-01-combat-damage-pipeline-design.md) — Project 4 of 5.
**Prior projects (merged):**
- Project 1: [`2026-06-01-mesh-accurate-hit-resolution-design.md`](./2026-06-01-mesh-accurate-hit-resolution-design.md)
- Project 2: [`2026-06-01-subsystem-damage-propagation-design.md`](./2026-06-01-subsystem-damage-propagation-design.md)
- Project 3: [`2026-06-01-shield-face-rotation-design.md`](./2026-06-01-shield-face-rotation-design.md)

## 1. Goal

Spawn meaningful visual + audible feedback at every weapon impact, oriented by the surface normal returned by the mesh ray-trace, tiered by what was hit and how much. Add a player-only bridge-view feedback channel (positional audio + camera shake) so the player can feel hits without seeing the external view.

Three deliverable surfaces:

1. **Severity-tiered impact VFX** — shield bubble splash (SHIELD), tinted hull-sparks billboard (HULL), or larger flash + ejected spark burst along the surface normal (CRITICAL). Mutually exclusive — exactly one tier fires per impact.
2. **Per-tier positional audio** — `App.PlaySoundAt` using SDK-registered sound names, fired alongside the VFX.
3. **Player-only camera shake** — decaying-noise perturbation of the final `(eye, target, up)` returned by `_compute_camera`, fed by player-targeted hits. Works in both exterior and bridge views.

## 2. What the prior projects provide

- The hit point fed to `apply_hit` is a real surface point in world space (Project 1).
- `_dauntless_host.ray_trace_mesh` returns `(point, normal, t)`; the normal is currently discarded at [`engine/appc/combat.py:87`](../../../engine/appc/combat.py#L87).
- The picked subsystem and its identity (hull vs. non-hull) are available inside `apply_hit` (Project 2).
- Shield face index is rotation-correct; the existing `host.shield_hit(...)` C++ pass already produces the bubble splash at the strike point (Project 3).
- `WeaponHitEvent` is broadcast from `apply_hit` after damage routing.

What's missing:

- Surface normal threading from the ray-trace binding all the way to the renderer.
- A single place that classifies severity from the per-stage absorbed amounts and the picked subsystem's state transition.
- Mutual exclusivity between shield-bubble splashes and hull billboards — today both fire on every hit (see `_advance_combat` at [`engine/host_loop.py:236-249`](../../../engine/host_loop.py#L236-L249) and [`L311-L321`](../../../engine/host_loop.py#L311-L321)).
- Per-tier audio. `LoadTacticalSounds` registers `g_lsWeaponExplosions` (Explosion 1–19) and `g_lsCollisionSounds` (Collision 1–8) but the SDK never plays from either pool; they are orphaned, available for our use.
- Player-targeted camera shake. The camera math in [`_compute_camera`](../../../engine/host_loop.py#L1854-L1910) has no perturbation channel.

## 3. Design decisions (locked in this session)

The brainstorm produced six load-bearing decisions; recording them here so the implementation plan and any future revisit have a fixed reference.

1. **Severity dispatch is internal to `apply_hit`.** A new module `engine/appc/hit_feedback.py` exposes `dispatch(...)` which `apply_hit` calls directly *before* the `WeaponHitEvent` broadcast. `WeaponHitEvent`'s shape is unchanged.
2. **Audio sources are mixed.** HULL tier reuses the orphaned `g_lsWeaponExplosions` pool. CRITICAL tier uses a new pool `g_lsSubsystemCriticals` registered by a new SDK companion script `LoadDamageHitSounds.py`, pointing at the existing `Explosions/explo_large_NN.WAV` files under new names (so the existing `g_lsBigDeathExplosions` registration for station deaths is not overloaded). SHIELD tier uses a new `"Shield Hit"` name registered by the same script, pointing at a softer existing WAV.
3. **Renderer extends the existing `HitVfxPass`.** `HitVfxDescriptor` gains `surface_normal` (vec3) and `severity` (int). SHIELD severity is filtered at the Python side and never reaches the renderer (the shield_hit pass already handles it). HULL → single tinted billboard. CRITICAL → larger billboard + 6 ejected spark quads.
4. **CRITICAL trigger is state-transition only.** A non-hull subsystem flipping `IsDamaged`, `IsDisabled`, or `IsDestroyed` to `True` for the first time on this tick. No damage-amount tiebreaker.
5. **Camera shake is decaying noise on the final `(eye, target, up)`.** Module `engine/appc/camera_shake.py`. Energy accumulates from `apply_kick(damage)`, decays at `τ = 0.15s`. Yaw + pitch perturbation via a sum of two incommensurate sinusoids per axis (deterministic, no RNG); small lateral eye-translation rumble. Up vector left alone. Applied to the result of `_compute_camera` so both exterior and bridge views are perturbed identically.
6. **Player identity via `App.Game_GetCurrentGame().GetPlayer()`** inside `hit_feedback.dispatch`. Matches `engine/ui/ship_display_panel.py:_get_player`.

## 4. Architecture

### 4.1 New / changed files

| File | Status | Purpose |
|---|---|---|
| `sdk/Build/scripts/LoadDamageHitSounds.py` | new | Registers `"Shield Hit"` and `"Subsystem Critical 1..8"` via `pGame.LoadSound`. Called once at host bootstrap alongside `LoadTacticalSounds.LoadSounds()`. |
| `engine/appc/hit_feedback.py` | new | `dispatch(...)` — severity classifier + fan-out to VFX, audio, camera shake. |
| `engine/appc/camera_shake.py` | new | `apply_kick(damage)`, `update(dt)`, `perturb(eye, target, up)`, `reset()`, `get_energy()`. |
| `engine/appc/combat.py` | edit | `_resolve_hit_point` returns `(point, normal)`. `apply_hit` records per-stage absorbed amounts + subsystem state transition, calls `hit_feedback.dispatch(...)` before the event broadcast. Accepts `normal`, `host`, `ship_instances` kwargs. |
| `engine/appc/hit_vfx.py` | edit | `spawn(point, normal=None, severity=Severity.HULL)`. SHIELD severity is an early-return. `Severity` enum added. `_LIFETIME` widens to 0.7s. |
| `engine/host_loop.py` | edit | `_advance_combat` no longer fires `host.shield_hit` / `hit_vfx.spawn` itself — both go through dispatch via `apply_hit`. `_resolve_hit_point` callers unpack the new `(point, normal)` tuple. `LoadDamageHitSounds.LoadSounds()` invoked next to `LoadTacticalSounds.LoadSounds()`. `_compute_camera` result is passed through `camera_shake.perturb(...)` before being handed to `r.set_camera` / `r.set_bridge_camera`. `camera_shake.update(dt)` called once per tick alongside `hit_vfx.update_ages(dt)`. `_build_hit_vfx_render_data` includes `normal` + `severity`. |
| `native/src/renderer/include/renderer/frame.h` | edit | `HitVfxDescriptor` gains `glm::vec3 surface_normal` and `int severity`. |
| `native/src/renderer/hit_vfx_pass.cc` | edit | Per-tier `kPeakSize` / `kSpawnDur` / `kFadeDur` / `kTotalLife`. Per-tier tint uniform. CRITICAL branch emits 6 spark quads along the normal with deterministic per-descriptor jitter. |
| `native/src/renderer/shaders/hit_vfx.frag` | edit | Add `u_tint vec4` uniform multiplied through the texture sample. Reminder: shader edits require re-running `cmake -B build -S .`, not just `cmake --build`. |
| `native/src/host/host_bindings.cc` | edit | `set_hit_vfx` reads `normal` + `severity` from the descriptor dict. |
| Tests (see §7) | new + edit | Unit tests for severity classification, camera shake decay, state diff; integration test for severity-stream transitions over a continuous-fire scenario. |

### 4.2 Data flow per impact

```
                         _advance_combat tick
                                │
                ┌──────── torpedo hit  ────────┐  ┌──── phaser tick ────┐
                │  (already has hit_point)     │  │  computes emitter,  │
                │                              │  │  aim_unit, dist,    │
                │  _resolve_hit_point_for_     │  │  target, target_sub │
                │   torpedo → (point, normal)  │  │                     │
                └──────────────┬───────────────┘  └──────────┬──────────┘
                               │                             │
                               │     _resolve_hit_point      │
                               │     → (point, normal)       │
                               │                             │
                               └────────────┬────────────────┘
                                            ▼
              apply_hit(ship, damage, point, source=…, subsystem=…,
                        normal=normal, host=host, ship_instances=…)
                                            │
            ┌───────────────────────────────┼───────────────────────────────┐
            │   1. shields face            ApplyDamage   → absorbed_shields │
            │   2. picked subsystem (≠ hull) DamageSystem → absorbed_sub +  │
            │                                                sub_transition │
            │   3. hull bleed              DamageSystem   → absorbed_hull   │
            └───────────────────────────────┬───────────────────────────────┘
                                            ▼
                          hit_feedback.dispatch(...)
                                            │
                  ┌─────────────────────────┼────────────────────────────┐
                  ▼                         ▼                            ▼
              severity = …                  player gate:           tier-routed:
              SHIELD / HULL / CRITICAL      ship == player?        host.shield_hit
                                            ↓ yes                  hit_vfx.spawn
                                       camera_shake.apply_kick     App.PlaySoundAt
                                            ▼
                  WeaponHitEvent broadcast (unchanged)
```

### 4.3 The mutual-exclusivity invariant

After this project lands, every impact produces *exactly one* of:

- A `host.shield_hit` call (SHIELD), or
- A `hit_vfx.spawn` descriptor with severity HULL or CRITICAL.

Never both for the same impact. This is enforced inside `dispatch` (single `if/elif` chain on severity).

## 5. Module specifications

### 5.1 `engine/appc/hit_feedback.py`

```python
from enum import IntEnum

class Severity(IntEnum):
    SHIELD = 0
    HULL = 1
    CRITICAL = 2

def classify(absorbed_shields, absorbed_sub, absorbed_hull,
             sub_transition, subsystem, hull) -> Severity:
    """Pure function. Used by dispatch + directly by tests."""
    if sub_transition is not None and subsystem is not None and subsystem is not hull:
        return Severity.CRITICAL
    if absorbed_shields > 0 and absorbed_sub == 0 and absorbed_hull == 0:
        return Severity.SHIELD
    return Severity.HULL

def dispatch(ship, source, point, normal, damage, subsystem,
             absorbed_shields, absorbed_subsystem, absorbed_hull,
             sub_transition, *, host=None, ship_instances=None) -> None:
    """Single per-impact entry point called from apply_hit. Computes
    severity, fans out to VFX / audio / camera shake. Errors swallowed
    after logging once per failure-class so the downstream WeaponHitEvent
    broadcast in apply_hit always runs.
    """
```

`dispatch` reads `App.Game_GetCurrentGame().GetPlayer()` once per call (guarded by `try/except` for headless contexts where `App.Game_GetCurrentGame()` returns a stub without a player). Camera shake fires iff `ship is player`.

Audio playback uses the existing `TGSoundManager` + `TGSound.Play(position=...)` path (same surface `engine/audio/engine_rumble.py` uses):

```python
import App, LoadDamageHitSounds, LoadTacticalSounds
name = {
    Severity.SHIELD:   "Shield Hit",
    Severity.HULL:     LoadTacticalSounds.GetRandomSound(LoadTacticalSounds.g_lsWeaponExplosions),
    Severity.CRITICAL: LoadDamageHitSounds.GetRandomSound(LoadDamageHitSounds.g_lsSubsystemCriticals),
}[severity]
mgr = getattr(App, "g_kSoundManager", None)
snd = mgr.GetSound(name) if mgr is not None else None
if snd is not None:
    snd.Play(position=(point.x, point.y, point.z))
```

Headless tests where `App.g_kSoundManager is None` (the post-`shutdown_audio_for_tests` state) fall through silently. The `snd is None` branch covers a missing sound name (e.g. `LoadDamageHitSounds.LoadSounds()` not yet called).

### 5.2 `engine/appc/camera_shake.py`

```python
import math

_energy = 0.0
_phase = 0.0

DAMAGE_PER_UNIT_ENERGY = 50.0   # 100 damage → 2.0 energy
MAX_KICK_ENERGY        = 4.0    # single-hit ceiling
MAX_ENERGY             = 8.0    # sustained-fire ceiling
TAU                    = 0.15   # decay time constant (s)
ANGULAR_GAIN           = 0.013  # rad per energy unit (~0.75°)
LATERAL_GAIN           = 0.03   # wu per energy unit

def apply_kick(damage: float) -> None: ...
def update(dt: float) -> None: ...
def perturb(eye, target, up) -> tuple: ...
def reset() -> None: ...
def get_energy() -> float: ...
```

Waveform:

```python
amp = ANGULAR_GAIN * _energy
yaw   = amp * (math.sin(_phase * 47.1)         + 0.5 * math.sin(_phase * 113.7 + 1.3))
pitch = amp * (math.sin(_phase * 59.3 + 0.7)   + 0.5 * math.sin(_phase *  91.1 + 2.1))
lateral_offset = LATERAL_GAIN * _energy * math.sin(_phase * 31.5)
```

`perturb`:

1. `r = normalize(cross(target - eye, up))` (camera-right).
2. Compose `R = R_yaw(up) · R_pitch(r)`. Apply to `(target - eye)` → `target'`.
3. `eye' = eye + lateral_offset * r`.
4. Return `(eye', target', up)`.

`up` is left untouched to keep the horizon stable.

`update(dt)`:

```python
global _energy, _phase
_energy = min(MAX_ENERGY, _energy)
_energy *= math.exp(-dt / TAU)
_phase += dt
```

`apply_kick(damage)`:

```python
global _energy
delta = min(damage / DAMAGE_PER_UNIT_ENERGY, MAX_KICK_ENERGY)
if delta <= 0:
    return
_energy = min(_energy + delta, MAX_ENERGY)
```

`reset()` zeroes `_energy` and `_phase`. Called on view-mode transitions and by tests.

### 5.3 `engine/appc/hit_vfx.py` (edits)

```python
from enum import IntEnum
from engine.appc.math import TGPoint3

class Severity(IntEnum):
    SHIELD = 0
    HULL = 1
    CRITICAL = 2

_LIFETIME = 0.7   # widened from 0.5 to cover CRITICAL tail

_active: list[dict] = []

def spawn(position: TGPoint3, normal=None, severity=Severity.HULL) -> None:
    """Register a new hit VFX. SHIELD severity is a no-op: the shield_hit
    renderer pass handles its own splash.
    """
    if severity == Severity.SHIELD:
        return
    _active.append({
        "position": position,
        "normal":   normal,
        "severity": int(severity),
        "age":      0.0,
    })

def update_ages(dt: float) -> None: ...    # unchanged shape
def snapshot() -> list[dict]: ...          # unchanged shape
```

`_build_hit_vfx_render_data` ([`engine/host_loop.py:386-395`](../../../engine/host_loop.py#L386-L395)) widens to include `normal` and `severity`. `normal=None` is serialised as `(0.0, 0.0, 0.0)` — the renderer's sentinel.

### 5.4 `engine/appc/combat.py` (edits)

`_resolve_hit_point` returns `tuple[TGPoint3, TGPoint3 | None]`. The normal is `None` for every non-mesh-trace path (sphere entry, fallback point).

`apply_hit` signature widens:

```python
def apply_hit(ship, damage, hit_point, source, subsystem=None,
              *, normal=None, host=None, ship_instances=None) -> None:
```

Per-stage absorbed amounts are tracked as local floats. `_subsystem_state_flags(sub)` snapshots `(IsDamaged, IsDisabled, IsDestroyed)` before and after `DamageSystem`. `_diff_state(before, after)` returns `"destroyed" > "disabled" > "damaged" > None` — only the highest *newly-set* flag.

`hit_feedback.dispatch(...)` is called between step 3 (hull bleed) and step 4 (WeaponHitEvent broadcast). Dispatch is wrapped in `try/except Exception` so a renderer failure cannot suppress the event broadcast.

### 5.5 `engine/host_loop.py` (edits)

- Bootstrap: add `LoadDamageHitSounds.LoadSounds()` next to the existing `LoadTacticalSounds.LoadSounds()` call.
- `_advance_combat`:
  - Torpedo branch: call `_resolve_hit_point` for the torpedo's per-tick motion ray to obtain `(point, normal)`. Pass `normal`, `host`, `ship_instances` through `apply_hit` kwargs.
  - Phaser branch: unpack `(point, normal)` from the existing `_resolve_hit_point` call. Pass through `apply_hit` kwargs.
  - Remove the unconditional `host.shield_hit(...)` and `hit_vfx.spawn(...)` calls — both are now `dispatch`'s job.
  - Keep `hit_vfx.update_ages(dt)` and the batch `host.set_*` pushes.
  - Add `camera_shake.update(dt)` next to `hit_vfx.update_ages(dt)`.
- `_compute_camera`'s return value is passed through `camera_shake.perturb(...)` at the call site in the main loop, before `r.set_camera` / `r.set_bridge_camera`.
- View-mode transitions call `camera_shake.reset()` alongside `cam_control.reset_smoothing()`.

### 5.6 `sdk/Build/scripts/LoadDamageHitSounds.py`

```python
import App

def LoadSounds():
    pGame = App.Game_GetCurrentGame()
    # SHIELD tier — single name, softer existing WAV.
    pGame.LoadSound("sfx/Explosions/explo15.WAV", "Shield Hit", App.TGSound.LS_3D).SetVolume(0.6)
    # CRITICAL tier — dedicated pool, reuses the explo_large_*.wav files
    # without overloading the existing g_lsBigDeathExplosions registrations.
    pGame.LoadSound("sfx/Explosions/explo_large_01.WAV", "Subsystem Critical 1", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_02.WAV", "Subsystem Critical 2", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_03.WAV", "Subsystem Critical 3", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_04.WAV", "Subsystem Critical 4", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_05.WAV", "Subsystem Critical 5", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_06.WAV", "Subsystem Critical 6", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_07.WAV", "Subsystem Critical 7", App.TGSound.LS_3D)
    pGame.LoadSound("sfx/Explosions/explo_large_08.WAV", "Subsystem Critical 8", App.TGSound.LS_3D)

g_lsSubsystemCriticals = (
    "Subsystem Critical 1", "Subsystem Critical 2", "Subsystem Critical 3",
    "Subsystem Critical 4", "Subsystem Critical 5", "Subsystem Critical 6",
    "Subsystem Critical 7", "Subsystem Critical 8",
)

# Mirror LoadTacticalSounds.GetRandomSound so callers can reuse the
# "don't repeat within 3 calls" picker without re-importing TacticalSounds.
GetRandomSound = None  # Bound at LoadSounds() time to LoadTacticalSounds.GetRandomSound
```

`GetRandomSound` binding is wired up in `LoadSounds()` to avoid an import cycle with `LoadTacticalSounds` at module-eval time.

## 6. Renderer specification

### 6.1 Per-tier visual constants

| Severity | `kPeakSize` (wu) | `kSpawnDur` (s) | `kFadeDur` (s) | `kTotalLife` (s) | Tint RGBA |
|---|---|---|---|---|---|
| HULL | 3.0 | 0.08 | 0.25 | 0.33 | (1.0, 0.55, 0.20, 1.0) |
| CRITICAL | 7.0 | 0.10 | 0.55 | 0.65 | (1.0, 0.92, 0.80, 1.0) |

`kPeakSize` is the half-size at peak expansion; size eases 0→`kPeakSize` over `kSpawnDur`, alpha fades 1→0 over `kFadeDur` starting at `t = kSpawnDur`. Same easing shape as today's `hit_vfx_pass.cc`, parameterised per tier.

### 6.2 Sparks burst (CRITICAL only)

For each CRITICAL descriptor, after the main billboard, emit 6 extra quads:

```cpp
constexpr int   kSparkCount = 6;
constexpr float kSparkSpeed = 4.0f;   // wu/s
constexpr float kSparkSize  = 0.6f;   // multiplier on kPeakSize_CRITICAL

for (int i = 0; i < kSparkCount; ++i) {
    const glm::vec3 base = (length(v.surface_normal) > 1e-3f)
                         ? v.surface_normal
                         : cam_right;           // sentinel fallback
    const glm::vec3 dir  = rotate_jitter(base, hash3(v.world_pos, i));
    const float t        = v.age;
    const glm::vec3 pos  = v.world_pos + dir * (kSparkSpeed * t);
    const float size     = kSparkSize * kPeakSize_CRITICAL * (1.0f - t / kTotalLife_CRITICAL);
    const float alpha    = 1.0f - t / kTotalLife_CRITICAL;
    shader.set_vec3 ("u_world_position", pos);
    shader.set_float("u_size",           size);
    shader.set_float("u_alpha",          alpha);
    glDrawArrays(GL_TRIANGLES, 0, 6);
}
```

`hash3(world_pos, i)` is a deterministic float-pair-from-vec3+int hash (see implementation plan for the exact mix; xorshift on float bit-reinterprets is sufficient). `rotate_jitter(base, h)` rotates `base` by `h.x * 30°` around `cam_up` and `h.y * 30°` around `cam_right` — a 60°-cone spray oriented along the surface normal.

### 6.3 Sentinel-normal fallback

If `length(surface_normal) < 1e-3` (the `(0,0,0)` sentinel from the Python side), `base = cam_right` so the sparks spread in screen space instead of along the surface. The main billboard is unaffected (it's already camera-facing). Documented as a degraded-mode visual; the spec accepts that the fallback path produces visibly less satisfying sparks.

### 6.4 Shader change

`shaders/hit_vfx.frag` gains:

```glsl
uniform vec4 u_tint;
// ... existing texture sample ...
out_color = tex_sample * u_tint * vec4(1.0, 1.0, 1.0, u_alpha);
```

`u_tint` is set per-descriptor on the host side from the per-tier table in §6.1.

### 6.5 Binding extension

`set_hit_vfx` in [`host_bindings.cc:575-588`](../../../native/src/host/host_bindings.cc#L575-L588):

```cpp
auto n = d["normal"].cast<std::tuple<float, float, float>>();
v.surface_normal = {std::get<0>(n), std::get<1>(n), std::get<2>(n)};
v.severity = d["severity"].cast<int>();
```

Keys are required — `_build_hit_vfx_render_data` is the only producer, and a missing key from an old build indicates a stale `.so` (CLAUDE.md's existing diagnostic for `AttributeError: module '_open_stbc_host' has no attribute X` covers this failure mode).

## 7. Tests

### 7.1 Unit — severity classification (`tests/unit/test_hit_feedback_severity.py`)

Parametrised over `Severity.classify(...)` (the pure-function form). Cases from the brainstorm §6.1 table:

| # | absorbed_shields | absorbed_sub | absorbed_hull | sub_transition | subsystem | Expected |
|---|---|---|---|---|---|---|
| 1 | 50 | 0 | 0 | None | hull | SHIELD |
| 2 | 30 | 20 | 0 | None | sensors | HULL |
| 3 | 30 | 0 | 20 | None | hull | HULL |
| 4 | 0 | 0 | 50 | None | hull | HULL |
| 5 | 0 | 50 | 0 | `"damaged"` | engines | CRITICAL |
| 6 | 0 | 100 | 0 | `"disabled"` | weapons | CRITICAL |
| 7 | 0 | 80 | 0 | `"destroyed"` | sensors | CRITICAL |
| 8 | 0 | 0 | 999 | `"damaged"` | hull | HULL (hull excluded from CRITICAL promotion) |

A second test file `test_hit_feedback_dispatch.py` covers fan-out: inject fake `_spawn_vfx` / `_play_audio` / `_camera_kick` callables via monkeypatch, drive `dispatch(...)` with each severity, assert the right callables fired with the right arguments. Player gate verified by faking `App.Game_GetCurrentGame().GetPlayer()` to return / not return the target ship.

### 7.2 Unit — camera shake decay (`tests/unit/test_camera_shake_decay.py`)

Pure-Python, no host:

- `apply_kick(100); for _ in 60 ticks of dt=1/60: update(dt)` — assert `get_energy()` strictly non-increasing; crosses 1% of peak within `[0.45s, 0.55s]`.
- `apply_kick(100); record perturb(...)` over a 30-tick window — assert peak yaw deflection ∈ `[1.0°, 2.0°]`; yaw crosses zero ≥ 4 times in first 0.3s.
- Determinism: `reset(); apply_kick(50); seq_A = [perturb(...) for _ in 30 ticks]`; repeat; assert `seq_A == seq_B`.
- `apply_kick(0)` is a no-op (no division by zero).
- `perturb(...)` on `_energy == 0` returns the input tuple unchanged.
- Sustained-fire cap: 100× `apply_kick(1000)` in one tick → `get_energy() <= MAX_ENERGY`.

### 7.3 Unit — state diff (`tests/unit/test_apply_hit_state_diff.py`)

`_diff_state` priority: `before=(False,False,False), after=(True,True,True)` → `"destroyed"`. Eight cases covering each transition.

### 7.4 Integration — severity transition sequence (`tests/integration/test_damage_severity_sequence.py`)

Uses the same harness as `test_phaser_damage_applied_through_apply_hit.py`. Setup:

- Target ship with FRONT shield charged to 100, sensors subsystem `MaxCondition=100`, `DisabledPercentage=0.5`.
- `_FakeHost` capturing `shield_hit` calls + `set_hit_vfx` descriptors.
- Monkeypatched `hit_feedback._play_audio` and `camera_shake.apply_kick` capturing call args.

Sequence (10 ticks at 30 damage each):

| Tick | shields after | sensors after | sub_transition | Expected severity |
|---|---|---|---|---|
| 1 | 70 | 100 | None | SHIELD |
| 2 | 40 | 100 | None | SHIELD |
| 3 | 10 | 100 | None | SHIELD |
| 4 | 0 (–20 overflow) | 80 | None | HULL |
| 5 | 0 | 50 | `"disabled"` | CRITICAL (crosses 50% DisabledPercentage) |
| 6 | 0 | 20 | None | HULL |
| 7 | 0 | 0 | `"destroyed"` | CRITICAL |
| 8–10 | 0 | 0 | None | HULL (no further flip) |

Mutual exclusivity invariant: no tick has both a `shield_hit` capture *and* a `set_hit_vfx` descriptor pushed for the same impact.

Player-only camera shake: re-run with target ship == player → `apply_kick` fired N times; rerun with target ship != player → zero calls.

### 7.5 Existing tests that must stay green

- `tests/integration/test_phaser_damage_applied_through_apply_hit.py`
- `tests/integration/test_mesh_ray_trace.py`
- `tests/unit/test_shield_face_from_hit_point.py` and the Project 3 rotation variants
- `tests/integration/test_subsystem_damage_propagation.py`
- `tests/unit/test_hit_vfx.py` — `spawn(point)` keeps working by virtue of default kwargs.

### 7.6 Visual smoke (manual, post-merge)

1. `cmake -B build -S . && cmake --build build -j && ./build/dauntless`.
2. Default mission (M2Objects). Approach a Warbird.
3. Fire phasers on the Warbird front. Confirm: shield bubble splashes for ~first 3 seconds, no hull billboard, no sparks. Audio: `"Shield Hit"`.
4. Shields exhaust on front face. Confirm: bubble splashes stop, tinted hull billboard appears at the impact point, audio switches to `g_lsWeaponExplosions` pool.
5. Target Sensors with `T`. Continue firing. Confirm: at the moment the Sensors row on the ShipDisplay panel flips, one tick produces a larger flash + 6 sparks ejected along the hull surface. Audio: `g_lsSubsystemCriticals` pool.
6. Have an NPC fire on the player. Confirm: camera rocks ~1–2° on hits, decays within ~0.5s. Test in both exterior and bridge views.

## 8. Non-goals

Mirroring roadmap §5 and §6 — re-stated here so they're not re-litigated mid-implementation:

- Subsystem-failure gameplay consequences (Project 5).
- Bridge interior reactions beyond audio + camera shake (parking lot).
- Multi-point along-beam sampling (parking lot).
- BVH or other ray-trace acceleration (parking lot).
- Per-faction or per-weapon sound variants.
- Damage-amount-based CRITICAL trigger (rejected in §3.4).
- Sustained ambient damage VFX (smoke trails, persistent sparks on damaged hulls).
- Save / load of camera-shake or hit-VFX state (transient; resets on load).

## 9. Risks + open implementation items

### 9.1 Audio API confirmed: `TGSound.Play(position=...)`

A post-brainstorm shim audit (`engine/audio/tg_sound.py`) confirmed there is **no** `Game_GetCurrentGame().PlaySoundAt(...)` method. The actual positional-playback path is `App.g_kSoundManager.GetSound(name).Play(position=(x,y,z))`, the same one [`engine/audio/engine_rumble.py:52-57`](../../../engine/audio/engine_rumble.py#L52-L57) uses for ship-attached rumbles. Spec §5.1's audio call uses this confirmed API. No shim work needed.

### 9.2 `normal=None` is the common case for torpedoes

Torpedoes that spawn already inside a target's bounding sphere (low-angle salvos at close range) will produce `normal=None`. The sentinel-normal branch in the renderer (§6.3) and the camera-spread fallback are tested by an integration case that intentionally constructs an "inside" hit.

### 9.3 `shield_hit` call sites must be re-pointed

`shield_hit` moves from `_advance_combat` into `dispatch`. Implementation includes a `grep -rn shield_hit` audit at the end to ensure no caller was missed.

### 9.4 Camera shake vs. spring-lag chase camera

Camera shake's perturbation is applied *after* the chase camera's spring-lag and target-lock orbiting. There is a theoretical risk of visual beating between the lag camera and the shake during sustained fire. The damped-noise design (yaw passes through zero many times per second) is expected to be benign, but this needs eyeballing in the visual smoke test before merge.

### 9.5 Inverted control of `host.shield_hit` vs. `set_hit_vfx`

`set_hit_vfx` is a per-tick batch push of the descriptor list (stays in `_advance_combat`). `host.shield_hit` is a per-impact discrete event (moves to `dispatch`). They look architecturally similar but are deliberately routed differently. The implementation plan calls this out explicitly so future-us doesn't try to "unify" them.

## 10. Definition of done

- All three severity tiers fire correctly from `apply_hit`. Mutual exclusivity invariant holds in the integration test.
- Surface normal threaded from `ray_trace_mesh` through to the renderer for HULL + CRITICAL descriptors.
- Per-tier audio plays via `App.g_kSoundManager.GetSound(name).Play(position=...)`.
- Player camera shake fires on player-targeted hits in both exterior and bridge views, decays smoothly within ~0.5s.
- All §7.5 existing tests still pass.
- New §7.1–7.4 tests pass.
- Visual smoke procedure §7.6 reproduces the expected sequence on M2Objects.
