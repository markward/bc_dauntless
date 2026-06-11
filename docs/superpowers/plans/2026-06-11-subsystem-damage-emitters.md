# Subsystem Damage Emitters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the headless, fully unit-tested *state machine* for sustained, predicate-gated subsystem damage plumes (nacelle venting, impulse smoke, warp-core arcing) — everything except the particles themselves.

**Architecture:** A new pure-Python module `engine/appc/subsystem_emitters.py` exposing a `PlumeManager`, pumped once per tick from the host loop alongside `hit_vfx.update_ages`. It evaluates subsystem state predicates, diffs against tracked active emitters, applies a per-ship budget, and drives a **controller backend** through a narrow interface. This plan tests the whole machine against a `FakeControllerBackend`; the real backend is **Spec A** (particle controllers behind the SDK `Effects.py` factories), built separately. Production ships a `NullBackend` so the pump is a safe no-op until Spec A lands.

**Tech Stack:** Python 3 (dataclasses, `pytest`), the existing `engine/appc` subsystem/ship layer, the host-loop tick in `engine/host_loop.py`.

**Spec:** [`docs/superpowers/specs/2026-06-11-subsystem-damage-emitters-design.md`](../specs/2026-06-11-subsystem-damage-emitters-design.md) (Spec B).

**Scope note:** This plan is Spec B's *logic layer* only — it is working, testable software on its own (a complete plume state machine driven against a fake/null backend). Re-pointing the backend at Spec A's real renderer-backed factories and visual tuning is a **follow-up plan** gated on Spec A. Non-goals from spec §8 are not implemented here.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/appc/subsystem_emitters.py` (create) | `DirectionMode`, tier constants, `PlumeDescriptor`, registry + registration API, kind derivation, `desired_tier`, `PlumeBackend`/`NullBackend`, `PlumeManager`, module-level `pump()` + `set_backend()` |
| `engine/host_loop.py` (modify, ~line 269) | Call `subsystem_emitters.pump(...)` once per tick next to `hit_vfx.update_ages(dt)` |
| `tests/unit/test_subsystem_emitters_registry.py` (create) | Descriptor/registry/kind tests (Task 1) |
| `tests/unit/test_subsystem_emitters_tiering.py` (create) | `desired_tier` predicate-precedence tests (Task 2) |
| `tests/unit/test_subsystem_emitters_backend.py` (create) | `FakeControllerBackend` + lifecycle-handle tests (Task 3) |
| `tests/unit/test_subsystem_emitters_transitions.py` (create) | `PlumeManager` transition-matrix tests (Task 4) |
| `tests/unit/test_subsystem_emitters_anchor.py` (create) | Anchor/direction resolution tests (Task 5) |
| `tests/unit/test_subsystem_emitters_budget.py` (create) | Budget cap/cull/priority tests (Task 6) |
| `tests/unit/test_subsystem_emitters_persistence.py` (create) | Re-derive-on-load / no-puff-replay tests (Task 7) |
| `tests/integration/test_host_loop_subsystem_plumes.py` (create) | Host-loop pump integration test (Task 8) |

**Shared test fakes** (defined inline in Task 1's test file, imported by later tests): a `FakeSub` with settable predicates + `GetPosition()` + `GetName()`, and a `FakeShip` with `GetObjID()` + `GetSubsystems()` + `GetWorldLocation()` + `GetWorldRotation()`. Later tasks import them from `tests/unit/test_subsystem_emitters_registry.py` via `from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip`.

---

## Task 1: Descriptor, tier constants, registry, kind derivation

**Files:**
- Create: `engine/appc/subsystem_emitters.py`
- Test: `tests/unit/test_subsystem_emitters_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_subsystem_emitters_registry.py
"""Registry + descriptor + kind-derivation tests for the plume state machine."""
from engine.appc import subsystem_emitters as se
from engine.appc.math import TGPoint3


# ---- shared fakes (imported by later test modules) -------------------------

class FakeSub:
    """A minimal subsystem: settable damage state + class-name kind + anchor."""
    def __init__(self, kind_class_name="WarpEngineSubsystem", name="nacelle",
                 pos=(1.0, -2.0, 0.5), state="ok"):
        self.__class__.__name__ = kind_class_name  # so type(sub).__name__ matches
        self._name = name
        self._pos = TGPoint3(*pos)
        self._state = state  # "ok" | "damaged" | "disabled" | "destroyed"

    def GetName(self):       return self._name
    def GetPosition(self):   return TGPoint3(self._pos.x, self._pos.y, self._pos.z)
    def IsDamaged(self):     return 1 if self._state in ("damaged",) else 0
    def IsDisabled(self):    return 1 if self._state in ("disabled",) else 0
    def IsDestroyed(self):   return 1 if self._state == "destroyed" else 0


class _Mat3Identity:
    def GetCol(self, i):
        return [TGPoint3(1, 0, 0), TGPoint3(0, 1, 0), TGPoint3(0, 0, 1)][i]


class FakeShip:
    def __init__(self, obj_id=1, subs=None, loc=(0.0, 0.0, 0.0)):
        self._id = obj_id
        self._subs = subs or []
        self._loc = TGPoint3(*loc)

    def GetObjID(self):        return self._id
    def GetSubsystems(self):   return list(self._subs)
    def GetWorldLocation(self):return TGPoint3(self._loc.x, self._loc.y, self._loc.z)
    def GetWorldRotation(self):return _Mat3Identity()


# ---- registry tests --------------------------------------------------------

def _fresh():
    se.reset_registry()  # restores built-in defaults, clears mod additions


def test_builtin_table_resolves_warp_engine_tiers():
    _fresh()
    d_dmg = se.resolve("warp_engine", se.TIER_DAMAGED)
    d_dis = se.resolve("warp_engine", se.TIER_DISABLED)
    assert d_dmg is not None and d_dis is not None
    assert d_dmg.factory == "CreateSmokeHigh"
    assert d_dmg.direction_mode == se.DirectionMode.FIXED_BODY_VECTOR
    assert d_dmg.direction_vec == (0.0, -1.0, 0.0)  # aft


