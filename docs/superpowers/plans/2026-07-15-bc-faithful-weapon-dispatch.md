# BC-Faithful Weapon Dispatch and Torpedo Flight — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port BC's audited `UpdateWeapons`/`TryFireWeapon` tick as the shared dispatch for all weapon systems, and make torpedo launch/guidance byte-faithful to the decompiled engine.

**Architecture:** Spec: `docs/superpowers/specs/2026-07-15-bc-faithful-weapon-dispatch-design.md`. Evidence: `../STBC-Reverse-Engineering-1/docs/gameplay/weapon-firing-mechanics.md` (2026-07-15 revision). Layered: event constants → weapon/property state → chain resolution → tick engine → rewiring → torpedo launch → chains UI → guidance → phaser gates → sweep.

**Tech Stack:** Pure Python (`engine/appc/`), pytest. No native/C++ changes.

## Global Constraints

- Branch: all work on `feat/bc-faithful-weapon-dispatch` (created from `main` in Task 0). Shared checkout: **never** `git add -A`/`checkout --`/`restore`/`stash`/`clean`/`reset --hard`; stage with explicit pathspecs only.
- **FROZEN (spec §7):** phaser discharge-rate source (`_normal_discharge_rate`), the damage formula in `host_loop._phaser_damage_for_tick`, all damage scales, and the PP_LOW `damage_hull` routing in `host_loop.py:659-671`. Do not touch.
- Cone half-angle constant is exactly `0.5235984` (BC's literal), not `math.radians(30)`.
- Torpedo defaults: guidance 4.0 s, max angular accel 0.125, lifetime 60.0 s.
- Ship-wide torpedo stagger: 0.5 s, game clock (`_game_time()` in `weapon_subsystems.py`), skipped for skew-firing tubes.
- Tick inter-shot threshold: 0.33; random re-seed `random.uniform(0.0, 0.33)` (BC's draw distribution unverified — comment it).
- Weapon `Groups` is a **uint bitmask with 1-based group ids**: member of group g ⟺ `mask & (1 << (g-1))`; group 0 means "all weapons".
- Firing chains stay parsed as **ordered group-id lists** (existing digit parser — matches authored names; ordering question logged back to the decomp project in Task 10).
- Every task: run the named tests, then `bash scripts/run_tests.sh` before committing. Task 10 runs `bash scripts/check_tests.sh` (full gate vs `tests/known_failures.txt` — only the 7 headless-GL FrameTest entries are baselined).
- Python engine only; no edits under `native/` or `sdk/`.

---

### Task 0: Branch

- [ ] **Step 1:** `git checkout -b feat/bc-faithful-weapon-dispatch` (from main; do not touch other sessions' uncommitted files — commit only paths this plan names).

---

### Task 1: Event constants and posting helper

**Files:**
- Modify: `engine/appc/events.py` (constants block, after `ET_TORPEDO_FIRED` at line ~28)
- Modify: `App.py` (project root — the Phase-1 shim; add `ET_WEAPON_FIRED` to the import/re-export from `engine.appc.events`, alongside `ET_TORPEDO_FIRED` at line 8)
- Test: `tests/unit/test_weapon_events_constants.py` (create)

**Interfaces:**
- Produces: `events.ET_WEAPON_FIRED = 0x0080007C`, `events.ET_WEAPON_FIRE_FAILED = 0x00800037`, `events.ET_TORPEDO_AMMO_CONSUMED = 0x00800067`; `App.ET_WEAPON_FIRED` re-export. Later tasks post these via the existing `TGEvent`/`g_kEventManager` pattern used by `_post_torpedo_fired` (`weapon_subsystems.py:2126`).

- [ ] **Step 1: Write the failing test**

```python
"""Audited BC event ids — weapon-firing-mechanics.md §1.5, §2.4."""


def test_weapon_event_ids_match_audited_values():
    from engine.appc import events
    assert events.ET_WEAPON_FIRED == 0x0080007C
    assert events.ET_WEAPON_FIRE_FAILED == 0x00800037
    assert events.ET_TORPEDO_AMMO_CONSUMED == 0x00800067


def test_app_shim_reexports_weapon_fired():
    import App
    assert App.ET_WEAPON_FIRED == 0x0080007C
```

- [ ] **Step 2:** `uv run pytest tests/unit/test_weapon_events_constants.py -v` — expect FAIL (AttributeError).
- [ ] **Step 3: Implement.** In `engine/appc/events.py`, directly under the `ET_TORPEDO_FIRED` block:

```python
# ── Weapon-fire events — ids from decompiled stbc.exe (weapon-firing-
# mechanics.md §1.5/§2.4; RE-tier evidence, not SDK inference).
#   ET_WEAPON_FIRED          posted by TorpedoTube fire (AFTER ET_TORPEDO_FIRED,
#                            BC's order) and by phaser first-shot (beam start).
#                            Bound to (weapon, owner ship). SDK name: App.py:12958.
#   ET_WEAPON_FIRE_FAILED    posted when a targeted torpedo fire fails the
#                            aim-point resolve or the ±30° cone (0x00800037).
#                            No SDK symbol; no shipped script listens — defined
#                            for fidelity + mod surface.
#   ET_TORPEDO_AMMO_CONSUMED 0x00800067, posted on torpedo fire ONLY when the
#                            firing ship is the player ship (BC locality gate).
ET_WEAPON_FIRED:           int = 0x0080007C
ET_WEAPON_FIRE_FAILED:     int = 0x00800037
ET_TORPEDO_AMMO_CONSUMED:  int = 0x00800067
```

In root `App.py` line 8, extend the existing `from engine.appc.events import (...)` list with `ET_WEAPON_FIRED, ET_WEAPON_FIRE_FAILED, ET_TORPEDO_AMMO_CONSUMED`.

- [ ] **Step 4:** Re-run step-2 command — PASS. Run `bash scripts/run_tests.sh`.
- [ ] **Step 5:** `git add engine/appc/events.py App.py tests/unit/test_weapon_events_constants.py && git commit -m "feat(events): audited ET_WEAPON_FIRED / fire-failed / ammo-consumed ids"`

---

### Task 2: Weapon groups, dumbfire flag, fire timer, skew fire

**Files:**
- Modify: `engine/appc/properties.py` (`WeaponProperty` base — find the class the leaf-weapon properties derive from; `TorpedoTubeProperty`/`EnergyWeaponProperty` are siblings under it)
- Modify: `engine/appc/weapon_subsystems.py` (`Weapon` class, line ~566; `TorpedoTube` line ~1814; `TorpedoSystem`)
- Test: `tests/unit/test_weapon_groups_and_skew.py` (create)

**Interfaces:**
- Produces on the weapon property base: `SetGroups(mask: int)`, `GetGroups() -> int` (default 0). **Note:** hardpoints already call `SetGroups` (e.g. `galaxy.py:22`) and it is currently a silent `_Stub` no-op — this task makes it real.
- Produces on `Weapon`: `_fire_timer: float = 0.0` (seeded in `__init__`), `IsMemberOfGroup(g) -> int` (g==0 → 1; else bit test on `GetProperty().GetGroups()`), `IsDumbFire() -> int` (0 on the base; `TorpedoTube` overrides → 1: BC's dumbfire fallback is the torpedo path, `AI/Preprocessors.py:458`).
- Produces on `TorpedoTube`: `SetSkewFire(flag)`, `IsSkewFire() -> int` (persistent `_skew_fire` bool, **never cleared by firing**); on `TorpedoSystem`: `SetSkewFire(flag)` — pure broadcast to child tubes, no system state.
- Update the `Weapon` docstring (line ~573): `IsMemberOfGroup`/`IsDumbFire`/`SetSkewFire`/`IsSkewFire` are no longer "deliberately absent" — the tick port needs them.

- [ ] **Step 1: Write the failing tests**

```python
from engine.appc.weapon_subsystems import TorpedoTube, TorpedoSystem
from engine.appc.properties import TorpedoTubeProperty


def _tube_with_groups(mask):
    tube = TorpedoTube("FT1")
    prop = TorpedoTubeProperty("FT1")
    prop.SetGroups(mask)
    tube.SetProperty(prop)
    return tube


def test_groups_bitmask_one_based_membership():
    # galaxy.py ForwardTorpedo1.SetGroups(25): bits {0,3,4} -> groups {1,4,5}
    tube = _tube_with_groups(25)
    assert tube.IsMemberOfGroup(1)
    assert tube.IsMemberOfGroup(4)
    assert tube.IsMemberOfGroup(5)
    assert not tube.IsMemberOfGroup(2)
    assert not tube.IsMemberOfGroup(3)


def test_group_zero_means_all_weapons():
    assert _tube_with_groups(0).IsMemberOfGroup(0)
    assert TorpedoTube("bare").IsMemberOfGroup(0)   # no property at all


def test_skew_fire_is_persistent_and_survives_firing():
    tube = _tube_with_groups(25)
    assert tube.IsSkewFire() == 0
    tube.SetSkewFire(1)
    assert tube.IsSkewFire() == 1
    tube.StopFiring()            # firing lifecycle must NOT clear it
    assert tube.IsSkewFire() == 1


def test_system_skew_broadcast_sets_children_only():
    sys_ = TorpedoSystem("Torpedoes")
    t1, t2 = _tube_with_groups(25), _tube_with_groups(26)
    sys_.AddChildSubsystem(t1)
    sys_.AddChildSubsystem(t2)
    sys_.SetSkewFire(1)
    assert t1.IsSkewFire() == 1 and t2.IsSkewFire() == 1
    assert not hasattr(sys_, "_skew_fire")   # no system-level flag (audited)


def test_tube_is_dumbfire_capable_banks_are_not():
    from engine.appc.weapon_subsystems import PhaserBank
    assert _tube_with_groups(0).IsDumbFire() == 1
    assert PhaserBank("bank").IsDumbFire() == 0
```

- [ ] **Step 2:** `uv run pytest tests/unit/test_weapon_groups_and_skew.py -v` — FAIL.
- [ ] **Step 3: Implement.** Property base (adjacent to the other simple scalar setters):

```python
    def SetGroups(self, mask) -> None:
        """Weapon-group bitmask (uint, 1-based group ids — decompiled
        WeaponProperty+0x50). Previously a silent _Stub no-op even though
        every stock hardpoint authors it (galaxy.py:22 etc.)."""
        self._groups = int(mask)

    def GetGroups(self) -> int:
        return int(getattr(self, "_groups", 0))
```

`Weapon.__init__`: add `self._fire_timer: float = 0.0` with a comment (`# BC Weapon+0x9C — inter-shot delay accumulator for TryFireWeapon`). `Weapon` methods:

```python
    def IsMemberOfGroup(self, g) -> int:
        """Weapon::IsMemberOfGroup (0x00583240). Group ids are 1-BASED bits
        in the property's Groups mask; group 0 means 'all weapons'."""
        g = int(g)
        if g == 0:
            return 1
        prop = self.GetProperty()
        get = getattr(prop, "GetGroups", None) if prop is not None else None
        mask = get() if callable(get) else 0
        return 1 if (int(mask) & (1 << (g - 1))) else 0

    def IsDumbFire(self) -> int:
        """Weapon::IsDumbFire (0x00583270, property+0x48). Only torpedo
        tubes are dumbfire-capable in our surface (AI/Preprocessors.py:458)."""
        return 0
```

`TorpedoTube`: `self._skew_fire: bool = False` in `__init__`; `IsDumbFire` → `return 1`; `SetSkewFire(self, flag) -> None: self._skew_fire = bool(flag)`; `IsSkewFire(self) -> int: return 1 if self._skew_fire else 0`. `TorpedoSystem`:

```python
    def SetSkewFire(self, flag) -> None:
        """Pure broadcast to child tubes (0x0057B1C0) — NO system-level
        state; audited §2.10. Dormant in stock play (zero SDK call sites)."""
        for i in range(self.GetNumWeapons()):
            w = self.GetWeapon(i)
            if w is not None and hasattr(w, "SetSkewFire"):
                w.SetSkewFire(flag)
```

- [ ] **Step 4:** Re-run tests — PASS. `bash scripts/run_tests.sh`.
- [ ] **Step 5:** `git add engine/appc/properties.py engine/appc/weapon_subsystems.py tests/unit/test_weapon_groups_and_skew.py && git commit -m "feat(weapons): real Groups bitmask, IsDumbFire, fire timer, dormant skew fire"`

---

### Task 3: WeaponSystem chain state and group resolution

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`WeaponSystem.__init__` line ~658 and new methods)
- Test: `tests/unit/test_firing_chains.py` (create)

**Interfaces:**
- Consumes: `WeaponSystemProperty.GetFiringChains() -> list[tuple[str, list[int]]]` (properties.py:855 — ordered group-id lists), `Weapon.IsMemberOfGroup` (Task 2).
- Produces on `WeaponSystem`: `_force_update: bool`, `_group_fire_mode: int`, `_last_weapon_idx: int` (−1), `_firing_chain_mode: int`, `_last_group_fired: int` (−1), `_target_list: list`;
  `SetForceUpdate(flag)` / `GetForceUpdate()`; `SetFiringChainMode(n)` (clamps to `[0, len(chains)-1]`, 0 when no chains) / `GetFiringChainMode()`; `GetFiringChains()` (delegates to property, `[]` without one); `SetGroupFireMode(g)` / `GetGroupFireMode()`; `_active_chain_groups() -> list[int]` (`[0]` when no chains); `_resolve_working_group() -> int` (resume semantics); `_add_target(t)` (dedupe, appends); `_prune_targets()` (drops dead/unresolvable); `GetNumTargets()`.

- [ ] **Step 1: Write the failing tests**

```python
from engine.appc.weapon_subsystems import WeaponSystem
from engine.appc.properties import WeaponSystemProperty


def _system_with_chains(raw="0;Single;123;Dual;53;Quad"):
    sys_ = WeaponSystem("Torpedoes")
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetFiringChainString(raw)
    sys_.SetProperty(prop)
    return sys_


def test_chain_mode_clamps_to_chain_count():
    sys_ = _system_with_chains()
    sys_.SetFiringChainMode(2)
    assert sys_.GetFiringChainMode() == 2
    sys_.SetFiringChainMode(99)          # BC clamps below chain count
    assert sys_.GetFiringChainMode() == 2
    sys_.SetFiringChainMode(-1)
    assert sys_.GetFiringChainMode() == 0


def test_active_chain_groups_ordered_and_group0_fallback():
    sys_ = _system_with_chains()
    sys_.SetFiringChainMode(2)           # "Quad" -> [5, 3] (authored order)
    assert sys_._active_chain_groups() == [5, 3]
    bare = WeaponSystem("NoChains")      # no property / empty chain string
    assert bare._active_chain_groups() == [0]


def test_resolve_working_group_resume_semantics():
    sys_ = _system_with_chains()
    sys_.SetFiringChainMode(1)           # "Dual" -> [1, 2, 3]
    assert sys_._resolve_working_group() == 1        # sentinel -> first group
    sys_._last_group_fired = 2
    assert sys_._resolve_working_group() == 2        # resume last-fired
    sys_._last_group_fired = 7                       # no longer in the chain
    assert sys_._resolve_working_group() == 1        # fall back to first


def test_target_list_prunes_dead():
    class _T:
        def __init__(self, dead): self._dead = dead
        def IsDead(self): return self._dead
    sys_ = _system_with_chains()
    live, dead = _T(False), _T(True)
    sys_._add_target(live); sys_._add_target(dead); sys_._add_target(live)
    assert sys_.GetNumTargets() == 2      # deduped
    sys_._prune_targets()
    assert sys_.GetNumTargets() == 1
```

- [ ] **Step 2:** `uv run pytest tests/unit/test_firing_chains.py -v` — FAIL.
- [ ] **Step 3: Implement** on `WeaponSystem` (init additions + methods):

```python
        # ── BC tick state (weapon-firing-mechanics.md §3.1-3.3) ──────────
        self._force_update: bool = False    # +0xAC: bypass 0.33s delay this tick
        self._group_fire_mode: int = 0      # +0xB0: published working group
        self._last_weapon_idx: int = -1     # +0xB4: round-robin cursor
        self._firing_chain_mode: int = 0    # +0xB8: active chain index
        self._last_group_fired: int = -1    # +0xBC: resume input, -1 sentinel
        self._target_list: list = []        # +0xC4: pruned per tick
```

```python
    def SetForceUpdate(self, flag) -> None:  self._force_update = bool(flag)
    def GetForceUpdate(self) -> int:         return 1 if self._force_update else 0

    def GetFiringChains(self) -> list:
        prop = self.GetProperty()
        get = getattr(prop, "GetFiringChains", None) if prop is not None else None
        chains = get() if callable(get) else []
        return chains if isinstance(chains, list) else []

    def SetFiringChainMode(self, n) -> None:
        """WeaponSystem::SetFiringChainMode (0x00584FA0): clamped below the
        chain count. This is what BC's tactical 'torpedo spread' toggle calls."""
        chains = self.GetFiringChains()
        hi = max(0, len(chains) - 1)
        self._firing_chain_mode = max(0, min(int(n), hi))

    def GetFiringChainMode(self) -> int:     return self._firing_chain_mode

    def SetGroupFireMode(self, g) -> None:   self._group_fire_mode = int(g)
    def GetGroupFireMode(self) -> int:       return self._group_fire_mode

    def _active_chain_groups(self) -> list:
        """Ordered group ids of the active chain; [0] ('all weapons') when
        the ship authors no chains (67 of 70 stock hardpoints)."""
        chains = self.GetFiringChains()
        if not chains:
            return [0]
        _label, groups = chains[self._firing_chain_mode % len(chains)]
        return list(groups) if groups else [0]

    def _resolve_working_group(self) -> int:
        """§3.2 step 3 — LastGroupFired is an INPUT: keep firing the group we
        last fired while it is still in the chain; else the chain's first."""
        groups = self._active_chain_groups()
        if self._last_group_fired != -1 and self._last_group_fired in groups:
            return self._last_group_fired
        return groups[0]

    def _add_target(self, target) -> None:
        if target is not None and target not in self._target_list:
            self._target_list.append(target)

    def _prune_targets(self) -> None:
        """§3.2 step 2 — unlink anything dead or unresolvable."""
        self._target_list = [
            t for t in self._target_list
            if t is not None
            and not (hasattr(t, "IsDead") and t.IsDead())
        ]

    def GetNumTargets(self) -> int:          return len(self._target_list)
```

- [ ] **Step 4:** Tests PASS; `bash scripts/run_tests.sh`.
- [ ] **Step 5:** `git add engine/appc/weapon_subsystems.py tests/unit/test_firing_chains.py && git commit -m "feat(weapons): firing-chain state + working-group resume resolution"`

---

### Task 4: The tick engine — `try_fire_weapon` + `update_weapons`

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (new `WeaponSystem` methods; module needs `import random` — check top-of-file imports)
- Test: `tests/unit/test_weapon_tick.py` (create)

**Interfaces:**
- Consumes: Task 2/3 surfaces; `Weapon.CanFire/Fire/StopFiring/IsFiring`; `self.GetParentShip()`.
- Produces: `WeaponSystem.try_fire_weapon(weapon, dt, target, offset) -> bool` and `WeaponSystem.update_weapons(dt) -> bool` (returns `did_fire`). **Pure dispatch** — no gates beyond §3.2/§3.3; system-level gates stay in `StartFiring` (Task 5).

- [ ] **Step 1: Write the failing tests** (use a fake weapon so the tick logic is tested in isolation):

```python
from engine.appc.weapon_subsystems import WeaponSystem
from engine.appc.properties import WeaponSystemProperty


class FakeWeapon:
    def __init__(self, groups=(1,), can_fire=True, dumb=False):
        self._groups = set(groups); self._can = can_fire; self._dumb = dumb
        self._fire_timer = 0.0; self._firing = False
        self._target = None; self._target_offset = None
        self.fired = 0; self.dumb_fired = 0; self.stopped = 0
    def IsMemberOfGroup(self, g): return 1 if (g == 0 or g in self._groups) else 0
    def IsDumbFire(self): return 1 if self._dumb else 0
    def CanFire(self): return 1 if self._can else 0
    def IsFiring(self): return 1 if self._firing else 0
    def StopFiring(self): self.stopped += 1
    def Fire(self, target=None, offset=None):
        self.fired += 1; self._target = target; return None
    def FireDumb(self, iReserved=0, iForce=1): self.dumb_fired += 1


def _system(weapons, chains="", single_fire=False):
    sys_ = WeaponSystem("W")
    prop = WeaponSystemProperty("W")
    if chains:
        prop.SetFiringChainString(chains)
    sys_.SetProperty(prop)
    sys_._single_fire = single_fire
    for w in weapons:
        sys_._test_weapons = getattr(sys_, "_test_weapons", [])
        sys_._test_weapons.append(w)
    sys_.GetNumWeapons = lambda: len(weapons)
    sys_.GetWeapon = lambda i: weapons[i]
    sys_.GetParentShip = lambda: None
    return sys_


def test_timer_gates_below_033_and_force_update_bypasses():
    w = FakeWeapon()
    sys_ = _system([w])
    assert sys_.try_fire_weapon(w, 0.1, None, None) is False   # 0.1 < 0.33
    assert w.fired == 0
    sys_.SetForceUpdate(1)
    assert sys_.try_fire_weapon(w, 0.016, None, None) is True  # forced to 0.33
    assert w.fired == 1


def test_canfire_failure_calls_stopfiring():
    w = FakeWeapon(can_fire=False)
    sys_ = _system([w])
    sys_.SetForceUpdate(1)
    assert sys_.try_fire_weapon(w, 0.016, None, None) is False
    assert w.stopped == 1 and w.fired == 0


def test_update_weapons_round_robin_resumes_past_last_idx():
    a, b = FakeWeapon(), FakeWeapon()
    sys_ = _system([a, b], single_fire=True)
    sys_.SetForceUpdate(1); sys_._add_target(object())
    sys_.update_weapons(0.016)
    sys_.SetForceUpdate(1)
    sys_.update_weapons(0.016)
    assert a.fired == 1 and b.fired == 1     # alternated, not a-a


def test_single_fire_stops_after_first_success():
    a, b = FakeWeapon(), FakeWeapon()
    sys_ = _system([a, b], single_fire=True)
    sys_.SetForceUpdate(1); sys_._add_target(object())
    sys_.update_weapons(0.016)
    assert a.fired + b.fired == 1


def test_multi_fire_tries_every_group_member():
    a, b = FakeWeapon(), FakeWeapon()
    sys_ = _system([a, b], single_fire=False)
    sys_.SetForceUpdate(1); sys_._add_target(object())
    sys_.update_weapons(0.016)
    assert a.fired == 1 and b.fired == 1


def test_dumbfire_fallback_only_on_zero_targets_and_dumb_weapon():
    dumb = FakeWeapon(can_fire=False, dumb=True)
    guided = FakeWeapon(can_fire=False, dumb=False)
    sys_ = _system([dumb, guided])
    sys_.SetForceUpdate(1)
    sys_.update_weapons(0.016)               # zero targets
    assert dumb.dumb_fired == 1
    assert guided.dumb_fired == 0
    dumb.dumb_fired = 0
    sys_.SetForceUpdate(1); sys_._add_target(object())
    sys_.update_weapons(0.016)               # has a target -> no fallback
    assert dumb.dumb_fired == 0


def test_group_advance_on_dry_group():
    dry = FakeWeapon(groups=(1,), can_fire=False)
    wet = FakeWeapon(groups=(2,))
    sys_ = _system([dry, wet], chains="12;Chain")
    sys_.SetForceUpdate(1); sys_._add_target(object())
    assert sys_.update_weapons(0.016) is True
    assert wet.fired == 1
    assert sys_._last_group_fired == 2
```

- [ ] **Step 2:** `uv run pytest tests/unit/test_weapon_tick.py -v` — FAIL.
- [ ] **Step 3: Implement** (faithful to §3.2 seven steps / §3.3 six steps):

```python
    # BC inter-shot delay threshold (TryFireWeapon, 0x00584E40).
    FIRE_TIMER_THRESHOLD = 0.33

    def try_fire_weapon(self, weapon, dt, target, offset) -> bool:
        """TryFireWeapon (0x00584E40), §3.3. Plain bool — BC has no tri-state."""
        import random
        if self._force_update:
            weapon._fire_timer = self.FIRE_TIMER_THRESHOLD   # bypass this tick
        else:
            weapon._fire_timer = getattr(weapon, "_fire_timer", 0.0) + dt
        if not weapon.IsFiring() and weapon._fire_timer < self.FIRE_TIMER_THRESHOLD:
            return False
        # Re-seed reads the PRE-EXISTING state: a continuously-firing weapon
        # zeroes; everything else draws fresh. BC's draw distribution is
        # unverified in the corpus — uniform(0, 0.33) is our choice.
        if weapon.IsFiring():
            weapon._fire_timer = 0.0
        else:
            weapon._fire_timer = random.uniform(0.0, self.FIRE_TIMER_THRESHOLD)
        if not weapon.CanFire():
            weapon.StopFiring()      # what makes a beam vanish on charge-out
            return False
        before = weapon.fired if hasattr(weapon, "fired") else None
        result = weapon.Fire(target, offset)
        if self._weapon_did_fire(weapon, result, before):
            return True
        # §3.3 step 6: clear target, retry against the system target list.
        weapon._target = None
        for entry in list(self._target_list):
            if entry is None or (hasattr(entry, "IsDead") and entry.IsDead()):
                continue
            before = weapon.fired if hasattr(weapon, "fired") else None
            result = weapon.Fire(entry, offset)
            if self._weapon_did_fire(weapon, result, before):
                return True
        return False

    @staticmethod
    def _weapon_did_fire(weapon, result, before) -> bool:
        """Our Fire() implementations return None; success is observable as
        IsFiring() (beams/held) or a discrete-shot side effect. Explicit
        True/False from Fire wins when provided; test fakes expose `fired`."""
        if isinstance(result, bool):
            return result
        if before is not None:
            return weapon.fired > before
        return bool(weapon.IsFiring())

    def update_weapons(self, dt) -> bool:
        """UpdateWeapons (0x00584930), §3.2. Returns did_fire."""
        did_fire = False
        ship = self.GetParentShip()
        if ship is not None and hasattr(ship, "IsDead") and ship.IsDead():
            return False
        self._prune_targets()
        target = self._target_list[0] if self._target_list else None
        offset = getattr(self, "_held_offset", None)
        groups = self._active_chain_groups()
        working = self._resolve_working_group()
        start_group = working
        while True:
            self.SetGroupFireMode(working)
            n = self.GetNumWeapons()
            fired_this_group = False
            for delta in range(1, n + 1):
                idx = (self._last_weapon_idx + delta) % n if n else 0
                weapon = self.GetWeapon(idx)
                if weapon is None or not weapon.IsMemberOfGroup(working):
                    continue
                if self.try_fire_weapon(weapon, dt, target, offset):
                    did_fire = fired_this_group = True
                    self._last_weapon_idx = idx
                    self._last_group_fired = working
                    if self._single_fire:
                        break
                else:
                    weapon._target = None      # ClearTarget, NOT a timer reset
                    if self.GetNumTargets() == 0 and weapon.IsDumbFire():
                        weapon.FireDumb(0, 1)
            if fired_this_group or len(groups) <= 1:
                break
            # §3.2 step 7: advance to the next group in the chain, wrapping.
            working = groups[(groups.index(working) + 1) % len(groups)]
            if working == start_group:
                self._last_group_fired = -1
                break
        self._force_update = False    # one-tick bypass, consumed
        return did_fire
```

Note: `_single_fire` already exists on the held-fire systems; add `self._single_fire = getattr(self, "_single_fire", False)` guard in `WeaponSystem.__init__` so the base has it too.

- [ ] **Step 4:** Tests PASS; `bash scripts/run_tests.sh`.
- [ ] **Step 5:** `git add engine/appc/weapon_subsystems.py tests/unit/test_weapon_tick.py && git commit -m "feat(weapons): BC UpdateWeapons/TryFireWeapon tick engine"`

---

### Task 5: Rewire — StartFiring arms, host_loop pumps the tick

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`WeaponSystem.StartFiring` line ~745; `_HeldFireWeaponSystem` line ~1244 incl. `retry_held_fire` ~1297 and `_dispatch_one_or_all` ~1338; `TorpedoSystem.StartFiring` line ~945; TractorBeamSystem `retry_held_fire` ~1534)
- Modify: `engine/host_loop.py` (`_advance_combat`: phaser `retry_held_fire` call ~600, pulse pump ~679-683, tractor pump ~691-695)
- Test: `tests/unit/test_start_firing_arms_tick.py` (create); update `tests/integration/test_pulse_singlefire_modes.py`, `tests/integration/test_tractor_singlefire_dispatch.py`, `tests/integration/test_galaxy_combat_fire_diagnostic.py`, `tests/unit/test_phaser_fire_sfx_edge_trigger.py` (whatever asserts immediate dispatch from StartFiring now pumps one `update_weapons(0.34)` first)

**Interfaces:**
- Consumes: Task 4 `update_weapons`.
- Produces: `StartFiring(target, offset)` = gates (IsOn / `_is_offline` / `_cloak_blocks_fire` / `_target_undetectable`) → `_add_target(target)`, `_held_target=target`, `_held_offset=offset`, `_fire_held=True`, `SetForceUpdate(1)` → **one immediate `update_weapons(0.0)`** (so a single key-press still fires this frame — ForceUpdate makes the timer pass). `StopFiring()` additionally clears `_fire_held`, `_target_list`, and resets `_last_group_fired = -1`.
- host_loop `_advance_combat` gains one unified pump before the phaser damage loop:

```python
    # BC WeaponSystem tick (§3.2): one update_weapons per armed system per
    # frame. Replaces the per-class retry_held_fire pumps.
    for ship in ships_list:
        for getter in ("GetPhaserSystem", "GetPulseWeaponSystem",
                       "GetTractorBeamSystem", "GetTorpedoSystem"):
            sys_ = getattr(ship, getter)() if hasattr(ship, getter) else None
            if sys_ is None or not getattr(sys_, "_fire_held", False):
                continue
            if _is_offline(sys_) or not sys_.IsOn():
                sys_.StopFiring()
                continue
            held = getattr(sys_, "_held_target", None)
            if held is not None and _target_undetectable(sys_, held):
                sys_.StopFiring()      # preserves the anti-horn-loop stop
                continue
            if held is not None and hasattr(sys_, "_can_engage") \
                    and not sys_._can_engage(ship, held):
                sys_.StopFiring()      # range gate (phaser global range etc.)
                continue
            sys_.update_weapons(dt)
```

(`_target_undetectable` and `_is_offline` are importable from `engine.appc.weapon_subsystems`; extend the existing import at `host_loop.py:84`.)

- Deletions: `_dispatch_one_or_all` (both branches), all `retry_held_fire` methods, and the host_loop pulse/tractor `retry_held_fire` loops. Their gate logic already lives in `StartFiring` gates + the pump above + per-weapon `CanFire`. Torpedo `StartFiring` loses the whole eligible-scan/spread branch — it is now just the base arm (ammo reserve gate stays, moved before arming). The phaser continuous-damage loop and `_advance_weapons` (UpdateCharge/UpdateReload) are untouched.
- Trigger semantics (spec §2.4): press = `StartFiring`, release = `StopFiring` — already how the input path drives held systems; torpedoes now join it (hold = stagger walk-out, tap = one launch via ForceUpdate).

- [ ] **Step 1: Write the failing test**

```python
from engine.appc.weapon_subsystems import TorpedoSystem


class _LiveTarget:
    def IsDead(self): return False


def test_start_firing_arms_and_fires_via_force_update(monkeypatch):
    sys_ = TorpedoSystem("Torpedoes")
    fired = []
    monkeypatch.setattr(sys_, "update_weapons", lambda dt: fired.append(dt) or True)
    target = _LiveTarget()
    sys_.StartFiring(target, None)
    assert getattr(sys_, "_fire_held", False)
    assert target in sys_._target_list
    assert fired == [0.0]                 # immediate same-frame attempt


def test_stop_firing_disarms_and_clears_targets():
    sys_ = TorpedoSystem("Torpedoes")
    sys_.StartFiring(_LiveTarget(), None)
    sys_.StopFiring()
    assert not sys_._fire_held
    assert sys_.GetNumTargets() == 0
    assert sys_._last_group_fired == -1
```

- [ ] **Step 2:** Run — FAIL (no `_fire_held` on base; old dispatch path fires immediately).
- [ ] **Step 3: Implement** the base `StartFiring`/`StopFiring` rewrite:

```python
    def StartFiring(self, target=None, offset=None) -> None:
        """Arms the tick (BC StartFiring reads no spread/skew state — §2.10).
        The actual dispatch is update_weapons, pumped per frame by host_loop;
        SetForceUpdate(1) + one immediate update makes a tap fire this frame
        (SDK FireWeapons does exactly StartFiring + SetForceUpdate(1))."""
        if not self.IsOn():
            return
        if _is_offline(self):
            return
        if _cloak_blocks_fire(self):
            return
        if _target_undetectable(self, target):
            return
        self._add_target(target)
        self._held_target = target
        self._held_offset = offset
        self._fire_held = True
        self.SetForceUpdate(1)
        self.update_weapons(0.0)

    def StopFiring(self, *args) -> None:
        self._fire_held = False
        self._held_target = None
        self._target_list = []
        self._last_group_fired = -1
        for i in range(self.GetNumWeapons()):
            w = self.GetWeapon(i)
            if w is not None and hasattr(w, "StopFiring"):
                w.StopFiring()
```

`TorpedoSystem.StartFiring` shrinks to: the ammo reserve gate (lines 965–971 unchanged) then `super().StartFiring(target, offset)`; the per-launch ammo debit moves to `TorpedoTube.Fire` in Task 7 (this task keeps the debit by counting `_currently_firing` growth OR — simpler and correct — move `ammo.AddAvailable(-1)` into `_spawn_torpedo` now, guarded `if finite`). Delete `_currently_firing` bookkeeping from the base (its only remaining consumer was StopFiring's walk — the rewrite above walks all weapons instead) and update `IsFiring()` to `any(w.IsFiring() for w in weapons) or self._fire_held`.

- [ ] **Step 4:** New tests PASS. Update the four listed existing test files: anywhere a test called `StartFiring` and asserted an immediate `Fire`, it still passes via the immediate forced update; tests that asserted `retry_held_fire` behaviour now pump `sys_.update_weapons(0.34)` instead (0.34 > threshold). Run `bash scripts/run_tests.sh` — fix all fallout in the same commit (never orphan).
- [ ] **Step 5:** `git add engine/appc/weapon_subsystems.py engine/host_loop.py tests/unit/test_start_firing_arms_tick.py tests/integration/test_pulse_singlefire_modes.py tests/integration/test_tractor_singlefire_dispatch.py tests/integration/test_galaxy_combat_fire_diagnostic.py tests/unit/test_phaser_fire_sfx_edge_trigger.py && git commit -m "feat(weapons): StartFiring arms the BC tick; host_loop pumps update_weapons"`

---

### Task 6: Torpedo spawn — tube direction + inherited velocity

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`_spawn_projectile` lines ~271-390)
- Test: `tests/unit/test_torpedo_launch_fidelity.py` (create)

**Interfaces:**
- Consumes: `emitter.GetDirection()/GetRight()` (subsystems.py:657/664, body-frame `TGPoint3`), `ship.GetVelocityTG()` (objects.py:453), `emitter.IsSkewFire()` (Task 2).
- Produces: `_spawn_projectile(emitter, mod, *, drf_override=0.0)` — **signature loses `spread_unit`/`homing_delay`**. Velocity = world tube direction × `GetLaunchSpeed()` + ship velocity; skew perturbs the LOCAL direction by `+ 0.033 × Right` before the world transform. Target lock stamping (`_target_ship`) moves to the caller (`TorpedoTube.Fire`, Task 7) — this task stamps it exactly as before to stay green: keep the `GetTarget()` lookup for `torp._target_ship`/`torp._target_subsystem` but **stop using it for velocity**.

- [ ] **Step 1: Write the failing tests**

```python
import math
from engine.appc.math import TGPoint3, TGMatrix3


SKEW = 0.033   # audited .rdata constant, fixed sign, local frame


def _fire_and_capture(tube_direction, tube_right, ship_vel, skew=False,
                      launch_speed=10.0):
    """Build a minimal ship+tube via the existing test helpers in
    tests/unit/test_torpedo_spread_volley.py (_make_ship_with_tubes) — reuse
    that fixture module; parametrize direction/right on the tube property.
    Returns the spawned Torpedo."""
    ...  # see step 3 note: extract _make_ship_with_tubes into tests/helpers


def test_targeted_launch_ignores_target_position():
    # Target far off to starboard; tube points ship-forward.
    torp = _fire_and_capture(tube_direction=TGPoint3(0, 1, 0),
                             tube_right=TGPoint3(1, 0, 0),
                             ship_vel=TGPoint3(0, 0, 0))
    v = torp._velocity
    speed = v.Length()
    assert abs(v.y / speed - 1.0) < 1e-6      # straight out the tube
    assert abs(v.x) < 1e-6 and abs(v.z) < 1e-6


def test_velocity_inherits_ship_motion():
    torp = _fire_and_capture(tube_direction=TGPoint3(0, 1, 0),
                             tube_right=TGPoint3(1, 0, 0),
                             ship_vel=TGPoint3(3.0, 0, 0), launch_speed=10.0)
    assert abs(torp._velocity.x - 3.0) < 1e-6
    assert abs(torp._velocity.y - 10.0) < 1e-6


def test_skew_perturbs_local_direction_fixed_sign():
    straight = _fire_and_capture(TGPoint3(0, 1, 0), TGPoint3(1, 0, 0),
                                 TGPoint3(0, 0, 0), skew=False)
    skewed = _fire_and_capture(TGPoint3(0, 1, 0), TGPoint3(1, 0, 0),
                               TGPoint3(0, 0, 0), skew=True)
    # +0.033 x Right -> positive x component, same speed.
    assert skewed._velocity.x > 0
    expected = math.atan2(SKEW, 1.0)
    got = math.atan2(skewed._velocity.x, skewed._velocity.y)
    assert abs(got - expected) < 1e-6
    assert abs(skewed._velocity.Length() - straight._velocity.Length()) < 1e-6
```

- [ ] **Step 2:** Run — FAIL (current code aims at the target / has no velocity inheritance).
- [ ] **Step 3: Implement.** Replace `_spawn_projectile`'s velocity block (lines ~310-379) with:

```python
    # ── Launch trajectory (audited §2.4.1): the aim point NEVER steers the
    # launch. Direction = tube-local Direction (skew: + 0.033 x Right, local
    # frame, fixed sign) rotated to world; speed from the Python projectile
    # module; plus the firing ship's own linear velocity.
    local_dir = None
    got = emitter.GetDirection() if hasattr(emitter, "GetDirection") else None
    if isinstance(got, TGPoint3):
        local_dir = TGPoint3(got.x, got.y, got.z)
    if local_dir is None:
        local_dir = TGPoint3(0.0, 1.0, 0.0)
    if getattr(emitter, "IsSkewFire", None) and emitter.IsSkewFire():
        right = emitter.GetRight() if hasattr(emitter, "GetRight") else None
        if isinstance(right, TGPoint3):
            local_dir = TGPoint3(local_dir.x + 0.033 * right.x,
                                 local_dir.y + 0.033 * right.y,
                                 local_dir.z + 0.033 * right.z)
    world_dir = TGPoint3(local_dir.x, local_dir.y, local_dir.z)
    if source_ship is not None and hasattr(source_ship, "GetWorldRotation"):
        rot = source_ship.GetWorldRotation()
        from engine.appc.math import TGMatrix3
        if isinstance(rot, TGMatrix3):
            world_dir.MultMatrixLeft(rot)
    length = world_dir.Length()
    ship_vel = (source_ship.GetVelocityTG()
                if source_ship is not None and hasattr(source_ship, "GetVelocityTG")
                else TGPoint3(0.0, 0.0, 0.0))
    if not isinstance(ship_vel, TGPoint3):
        ship_vel = TGPoint3(0.0, 0.0, 0.0)
    if length > 1e-6:
        torp._velocity = TGPoint3(
            world_dir.x / length * launch_speed + ship_vel.x,
            world_dir.y / length * launch_speed + ship_vel.y,
            world_dir.z / length * launch_speed + ship_vel.z,
        )
    # Homing state (guidance-only; does not shape the launch):
    target_ship = source_ship.GetTarget() if source_ship is not None else None
    if (target_ship is not None
            and hasattr(target_ship, "IsDead") and not target_ship.IsDead()):
        torp._target_ship = target_ship
    else:
        torp._target_ship = None
```

Delete the `spread_unit` fan block and the `homing_delay` stamp; delete the two parameters from the signature and from `TorpedoTube.Fire`'s signature/passthrough (Fire keeps `target`/`offset` only). Delete `_SPREAD_DIVERGENCE_TAN` / `_SPREAD_DELAY` module constants. Extract the ship+tube fixture from `tests/unit/test_torpedo_spread_volley.py` into `tests/helpers/torpedo_fixtures.py` if not already shared, then **delete** `tests/unit/test_torpedo_spread_volley.py` (its feature is gone; walk-out coverage arrives in Task 7).

- [ ] **Step 4:** Tests PASS; `bash scripts/run_tests.sh`; fix fallout in tests that imported the deleted constants.
- [ ] **Step 5:** `git add -- engine/appc/weapon_subsystems.py tests/unit/test_torpedo_launch_fidelity.py tests/helpers/torpedo_fixtures.py && git rm tests/unit/test_torpedo_spread_volley.py && git commit -m "feat(torpedo): BC-faithful launch — tube direction + inherited ship velocity"`

---

### Task 7: TorpedoTube.Fire gates — aim resolve, ±30° cone, stagger, events

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`TorpedoTube.Fire` ~1967, `TorpedoTube.CanFire` ~1945, `_spawn_torpedo` ~1988, `TorpedoSystem.__init__`; new module helpers `_resolve_torpedo_aim_point` and `_in_torpedo_cone`)
- Test: `tests/unit/test_torpedo_fire_gates.py` (create)

**Interfaces:**
- Consumes: Tasks 1/2/6; `_game_time()` (weapon_subsystems.py:45); existing `_post_torpedo_fired` (~2126) / `_post_torpedo_reload` (~2101) posting pattern.
- Produces:
  - `TorpedoSystem._last_system_fire_time: float = -1000.0` (init), stamped by every tube fire.
  - `_resolve_torpedo_aim_point(tube, target) -> TGPoint3 | None` — `None` when the target is unresolvable; else `target.GetWorldLocation() + R_target · (offset × target_world_scale)` where offset is the tube's `_target_offset` (or zero vector when absent).
  - `_in_torpedo_cone(tube, ship, aim_point) -> bool` — tube world mount → aim-point vector expressed in the tube's local basis (Direction/Right/Up rotated by ship rotation); forward > 0 AND `abs(math.atan2(r, f)) <= 0.5235984` AND `abs(math.atan2(u, f)) <= 0.5235984`.
  - `TorpedoTube.Fire(target=None, offset=None)`: `CanFire` gate → **targeted path** (target not None): aim resolve (fail → post `ET_WEAPON_FIRE_FAILED` dest=tube, return) → cone (fail → same event, return) → stamp `_target`/`_target_offset` → common bookkeeping. **Dumb path** (target None): straight to bookkeeping. Bookkeeping: `_num_ready -= 1`, `_last_fire_time = now`, parent `_last_system_fire_time = now`, `_start_slot_cooldown(now)`, finite-ammo debit (moved here from StartFiring if Task 5 left it there), `_spawn_torpedo()`, post `ET_TORPEDO_FIRED` (existing helper) **then** `ET_WEAPON_FIRED` (src=tube, dest=owner ship), then `ET_TORPEDO_AMMO_CONSUMED` only when the firing ship is the player (`App.g_kUtopiaModule.GetPlayer()`-equivalent: use `engine.appc.ships` player lookup already used by `dev_combat_cheats` — grep `is_player` there and reuse).
  - `TorpedoTube.CanFire` gains gate 3 between disabled and ImmediateDelay: `if not self.IsSkewFire() and parent is not None and _game_time() - getattr(parent, "_last_system_fire_time", -1000.0) <= 0.5: return 0`.

- [ ] **Step 1: Write the failing tests** (reuse `tests/helpers/torpedo_fixtures.py`; place target ships at controlled world positions):

```python
def test_ship_wide_stagger_blocks_second_tube_within_half_second():
    ship, sys_, (t1, t2) = make_ship_with_two_tubes()
    fire_time = advance_game_clock_to(100.0)
    t1.Fire(None, None)
    assert t1.GetNumReady() == t1.GetMaxReady() - 1
    t2.Fire(None, None)                       # 0.0s later — staggered out
    assert t2.GetNumReady() == t2.GetMaxReady()
    advance_game_clock_to(100.6)
    t2.Fire(None, None)
    assert t2.GetNumReady() == t2.GetMaxReady() - 1


def test_skew_fire_exempt_from_stagger():
    ship, sys_, (t1, t2) = make_ship_with_two_tubes()
    t2.SetSkewFire(1)
    advance_game_clock_to(100.0)
    t1.Fire(None, None)
    t2.Fire(None, None)                       # same instant, skew — allowed
    assert t2.GetNumReady() == t2.GetMaxReady() - 1


def test_cone_rejects_target_astern_and_posts_fire_failed(recorded_events):
    ship, sys_, (t1, _) = make_ship_with_two_tubes()   # tubes face +Y
    target = make_target_at(TGPoint3(0.0, -500.0, 0.0))
    t1.Fire(target, None)
    assert t1.GetNumReady() == t1.GetMaxReady()        # no launch
    assert events.ET_WEAPON_FIRE_FAILED in recorded_events


def test_cone_boundary_at_30_degrees():
    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    inside = make_target_at(pos_at_bearing_deg(29.0))
    outside = make_target_at(pos_at_bearing_deg(31.0))
    t1.Fire(inside, None);  assert t1.GetNumReady() == t1.GetMaxReady() - 1
    advance_game_clock_by(1.0)
    t1.Fire(outside, None); assert t1.GetNumReady() == t1.GetMaxReady() - 1  # unchanged


def test_fire_posts_torpedo_fired_then_weapon_fired(recorded_events):
    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    t1.Fire(None, None)
    ids = [e for e in recorded_events
           if e in (events.ET_TORPEDO_FIRED, events.ET_WEAPON_FIRED)]
    assert ids == [events.ET_TORPEDO_FIRED, events.ET_WEAPON_FIRED]
```

(`recorded_events` fixture: register broadcast handlers via the same `g_kEventManager` API `tests/unit/test_torpedo_fired_event.py` already uses — copy its pattern. `advance_game_clock_*`: monkeypatch the same clock `_game_time()` reads, as `test_torpedo_tube_reload.py` already does.)

- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3: Implement** per the Interfaces block. Cone helper:

```python
_TORPEDO_CONE_HALF_ANGLE = 0.5235984   # BC's literal, NOT math.radians(30)


def _in_torpedo_cone(tube, ship, aim_point) -> bool:
    """0x0057DA90→0x0057DC10: square ±30° cone about the tube direction,
    yaw and pitch checked INDEPENDENTLY via atan2; forward must be > 0.
    No occlusion test — firing through an asteroid is legal (audited)."""
    import math as _m
    mount = tube._emitter_world_position()
    to_aim = aim_point - mount
    if to_aim.Length() < 1e-6:
        return False
    d = tube.GetDirection() if hasattr(tube, "GetDirection") else None
    r = tube.GetRight() if hasattr(tube, "GetRight") else None
    if not isinstance(d, TGPoint3):
        d = TGPoint3(0.0, 1.0, 0.0)
    if not isinstance(r, TGPoint3):
        r = TGPoint3(1.0, 0.0, 0.0)
    u = TGPoint3(d.y * r.z - d.z * r.y,      # up = dir x right (local)
                 d.z * r.x - d.x * r.z,
                 d.x * r.y - d.y * r.x)
    rot = ship.GetWorldRotation() if (ship is not None
              and hasattr(ship, "GetWorldRotation")) else None
    basis = []
    for v in (d, r, u):
        w = TGPoint3(v.x, v.y, v.z)
        if isinstance(rot, TGMatrix3):
            w.MultMatrixLeft(rot)
        basis.append(w)
    fwd = basis[0].Dot(to_aim)
    if fwd <= 0.0:
        return False
    yaw = _m.atan2(abs(basis[1].Dot(to_aim)), fwd)
    pitch = _m.atan2(abs(basis[2].Dot(to_aim)), fwd)
    return yaw <= _TORPEDO_CONE_HALF_ANGLE and pitch <= _TORPEDO_CONE_HALF_ANGLE
```

Aim-point resolver (audited: static point, no lead):

```python
def _resolve_torpedo_aim_point(tube, target):
    """0x005852A0: target world pos + tube aim offset scaled by target world
    scale and rotated by target world rotation. None => unresolvable (the
    caller posts ET_WEAPON_FIRE_FAILED). No speed/velocity/intercept enters."""
    if target is None or not hasattr(target, "GetWorldLocation"):
        return None
    if hasattr(target, "IsDead") and target.IsDead():
        return None
    pos = target.GetWorldLocation()
    offset = getattr(tube, "_target_offset", None)
    if not isinstance(offset, TGPoint3):
        return TGPoint3(pos.x, pos.y, pos.z)
    scale = float(target.GetScale()) if hasattr(target, "GetScale") else 1.0
    o = TGPoint3(offset.x * scale, offset.y * scale, offset.z * scale)
    rot = target.GetWorldRotation() if hasattr(target, "GetWorldRotation") else None
    if isinstance(rot, TGMatrix3):
        o.MultMatrixLeft(rot)
    return TGPoint3(pos.x + o.x, pos.y + o.y, pos.z + o.z)
```

`ET_WEAPON_FIRED` post helper mirrors `_post_torpedo_fired` (~2126) with src=tube, dest=`tube._climb_to_ship()`; fire-failed helper mirrors it with dest=tube. Keep all posts inside the same `try/except` + `dev_mode.log_swallowed` pattern the existing helpers use.

- [ ] **Step 4:** Tests PASS; `bash scripts/run_tests.sh`; update `tests/unit/test_torpedo_spread.py` (spread selection is gone from TorpedoSystem — becomes chain-mode coverage or is deleted in Task 8; if it blocks here, move its deletion into this commit and note it).
- [ ] **Step 5:** `git add engine/appc/weapon_subsystems.py tests/unit/test_torpedo_fire_gates.py && git commit -m "feat(torpedo): aim resolve + ±30° cone + ship-wide stagger + audited fire events"`

---

### Task 8: Spread selector → firing chains (engine + UI)

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (delete `TorpedoSystem` `_spread`/`GetSpread`/`SetSpread`/`GetSpreadOptions`, ~lines 902-943)
- Modify: `engine/appc/weapon_config.py` (config dict lines ~83-106/148-149; `cycle_torpedo_spread` ~214-229)
- Modify: `engine/ui/weapons_display_panel.py` (action map line ~55 keeps `"cycle-spread"` name; freeze tuple ~420)
- Modify: `native/assets/ui-cef/js/` — grep for `spread` in the weapons panel JS and relabel from the new config keys (labels come from the engine; JS renders strings it is given)
- Test: update `tests/unit/test_torpedo_spread.py` → rename `tests/unit/test_firing_chain_selection.py`; update `tests/unit/test_weapons_display_panel.py`

**Interfaces:**
- Consumes: `SetFiringChainMode`/`GetFiringChainMode`/`GetFiringChains` (Task 3).
- Produces in `weapon_config.get_config(ship)` dict: replace `"spread": int` / `"spread_options": list[int]` with `"spread": str` (active chain label, `""` when no chains) and `"spread_options": list[str]` (chain labels in authored order, `[]` when none — panel hides the control on empty, matching BC ships without chains). `cycle_torpedo_spread(ship)` advances `SetFiringChainMode((mode+1) % len(chains))`, no-op when < 2 chains.

- [ ] **Step 1: Write the failing tests**

```python
def test_config_exposes_chain_labels_for_galaxy_style_chains():
    ship = make_ship_with_torpedo_chains("0;Single;123;Dual;53;Quad")
    cfg = weapon_config.get_config(ship)
    assert cfg["spread_options"] == ["Single", "Dual", "Quad"]
    assert cfg["spread"] == "Single"


def test_cycle_advances_chain_mode_and_wraps():
    ship = make_ship_with_torpedo_chains("0;Single;123;Dual;53;Quad")
    torps = ship.GetTorpedoSystem()
    weapon_config.cycle_torpedo_spread(ship)
    assert torps.GetFiringChainMode() == 1
    weapon_config.cycle_torpedo_spread(ship)
    weapon_config.cycle_torpedo_spread(ship)
    assert torps.GetFiringChainMode() == 0            # wrapped


def test_chainless_ship_shows_no_spread_control():
    ship = make_ship_with_torpedo_chains("")
    cfg = weapon_config.get_config(ship)
    assert cfg["spread_options"] == []
    weapon_config.cycle_torpedo_spread(ship)          # silent no-op
```

- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3: Implement:** in `weapon_config.py`:

```python
        chains = torps.GetFiringChains() if hasattr(torps, "GetFiringChains") else []
        spread_options = [label for (label, _groups) in chains]
        if spread_options:
            mode = int(torps.GetFiringChainMode())
            spread = spread_options[mode % len(spread_options)]
        else:
            spread = ""
```

```python
def cycle_torpedo_spread(ship) -> None:
    """Advance the torpedo firing chain (BC's tactical 'spread' toggle IS
    the chain selector — SetFiringChainMode; audited §2.10). Wraps; no-op
    when the hardpoint authors fewer than two chains."""
    torps = _torpedo_system(ship)
    if torps is None or not hasattr(torps, "GetFiringChains"):
        return
    n = len(torps.GetFiringChains())
    if n < 2:
        return
    torps.SetFiringChainMode((torps.GetFiringChainMode() + 1) % n)
```

Delete the `GetSpread`/`GetSpreadOptions` try/except blocks in `get_config`; delete the four TorpedoSystem spread methods and `_spread` init. Panel: labels are already strings end-to-end (`spread` was rendered via str) — update the freeze tuple and any `f"x{spread}"` formatting in JS/panel to render the label directly.

- [ ] **Step 4:** Tests PASS; `bash scripts/run_tests.sh` (fix `test_weapons_display_panel.py` expectations in the same commit).
- [ ] **Step 5:** `git add -- engine/appc/weapon_subsystems.py engine/appc/weapon_config.py engine/ui/weapons_display_panel.py native/assets/ui-cef/js tests/unit/test_firing_chain_selection.py tests/unit/test_weapons_display_panel.py && git rm tests/unit/test_torpedo_spread.py && git commit -m "feat(ui): spread selector drives firing chains (SetFiringChainMode)"`

---

### Task 9: Guidance — lead pursuit, decaying authority, cloak/dead handling

**Files:**
- Modify: `engine/appc/projectiles.py` (`Torpedo.__init__` defaults; `_steer_toward` → rewrite; `update_all` guidance call site lines ~161-164)
- Test: `tests/unit/test_torpedo_guidance_fidelity.py` (create); update `tests/unit/test_torpedo_fired_event.py` and any test asserting subsystem homing / 30 s TTL

**Interfaces:**
- Consumes: `engine.appc.sensor_detection.can_detect(observer, target) -> bool` (sensor_detection.py:133) for the cloak/visibility cache; `torpedo._source_ship` as the observer.
- Produces: new `Torpedo` slots `_guidance_initial` (4.0), `_last_seen_target_pos` (None), `_last_target_vel` (None); defaults `_ttl = 60.0`, `_guidance_lifetime = 4.0` + `_guidance_initial = 4.0` (`SetGuidanceLifetime` writes BOTH — BC's setter does), `_max_angular_accel = 0.125`. **Deleted:** `_target_subsystem` slot + all reads, `_homing_start_age`. `update_all` guidance condition becomes `t._target_ship is not None and t._age < t._guidance_lifetime`.

- [ ] **Step 1: Write the failing tests**

```python
from engine.appc.projectiles import Torpedo
from engine.appc.math import TGPoint3


class FakeShip:
    def __init__(self, pos, vel=(0, 0, 0), dead=False, detectable=True):
        self._pos = TGPoint3(*pos); self._vel = TGPoint3(*vel)
        self._dead = dead; self.detectable = detectable
    def GetWorldLocation(self): return self._pos
    def GetVelocityTG(self): return self._vel
    def IsDead(self): return self._dead


def _torp(pos=(0, 0, 0), vel=(0, 10, 0), target=None):
    t = Torpedo()
    t._position = TGPoint3(*pos); t._velocity = TGPoint3(*vel)
    t._target_ship = target
    t.SetGuidanceLifetime(4.0); t.SetMaxAngularAccel(0.125)
    return t


def test_defaults_match_bc_ctor():
    t = Torpedo()
    assert t._ttl == 60.0
    assert t._guidance_lifetime == 4.0 and t._guidance_initial == 4.0
    assert t._max_angular_accel == 0.125


def test_lead_pursuit_steers_ahead_of_crossing_target():
    target = FakeShip(pos=(100, 100, 0), vel=(50, 0, 0))   # crossing +x
    t = _torp(target=target)
    from engine.appc import projectiles
    projectiles._guide(t, 0.016)
    # Pure pursuit would rotate toward (100,100); lead must rotate FURTHER
    # toward +x than the pure-pursuit bearing.
    import math
    pure = math.atan2(100, 100)
    got = math.atan2(t._velocity.x, t._velocity.y)
    assert got > 0                       # turned toward the target at all
    # With max_step = 0.125*0.016 the turn is budget-clamped; assert the
    # DESIRED direction by widening the budget:
    t2 = _torp(target=target); t2.SetMaxAngularAccel(1000.0)
    projectiles._guide(t2, 0.016)
    got2 = math.atan2(t2._velocity.x, t2._velocity.y)
    assert got2 > pure - 1e-6            # at least as far starboard as pure


def test_turn_budget_decays_linearly_to_zero():
    target = FakeShip(pos=(1000, 0, 0))
    early = _torp(target=target); early._age = 0.0
    late = _torp(target=target); late._age = 3.9
    from engine.appc import projectiles
    projectiles._guide(early, 0.1); projectiles._guide(late, 0.1)
    import math
    turn_early = abs(math.atan2(early._velocity.x, early._velocity.y))
    turn_late = abs(math.atan2(late._velocity.x, late._velocity.y))
    assert turn_early > turn_late > 0.0
    expected_late = (0.1 / 4.0) * 0.125 * 0.1      # remaining/initial × accel × dt
    assert abs(turn_late - expected_late) < 1e-6


def test_dead_target_goes_ballistic_no_cache():
    target = FakeShip(pos=(100, 0, 0), dead=True)
    t = _torp(target=target)
    before = (t._velocity.x, t._velocity.y, t._velocity.z)
    from engine.appc import projectiles
    projectiles._guide(t, 0.1)
    assert (t._velocity.x, t._velocity.y, t._velocity.z) == before


def test_cloaked_target_steers_to_frozen_last_seen(monkeypatch):
    from engine.appc import projectiles
    target = FakeShip(pos=(100, 100, 0))
    t = _torp(target=target)
    monkeypatch.setattr(projectiles, "_target_visible", lambda torp, tgt: True)
    projectiles._guide(t, 0.016)                    # caches (100,100,0)
    assert t._last_seen_target_pos is not None
    target._pos = TGPoint3(-500, 100, 0)            # moves while cloaked
    monkeypatch.setattr(projectiles, "_target_visible", lambda torp, tgt: False)
    t2_vel_before_x = t._velocity.x
    projectiles._guide(t, 0.016)
    assert t._velocity.x >= t2_vel_before_x         # still steering +x-ward


def test_speed_constant_under_guidance():
    target = FakeShip(pos=(100, 100, 0), vel=(50, 0, 0))
    t = _torp(target=target)
    from engine.appc import projectiles
    for _ in range(20):
        projectiles._guide(t, 0.05)
    assert abs(t._velocity.Length() - 10.0) < 1e-6
```

- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3: Implement.** Slots/defaults per Interfaces (`SetGuidanceLifetime` sets both fields). Module-level:

```python
_LEAD_ACCEL_K = 0.5   # BC _DAT_008887A8 ≈ 0.5 — second-order lead term


def _target_visible(torpedo, target) -> bool:
    """Cloak/visibility check for the last-seen cache (BC 0x005AC450 via
    Guide). Observer is the FIRING ship; headless fixtures without a source
    ship count as visible."""
    src = torpedo._source_ship
    if src is None:
        return True
    try:
        from engine.appc.sensor_detection import can_detect
        return bool(can_detect(src, target))
    except Exception:
        return True


def _guide(torpedo, dt: float) -> None:
    """Torpedo::Guide (0x00578CB0), audited §5.5.
    Order: dead-target ballistic → cloak cache → second-order lead →
    linearly-decaying turn budget → clamped rotation, speed preserved."""
    target = torpedo._target_ship
    if target is None:
        return
    if hasattr(target, "IsDead") and target.IsDead():
        return                       # ballistic; NOT the cloak cache
    speed = torpedo._velocity.Length()
    if speed < 1e-6:
        return
    if _target_visible(torpedo, target):
        pos = target.GetWorldLocation()
        torpedo._last_seen_target_pos = TGPoint3(pos.x, pos.y, pos.z)
        vel = (target.GetVelocityTG()
               if hasattr(target, "GetVelocityTG") else TGPoint3(0, 0, 0))
        if not isinstance(vel, TGPoint3):
            vel = TGPoint3(0.0, 0.0, 0.0)
        to_t = pos - torpedo._position
        t_go = to_t.Length() / speed
        prev_vel = torpedo._last_target_vel
        if isinstance(prev_vel, TGPoint3) and dt > 1e-9:
            acc = TGPoint3((vel.x - prev_vel.x) / dt,
                           (vel.y - prev_vel.y) / dt,
                           (vel.z - prev_vel.z) / dt)
        else:
            acc = TGPoint3(0.0, 0.0, 0.0)
        torpedo._last_target_vel = TGPoint3(vel.x, vel.y, vel.z)
        aim = TGPoint3(
            pos.x + vel.x * t_go + _LEAD_ACCEL_K * acc.x * t_go * t_go,
            pos.y + vel.y * t_go + _LEAD_ACCEL_K * acc.y * t_go * t_go,
            pos.z + vel.z * t_go + _LEAD_ACCEL_K * acc.z * t_go * t_go,
        )
    else:
        aim = torpedo._last_seen_target_pos
        if aim is None:
            return
    to_aim = aim - torpedo._position
    dist = to_aim.Length()
    if dist < 1e-6:
        return
    desired = TGPoint3(to_aim.x / dist, to_aim.y / dist, to_aim.z / dist)
    current = TGPoint3(torpedo._velocity.x / speed,
                       torpedo._velocity.y / speed,
                       torpedo._velocity.z / speed)
    remaining = max(0.0, torpedo._guidance_lifetime - torpedo._age)
    initial = torpedo._guidance_initial if torpedo._guidance_initial > 1e-9 else 1.0
    max_step = (remaining / initial) * torpedo._max_angular_accel * dt
    cos_theta = max(-1.0, min(1.0, current.Dot(desired)))
    theta = math.acos(cos_theta)
    if theta <= max_step or theta < 1e-6:
        new_dir = desired
    else:
        sin_theta = math.sin(theta)
        a = math.sin(theta - max_step) / sin_theta
        b = math.sin(max_step) / sin_theta
        new_dir = TGPoint3(current.x * a + desired.x * b,
                           current.y * a + desired.y * b,
                           current.z * a + desired.z * b)
    torpedo._velocity = new_dir * speed
```

`update_all` line ~161: condition becomes `if t._target_ship is not None and t._age < t._guidance_lifetime: _guide(t, dt)`. Delete `_steer_toward`, `_homing_start_age`, and `_target_subsystem` (slot, init, and the stamp in `_spawn_projectile`).

- [ ] **Step 4:** Tests PASS; `bash scripts/run_tests.sh` (update any test stamping `_target_subsystem`/`_homing_start_age`).
- [ ] **Step 5:** `git add engine/appc/projectiles.py engine/appc/weapon_subsystems.py tests/unit/test_torpedo_guidance_fidelity.py && git commit -m "feat(torpedo): audited guidance — lead pursuit, decaying authority, cloak/dead handling, 60s lifetime"`

---

### Task 10: Phaser safe group + full gate + doc-rot

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`_EnergyWeaponFireMixin` lines ~393-475; `PhaserSystem.SetPowerLevel` ~1393; `GetChargePercentage` ~1603/1637; phaser first-shot `ET_WEAPON_FIRED` in `Fire` ~419)
- Modify: `docs/superpowers/specs/2026-07-15-bc-faithful-weapon-dispatch-design.md` (§9: append the chain-string parse/ordering clarifying question for the decomp project)
- Test: `tests/unit/test_phaser_canfire_fidelity.py` (create); update tests asserting `REFIRE_HEADROOM_FRACTION`/`_armed`

**Interfaces:**
- Consumes: existing `_charge_level`/`_min_firing_charge`/`GetOverallConditionPercentage`-equivalent (`GetConditionPercentage` on bank and parent), Task 1 `ET_WEAPON_FIRED`.
- Produces: mixin `CanFire` = ship-alive (`self._climb_to_ship()` dead check) AND charge (`> 0` if `IsFiring()` else `>= _min_firing_charge`) AND disabled-product (`prop.GetDisabledPercentage() < bank.GetConditionPercentage() × parent.GetConditionPercentage()` — follow the existing accessor names in `subsystems.py`; keep the existing parent-`IsOn` gate). **Delete** `REFIRE_HEADROOM_FRACTION`, `_armed`, and the re-arm block in `UpdateCharge` (lines ~469-474). Recharge gains `× self.GetConditionPercentage()`. `SetPowerLevel` clamps: `self._power_level = max(0, min(2, int(level)))` with a comment naming BC's uninitialized-stack bug. `GetChargePercentage` returns 0.0 when parent off or self disabled. `PhaserBank.Fire` posts `ET_WEAPON_FIRED` on the was-not-firing edge (same edge as the SFX at line ~432). **FROZEN reminder:** do not touch `_normal_discharge_rate` usage or anything in `host_loop._phaser_damage_for_tick`.

- [ ] **Step 1: Write the failing tests**

```python
def test_start_needs_min_firing_charge_but_sustain_only_needs_nonzero():
    bank = make_charged_bank(min_firing=2.0, charge=1.0)
    assert bank.CanFire() == 0            # below start threshold
    bank._charge_level = 2.0
    bank.Fire(target=make_target())
    bank._charge_level = 0.5              # drained mid-beam
    assert bank.CanFire() == 1            # sustain: > 0 suffices
    bank._charge_level = 0.0
    assert bank.CanFire() == 0


def test_restart_after_depletion_needs_min_firing_charge_no_headroom():
    bank = make_charged_bank(min_firing=2.0, charge=2.0, max_charge=10.0)
    bank.Fire(target=make_target())
    bank._charge_level = 0.0
    bank.UpdateCharge(0.016)              # depletion auto-stop
    assert bank.IsFiring() == 0
    bank._charge_level = 2.0              # exactly MinFiringCharge — enough
    assert bank.CanFire() == 1            # (old code demanded 2.0 + 20% of 10)


def test_recharge_scales_with_condition():
    healthy = make_charged_bank(charge=0.0, recharge=1.0, condition_pct=1.0)
    damaged = make_charged_bank(charge=0.0, recharge=1.0, condition_pct=0.5)
    healthy.UpdateCharge(1.0); damaged.UpdateCharge(1.0)
    assert abs(healthy._charge_level - 2 * damaged._charge_level) < 1e-9


def test_set_power_level_clamps():
    from engine.appc.weapon_subsystems import PhaserSystem
    sys_ = PhaserSystem("Phasers")
    sys_.SetPowerLevel(5)
    assert sys_.GetPowerLevel() == 2      # BC: uninitialized-stack bug; we clamp
    sys_.SetPowerLevel(-3)
    assert sys_.GetPowerLevel() == 0


def test_phaser_first_shot_posts_weapon_fired(recorded_events):
    bank = make_charged_bank(min_firing=1.0, charge=5.0)
    bank.Fire(target=make_target())
    assert events.ET_WEAPON_FIRED in recorded_events
    n = recorded_events.count(events.ET_WEAPON_FIRED)
    bank.Fire(target=make_target())       # already firing — no re-post
    assert recorded_events.count(events.ET_WEAPON_FIRED) == n
```

- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3: Implement** per Interfaces. Spec §9 addendum (append verbatim):

> **Second question for the decomp project (chain parse):** how does the C++ parse `FiringChainString` segments into chain masks — per-digit group ids (`"53"` → groups {5,3}) or `atoi` decimal bitmask (`53` → groups {1,3,5,6})? And does the group sweep honour authored segment order or ascending bit order (`GetNextGroup` scans upward, which would try group 3 before 5 in Quad)? Our implementation keeps the per-digit ordered-list reading — it is the only one under which the authored names (Single/Dual/Quad vs tube `SetGroups` masks 25/26/4) make sense.

- [ ] **Step 4:** Tests PASS. Run the **full gate**: `bash scripts/check_tests.sh` — every failure must be in `tests/known_failures.txt` (the 7 FrameTests); anything else is this branch's regression: fix before committing.
- [ ] **Step 5:** `git add engine/appc/weapon_subsystems.py tests/unit/test_phaser_canfire_fidelity.py docs/superpowers/specs/2026-07-15-bc-faithful-weapon-dispatch-design.md && git commit -m "feat(phasers): audited CanFire asymmetry + condition-scaled recharge + clamps"`

---

### Task 11: Final sweep

- [ ] **Step 1:** `rg -n "spread_unit|homing_delay|_homing_start_age|GetSpreadOptions|REFIRE_HEADROOM|_SPREAD_" engine/ tests/ App.py` — must return nothing (stale references = doc-rot/bugs).
- [ ] **Step 2:** `bash scripts/check_tests.sh` once more from a clean state.
- [ ] **Step 3:** Update `CLAUDE.md`'s reference table is NOT needed (no new subsystem); instead append one line to the spec's §10 noting live verification is pending Mark's QuickBattle pass (spec §8 items 1-6).
- [ ] **Step 4:** `git add -- docs/superpowers/specs/2026-07-15-bc-faithful-weapon-dispatch-design.md && git commit -m "chore: weapon-dispatch sweep + live-verify note"` (plus any sweep fixes with explicit paths).

---

## Self-Review Notes (already applied)

- Spec §2.2 step 1 "clear didFire" → local return value; §2.2 step 5 SetGroupFireMode published before candidates fire — implemented before the candidate loop each group iteration.
- Benign double-examine quirk (§2.2 correction 3): NOT reproduced — our round-robin uses a clean `range(1, n+1)` walk; the spec calls the quirk "reproduced for fidelity" but it is observationally equivalent (the second examination can never fire — the timer was just re-seeded); noted here as the one deliberate simplification.
- Type consistency: `GetFiringChains() -> list[tuple[str, list[int]]]` everywhere; `_fire_timer` on Weapon; `_last_system_fire_time` on TorpedoSystem; cone constant named `_TORPEDO_CONE_HALF_ANGLE` in Tasks 7.
- Spec coverage: §2 → Tasks 3-5; §3 → Tasks 6-7; §4 → Task 9; §5 → Task 8; §6 → Tasks 1, 7, 10; §7 → Task 10; §8 → per-task tests + Task 10/11 gates; §9-10 → Task 10 spec addendum + Task 11.