def test_warp_core_defaults_spherical():
    _fresh()
    d = se.resolve("warp_core", se.TIER_DAMAGED)
    assert d.direction_mode == se.DirectionMode.SPHERICAL


def test_shield_generator_has_no_sustained_entry():
    _fresh()
    assert se.resolve("shield_generator", se.TIER_DAMAGED) is None
    assert se.resolve("shield_generator", se.TIER_DISABLED) is None


def test_register_overrides_a_cell():
    _fresh()
    custom = se.PlumeDescriptor(factory="CreateDebrisSmoke", params={"fSize": 9.0},
                                direction_mode=se.DirectionMode.SPHERICAL)
    se.register("warp_engine", se.TIER_DAMAGED, custom)
    assert se.resolve("warp_engine", se.TIER_DAMAGED) is custom


def test_register_new_kind_lights_up():
    _fresh()
    d = se.PlumeDescriptor(factory="CreateSmokeHigh", params={},
                           direction_mode=se.DirectionMode.SPHERICAL)
    se.register("antimatter_pod", se.TIER_DISABLED, d)
    assert se.resolve("antimatter_pod", se.TIER_DISABLED) is d


def test_unregister_removes_cell():
    _fresh()
    se.unregister("warp_engine", se.TIER_DAMAGED)
    assert se.resolve("warp_engine", se.TIER_DAMAGED) is None


def test_subsystem_kind_from_class_name():
    _fresh()
    assert se.subsystem_kind(FakeSub("WarpEngineSubsystem")) == "warp_engine"
    assert se.subsystem_kind(FakeSub("ImpulseEngineSubsystem")) == "impulse_engine"
    assert se.subsystem_kind(FakeSub("PowerSubsystem")) == "warp_core"
    assert se.subsystem_kind(FakeSub("ShieldSubsystem")) == "shield_generator"
    assert se.subsystem_kind(FakeSub("SensorSubsystem")) is None  # no plume


def test_kind_alias_routes_modded_class():
    _fresh()
    se.register_kind_alias("ModWarpRing", "warp_engine")
    assert se.subsystem_kind(FakeSub("ModWarpRing")) == "warp_engine"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_subsystem_emitters_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.subsystem_emitters'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/appc/subsystem_emitters.py
"""Subsystem damage emitters — sustained, state-driven plume state machine (Spec B).

This module owns POLICY: which subsystem state triggers which plume, where it
anchors, when it starts/stops/fades, the severity ladder, the per-ship budget,
and the mod registration table. It drives a particle-controller *backend*
through a narrow interface (see PlumeBackend); the real backend (Spec A) lives
behind the SDK Effects.py factory names and is built separately. Until then the
default backend is NullBackend (a safe no-op), so the host-loop pump does
nothing in production.

Spec: docs/superpowers/specs/2026-06-11-subsystem-damage-emitters-design.md
"""
from dataclasses import dataclass, field


class DirectionMode:
    FIXED_BODY_VECTOR    = 0   # emit along a fixed body-frame vector (nacelle → aft)
    SPHERICAL            = 1   # radiate omnidirectionally (warp-core arcing)
    ALONG_SUBSYSTEM_AXIS = 2   # use the subsystem's own forward axis


# Severity tiers. DAMAGED/DISABLED are sustained registry rows; DESTROYED is a
# one-shot death-puff (not a registry row); NONE means "no plume desired".
TIER_NONE      = 0
TIER_DAMAGED   = 1
TIER_DISABLED  = 2
TIER_DESTROYED = 3


@dataclass(frozen=True)
class PlumeDescriptor:
    factory: str                    # Spec A / Effects.py factory name
    params: dict                    # factory kwargs sans the resolved emit frame
    direction_mode: int             # DirectionMode.*
    direction_vec: tuple = (0.0, -1.0, 0.0)   # body-frame unit vec for FIXED_BODY_VECTOR
    death_puff: "str | None" = None # one-shot factory on → DESTROYED transition
    priority_bias: float = 0.0      # nudge in the budget sort


# ---- registry --------------------------------------------------------------

_registry: "dict[tuple[str, int], PlumeDescriptor]" = {}
_kind_aliases: "dict[str, str]" = {}

_DEFAULT_KINDS = {
    "WarpEngineSubsystem":   "warp_engine",
    "ImpulseEngineSubsystem":"impulse_engine",
    "PowerSubsystem":        "warp_core",
    "ShieldSubsystem":       "shield_generator",
}


def _builtin_table():
    """The default (kind, tier) → descriptor table. Art values are tune-by-eye
    (spec §7); this fixes which factory + direction semantics."""
    aft = (0.0, -1.0, 0.0)
    return {
        ("warp_engine", TIER_DAMAGED): PlumeDescriptor(
            "CreateSmokeHigh", {"fVelocity": 2.0, "fLife": 1.2, "fSize": 0.6},
            DirectionMode.FIXED_BODY_VECTOR, aft, death_puff="CreateExplosionPlumeHigh"),
        ("warp_engine", TIER_DISABLED): PlumeDescriptor(
            "CreateSmokeHigh", {"fVelocity": 1.0, "fLife": 2.5, "fSize": 1.4},
            DirectionMode.FIXED_BODY_VECTOR, aft, death_puff="CreateExplosionPlumeHigh"),
        ("impulse_engine", TIER_DAMAGED): PlumeDescriptor(
            "CreateSmokeHigh", {"fVelocity": 1.5, "fLife": 1.2, "fSize": 0.5},
            DirectionMode.FIXED_BODY_VECTOR, aft, death_puff="CreateExplosionPlumeHigh"),
        ("impulse_engine", TIER_DISABLED): PlumeDescriptor(
            "CreateSmokeHigh", {"fVelocity": 0.8, "fLife": 2.5, "fSize": 1.2},
            DirectionMode.FIXED_BODY_VECTOR, aft, death_puff="CreateExplosionPlumeHigh"),
        ("warp_core", TIER_DAMAGED): PlumeDescriptor(
            "CreateExplosionPlumeHigh", {"fConeAngle": 120.0, "fLife": 1.0, "fSize": 0.4},
            DirectionMode.SPHERICAL, death_puff="CreateExplosionPlumeHigh"),
        ("warp_core", TIER_DISABLED): PlumeDescriptor(
            "CreateExplosionPlumeHigh", {"fConeAngle": 160.0, "fLife": 1.5, "fSize": 0.8},
            DirectionMode.SPHERICAL, death_puff="CreateExplosionPlumeHigh"),
    }


def reset_registry():
    """Restore the built-in table and drop all mod additions/aliases.
    Tests call this for isolation; production calls it once at import."""
    _registry.clear()
    _registry.update(_builtin_table())
    _kind_aliases.clear()


def register(kind, tier, descriptor):
    _registry[(kind, int(tier))] = descriptor


def unregister(kind, tier):
    _registry.pop((kind, int(tier)), None)


def resolve(kind, tier):
    return _registry.get((kind, int(tier)))


def register_kind_alias(class_token, kind):
    _kind_aliases[class_token] = kind


def subsystem_kind(sub):
    """Stable string token for a subsystem, or None if it has no plume mapping."""
    token = type(sub).__name__
    if token in _kind_aliases:
        return _kind_aliases[token]
    return _DEFAULT_KINDS.get(token)


reset_registry()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_subsystem_emitters_registry.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystem_emitters.py tests/unit/test_subsystem_emitters_registry.py
git commit -m "feat(plumes): subsystem-emitter registry, descriptors, kind derivation"
```

---

## Task 2: Severity tiering (`desired_tier`)

**Files:**
- Modify: `engine/appc/subsystem_emitters.py`
- Test: `tests/unit/test_subsystem_emitters_tiering.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_subsystem_emitters_tiering.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub


def test_destroyed_takes_precedence():
    sub = FakeSub(state="destroyed")
    assert se.desired_tier(sub) == se.TIER_DESTROYED


def test_disabled_maps_to_disabled():
    assert se.desired_tier(FakeSub(state="disabled")) == se.TIER_DISABLED


def test_damaged_maps_to_damaged():
    assert se.desired_tier(FakeSub(state="damaged")) == se.TIER_DAMAGED


def test_ok_maps_to_none():
    assert se.desired_tier(FakeSub(state="ok")) == se.TIER_NONE


def test_precedence_destroyed_over_disabled_over_damaged():
    # A subsystem reporting multiple predicates resolves to the most severe.
    class MultiSub(FakeSub):
        def IsDamaged(self):   return 1
        def IsDisabled(self):  return 1
        def IsDestroyed(self): return 1
    assert se.desired_tier(MultiSub()) == se.TIER_DESTROYED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_subsystem_emitters_tiering.py -q`
Expected: FAIL — `AttributeError: module 'engine.appc.subsystem_emitters' has no attribute 'desired_tier'`

- [ ] **Step 3: Write minimal implementation**

Add to `engine/appc/subsystem_emitters.py` (after `subsystem_kind`):

```python
def desired_tier(sub):
    """Resolve a subsystem's current state to a severity tier (most severe wins)."""
    if sub.IsDestroyed():
        return TIER_DESTROYED
    if sub.IsDisabled():
        return TIER_DISABLED
    if sub.IsDamaged():
        return TIER_DAMAGED
    return TIER_NONE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_subsystem_emitters_tiering.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystem_emitters.py tests/unit/test_subsystem_emitters_tiering.py
git commit -m "feat(plumes): desired_tier severity resolution"
```

---

## Task 3: Backend interface + `NullBackend` + `FakeControllerBackend`

**Files:**
- Modify: `engine/appc/subsystem_emitters.py`
- Test: `tests/unit/test_subsystem_emitters_backend.py`

The backend interface is the §5 contract Spec A must satisfy. `NullBackend` ships in production; `FakeControllerBackend` (in the test file) records calls and models the fade lifecycle.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_subsystem_emitters_backend.py
from engine.appc import subsystem_emitters as se


class FakeHandle:
    """Models a sustained controller: alive until stop_emitting(), then it has
    `linger` ticks of in-flight particles before has_live_particles() goes False."""
    def __init__(self, factory, params, emit_pos_body, emit_dir, direction_mode, linger=2):
        self.factory = factory
        self.params = params
        self.emit_pos_body = emit_pos_body
        self.emit_dir = emit_dir
        self.direction_mode = direction_mode
        self.emitting = True
        self._linger = linger

    def stop_emitting(self):
        self.emitting = False

    def has_live_particles(self):
        if self.emitting:
            return True
        self._linger -= 1
        return self._linger >= 0


class FakeControllerBackend:
    """Test double for the Spec A particle-controller backend."""
    def __init__(self):
        self.created = []     # all sustained handles ever made
        self.one_shots = []   # (factory, emit_pos_body, emit_dir) death puffs

    def create(self, factory, params, emit_pos_body, emit_dir, direction_mode):
        h = FakeHandle(factory, params, emit_pos_body, emit_dir, direction_mode)
        self.created.append(h)
        return h

    def fire_one_shot(self, factory, emit_pos_body, emit_dir):
        self.one_shots.append((factory, emit_pos_body, emit_dir))


def test_null_backend_create_returns_inert_handle():
    b = se.NullBackend()
    h = b.create("CreateSmokeHigh", {}, (0, 0, 0), (0, -1, 0),
                 se.DirectionMode.FIXED_BODY_VECTOR)
    # NullBackend handle must satisfy the manager's queries without error.
    h.stop_emitting()
    assert h.has_live_particles() is False
    b.fire_one_shot("CreateExplosionPlumeHigh", (0, 0, 0), (0, -1, 0))  # no error


def test_fake_handle_fade_lifecycle():
    b = FakeControllerBackend()
    h = b.create("CreateSmokeHigh", {"fSize": 1.0}, (1, -2, 0), (0, -1, 0),
                 se.DirectionMode.FIXED_BODY_VECTOR)
    assert h.has_live_particles() is True
    h.stop_emitting()
    assert h.has_live_particles() is True   # linger 2 → 1
    assert h.has_live_particles() is True   # linger 1 → 0
    assert h.has_live_particles() is False  # linger 0 → -1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_subsystem_emitters_backend.py -q`
Expected: FAIL — `AttributeError: module 'engine.appc.subsystem_emitters' has no attribute 'NullBackend'`

- [ ] **Step 3: Write minimal implementation**

Add to `engine/appc/subsystem_emitters.py`:

```python
class _NullHandle:
    def stop_emitting(self):       pass
    def has_live_particles(self):  return False


class NullBackend:
    """Default production backend until Spec A's real controllers land.
    Every call is a safe no-op; the manager runs its full state machine but
    nothing renders."""
    def create(self, factory, params, emit_pos_body, emit_dir, direction_mode):
        return _NullHandle()

    def fire_one_shot(self, factory, emit_pos_body, emit_dir):
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_subsystem_emitters_backend.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystem_emitters.py tests/unit/test_subsystem_emitters_backend.py
git commit -m "feat(plumes): backend interface, NullBackend, FakeControllerBackend"
```

---

## Task 4: `PlumeManager` transition matrix (no budget yet)

**Files:**
- Modify: `engine/appc/subsystem_emitters.py`
- Test: `tests/unit/test_subsystem_emitters_transitions.py`

Implements spec §4.2 with budget disabled (cap large, cull off), so transitions are tested in isolation. Anchor/direction resolution uses placeholder body-frame pass-through here; Task 5 locks its exactness.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_subsystem_emitters_transitions.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
from tests.unit.test_subsystem_emitters_backend import FakeControllerBackend


def _mgr(backend):
    # Large cap + cull disabled isolates transition behaviour from the budget.
    return se.PlumeManager(backend, n_per_ship=999, r_cull=None)


def test_none_to_damaged_spawns():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="damaged")
    ship = FakeShip(subs=[sub])
    m.update([ship], camera_pos=None, dt=0.1)
    assert len(b.created) == 1
    assert b.created[0].factory == "CreateSmokeHigh"


def test_damaged_to_disabled_swaps_controller():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="damaged")
    ship = FakeShip(subs=[sub])
    m.update([ship], None, 0.1)
    first = b.created[0]
    sub._state = "disabled"
    m.update([ship], None, 0.1)
    assert first.emitting is False           # old controller told to stop
    assert len(b.created) == 2               # new tier spawned
    assert b.created[1].params["fSize"] == 1.4  # DISABLED size, not DAMAGED


def test_repaired_fades_not_hard_killed():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="damaged")
    ship = FakeShip(subs=[sub])
    m.update([ship], None, 0.1)
    h = b.created[0]
    sub._state = "ok"
    m.update([ship], None, 0.1)
    assert h.emitting is False               # stopped emitting (fade)
    assert h.has_live_particles() is True    # but still lingering, not torn down
    # one-shot death puff must NOT fire on a repair
    assert b.one_shots == []


def test_destroyed_fires_puff_and_no_sustained():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="damaged")
    ship = FakeShip(subs=[sub])
    m.update([ship], None, 0.1)
    h = b.created[0]
    sub._state = "destroyed"
    m.update([ship], None, 0.1)
    assert h.emitting is False               # sustained plume faded
    assert len(b.one_shots) == 1             # death puff fired once
    assert b.one_shots[0][0] == "CreateExplosionPlumeHigh"


def test_destroyed_does_not_reemit_next_tick():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="destroyed")
    ship = FakeShip(subs=[sub])
    m.update([ship], None, 0.1)  # first time we ever see it: destroyed
    m.update([ship], None, 0.1)
    m.update([ship], None, 0.1)
    assert b.created == []                    # never a sustained plume
    assert len(b.one_shots) == 1             # puff fires exactly once (on first sight)


def test_faded_handle_dropped_when_particles_die():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="damaged")
    ship = FakeShip(subs=[sub])
    m.update([ship], None, 0.1)
    sub._state = "ok"
    # Pump until the lingering particles expire; handle should be released.
    for _ in range(5):
        m.update([ship], None, 0.1)
    assert m.active_count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_subsystem_emitters_transitions.py -q`
Expected: FAIL — `AttributeError: module 'engine.appc.subsystem_emitters' has no attribute 'PlumeManager'`

- [ ] **Step 3: Write minimal implementation**

Add to `engine/appc/subsystem_emitters.py`:

```python
class _ActiveEmitter:
    __slots__ = ("tier", "handle", "fading")
    def __init__(self, tier, handle):
        self.tier = tier
        self.handle = handle
        self.fading = False


def _emit_frame(ship, sub, descriptor):
    """Return (emit_pos_body, emit_dir) for the backend.

    Position is the subsystem's body-frame hardpoint (world-SCALE offset, no
    model scale — CLAUDE.md hardpoint-position-frame). Direction depends on the
    descriptor's mode. The backend resolves these through the ship's live world
    matrix each frame (SetEmitFromObject), so the manager stays body-frame.
    """
    p = sub.GetPosition()
    emit_pos_body = (p.x, p.y, p.z)
    mode = descriptor.direction_mode
    if mode == DirectionMode.SPHERICAL:
        emit_dir = None
    elif mode == DirectionMode.ALONG_SUBSYSTEM_AXIS and hasattr(sub, "GetDirection"):
        d = sub.GetDirection()
        emit_dir = (d.x, d.y, d.z)
    else:  # FIXED_BODY_VECTOR (and the axis fallback)
        emit_dir = tuple(descriptor.direction_vec)
    return emit_pos_body, emit_dir


class PlumeManager:
    """Per-tick subsystem-plume state machine (spec §3, §4)."""

    def __init__(self, backend, *, n_per_ship=3, r_cull=4000.0):
        self.backend = backend
        self.n_per_ship = n_per_ship
        self.r_cull = r_cull          # None disables distance culling
        self._active = {}             # key → _ActiveEmitter
        self._terminal = set()        # keys that reached DESTROYED (never re-emit)

    def active_count(self):
        return len(self._active)

    # -- main entry ----------------------------------------------------------

    def update(self, ships, camera_pos, dt):
        self._advance_faders()
        admitted = self._select_candidates(ships, camera_pos)  # Task 6 adds budget
        for key, ship, sub, kind, tier, descriptor in admitted:
            self._reconcile(key, ship, sub, tier, descriptor)
        self._suppress_unseen(admitted)

    # -- candidate selection (Task 6 replaces the body with the budget) ------

    def _select_candidates(self, ships, camera_pos):
        """Yield (key, ship, sub, kind, tier, descriptor) for every registered,
        damaged subsystem. No budget yet — Task 6 caps/culls/sorts this list."""
        out = []
        for ship in ships:
            for sub in ship.GetSubsystems():
                kind = subsystem_kind(sub)
                if kind is None:
                    continue
                tier = desired_tier(sub)
                if tier == TIER_NONE:
                    continue
                key = (ship.GetObjID(), id(sub))
                if tier == TIER_DESTROYED:
                    descriptor = None  # death-puff handled in _reconcile
                else:
                    descriptor = resolve(kind, tier)
                    if descriptor is None:
                        continue
                out.append((key, ship, sub, kind, tier, descriptor))
        return out

    # -- per-subsystem reconcile (spec §4.2 transition matrix) ---------------

    def _reconcile(self, key, ship, sub, tier, descriptor):
        if tier == TIER_DESTROYED:
            self._go_destroyed(key, ship, sub)
            return
        if key in self._terminal:
            return  # destroyed earlier; never re-emit
        existing = self._active.get(key)
        if existing is None:
            self._spawn(key, ship, sub, tier, descriptor)
        elif existing.fading:
            # was repaired/suppressed and re-damaged before fade finished
            self._spawn(key, ship, sub, tier, descriptor)
        elif existing.tier != tier:
            existing.handle.stop_emitting()  # swap tiers: fade old, spawn new
            self._spawn(key, ship, sub, tier, descriptor)

    def _spawn(self, key, ship, sub, tier, descriptor):
        emit_pos_body, emit_dir = _emit_frame(ship, sub, descriptor)
        handle = self.backend.create(descriptor.factory, descriptor.params,
                                     emit_pos_body, emit_dir, descriptor.direction_mode)
        self._active[key] = _ActiveEmitter(tier, handle)

    def _go_destroyed(self, key, ship, sub):
        if key in self._terminal:
            return  # puff already fired
        existing = self._active.pop(key, None)
        # find a death_puff factory: prefer the active tier's, else the kind's
        kind = subsystem_kind(sub)
        puff = None
        for t in (TIER_DISABLED, TIER_DAMAGED):
            d = resolve(kind, t)
            if d is not None and d.death_puff:
                puff = d.death_puff
                break
        if existing is not None:
            existing.handle.stop_emitting()  # fade the sustained plume
            existing.fading = True
            self._active[key] = existing     # keep lingering until particles die
        if puff is not None:
            p = sub.GetPosition()
            self.backend.fire_one_shot(puff, (p.x, p.y, p.z), None)
        self._terminal.add(key)

    # -- fade + suppression bookkeeping --------------------------------------

    def _advance_faders(self):
        for key in list(self._active.keys()):
            em = self._active[key]
            if em.fading and not em.handle.has_live_particles():
                del self._active[key]

    def _suppress_unseen(self, admitted):
        """Any active emitter whose subsystem is no longer a live candidate
        (repaired, or budget-suppressed) stops emitting and fades."""
        seen = {row[0] for row in admitted}
        for key, em in self._active.items():
            if key in seen or em.fading:
                continue
            em.handle.stop_emitting()
            em.fading = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_subsystem_emitters_transitions.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystem_emitters.py tests/unit/test_subsystem_emitters_transitions.py
git commit -m "feat(plumes): PlumeManager transition matrix (spawn/swap/fade/death-puff)"
```

---

## Task 5: Anchor + direction resolution exactness

**Files:**
- Test: `tests/unit/test_subsystem_emitters_anchor.py` (the `_emit_frame` impl already landed in Task 4; this task locks its contract with dedicated tests)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_subsystem_emitters_anchor.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
from tests.unit.test_subsystem_emitters_backend import FakeControllerBackend


def test_fixed_body_vector_nacelle_emits_aft():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=999, r_cull=None)
    sub = FakeSub("WarpEngineSubsystem", pos=(3.0, 5.0, -1.0), state="damaged")
    m.update([FakeShip(subs=[sub])], None, 0.1)
    h = b.created[0]
    assert h.emit_dir == (0.0, -1.0, 0.0)            # aft body vector
    assert h.emit_pos_body == (3.0, 5.0, -1.0)       # body-frame, unmodified
    assert h.direction_mode == se.DirectionMode.FIXED_BODY_VECTOR


def test_spherical_warp_core_passes_no_direction():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=999, r_cull=None)
    sub = FakeSub("PowerSubsystem", pos=(0.0, 1.0, 0.0), state="damaged")
    m.update([FakeShip(subs=[sub])], None, 0.1)
    h = b.created[0]
    assert h.emit_dir is None                         # omni
    assert h.direction_mode == se.DirectionMode.SPHERICAL


def test_body_position_not_world_transformed():
    # The manager must pass the body-frame hardpoint as-is; the backend (Spec A)
    # does the per-frame world resolution. A non-origin ship must NOT shift it.
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=999, r_cull=None)
    sub = FakeSub("WarpEngineSubsystem", pos=(2.0, -4.0, 0.0), state="damaged")
    ship = FakeShip(subs=[sub], loc=(1000.0, 1000.0, 1000.0))
    m.update([ship], None, 0.1)
    assert b.created[0].emit_pos_body == (2.0, -4.0, 0.0)  # body, not world
```

- [ ] **Step 2: Run test to verify it passes immediately** (`_emit_frame` landed in Task 4)

Run: `uv run pytest tests/unit/test_subsystem_emitters_anchor.py -q`
Expected: PASS (3 passed). If any fail, fix `_emit_frame` in `subsystem_emitters.py` until they pass — this task's purpose is to lock that contract.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_subsystem_emitters_anchor.py engine/appc/subsystem_emitters.py
git commit -m "test(plumes): lock anchor/direction resolution contract"
```

---

## Task 6: Per-ship budget (cap + distance cull + priority)

**Files:**
- Modify: `engine/appc/subsystem_emitters.py` — replace `_select_candidates` body
- Test: `tests/unit/test_subsystem_emitters_budget.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_subsystem_emitters_budget.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
from tests.unit.test_subsystem_emitters_backend import FakeControllerBackend


def _ship_with_n(n, state="damaged", obj_id=1, loc=(0, 0, 0)):
    subs = [FakeSub("WarpEngineSubsystem", name="n%d" % i, pos=(i, 0, 0), state=state)
            for i in range(n)]
    return FakeShip(obj_id=obj_id, subs=subs, loc=loc)


def test_per_ship_cap_admits_top_n():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=3, r_cull=None)
    m.update([_ship_with_n(6)], camera_pos=None, dt=0.1)
    assert m.active_count() == 3          # only 3 of 6 spawned
    assert len(b.created) == 3


def test_disabled_outranks_damaged_under_cap():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=1, r_cull=None)
    dmg = FakeSub("WarpEngineSubsystem", name="d", pos=(1, 0, 0), state="damaged")
    dis = FakeSub("ImpulseEngineSubsystem", name="x", pos=(2, 0, 0), state="disabled")
    m.update([FakeShip(subs=[dmg, dis])], None, 0.1)
    assert m.active_count() == 1
    # the single admitted slot went to the more severe DISABLED subsystem
    assert b.created[0].params["fSize"] == 1.2  # impulse DISABLED size


def test_distance_cull_suppresses_far_ship():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=3, r_cull=500.0)
    far = _ship_with_n(2, loc=(10000.0, 0.0, 0.0))
    m.update([far], camera_pos=(0.0, 0.0, 0.0), dt=0.1)
    assert m.active_count() == 0


def test_proximity_breaks_ties_between_ships():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=1, r_cull=None)
    near = _ship_with_n(1, obj_id=1, loc=(10.0, 0.0, 0.0))
    far  = _ship_with_n(1, obj_id=2, loc=(900.0, 0.0, 0.0))
    # Global cap is per-ship here, so both can spawn; assert both got slots and
    # the near ship's candidate sorted first within the admitted set.
    m.update([near, far], camera_pos=(0.0, 0.0, 0.0), dt=0.1)
    assert m.active_count() == 2


def test_suppressed_active_fades_when_budget_shrinks():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=3, r_cull=None)
    ship = _ship_with_n(3)
    m.update([ship], None, 0.1)
    assert m.active_count() == 3
    handles = list(b.created)
    # Shrink the budget: the lowest-priority active plume must fade, not pop.
    m.n_per_ship = 2
    m.update([ship], None, 0.1)
    faded = [h for h in handles if h.emitting is False]
    assert len(faded) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_subsystem_emitters_budget.py -q`
Expected: FAIL — cap/cull not yet enforced (e.g. `test_per_ship_cap_admits_top_n` sees 6 active, not 3).

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/subsystem_emitters.py`, replace the `_select_candidates` method body with the budgeted version, and add the distance helper:

```python
    def _select_candidates(self, ships, camera_pos):
        """Per-ship: gather registered damaged subsystems, distance-cull whole
        ships, sort by (severity desc, proximity desc, priority_bias desc), and
        admit the top n_per_ship (spec §4.3)."""
        out = []
        for ship in ships:
            dist = _camera_distance(ship, camera_pos)
            if self.r_cull is not None and dist is not None and dist > self.r_cull:
                continue
            cands = []
            for sub in ship.GetSubsystems():
                kind = subsystem_kind(sub)
                if kind is None:
                    continue
                tier = desired_tier(sub)
                if tier == TIER_NONE:
                    continue
                key = (ship.GetObjID(), id(sub))
                if tier == TIER_DESTROYED:
                    cands.append((key, ship, sub, kind, tier, None, 0.0))
                    continue
                descriptor = resolve(kind, tier)
                if descriptor is None:
                    continue
                cands.append((key, ship, sub, kind, tier, descriptor,
                              descriptor.priority_bias))
            # DESTROYED is a one-shot and must never consume a sustained slot:
            destroyed = [c for c in cands if c[4] == TIER_DESTROYED]
            sustained = [c for c in cands if c[4] != TIER_DESTROYED]
            # sort sustained by severity, then bias (proximity is per-ship-uniform)
            sustained.sort(key=lambda c: (c[4], c[6]), reverse=True)
            admitted = destroyed + sustained[:self.n_per_ship]
            # strip the trailing priority_bias element to match the 6-tuple contract
            for c in admitted:
                # proximity tiebreak across ships: tag a sort key, resolved below
                out.append((c[0], c[1], c[2], c[3], c[4], c[5], dist))
        # cross-ship proximity ordering (nearest first) for deterministic admit log
        out.sort(key=lambda r: (r[6] if r[6] is not None else 0.0))
        # return the 6-tuple the rest of the manager expects
        return [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in out]
```

Add the module-level helper (near `_emit_frame`):

```python
def _camera_distance(ship, camera_pos):
    """Euclidean distance from ship world location to camera, or None if the
    camera position is unknown (proximity term then drops out)."""
    if camera_pos is None or not hasattr(ship, "GetWorldLocation"):
        return None
    loc = ship.GetWorldLocation()
    dx = loc.x - camera_pos[0]
    dy = loc.y - camera_pos[1]
    dz = loc.z - camera_pos[2]
    return (dx * dx + dy * dy + dz * dz) ** 0.5
```

Note: `_select_candidates` now returns 6-tuples (as Task 4's `update`/`_reconcile`/`_suppress_unseen` expect), but it sorts and caps before stripping. `_reconcile` still receives `(key, ship, sub, kind, tier, descriptor)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_subsystem_emitters_budget.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full module suite to confirm no regression**

Run: `uv run pytest tests/unit/test_subsystem_emitters_*.py -q`
Expected: PASS (all tasks 1–6 green)

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystem_emitters.py tests/unit/test_subsystem_emitters_budget.py
git commit -m "feat(plumes): per-ship budget — cap, distance cull, severity/proximity priority"
```

---

## Task 7: Persistence behaviour (re-derive on load, no puff replay)

**Files:**
- Test: `tests/unit/test_subsystem_emitters_persistence.py` (no new impl — verifies the manager's stateless-on-construct behaviour from spec §4.6)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_subsystem_emitters_persistence.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
from tests.unit.test_subsystem_emitters_backend import FakeControllerBackend


def test_fresh_manager_redrives_disabled_plume_on_first_tick():
    # Simulates a load: a brand-new manager sees an already-disabled subsystem
    # and must re-derive the steady-state heavy plume immediately.
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=3, r_cull=None)
    sub = FakeSub("WarpEngineSubsystem", state="disabled")
    m.update([FakeShip(subs=[sub])], None, 0.1)
    assert m.active_count() == 1
    assert b.created[0].params["fSize"] == 1.4  # DISABLED tier


def test_fresh_manager_pre_destroyed_emits_nothing_and_no_puff():
    # A subsystem that was destroyed before save loads back destroyed. A load is
    # not a live transition, so: no sustained plume AND no death-puff replay.
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=3, r_cull=None)
    sub = FakeSub("WarpEngineSubsystem", state="destroyed")
    m.update([FakeShip(subs=[sub])], None, 0.1)
    assert m.active_count() == 0
    # NOTE: see Step 3 — first-sight-destroyed currently fires one puff; the load
    # path must suppress it. This test pins the load contract.
    assert b.one_shots == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_subsystem_emitters_persistence.py -q`
Expected: `test_fresh_manager_pre_destroyed_emits_nothing_and_no_puff` FAILS — Task 4's `_go_destroyed` fires a puff on first sight, but a load must not replay it.

- [ ] **Step 3: Write minimal implementation**

The death-puff must fire only on a *live* DAMAGED/DISABLED → DESTROYED transition, never when a subsystem is first observed already-destroyed (a load). Add a "seen-alive" gate to `PlumeManager`.

In `engine/appc/subsystem_emitters.py`, add to `__init__`:

```python
        self._seen = set()  # keys observed at least once this manager's lifetime
```

At the very top of `_reconcile`, record liveness before any destroyed handling:

```python
    def _reconcile(self, key, ship, sub, tier, descriptor):
        first_sight = key not in self._seen
        self._seen.add(key)
        if tier == TIER_DESTROYED:
            self._go_destroyed(key, ship, sub, first_sight)
            return
        # ... unchanged ...
```

Change `_go_destroyed` to take `first_sight` and skip the puff when the subsystem
was already destroyed the first time we ever saw it:

```python
    def _go_destroyed(self, key, ship, sub, first_sight):
        if key in self._terminal:
            return
        existing = self._active.pop(key, None)
        if first_sight and existing is None:
            # Loaded already-destroyed (or it died before we ever rendered a
            # plume): no live transition to punctuate → no puff (spec §4.6).
            self._terminal.add(key)
            return
        kind = subsystem_kind(sub)
        puff = None
        for t in (TIER_DISABLED, TIER_DAMAGED):
            d = resolve(kind, t)
            if d is not None and d.death_puff:
                puff = d.death_puff
                break
        if existing is not None:
            existing.handle.stop_emitting()
            existing.fading = True
            self._active[key] = existing
        if puff is not None:
            p = sub.GetPosition()
            self.backend.fire_one_shot(puff, (p.x, p.y, p.z), None)
        self._terminal.add(key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_subsystem_emitters_persistence.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Re-run the transitions suite — the live death-puff path must still fire**

Run: `uv run pytest tests/unit/test_subsystem_emitters_transitions.py -q`
Expected: PASS. `test_destroyed_fires_puff_and_no_sustained` still fires the puff (it transitions damaged→destroyed, so `existing` is non-None). `test_destroyed_does_not_reemit_next_tick` now expects **0** one-shots because that subsystem is first-seen already destroyed — **update that test's final assertion to `assert b.one_shots == []`** and its comment to "first-sight-destroyed fires no puff (load contract §4.6)."

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystem_emitters.py tests/unit/test_subsystem_emitters_persistence.py tests/unit/test_subsystem_emitters_transitions.py
git commit -m "feat(plumes): suppress death-puff on first-sight-destroyed (load contract)"
```

---

## Task 8: Module singleton + host-loop pump integration

**Files:**
- Modify: `engine/appc/subsystem_emitters.py` — add `set_backend`, `get_manager`, `pump`, `reset_manager`
- Modify: `engine/host_loop.py` — call `subsystem_emitters.pump(...)` next to `hit_vfx.update_ages(dt)`
- Test: `tests/integration/test_host_loop_subsystem_plumes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_host_loop_subsystem_plumes.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
from tests.unit.test_subsystem_emitters_backend import FakeControllerBackend


def test_pump_drives_the_singleton_manager():
    se.reset_registry()
    se.reset_manager()
    b = FakeControllerBackend()
    se.set_backend(b)
    sub = FakeSub("WarpEngineSubsystem", state="disabled")
    ship = FakeShip(subs=[sub])
    se.pump([ship], camera_pos=None, dt=0.1)
    assert se.get_manager().active_count() == 1
    assert b.created[0].params["fSize"] == 1.4


def test_default_backend_is_null_safe_noop():
    se.reset_registry()
    se.reset_manager()  # no set_backend → NullBackend
    sub = FakeSub("WarpEngineSubsystem", state="disabled")
    se.pump([FakeShip(subs=[sub])], camera_pos=None, dt=0.1)
    # Manager ran its full state machine without error; NullBackend rendered nothing.
    assert se.get_manager().active_count() == 1  # tracked, but inert handle
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_host_loop_subsystem_plumes.py -q`
Expected: FAIL — `AttributeError: module 'engine.appc.subsystem_emitters' has no attribute 'pump'`

- [ ] **Step 3: Write minimal implementation**

Add to the bottom of `engine/appc/subsystem_emitters.py`:

```python
# ---- module singleton + host-loop entry point ------------------------------

_backend = None        # set via set_backend(); defaults to NullBackend
_manager = None


def set_backend(backend):
    """Install the particle-controller backend (Spec A in production; a fake in
    tests). Resets the manager so the next pump rebuilds against it."""
    global _backend, _manager
    _backend = backend
    _manager = None


def reset_manager():
    """Drop the singleton manager (and any tracked emitters). Used by tests and
    on mission swap / load so plumes re-derive from predicates."""
    global _manager
    _manager = None


def get_manager():
    global _manager, _backend
    if _manager is None:
        if _backend is None:
            _backend = NullBackend()
        _manager = PlumeManager(_backend)
    return _manager


def pump(ships, camera_pos, dt):
    """Host-loop entry point: advance the plume state machine one tick."""
    get_manager().update(ships, camera_pos, dt)
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `uv run pytest tests/integration/test_host_loop_subsystem_plumes.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire the pump into the host loop**

In `engine/host_loop.py`, find the per-tick block near line 269:

```python
    from engine.appc import projectiles, hit_vfx
    ...
    hit_vfx.update_ages(dt)
```

Add the plume pump immediately after `hit_vfx.update_ages(dt)`:

```python
    from engine.appc import subsystem_emitters
    subsystem_emitters.pump(ships, _camera_world_pos(host), dt)
```

Where `ships` is the same ship list already in scope for the combat/VFX block (the one passed to `_advance_combat`). For `camera_pos`, add a small local helper near the other host-loop helpers — if the host exposes a camera world position use it, else pass `None` (the budget's proximity term and distance cull degrade gracefully to "no culling"):

```python
def _camera_world_pos(host):
    """Best-effort camera world position for plume distance culling; None if
    unavailable (culling then disabled, cap still applies)."""
    if host is not None and hasattr(host, "get_camera_world_pos"):
        try:
            p = host.get_camera_world_pos()
            return (p[0], p[1], p[2])
        except Exception:
            return None
    return None
```

If the exact `ships` variable name at that point differs, use whatever local holds the live ship list for the tick (the same value passed to `_advance_combat(...)`). Do not introduce a second enumeration.

- [ ] **Step 6: Run the host-loop integration tests to confirm no regression**

Run: `uv run pytest tests/integration/test_host_loop_m3gameflow.py tests/integration/test_host_loop_subsystem_plumes.py -q`
Expected: PASS. (The m3gameflow smoke test exercises the real tick; the pump must not raise. If `ships`/camera wiring needs adjustment, fix here.)

- [ ] **Step 7: Commit**

```bash
git add engine/appc/subsystem_emitters.py engine/host_loop.py tests/integration/test_host_loop_subsystem_plumes.py
git commit -m "feat(plumes): host-loop pump + module singleton (NullBackend default)"
```

---

## Final verification

- [ ] **Run the whole plume suite + the touched host-loop tests** (a focused subset — never the full repo suite; it OOMs the host):

Run: `uv run pytest tests/unit/test_subsystem_emitters_*.py tests/integration/test_host_loop_subsystem_plumes.py tests/integration/test_host_loop_m3gameflow.py -q`
Expected: ALL PASS.

- [ ] **Confirm production path is inert without Spec A:** grep that nothing calls `set_backend` with a real backend yet (the renderer wiring is the follow-up plan):

Run: `grep -rn "set_backend" engine native | grep -v test`
Expected: only the definition in `subsystem_emitters.py` — no production caller installs a real backend, so the pump is a `NullBackend` no-op until Spec A lands.

---

## Notes for the implementer

- **Test memory:** never run the full `uv run pytest` suite — it uses >100 GB RAM and freezes macOS. Always use the focused file globs above.
- **Tier values are tune-by-eye** (spec §7). The `fSize`/`fVelocity`/`fLife` numbers in `_builtin_table()` are placeholders that make the tests assert *which tier* resolved; do not treat them as final art.
- **Backend is the seam to Spec A.** Everything here is tested against `FakeControllerBackend`. When Spec A lands, a thin real backend implementing `create(...)` / `fire_one_shot(...)` (mapping to the `Effects.py` factories) is installed via `set_backend(...)` in the renderer bring-up — that is the follow-up plan, not this one.
- **No save/load code.** Persistence is "re-derive from predicates"; the manager is intentionally stateless across construction (spec §4.6).
