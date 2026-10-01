# Minor Rocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw thousands of small instanced catalogue rocks ("minors") as halos
around every major rock, inside BC's tile fields and as breakup debris, with a
cosmetic player fly-through response and no gameplay effect.

**Architecture:** A pure C++ `MinorField` (no GL) owns cloud instances, their
animation, culling, LOD binning, shove state and the player contact test. A GL
`MinorPass` draws the bins with `glDrawElementsInstanced`, using a new
`minor.vert` linked to the existing `opaque.frag`. Python owns which clouds
exist (`engine/rocks/minors.py`), the dials (`engine/rocks/minor_dials.py`,
reached through a shared dev dial-group registry) and the fly-through responses
(`engine/rocks/minor_contact.py`).

**Tech Stack:** C++20, OpenGL 4.1 core (GLSL 410), GoogleTest, pybind11,
Python 3, pytest.

**Spec:** `docs/superpowers/specs/2026-10-01-minor-rocks-design.md`. Read it
before any task. Decisions M1–M4 are binding.

## Global Constraints

- **Worktree:** everything happens in
  `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/minor-rocks`,
  on branch `feat/minor-rocks`. Never commit to `main`; never push.
- **Banned git**, in the worktree and the shared checkout alike, for you and
  every subagent you dispatch:
  - `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`
  - `git clean`, `git reset --hard`, `git add -A`, `git add .`
- **Staging:** explicit paths only. To mutate a file temporarily, back it up
  with `cp` and restore it by copy, then `diff` to prove the restore.
- **Build:** `cmake --build build -j` from the worktree root. Never run cmake
  inside `native/`. Shader edits need a reconfigure first:
  `cmake -B build -S . -DPython3_EXECUTABLE=$PWD/.venv/bin/python3`.
- **Python tests:** `uv run pytest <path> -q`.
- **C++ tests:** `ctest --test-dir build -R <regex> --output-on-failure`, or
  run the gtest binary directly: `build/native/tests/renderer/renderer_tests
  --gtest_filter=<Suite>.*`.
- **Gate:** `scripts/check_tests.sh` must exit 0 before the branch is called
  done. A GL test that skips without a baseline line fails the gate.
- **Units:** GU (1 GU = 175 m). Never name a variable `*_m` or `*_mps`.
- **Rotation:** column-vector, right-handed. `v_world = R · v_body`.
- **Glossary:**
  - **VIEW space:** the viewed set's coordinates, which is what Python pushes.
  - **RENDER space:** view space minus the floating render origin, which is
    what `inst->world` and the camera hold.
  - The two are related by `render = view − g_world.render_origin()`.
- **Paths:** never capture one at import, and never spell `game` or `sdk` as
  a path segment (`tests/unit/test_path_indirection.py`).
- **Never launch the game.** Mark does live checks.
- **Stub claims:** read `docs/stub_heatmap.md` before asserting that any SDK
  call is a no-op.
- **Fragment size:**
  - Every catalogue fragment has `bound_radius_m = 100`, which is
    `100 / 1.75 = 57.142857` model units at load scale 1.
  - A minor of radius `r` GU therefore draws with instance scale
    `r / (bound_radius_mu × BC_MODEL_SCALE)`, where `BC_MODEL_SCALE = 0.01`.
- **Families:** index 0 silicate, 1 carbonaceous, 2 icy, 3 metallic
  (`FAMILY_INDEX` in `engine/rocks/minor_dials.py`).

## Review Focus

1. **A hand-off or set change teleports the player** a long way in view
   space in one frame. The sweep must not shove every minor along that line
   or flood the contact buffer. This is pinned in Task 6 by
   `TeleportJumpDoesNotSweep`.
2. **A pause** (game time stands still) must freeze the clouds and produce no
   contacts or shoves, even if the camera moves. This is pinned in Task 6 by
   `PausedFrameMakesNoContacts`.
3. **A rock dying while its halo is natively live** must convert that halo,
   never duplicate it. The registry must not re-create the halo for the dying
   rock during its 0.5 s retirement. This is pinned in Task 10 by
   `test_dying_rock_halo_is_detached_not_recreated`.
4. **A mission swap** recycles model handles and instance ids. No cloud,
   fragment handle or player id may survive into the next mission. This is
   pinned in Task 8 by `test_minors_state_cleared_by_reset` and in Task 9 by
   `test_swap_reset_clears_registry`.
5. **The catalogue is unavailable** (empty manifest): no clouds are created
   and nothing raises. This is pinned in Task 9 by
   `test_no_catalogue_means_no_clouds`.

---

### Task 1: AsteroidField remembers its tile configuration

**Files:**
- Modify: `engine/appc/asteroid_field.py`
- Test: `tests/unit/test_asteroid_field_config.py` (create)

**Interfaces:**
- Produces:
  - `AsteroidField.GetNumTilesPerAxis() -> int` (default 1)
  - `AsteroidField.GetNumAsteroidsPerTile() -> int` (default 0)
  - `AsteroidField.GetAsteroidSizeFactor() -> float` (default 1.0)
  - `AsteroidField.GetFieldRadius() -> float` (exists)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_asteroid_field_config.py
"""AsteroidFieldPlacement keeps the tile setters BC scripts call (minor-rocks
spec §1): the minor registry builds a field's cloud from them."""
from engine.appc.asteroid_field import AsteroidField, AsteroidFieldPlacement_Create


def test_defaults():
    f = AsteroidField()
    assert f.GetNumTilesPerAxis() == 1
    assert f.GetNumAsteroidsPerTile() == 0
    assert f.GetAsteroidSizeFactor() == 1.0


def test_setters_round_trip_like_beol4():
    f = AsteroidFieldPlacement_Create("Asteroid Field 1")
    f.SetFieldRadius(1000.0)
    f.SetNumTilesPerAxis(3)
    f.SetNumAsteroidsPerTile(15)
    f.SetAsteroidSizeFactor(7.0)
    f.ConfigField()
    f.UpdateNodeOnly()
    assert f.GetFieldRadius() == 1000.0
    assert f.GetNumTilesPerAxis() == 3
    assert f.GetNumAsteroidsPerTile() == 15
    assert f.GetAsteroidSizeFactor() == 7.0


def test_is_ship_inside_unchanged():
    class _P:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z
    class _Ship:
        def GetWorldLocation(self):
            return _P(5.0, 0.0, 0.0)
    f = AsteroidField()
    f.SetFieldRadius(10.0)
    assert f.IsShipInside(_Ship()) == 1
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_asteroid_field_config.py -q`
Expected: FAIL, because the getters are not defined. They will resolve through
`TGObject.__getattr__` to a stub, so the asserts fail.

- [ ] **Step 3: Implement**

Replace the class body of `AsteroidField` in `engine/appc/asteroid_field.py`
and update the module docstring:

```python
"""AsteroidField placement — point-in-sphere field volume.

Mirrors the SDK App.AsteroidFieldPlacement_Create surface. Position + field
radius + IsShipInside drive warp gating (warp_gates.py). The tile setters are
REMEMBERED (minor-rocks spec §1): engine/rocks/minors.py builds each field's
minor cloud from radius, tiles³ × per-tile and the size factor. ConfigField /
UpdateNodeOnly stay no-ops. Subclasses the bare App.AsteroidField base so
CT_ASTEROID_FIELD isinstance/GetClassObjectList/AsteroidField_Cast all match.
"""
from App import AsteroidField as _AsteroidFieldBase


class AsteroidField(_AsteroidFieldBase):
    def __init__(self):
        super().__init__()
        self._field_radius = 0.0
        self._tiles_per_axis = 1
        self._per_tile = 0
        self._size_factor = 1.0

    def SetFieldRadius(self, r):
        self._field_radius = float(r)

    def GetFieldRadius(self):
        return self._field_radius

    def SetNumTilesPerAxis(self, n):
        self._tiles_per_axis = int(n)

    def GetNumTilesPerAxis(self):
        return self._tiles_per_axis

    def SetNumAsteroidsPerTile(self, n):
        self._per_tile = int(n)

    def GetNumAsteroidsPerTile(self):
        return self._per_tile

    def SetAsteroidSizeFactor(self, f):
        self._size_factor = float(f)

    def GetAsteroidSizeFactor(self):
        return self._size_factor

    def IsShipInside(self, ship):
        loc = ship.GetWorldLocation()
        c = self.GetWorldLocation()
        dx, dy, dz = loc.x - c.x, loc.y - c.y, loc.z - c.z
        r = self._field_radius
        return 1 if (dx * dx + dy * dy + dz * dz <= r * r) else 0

    def ConfigField(self, *a): pass
    def UpdateNodeOnly(self, *a): pass
```

Keep `AsteroidFieldPlacement_Create` and `AsteroidField_Cast` unchanged.

- [ ] **Step 4: Run the tests and the warp-gating suite**

Run: `uv run pytest tests/unit/test_asteroid_field_config.py tests -q -k "asteroid_field or warp_gate"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/asteroid_field.py tests/unit/test_asteroid_field_config.py
git commit -m "feat(minors): AsteroidField remembers its tile configuration"
```

---

### Task 2: Dev dial-group registry (`/`, `L`, `O` shared)

**Files:**
- Create: `engine/dev_dial_groups.py`
- Modify:
  - `engine/dev_nebula_dials.py`: `register()` delegates key registration to the registry
  - `engine/ui/developer_options_panel.py`: Lighting-tab row "Dial keys"
  - `native/assets/ui-cef/js/developer_options.js`: the row
  - `tests/unit/test_dev_key_collisions.py`: scan `dev_dial_groups.py`
  - `tests/conftest.py`: autouse reset
- Test: `tests/unit/test_dev_dial_groups.py` (create)

**Interfaces:**
- Produces, in `engine/dev_dial_groups.py`:
  - `register_group(name: str, order: tuple, get_dials: Callable[[], dict], step: Callable[[str, int], None]) -> None`
  - `groups() -> tuple[str, ...]`
  - `active() -> str`
  - `cycle_active() -> str`
  - `selected() -> str`
  - `cycle_dial() -> None`
  - `push(direction: int) -> None`
  - `register_keys(_h) -> None`
  - `reset() -> None`
- `dev_nebula_dials.register(_h)` registers group `"nebula"` (order
  `DIAL_ORDER`, step `_push`), then calls `dev_dial_groups.register_keys(_h)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_dev_dial_groups.py
"""One owner for the dev dial keys / L O (minor-rocks spec §5, M4)."""
import pytest

import engine.dev_dial_groups as g


@pytest.fixture(autouse=True)
def _fresh():
    g.reset()
    yield
    g.reset()


def _group(name, order, log):
    vals = {k: 1.0 for k in order}
    def step(dial, direction):
        vals[dial] += direction
        log.append((name, dial, direction))
    g.register_group(name, order, lambda: dict(vals), step)
    return vals


def test_first_registered_group_is_active():
    log = []
    _group("nebula", ("veil", "g"), log)
    _group("minors", ("halo_outer",), log)
    assert g.groups() == ("nebula", "minors")
    assert g.active() == "nebula"


def test_slash_cycles_dials_within_the_active_group_only():
    log = []
    _group("nebula", ("veil", "g"), log)
    _group("minors", ("halo_outer",), log)
    assert g.selected() == "veil"
    g.cycle_dial()
    assert g.selected() == "g"
    g.cycle_dial()
    assert g.selected() == "veil"


def test_push_steps_the_selected_dial_of_the_active_group():
    log = []
    _group("nebula", ("veil", "g"), log)
    _group("minors", ("halo_outer", "halo_inner"), log)
    g.cycle_active()
    assert g.active() == "minors"
    g.cycle_dial()
    g.push(+1)
    assert log == [("minors", "halo_inner", 1)]


def test_cycle_active_wraps_and_keeps_each_groups_selection():
    log = []
    _group("nebula", ("veil", "g"), log)
    _group("minors", ("halo_outer",), log)
    g.cycle_dial()                     # nebula -> g
    g.cycle_active()                   # minors
    g.cycle_active()                   # back to nebula
    assert g.active() == "nebula" and g.selected() == "g"


def test_reregistering_a_group_replaces_it():
    log = []
    _group("nebula", ("veil",), log)
    _group("nebula", ("veil", "g"), log)
    assert g.groups() == ("nebula",)


def test_register_keys_claims_exactly_slash_l_o(monkeypatch):
    import engine.dev_mode as dev_mode
    claimed = []
    monkeypatch.setattr(dev_mode, "register_dev_keybinding",
                        lambda key, fn, desc: claimed.append(key))
    class _Keys:
        KEY_SLASH, KEY_L, KEY_O = 1, 2, 3
    class _H:
        keys = _Keys
    g.register_keys(_H)
    assert sorted(claimed) == [1, 2, 3]
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_dev_dial_groups.py -q`
Expected: FAIL with `ModuleNotFoundError: engine.dev_dial_groups`.

- [ ] **Step 3: Implement `engine/dev_dial_groups.py`**

```python
"""Shared developer dial keys: / L O drive whichever dial GROUP is active.

minor-rocks spec §5 (M4). dev_nebula_dials.py found / L O to be the only keys
free on a MacBook in every namespace (test_dev_key_collisions.py), and the
nebula dials held all three. Groups now share them: `/` cycles the dials of
the ACTIVE group, L / O step the selected dial down / up, and Developer
Options -> Lighting -> "Dial keys" cycles which group is active. The first
registered group (nebula, at boot) is active by default.

Each group supplies its dial order, a getter for its live values (for the
print) and a step function `step(dial_name, direction)` that does the
group's own clamping and pushes to native. Every press prints
`[<group> dials] selected=<dial> {...}`.
"""
from typing import Callable

import engine.dev_mode as dev_mode

_groups: dict = {}        # name -> {"order", "get", "step", "sel"}
_names: list = []
_active: int = 0


def reset() -> None:
    global _active
    _groups.clear()
    _names.clear()
    _active = 0


def register_group(name: str, order: tuple, get_dials: Callable[[], dict],
                   step: Callable[[str, int], None]) -> None:
    if not order:
        raise ValueError("dial group %r has no dials" % (name,))
    if name not in _groups:
        _names.append(name)
    _groups[name] = {"order": tuple(order), "get": get_dials, "step": step,
                     "sel": 0}


def groups() -> tuple:
    return tuple(_names)


def active() -> str:
    return _names[_active] if _names else ""


def cycle_active() -> str:
    global _active
    if _names:
        _active = (_active + 1) % len(_names)
        _report()
    return active()


def _group():
    return _groups.get(active())


def selected() -> str:
    grp = _group()
    return grp["order"][grp["sel"]] if grp else ""


def cycle_dial() -> None:
    grp = _group()
    if grp is None:
        return
    grp["sel"] = (grp["sel"] + 1) % len(grp["order"])
    _report()


def push(direction: int) -> None:
    grp = _group()
    if grp is None:
        return
    grp["step"](selected(), direction)
    _report()


def _report() -> None:
    grp = _group()
    if grp is not None:
        print("[%s dials] selected=%s %s" % (active(), selected(), grp["get"]()))


def register_keys(_h) -> None:
    """Claim / L O once at boot (gated on dev_mode by the caller)."""
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_SLASH, cycle_dial,
        "Dev dials: select next dial in the active group (dev) - /")
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_L, lambda: push(-1),
        "Dev dials: selected dial down (dev) - L")
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_O, lambda: push(+1),
        "Dev dials: selected dial up (dev) - O")
```

- [ ] **Step 4: Rewire `dev_nebula_dials.register`**

In `engine/dev_nebula_dials.py`:
- Delete `_selected`, `selected()`, `_cycle()` and `_report()`.
- Keep `_push(direction)`, but change its signature to `_step(name: str, direction: int)`. It sets `_dials = step(_dials, name, direction)` and pushes `_native(_dials)`; it does not print.
- Replace `register` with:

```python
def register(_h) -> None:
    """Register the nebula dial group and the shared / L O keys. Call once at
    boot, gated on dev_mode.is_enabled() (engine/host_loop.py run())."""
    from engine import dev_dial_groups
    dev_dial_groups.register_group("nebula", DIAL_ORDER, current, _step)
    dev_dial_groups.register_keys(_h)
```

Update the module docstring's key paragraph to say the keys now live in
`engine/dev_dial_groups.py` and act on the active group. Then update
`tests/unit/test_dev_nebula_dials.py` wherever it called `_cycle`, `_push` or
`selected()`: use `dev_dial_groups.cycle_dial()` / `push(±1)` /
`dev_dial_groups.selected()` after calling `register` with a fake `_h`, and keep
every value assertion unchanged.

- [ ] **Step 5: Update the key-collision test**

In `tests/unit/test_dev_key_collisions.py`:
- Add `_ROOT / "engine" / "dev_dial_groups.py"` to `_DEV_KEYBINDING_FILES`.
- Change the two tests that select `dev_nebula_dials.py` by name (lines ~213–260) to select `dev_dial_groups.py` instead. The keys are registered there now, and the assertions about `/ L O` stay the same.

Run: `uv run pytest tests/unit/test_dev_key_collisions.py tests/unit/test_dev_nebula_dials.py -q`
Expected: PASS.

- [ ] **Step 6: Add the Developer Options "Dial keys" row**

In `engine/ui/developer_options_panel.py`:
- `__init__`: `self._dial_group = dev_dial_groups.active() or "nebula"` (import `engine.dev_dial_groups as dev_dial_groups`).
- `open()`: re-read `self._dial_group = dev_dial_groups.active() or "nebula"`.
- `render_payload` snapshot tuple: append `self._dial_group`. Settings dict: `"dial_group": self._dial_group`.
- `dispatch_event`: `if action == "action:dial_group": self._dial_group = dev_dial_groups.cycle_active() or "nebula"; return True`.
- `_focusables` Lighting list: append `("ctrl", "dial_group")`.

In `native/assets/ui-cef/js/developer_options.js`, after the
`rock_catalogue` toggle row, add an action row in the existing
`normal_strength` style (a cycling value button). It is labelled
`'Dial keys (/ L O act on)'`, shows `s.dial_group`, sends
`action:dial_group`, and is focusable under `'dial_group'`. Mirror exactly how
`normal_strength` is rendered and focused in that file.

Add to `tests/unit/test_developer_options_panel.py` (or the existing panel test
file that holds `test_every_setting_is_in_the_render_snapshot`):

```python
def test_dial_group_row_cycles_active_group():
    import engine.dev_dial_groups as g
    g.reset()
    g.register_group("nebula", ("veil",), lambda: {}, lambda n, d: None)
    g.register_group("minors", ("halo_outer",), lambda: {}, lambda n, d: None)
    from engine.ui.developer_options_panel import DeveloperOptionsPanel
    p = DeveloperOptionsPanel()
    p.open()
    assert p.dispatch_event("action:dial_group") is True
    assert g.active() == "minors"
    assert '"dial_group": "minors"' in p.render_payload()
    g.reset()
```

(Use the panel's real class name from the file.)

- [ ] **Step 7: Add the conftest autouse reset**

In `tests/conftest.py` `_reset_leakable_engine_globals`, beside the
rock-catalogue reset (~line 1487), add:

```python
    # Dev dial groups (minor-rocks spec §5): a test that registers a group
    # would otherwise leave every later test's / L O acting on it.
    try:
        import engine.dev_dial_groups as _ddg
        _ddg.reset()
    except Exception:
        pass
```

- [ ] **Step 8: Run the affected suites**

Run: `uv run pytest tests/unit/test_dev_dial_groups.py tests/unit/test_dev_key_collisions.py tests/unit/test_dev_nebula_dials.py tests/unit -q -k "developer_options or dial"`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add engine/dev_dial_groups.py engine/dev_nebula_dials.py engine/ui/developer_options_panel.py native/assets/ui-cef/js/developer_options.js tests/unit/test_dev_dial_groups.py tests/unit/test_dev_key_collisions.py tests/unit/test_dev_nebula_dials.py tests/conftest.py tests/unit/test_developer_options_panel.py
git commit -m "feat(dev): dial-group registry shares / L O between nebula and future groups"
```

(Stage the panel test file you actually edited.)

---

### Task 3: Minor dials module

**Files:**
- Create: `engine/rocks/minor_dials.py`
- Modify: `tests/conftest.py` (autouse reset)
- Test: `tests/unit/test_minor_dials.py` (create)

**Interfaces:**
- Produces, in `engine/rocks/minor_dials.py`:
  - `DEFAULTS: dict`
  - `NATIVE_KEYS: frozenset`
  - `DIAL_ORDER: tuple`
  - `FAMILY_INDEX: dict`
  - `get(name) -> float`
  - `current() -> dict`
  - `native() -> dict`
  - `step(dials, name, direction) -> dict` (pure)
  - `set_on_change(fn: Callable[[set], None])`
  - `register() -> None` (registers group `"minors"`)
  - `reset() -> None`
- `set_on_change` receives the set of changed dial names. Task 9 wires it to
  rebuild clouds when a Python-owned shape dial changes, and to push
  `native()` when a native dial changes.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_minor_dials.py
import pytest

from engine.rocks import minor_dials as md


@pytest.fixture(autouse=True)
def _fresh():
    md.reset()
    yield
    md.reset()


def test_spec_defaults():
    d = md.DEFAULTS
    assert d["halo_inner"] == 1.1 and d["halo_outer"] == 3.0
    assert d["halo_min"] == 12 and d["halo_max"] == 400
    assert d["halo_r_min_gu"] == 0.03 and d["halo_r_max_frac"] == 0.15
    assert d["halo_r_max_gu"] == 1.0
    assert d["tile_count_mult"] == 1.0 and d["tile_r_min_gu"] == 0.05
    assert d["tile_r_per_size_factor"] == 0.1
    assert d["max_debris_per_death"] == 40 and d["max_live_minors"] == 20000
    assert d["min_pixel_radius"] == 1.5 and d["lod0_pixel_radius"] == 24.0
    assert d["contact_margin_gu"] == 0.1 and d["shove_transfer"] == 0.6
    assert d["shove_min_gu"] == 0.3 and d["shove_damp_seconds"] == 4.0
    assert d["max_shoves_per_frame"] == 64 and d["teleport_gu"] == 20000.0
    assert d["debris_damp_seconds"] == 6.0
    assert d["cloud_fade_in_seconds"] == 1.5
    assert d["free_cloud_fade_seconds"] == 2.0
    assert d["puff_max_per_s"] == 6 and d["grit_max_per_s"] == 4
    assert d["flicker_max_per_s"] == 2 and d["flicker_intensity"] == 0.3


def test_native_keys_are_a_subset_and_native_filters():
    assert md.NATIVE_KEYS <= set(md.DEFAULTS)
    assert set(md.native()) == md.NATIVE_KEYS


def test_every_dial_is_in_the_cycle_order():
    assert set(md.DIAL_ORDER) == set(md.DEFAULTS)


def test_step_is_pure_and_multiplicative_for_floats():
    d0 = md.current()
    d1 = md.step(d0, "halo_outer", +1)
    assert d0["halo_outer"] == 3.0
    assert d1["halo_outer"] == pytest.approx(3.0 * 1.25)


def test_step_counts_are_ints_and_clamped():
    d = md.step(md.current(), "halo_min", -1)
    assert isinstance(d["halo_min"], int) and d["halo_min"] >= 0
    d = md.current()
    for _ in range(50):
        d = md.step(d, "max_shoves_per_frame", -1)
    assert d["max_shoves_per_frame"] >= 1


def test_registered_group_steps_and_notifies():
    import engine.dev_dial_groups as g
    g.reset()
    seen = []
    md.set_on_change(lambda names: seen.append(names))
    md.register()
    assert "minors" in g.groups()
    while g.active() != "minors":
        g.cycle_active()
    g.push(+1)
    assert seen == [{md.DIAL_ORDER[0]}]
    assert md.get(md.DIAL_ORDER[0]) != md.DEFAULTS[md.DIAL_ORDER[0]]
    g.reset()


def test_family_index():
    assert md.FAMILY_INDEX == {"silicate": 0, "carbonaceous": 1,
                               "icy": 2, "metallic": 3}
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/test_minor_dials.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `engine/rocks/minor_dials.py`**

```python
"""Every minor-rock number in one place (minor-rocks spec §5).

Python-owned dials are read at use by engine/rocks/minors.py and
engine/rocks/minor_contact.py; a count / shell / size change rebuilds the
viewed set's clouds. NATIVE_KEYS go to the native MinorField as one dict
(renderer.minors_set_dials). Not persisted; tuned live through the shared
/ L O keys once Developer Options -> Lighting -> "Dial keys" selects
"minors" (engine/dev_dial_groups.py).
"""
from typing import Callable, Optional

FAMILY_INDEX = {"silicate": 0, "carbonaceous": 1, "icy": 2, "metallic": 3}

DEFAULTS: dict = {
    # §1 halo
    "halo_inner": 1.1, "halo_outer": 3.0, "halo_falloff": 1.0,
    "halo_per_gu2": 8.0, "halo_min": 12, "halo_max": 400,
    "halo_r_min_gu": 0.03, "halo_r_max_frac": 0.15, "halo_r_max_gu": 1.0,
    "halo_size_exponent": 2.5, "halo_orbit_rate": 0.02,
    # §1 tile field
    "tile_count_mult": 1.0, "tile_r_min_gu": 0.05,
    "tile_r_per_size_factor": 0.1, "tile_size_exponent": 2.5,
    "tile_orbit_rate": 0.0,
    # §1 budget
    "max_live_minors": 20000, "free_cloud_fade_seconds": 2.0,
    # §2 render (native)
    "min_pixel_radius": 1.5, "lod0_pixel_radius": 24.0,
    "tumble_min": 0.05, "tumble_max": 0.6,
    "cloud_fade_in_seconds": 1.5,
    # §3 contact (native)
    "contact_margin_gu": 0.1, "shove_transfer": 0.6, "shove_min_gu": 0.3,
    "shove_damp_seconds": 4.0, "shove_tumble": 1.5,
    "max_shoves_per_frame": 64, "teleport_gu": 20000.0,
    "contact_cooldown_s": 0.5,
    # §3 responses (Python)
    "puff_min_radius_gu": 0.1, "puff_spark_count": 6, "puff_max_per_s": 6,
    "grit_volume": 0.25, "grit_max_per_s": 4,
    "flicker_intensity": 0.3, "flicker_radius": 0.05, "flicker_max_per_s": 2,
    # §4 breakup debris
    "debris_gravel_per_gu": 4.0, "debris_gravel_r_min_gu": 0.03,
    "debris_gravel_r_max_gu": 0.3, "max_debris_per_death": 40,
    "debris_damp_seconds": 6.0,
}

NATIVE_KEYS = frozenset({
    "min_pixel_radius", "lod0_pixel_radius", "tumble_min", "tumble_max",
    "cloud_fade_in_seconds", "contact_margin_gu", "shove_transfer",
    "shove_min_gu", "shove_damp_seconds", "shove_tumble",
    "max_shoves_per_frame", "teleport_gu", "contact_cooldown_s",
    "debris_damp_seconds",
})

DIAL_ORDER: tuple = tuple(DEFAULTS)
_FACTOR = 1.25

_dials: dict = dict(DEFAULTS)
_on_change: Optional[Callable[[set], None]] = None


def reset() -> None:
    global _dials, _on_change
    _dials = dict(DEFAULTS)
    _on_change = None


def get(name: str):
    return _dials[name]


def current() -> dict:
    return dict(_dials)


def native() -> dict:
    return {k: _dials[k] for k in NATIVE_KEYS}


def step(dials: dict, name: str, direction: int) -> dict:
    """Pure. Ints step by ±1 (±10% when ≥ 10), floor 0 (1 for per-frame
    caps); floats ×/÷ 1.25, and a float at 0 steps to 0.01 going up."""
    if name not in dials:
        raise ValueError("unknown minor dial: %r" % (name,))
    out = dict(dials)
    v = out[name]
    if isinstance(v, int):
        delta = max(1, abs(v) // 10)
        floor = 1 if name in ("max_shoves_per_frame", "max_debris_per_death",
                              "max_live_minors") else 0
        out[name] = max(floor, v + direction * delta)
    elif v == 0.0:
        out[name] = 0.01 if direction > 0 else 0.0
    else:
        out[name] = v * _FACTOR if direction > 0 else v / _FACTOR
    return out


def set_on_change(fn: Optional[Callable[[set], None]]) -> None:
    global _on_change
    _on_change = fn


def _step(name: str, direction: int) -> None:
    global _dials
    _dials = step(_dials, name, direction)
    if _on_change is not None:
        _on_change({name})


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("minors", DIAL_ORDER, current, _step)
```

- [ ] **Step 4: Add the conftest reset**

Beside the Task 2 reset in `tests/conftest.py`:

```python
    try:
        from engine.rocks import minor_dials as _md
        _md.reset()
    except Exception:
        pass
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_minor_dials.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/rocks/minor_dials.py tests/unit/test_minor_dials.py tests/conftest.py
git commit -m "feat(minors): minor_dials -- every minor-rock number as a dial"
```

---

### Task 4: `MinorField` cloud generation (C++, no GL)

**Files:**
- Create:
  - `native/src/renderer/include/renderer/minor_field.h`
  - `native/src/renderer/minor_field.cc`
  - `native/tests/renderer/minor_field_test.cc`
- Modify:
  - `native/src/renderer/CMakeLists.txt`: add `minor_field.cc` beside `dust_pass.cc`
  - `native/tests/renderer/CMakeLists.txt`: add `minor_field_test.cc` to `renderer_tests`

**Interfaces:**
- Produces (namespace `renderer::minors`). Tasks 5–8 rely on these names
  exactly:

```cpp
enum class Anchor : std::uint8_t { Instance, Point, Free };

struct DebrisSpec {            // a breakup minor (Free clouds only)
    glm::vec3 offset{0.0f};    // GU, relative to the cloud anchor at t0
    glm::vec3 v0{0.0f};        // GU/s outward, decays (debris_damp_seconds)
    float radius = 0.1f;       // GU
    std::uint32_t seed = 0;
};

struct CloudDesc {
    std::uint32_t id = 0;
    Anchor anchor = Anchor::Point;
    std::uint64_t instance_key = 0;      // Anchor::Instance: (index<<32)|generation
    glm::dvec3 point{0.0};               // VIEW space: Point position / Free p0
    glm::vec3 velocity{0.0f};            // Free: GU/s
    double t0 = 0.0;                     // Free: game time of p0
    float shell_inner = 0.0f, shell_outer = 1.0f, falloff = 0.0f;
    int count = 0;
    float r_min = 0.05f, r_max = 0.5f, size_exponent = 2.5f;
    int family = 0;
    std::uint32_t seed = 0;
    float orbit_rate = 0.0f;             // rad/s
    bool fade_in = false;
    std::vector<DebrisSpec> debris;
};

struct Minor {                 // one generated instance (immutable after build)
    glm::vec3 offset{0.0f};    // cloud-local GU (orbit/halo/tile); debris: start
    glm::vec3 v0{0.0f};        // debris only
    float radius = 0.1f;       // GU
    glm::vec3 tumble_axis{0.0f, 0.0f, 1.0f};
    float tumble_u = 0.0f;     // [0,1): rate = mix(tumble_min, tumble_max, u)
    float phase = 0.0f;        // initial rotation angle, radians
    float orbit_u = 1.0f;      // [0.5,1]: orbit rate factor
    std::uint32_t mesh_u = 0;  // mesh slot = mesh_u % fragment count
    bool debris = false;
};

std::vector<Minor> generate(const CloudDesc& d);   // deterministic, pure
```

- [ ] **Step 1: Write the failing tests**

```cpp
// native/tests/renderer/minor_field_test.cc
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <renderer/minor_field.h>

using namespace renderer::minors;

namespace {
CloudDesc halo(std::uint32_t seed = 7) {
    CloudDesc d;
    d.id = 1; d.anchor = Anchor::Point; d.seed = seed;
    d.shell_inner = 1.1f * 4.0f; d.shell_outer = 3.0f * 4.0f; d.falloff = 1.0f;
    d.count = 200; d.r_min = 0.03f; d.r_max = 0.6f; d.size_exponent = 2.5f;
    return d;
}
}  // namespace

TEST(MinorGenerate, DeterministicPerSeed) {
    auto a = generate(halo(7)), b = generate(halo(7)), c = generate(halo(8));
    ASSERT_EQ(a.size(), 200u);
    for (std::size_t i = 0; i < a.size(); ++i) {
        EXPECT_EQ(a[i].offset, b[i].offset);
        EXPECT_EQ(a[i].radius, b[i].radius);
        EXPECT_EQ(a[i].mesh_u, b[i].mesh_u);
    }
    EXPECT_NE(a[0].offset, c[0].offset);
}

TEST(MinorGenerate, InsideShellAndRadiusRange) {
    const auto d = halo();
    for (const auto& m : generate(d)) {
        const float r = glm::length(m.offset);
        EXPECT_GE(r, d.shell_inner - 1e-4f);
        EXPECT_LE(r, d.shell_outer + 1e-4f);
        EXPECT_GE(m.radius, d.r_min - 1e-6f);
        EXPECT_LE(m.radius, d.r_max + 1e-6f);
        EXPECT_NEAR(glm::length(m.tumble_axis), 1.0f, 1e-4f);
        EXPECT_GE(m.orbit_u, 0.5f); EXPECT_LE(m.orbit_u, 1.0f);
    }
}

TEST(MinorGenerate, FalloffPullsMinorsInward) {
    auto d0 = halo(); d0.falloff = 0.0f; d0.count = 4000;
    auto d1 = halo(); d1.falloff = 2.0f; d1.count = 4000;
    double m0 = 0, m1 = 0;
    for (const auto& m : generate(d0)) m0 += glm::length(m.offset);
    for (const auto& m : generate(d1)) m1 += glm::length(m.offset);
    EXPECT_LT(m1 / 4000.0, m0 / 4000.0 - 0.3);
}

TEST(MinorGenerate, PowerLawFavoursSmallRadii) {
    auto d = halo(); d.count = 4000;
    int small = 0;
    const float mid = 0.5f * (d.r_min + d.r_max);
    for (const auto& m : generate(d)) small += m.radius < mid ? 1 : 0;
    EXPECT_GT(small, 3000);    // well over half below the midpoint
}

TEST(MinorGenerate, UniformSphereWhenInnerZeroAndNoFalloff) {
    CloudDesc d; d.seed = 3; d.shell_inner = 0; d.shell_outer = 100;
    d.count = 8000; d.r_min = 0.05f; d.r_max = 0.7f;
    int inner_half = 0;        // r < R/2 holds 1/8 of a uniform sphere
    for (const auto& m : generate(d)) inner_half += glm::length(m.offset) < 50 ? 1 : 0;
    EXPECT_NEAR(inner_half / 8000.0, 0.125, 0.02);
}

TEST(MinorGenerate, DebrisAppendedVerbatim) {
    CloudDesc d; d.anchor = Anchor::Free; d.count = 10;
    d.debris = {{{1, 0, 0}, {0.8f, 0, 0}, 0.4f, 11}, {{0, 1, 0}, {0, 0.8f, 0}, 0.2f, 12}};
    auto g = generate(d);
    ASSERT_EQ(g.size(), 12u);
    EXPECT_TRUE(g[10].debris);
    EXPECT_EQ(g[10].offset, glm::vec3(1, 0, 0));
    EXPECT_EQ(g[10].v0, glm::vec3(0.8f, 0, 0));
    EXPECT_FLOAT_EQ(g[11].radius, 0.2f);
}

TEST(MinorGenerate, ZeroCountIsEmpty) {
    CloudDesc d; d.count = 0;
    EXPECT_TRUE(generate(d).empty());
}
```

- [ ] **Step 2: Wire the files into CMake, build and confirm the failure**

Add `minor_field.cc` to the renderer sources list in
`native/src/renderer/CMakeLists.txt` (next to `dust_pass.cc`, line ~157) and
`minor_field_test.cc` to `renderer_tests` in
`native/tests/renderer/CMakeLists.txt` (next to `dust_pass_test.cc`). Create an
empty `minor_field.cc` that includes the header.

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile errors (`generate` is undefined, or the header is missing).

- [ ] **Step 3: Implement the header and `generate`**

`native/src/renderer/include/renderer/minor_field.h`: write the declarations
from **Interfaces** above, plus the `#include`s `<glm/glm.hpp>`, `<cstdint>`
and `<vector>`, and a file comment pointing at the spec (§1, §2).

`native/src/renderer/minor_field.cc`:

```cpp
// native/src/renderer/minor_field.cc
// Minor rocks (docs/superpowers/specs/2026-10-01-minor-rocks-design.md).
#include "renderer/minor_field.h"

#include <cmath>

namespace renderer::minors {
namespace {

// splitmix64: deterministic, platform-independent (std::*_distribution is not).
struct Rng {
    std::uint64_t s;
    std::uint64_t next() {
        std::uint64_t z = (s += 0x9E3779B97F4A7C15ull);
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
        return z ^ (z >> 31);
    }
    float unit() { return static_cast<float>(next() >> 40) / 16777216.0f; }  // [0,1)
};

glm::vec3 unit_vector(Rng& r) {
    const float z = r.unit() * 2.0f - 1.0f;
    const float t = r.unit() * 6.28318530718f;
    const float s = std::sqrt(std::max(0.0f, 1.0f - z * z));
    return {s * std::cos(t), s * std::sin(t), z};
}

// Inverse CDF of pdf ∝ r^-a on [lo, hi].
float power_law(float u, float lo, float hi, float a) {
    if (hi <= lo) return lo;
    if (std::fabs(a - 1.0f) < 1e-4f)
        return lo * std::pow(hi / lo, u);
    const float e = 1.0f - a;
    const float l = std::pow(lo, e), h = std::pow(hi, e);
    return std::pow(l + u * (h - l), 1.0f / e);
}

}  // namespace

std::vector<Minor> generate(const CloudDesc& d) {
    std::vector<Minor> out;
    const int n = std::max(0, d.count);
    out.reserve(static_cast<std::size_t>(n) + d.debris.size());
    Rng rng{(static_cast<std::uint64_t>(d.seed) << 1) ^ 0xA57E401DULL};
    const float i3 = d.shell_inner * d.shell_inner * d.shell_inner;
    const float o3 = d.shell_outer * d.shell_outer * d.shell_outer;
    for (int i = 0; i < n; ++i) {
        Minor m;
        // Volume-uniform in the shell when falloff == 0; u^(1+falloff)
        // biases toward the inner surface.
        const float u = std::pow(rng.unit(), 1.0f + std::max(0.0f, d.falloff));
        const float dist = std::cbrt(i3 + (o3 - i3) * u);
        m.offset = unit_vector(rng) * dist;
        m.radius = power_law(rng.unit(), d.r_min, d.r_max, d.size_exponent);
        m.tumble_axis = unit_vector(rng);
        m.tumble_u = rng.unit();
        m.phase = rng.unit() * 6.28318530718f;
        m.orbit_u = 0.5f + 0.5f * rng.unit();
        m.mesh_u = static_cast<std::uint32_t>(rng.next() >> 32);
        out.push_back(m);
    }
    for (const auto& s : d.debris) {
        Rng dr{(static_cast<std::uint64_t>(s.seed) << 1) ^ 0xDEB815ULL};
        Minor m;
        m.offset = s.offset;
        m.v0 = s.v0;
        m.radius = s.radius;
        m.tumble_axis = unit_vector(dr);
        m.tumble_u = dr.unit();
        m.phase = dr.unit() * 6.28318530718f;
        m.orbit_u = 0.0f;                    // debris does not orbit
        m.mesh_u = static_cast<std::uint32_t>(dr.next() >> 32);
        m.debris = true;
        out.push_back(m);
    }
    return out;
}

}  // namespace renderer::minors
```

(Add `#include <algorithm>` for `std::max`.)

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='MinorGenerate.*'`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/minor_field.h native/src/renderer/minor_field.cc native/tests/renderer/minor_field_test.cc native/src/renderer/CMakeLists.txt native/tests/renderer/CMakeLists.txt
git commit -m "feat(minors): deterministic minor cloud generation (C++)"
```

---

### Task 5: `MinorField` step: anchors, motion, fades, cull, LOD bins

**Files:**
- Modify: `native/src/renderer/include/renderer/minor_field.h`, `native/src/renderer/minor_field.cc`
- Test: `native/tests/renderer/minor_field_test.cc`

**Interfaces:**
- Consumes: Task 4.
- Produces (Task 6 extends `StepInput` and `MinorField`; Tasks 7–8 consume
  these names):

```cpp
struct Dials {   // defaults MUST equal engine/rocks/minor_dials.py DEFAULTS
    float min_pixel_radius = 1.5f, lod0_pixel_radius = 24.0f;
    float tumble_min = 0.05f, tumble_max = 0.6f;
    float cloud_fade_in_seconds = 1.5f;
    float contact_margin_gu = 0.1f, shove_transfer = 0.6f, shove_min_gu = 0.3f;
    float shove_damp_seconds = 4.0f, shove_tumble = 1.5f;
    int   max_shoves_per_frame = 64;
    float teleport_gu = 20000.0f, contact_cooldown_s = 0.5f;
    float debris_damp_seconds = 6.0f;
};

struct Fragment { std::uint64_t lod0 = 0, lod1 = 0; float bound_radius_mu = 57.142857f; };

struct InstanceGpu { glm::vec4 row0, row1, row2; };   // rows of [R·s | t], render space

struct Bin { int family = 0; int slot = 0; int lod = 0; std::vector<InstanceGpu> items; };

using AnchorLookup = std::function<bool(std::uint64_t key, glm::vec3& out_render_pos)>;

struct StepInput {
    double game_time = 0.0;
    glm::dvec3 render_origin{0.0};
    glm::mat4 view{1.0f}, proj{1.0f};
    float viewport_h = 720.0f;
    AnchorLookup anchor_of;              // may be empty: Instance clouds then skip
};

struct Stats { int clouds = 0; int minors = 0; int drawn = 0; int bins = 0; };

class MinorField {
public:
    void set_dials(const Dials& d) { dials_ = d; }
    const Dials& dials() const { return dials_; }
    void set_fragments(int family, std::vector<Fragment> f);
    const std::vector<Fragment>& fragments(int family) const;
    void add_cloud(const CloudDesc& d, double now);   // replaces same id
    void remove_cloud(std::uint32_t id);
    // Instance -> Free, keeping instances and shove state; appends debris.
    void detach(std::uint32_t id, const glm::dvec3& p0_view, const glm::vec3& v,
                double t0, const std::vector<DebrisSpec>& debris);
    void fade_out(std::uint32_t id, float seconds, double now);
    void clear();
    void step(const StepInput& in);
    const std::vector<Bin>& bins() const { return bins_; }
    Stats stats() const { return stats_; }
    // Test hook: render-space centre of minor `i` of cloud `id` after the last step.
    bool minor_position(std::uint32_t id, std::size_t i, glm::vec3& out) const;
private:
    struct Shove { glm::vec3 offset{0.0f}, vel{0.0f}; float spin = 0.0f, spin_rate = 0.0f;
                   double last_contact = -1e9; };
    struct Cloud {
        CloudDesc desc; std::vector<Minor> minors;
        std::unordered_map<std::uint32_t, Shove> shoves;
        double born = 0.0; bool fading_in = false;
        double fade_out_start = -1.0; float fade_out_seconds = 0.0f;
        std::vector<glm::vec3> pos;    // last step, render space
        glm::vec3 anchor_render{0.0f}; bool anchor_ok = false;
    };
    Dials dials_;
    std::unordered_map<int, std::vector<Fragment>> fragments_;
    std::map<std::uint32_t, Cloud> clouds_;     // ordered: deterministic bins
    std::vector<Bin> bins_;
    Stats stats_;
    double last_time_ = -1.0;
};
```

Motion rules, all in `step`, with `t = in.game_time`:
- Anchor in render space:
  - Instance: `anchor_of(key)`. If it fails, the cloud is not drawn this frame.
  - Point: `vec3(point − render_origin)`.
  - Free: `vec3(point + velocity·(t − t0) − render_origin)`.
- Local offset:
  - Orbit minors: `rotate(orbit_axis, orbit_rate·orbit_u·t) · offset`. The
    `orbit_axis` is a unit vector derived from `desc.seed` with the same Rng.
  - Debris minors: `offset + v0·τ·(1 − exp(−max(0, t − t0)/τ))`, with
    `τ = debris_damp_seconds / ln 2`.
- Shove: add `shoves[i].offset` (Task 6 integrates it).
- Rotation: about `tumble_axis` by
  `phase + mix(tumble_min, tumble_max, tumble_u)·t + shove.spin`.
- Fade scale:
  - fade-in: `clamp((t − born)/cloud_fade_in_seconds, 0, 1)` while `fading_in`
  - fade-out: `1 − clamp((t − fade_out_start)/fade_out_seconds, 0, 1)` once
    `fade_out_start ≥ 0`
  - scale 0 means the minor is not drawn
- Cull:
  - frustum (planes of `proj·view`, sphere test with radius·scale)
  - then `pixel_r = r·scale·proj[1][1]·0.5·viewport_h / max(−z_view, 1e-3)`;
    skip below `min_pixel_radius`
  - `lod = pixel_r ≥ lod0_pixel_radius ? 0 : 1`
- Bin key `(family, mesh_u % fragments(family).size(), lod)`. A family with no
  fragments draws nothing.
  - Instance scale is
    `s = r·fade / (fragment.bound_radius_mu · 0.01)`.
  - `InstanceGpu` rows are `(R·s)` row `k` with the translation in `.w`.
- `stats_`:
  - `clouds`: the number of clouds
  - `minors`: the number of minors
  - `drawn`: the number of items across all bins
  - `bins`: the number of non-empty bins

- [ ] **Step 1: Write the failing tests** (append to `minor_field_test.cc`)

```cpp
#include <glm/gtc/matrix_transform.hpp>

namespace {
StepInput looking_down_minus_z(double t = 0.0) {
    StepInput in;
    in.game_time = t;
    in.view = glm::lookAt(glm::vec3(0, 0, 0), glm::vec3(0, 0, -1), glm::vec3(0, 1, 0));
    in.proj = glm::perspective(glm::radians(60.0f), 16.0f / 9.0f, 0.1f, 1e6f);
    in.viewport_h = 1080.0f;
    return in;
}
MinorField field_with_fragments() {
    MinorField f;
    f.set_fragments(0, {Fragment{1, 2, 57.142857f}, Fragment{3, 4, 57.142857f}});
    return f;
}
CloudDesc point_cloud(glm::dvec3 at, int count = 50) {
    CloudDesc d; d.id = 9; d.anchor = Anchor::Point; d.point = at;
    d.shell_inner = 0; d.shell_outer = 2; d.count = count;
    d.r_min = 0.3f; d.r_max = 0.3f; d.seed = 1;
    return d;
}
}  // namespace

TEST(MinorStep, PointCloudInViewIsDrawnAndBinned) {
    auto f = field_with_fragments();
    f.add_cloud(point_cloud({0, 0, -20}), 0.0);
    f.step(looking_down_minus_z());
    const auto s = f.stats();
    EXPECT_EQ(s.clouds, 1); EXPECT_EQ(s.minors, 50); EXPECT_EQ(s.drawn, 50);
    EXPECT_GE(s.bins, 1); EXPECT_LE(s.bins, 4);     // 2 slots x 2 lods
}

TEST(MinorStep, BehindCameraIsCulled) {
    auto f = field_with_fragments();
    f.add_cloud(point_cloud({0, 0, +20}), 0.0);
    f.step(looking_down_minus_z());
    EXPECT_EQ(f.stats().drawn, 0);
}

TEST(MinorStep, SubPixelIsCulledAndLodSwitchesWithDistance) {
    // pixel_r = r * proj[1][1] * 0.5 * viewport_h / depth, proj[1][1] = 1/tan(30deg) = 1.732
    // 0.3 GU at 5 GU    -> ~56 px  (lod0)
    // 0.3 GU at 100 GU  -> ~2.8 px (lod1)
    // 0.3 GU at 50k GU  -> ~0.006 px (culled)
    auto f = field_with_fragments();
    auto near = point_cloud({0, 0, -5}); near.id = 1;
    auto far = point_cloud({0, 0, -100}); far.id = 2;
    auto gone = point_cloud({0, 0, -50000}); gone.id = 3;
    f.add_cloud(near, 0); f.add_cloud(far, 0); f.add_cloud(gone, 0);
    f.step(looking_down_minus_z());
    int lod0 = 0, lod1 = 0;
    for (const auto& b : f.bins()) (b.lod == 0 ? lod0 : lod1) += int(b.items.size());
    EXPECT_EQ(lod0, 50);
    EXPECT_EQ(lod1, 50);
    EXPECT_EQ(f.stats().drawn, 100);
}
```

```cpp
TEST(MinorStep, RenderOriginIsSubtractedForPointAnchors) {
    auto f = field_with_fragments();
    f.add_cloud(point_cloud({1000, 0, -20}), 0.0);
    auto in = looking_down_minus_z();
    in.render_origin = glm::dvec3(1000, 0, 0);
    f.step(in);
    EXPECT_EQ(f.stats().drawn, 50);
}

TEST(MinorStep, InstanceAnchorFollowsLookupByTranslationOnly) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, 0}); d.anchor = Anchor::Instance; d.instance_key = 42;
    f.add_cloud(d, 0.0);
    glm::vec3 where(0, 0, -20);
    auto in = looking_down_minus_z();
    in.anchor_of = [&](std::uint64_t k, glm::vec3& out) { if (k != 42) return false; out = where; return true; };
    f.step(in);
    glm::vec3 p0; ASSERT_TRUE(f.minor_position(9, 0, p0));
    where = glm::vec3(5, 0, -20);
    f.step(in);
    glm::vec3 p1; ASSERT_TRUE(f.minor_position(9, 0, p1));
    EXPECT_NEAR(p1.x - p0.x, 5.0f, 1e-4f);
}

TEST(MinorStep, MissingInstanceAnchorDrawsNothing) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, -20}); d.anchor = Anchor::Instance; d.instance_key = 1;
    f.add_cloud(d, 0.0);
    auto in = looking_down_minus_z();
    in.anchor_of = [](std::uint64_t, glm::vec3&) { return false; };
    f.step(in);
    EXPECT_EQ(f.stats().drawn, 0);
}

TEST(MinorStep, FreeCloudMovesAnalytically) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, -20}); d.anchor = Anchor::Free;
    d.velocity = glm::vec3(1, 0, 0); d.t0 = 10.0;
    f.add_cloud(d, 10.0);
    f.step(looking_down_minus_z(10.0));
    glm::vec3 a; f.minor_position(9, 0, a);
    f.step(looking_down_minus_z(13.0));
    glm::vec3 b; f.minor_position(9, 0, b);
    EXPECT_NEAR(b.x - a.x, 3.0f, 1e-3f);
}

TEST(MinorStep, DebrisDecaysToAFiniteSpread) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, -20}, 0); d.anchor = Anchor::Free; d.t0 = 0.0;
    d.debris = {{{0, 0, 0}, {1, 0, 0}, 0.3f, 5}};
    f.add_cloud(d, 0.0);
    const float tau = 6.0f / std::log(2.0f);
    f.step(looking_down_minus_z(1000.0));
    glm::vec3 p; f.minor_position(9, 0, p);
    EXPECT_NEAR(p.x, tau, 1e-2f);                  // v0·τ at t → ∞
    // Matches a fine step-by-step integration of v = v0·0.5^(t/h):
    double x = 0, v = 1, dt = 1e-3;
    for (int i = 0; i < 6000; ++i) { x += v * dt; v *= std::pow(0.5, dt / 6.0); }
    f.step(looking_down_minus_z(6.0));
    f.minor_position(9, 0, p);
    EXPECT_NEAR(p.x, float(x), 2e-3f);
}

TEST(MinorStep, OrbitKeepsDistanceFromAnchor) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, -20}); d.orbit_rate = 0.5f;
    f.add_cloud(d, 0.0);
    f.step(looking_down_minus_z(0.0));
    glm::vec3 a; f.minor_position(9, 3, a);
    f.step(looking_down_minus_z(7.0));
    glm::vec3 b; f.minor_position(9, 3, b);
    const glm::vec3 c(0, 0, -20);
    EXPECT_NEAR(glm::length(a - c), glm::length(b - c), 1e-3f);
    EXPECT_GT(glm::length(a - b), 1e-3f);
}

TEST(MinorStep, FadeInScalesFromZero) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, -20}); d.fade_in = true;
    f.add_cloud(d, 5.0);
    f.step(looking_down_minus_z(5.0));
    EXPECT_EQ(f.stats().drawn, 0);                 // scale 0 at birth
    f.step(looking_down_minus_z(5.0 + 1.5));
    EXPECT_EQ(f.stats().drawn, 50);
}

TEST(MinorStep, FadeOutReachesZero) {
    auto f = field_with_fragments();
    f.add_cloud(point_cloud({0, 0, -20}), 0.0);
    f.fade_out(9, 2.0f, 1.0);
    f.step(looking_down_minus_z(3.5));
    EXPECT_EQ(f.stats().drawn, 0);
}

TEST(MinorStep, DetachKeepsMinorsAndTurnsFree) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, 0}); d.anchor = Anchor::Instance; d.instance_key = 7;
    f.add_cloud(d, 0.0);
    auto in = looking_down_minus_z(0.0);
    in.anchor_of = [](std::uint64_t, glm::vec3& o) { o = {0, 0, -20}; return true; };
    f.step(in);
    glm::vec3 before; f.minor_position(9, 0, before);
    f.detach(9, glm::dvec3(0, 0, -20), glm::vec3(0), 0.0, {{{0, 0, 0}, {0, 0, 0}, 0.2f, 1}});
    in.anchor_of = nullptr;                        // rock gone
    f.step(in);
    glm::vec3 after; ASSERT_TRUE(f.minor_position(9, 0, after));
    EXPECT_NEAR(glm::length(after - before), 0.0f, 1e-4f);
    EXPECT_EQ(f.stats().minors, 51);
}

TEST(MinorStep, NoFragmentsDrawsNothing) {
    MinorField f;
    f.add_cloud(point_cloud({0, 0, -20}), 0.0);
    f.step(looking_down_minus_z());
    EXPECT_EQ(f.stats().drawn, 0);
}

TEST(MinorStep, InstanceScaleDrawsAtMinorRadius) {
    auto f = field_with_fragments();
    f.add_cloud(point_cloud({0, 0, -20}, 1), 0.0);
    f.step(looking_down_minus_z());
    ASSERT_FALSE(f.bins().empty());
    const auto& g = f.bins()[0].items[0];
    const float s = glm::length(glm::vec3(g.row0.x, g.row1.x, g.row2.x));
    EXPECT_NEAR(s * 57.142857f * 0.01f, 0.3f, 1e-4f);
}
```

- [ ] **Step 2: Build and confirm the failure** (the API is missing).

- [ ] **Step 3: Implement**

Extend the header with the **Interfaces** block (include `<functional>`,
`<map>`, `<unordered_map>`) and implement `MinorField` in `minor_field.cc` to
the motion rules above:
- `add_cloud` regenerates the minors with `generate(d)`, sets
  `born = now` and `fading_in = d.fade_in`, and clears the shoves.
- `remove_cloud` erases.
- `detach`:
  - sets the anchor to Free with `point = p0_view`, `velocity = v`, `t0`;
  - appends `generate`d debris minors (a desc with `count = 0` and only
    `debris`) to `minors`;
  - re-bases every existing orbit minor so its position is continuous: store
    the anchor-relative position at detach time as its new `offset`, set
    `orbit_u = 0`, and keep the shoves.
- `fade_out` records the start and duration.
- `clear()` drops everything.

Frustum planes: extract the six planes from `M = proj·view` with
Gribb–Hartmann (rows `M[0..3]` as `glm::row(M, i)`), normalise them, and test
`dot(n, p) + d ≥ −r`.

Axis-angle rotation: `glm::mat3(glm::rotate(glm::mat4(1), angle, axis))`
(include `<glm/gtc/matrix_transform.hpp>`).

The orbit axis per cloud comes from
`Rng{desc.seed * 2654435761u}`, then `unit_vector`. That Rng and
`unit_vector` live in the anonymous namespace; reuse them.

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='Minor*'`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/minor_field.h native/src/renderer/minor_field.cc native/tests/renderer/minor_field_test.cc
git commit -m "feat(minors): MinorField step -- anchors, orbit, debris decay, fades, cull, LOD bins"
```

---

### Task 6: Player contact and shove (C++)

**Files:**
- Modify: `minor_field.h`, `minor_field.cc`
- Test: `native/tests/renderer/minor_field_test.cc`

**Interfaces:**
- Produces:

```cpp
struct PlayerBox {
    glm::mat4 world{1.0f};        // RENDER-space instance world (incl. scale)
    glm::vec3 center_mu{0.0f};    // model-space AABB centre
    glm::vec3 half_mu{1.0f};      // model-space AABB half extents
};
struct Contact { glm::dvec3 point_view{0.0}; float radius = 0.0f; float rel_speed = 0.0f; };
// StepInput gains:   std::optional<PlayerBox> player;
// MinorField gains:  std::vector<Contact> drain_contacts();
//                    void reset_player();   // forget the previous pose
```

Rules (spec §3), evaluated in `step` after the minor positions and before
culling, and only when `in.player` is set:
- `dt = game_time − last_time_`. When `dt ≤ 0` (paused, or the first frame),
  there is no contact and no shove integration, but the previous pose is still
  recorded.
- **OBB:** centre `c = world · center_mu`, axes `aᵢ = normalize(col i of world)`,
  half `hᵢ = |col i| · half_muᵢ + contact_margin_gu`, and
  `bound = |h|` (the box's bounding radius).
- **The previous centre is kept in VIEW space** (`c + render_origin`). This
  frame's `prev_render = prev_view − render_origin`.
- `travel = |c − prev_render|`. If `travel > teleport_gu` or there is no
  previous pose, the segment collapses to `c` (no sweep).
- `v_player = (c − prev_render)/dt` (zero on a teleport).
- **Cloud reject:** the cloud's anchor sphere, of radius
  `shell_outer + r_max + 10`, extended by every shove's offset length. For a
  Free cloud, use the max debris extent instead
  (`|offset| + |v0|·τ + radius`). Skip the cloud when that sphere is farther
  than its radius plus `bound` from the segment.
- **Minor reject:** skip the minor when its distance to the segment is greater
  than `radius + bound`.
- **Fine test:**
  - Sub-steps: `n = clamp(ceil(travel / max(min hᵢ, 0.05)), 1, 32)`, with the
    centre lerped along the segment and the orientation taken from this frame.
  - Find the closest point `q` on the OBB to the minor centre `p`. It is a hit
    when `|p − q| ≤ radius`, or when `p` is inside the box (`q == p`).
  - Normal `n = normalize(p − q)`. If `p` is inside, use
    `normalize(p − centre_k)`, and if that is degenerate, `a₁`.
- **On a hit**, if fewer than `max_shoves_per_frame` touches have happened
  this frame:
  - de-penetrate: add `n·(radius − |p − q|)` to `shove.offset`, so the minor
    sits on the surface
  - shove: `shove.vel = n · (max(dot(v_player, n), 0) · shove_transfer + shove_min_gu)`
  - spin: `shove.spin_rate += shove_tumble`
  - if `t − shove.last_contact ≥ contact_cooldown_s`, push a `Contact{q + render_origin, radius, |v_player|}` and set `last_contact = t`
- **Integration** (every step with `dt > 0`, for every shoved minor):
  - `offset += vel·dt`
  - `vel *= 0.5^(dt/shove_damp_seconds)`
  - `spin += spin_rate·dt`
  - `spin_rate *= 0.5^(dt/shove_damp_seconds)`
- `reset_player()` clears the previous pose. `add_cloud` on an existing id
  clears that cloud's shoves.

- [ ] **Step 1: Write the failing tests**

```cpp
namespace {
PlayerBox box_at(glm::vec3 p, glm::vec3 half_mu = {50, 100, 30}) {
    PlayerBox b;
    b.world = glm::translate(glm::mat4(1.0f), p) * glm::scale(glm::mat4(1.0f), glm::vec3(0.01f));
    b.half_mu = half_mu;                    // 0.5 x 1.0 x 0.3 GU at scale 0.01
    return b;
}
CloudDesc single_minor_at(glm::dvec3 at, float r = 0.2f) {
    CloudDesc d; d.id = 5; d.anchor = Anchor::Point; d.point = at;
    d.shell_inner = 0; d.shell_outer = 0; d.count = 1; d.r_min = d.r_max = r; d.seed = 2;
    return d;
}
}  // namespace

TEST(MinorContact, SweptBoxHitsAMinorAPointTestWouldMiss) {
    auto f = field_with_fragments();
    f.add_cloud(single_minor_at({0, 0, -20}), 0.0);
    auto in = looking_down_minus_z(0.0);
    in.player = box_at({0, -100, -20});
    f.step(in);
    in.game_time = 1.0 / 60.0;                 // 10,000 GU/s: 166 GU per frame
    in.player = box_at({0, +66, -20});
    f.step(in);
    const auto c = f.drain_contacts();
    ASSERT_EQ(c.size(), 1u);
    EXPECT_NEAR(c[0].rel_speed, 166.0f * 60.0f, 50.0f);
}

TEST(MinorContact, ShoveIsOutwardAndOffsetPersists) {
    auto f = field_with_fragments();
    f.add_cloud(single_minor_at({0.6, 0, -20}), 0.0);
    auto in = looking_down_minus_z(0.0);
    in.player = box_at({-2, 0, -20});
    f.step(in);
    in.game_time = 0.1;
    in.player = box_at({0.3, 0, -20});         // moving +x into the minor
    f.step(in);
    ASSERT_EQ(f.drain_contacts().size(), 1u);
    glm::vec3 p1; f.minor_position(5, 0, p1);
    EXPECT_GT(p1.x, 0.6f);
    in.player = box_at({0.3, 0, -20});
    for (int i = 0; i < 600; ++i) { in.game_time += 0.1; f.step(in); }   // 60 s
    glm::vec3 p2; f.minor_position(5, 0, p2);
    EXPECT_GT(p2.x, p1.x);                      // drifted further out
    glm::vec3 p3; in.game_time += 60.0; f.step(in); f.minor_position(5, 0, p3);
    EXPECT_NEAR(p3.x, p2.x, 0.05f);             // velocity has decayed; offset stays
}

TEST(MinorContact, VelocityHalvesAtTheHalfLife) {
    auto f = field_with_fragments();
    f.add_cloud(single_minor_at({0.6, 0, -20}), 0.0);
    auto in = looking_down_minus_z(0.0);
    in.player = box_at({-2, 0, -20}); f.step(in);
    in.game_time = 0.1; in.player = box_at({0.3, 0, -20}); f.step(in);
    in.player = box_at({-50, 0, -20});          // back off, then measure drift
    in.game_time = 0.2; f.step(in);
    glm::vec3 a; f.minor_position(5, 0, a);
    in.game_time = 0.3; f.step(in);
    glm::vec3 b; f.minor_position(5, 0, b);
    in.game_time = 4.2; f.step(in);
    glm::vec3 c; f.minor_position(5, 0, c);
    in.game_time = 4.3; f.step(in);
    glm::vec3 d; f.minor_position(5, 0, d);
    EXPECT_NEAR((d.x - c.x) / (b.x - a.x), 0.5f, 0.02f);
}

TEST(MinorContact, ShoveCapPerFrameHolds) {
    auto f = field_with_fragments();
    CloudDesc d; d.id = 1; d.anchor = Anchor::Point; d.point = {0, 0, -20};
    d.shell_inner = 0; d.shell_outer = 0.4f; d.count = 500; d.r_min = d.r_max = 0.05f;
    f.add_cloud(d, 0.0);
    auto dials = f.dials(); dials.contact_cooldown_s = 0.0f; f.set_dials(dials);
    auto in = looking_down_minus_z(0.0);
    in.player = box_at({0, -10, -20}); f.step(in);
    in.game_time = 0.1; in.player = box_at({0, 0, -20}); f.step(in);
    EXPECT_EQ(f.drain_contacts().size(), 64u);
}

TEST(MinorContact, CooldownLimitsRepeatContactsFromOneMinor) {
    auto f = field_with_fragments();
    f.add_cloud(single_minor_at({0, 0, -20}), 0.0);
    auto in = looking_down_minus_z(0.0);
    in.player = box_at({0, -2, -20}); f.step(in);
    int total = 0;
    for (int i = 1; i <= 30; ++i) {              // ploughing for 0.5 s at 60 Hz
        in.game_time = i / 60.0;
        in.player = box_at({0, -2.0f + i * 0.1f, -20});
        f.step(in);
        total += int(f.drain_contacts().size());
    }
    EXPECT_LE(total, 2);
}

TEST(MinorContact, TeleportJumpDoesNotSweep) {
    auto f = field_with_fragments();
    CloudDesc d; d.id = 1; d.anchor = Anchor::Point; d.point = {0, 0, -20};
    d.shell_inner = 0; d.shell_outer = 5; d.count = 300; d.r_min = d.r_max = 0.1f;
    f.add_cloud(d, 0.0);
    auto in = looking_down_minus_z(0.0);
    in.player = box_at({0, -30000, -20}); f.step(in);
    in.game_time = 1.0 / 60.0;
    in.player = box_at({0, +30000, -20}); f.step(in);   // 60,000 GU: a hand-off
    EXPECT_TRUE(f.drain_contacts().empty());
}

TEST(MinorContact, PausedFrameMakesNoContacts) {
    auto f = field_with_fragments();
    f.add_cloud(single_minor_at({0, 0, -20}), 0.0);
    auto in = looking_down_minus_z(1.0);
    in.player = box_at({0, -5, -20}); f.step(in);
    in.player = box_at({0, 0, -20}); f.step(in);        // same game time: paused
    EXPECT_TRUE(f.drain_contacts().empty());
}

TEST(MinorContact, ReAddingACloudClearsItsShoves) {
    auto f = field_with_fragments();
    auto d = single_minor_at({0.6, 0, -20});
    f.add_cloud(d, 0.0);
    auto in = looking_down_minus_z(0.0);
    in.player = box_at({-2, 0, -20}); f.step(in);
    in.game_time = 0.1; in.player = box_at({0.3, 0, -20}); f.step(in);
    f.add_cloud(d, 0.1);
    in.player.reset(); f.step(in);
    glm::vec3 p; f.minor_position(5, 0, p);
    EXPECT_NEAR(p.x, 0.6f, 1e-4f);
}

TEST(MinorContact, ContactPointIsInViewSpace) {
    auto f = field_with_fragments();
    f.add_cloud(single_minor_at({5000, 0, -20}), 0.0);
    auto in = looking_down_minus_z(0.0);
    in.render_origin = glm::dvec3(5000, 0, 0);
    in.player = box_at({0, -3, -20}); f.step(in);
    in.game_time = 0.1; in.player = box_at({0, 0, -20}); f.step(in);
    auto c = f.drain_contacts();
    ASSERT_EQ(c.size(), 1u);
    EXPECT_NEAR(c[0].point_view.x, 5000.0, 1.0);
}
```

- [ ] **Step 2: Build and confirm the failure.**

- [ ] **Step 3: Implement** the rules above in `MinorField::step`, adding
`std::optional<PlayerBox> player` to `StepInput` (include `<optional>`),
`std::vector<Contact> contacts_`, `drain_contacts()` (move out) and
`reset_player()`. Store `has_prev_`, `prev_center_view_` (dvec3) and set
`last_time_` at the end of `step`.

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='Minor*'`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/minor_field.h native/src/renderer/minor_field.cc native/tests/renderer/minor_field_test.cc
git commit -m "feat(minors): swept-box player contact, persistent shove, caps and teleport guard"
```

---

### Task 7: `MinorPass`: the instanced GL draw through `opaque.frag`

**Files:**
- Create:
  - `native/src/renderer/shaders/minor.vert`
  - `native/src/renderer/include/renderer/minor_pass.h`
  - `native/src/renderer/minor_pass.cc`
  - `native/tests/renderer/minor_pass_test.cc`
- Modify:
  - `native/src/renderer/CMakeLists.txt`: `embed_shader(SHADER_MINOR_VS shaders/minor.vert minor_vs)` beside `skinned_vs`, plus `minor_pass.cc`
  - `native/src/renderer/include/renderer/pipeline.h` and `pipeline.cc`: `minor_shader()` = `minor_vs` + `opaque_fs`, with unit 7 assigned like opaque
  - `native/src/renderer/frame.cc`: make `set_ambient_uniforms` callable from `minor_pass.cc` (move it into `namespace renderer` and declare it in `frame.h`), unchanged in behaviour
  - `native/tests/renderer/CMakeLists.txt`: add `minor_pass_test.cc`

**Interfaces:**
- Consumes: `minors::Bin`, `minors::Fragment`, `MinorField::bins()` and
  `fragments()` (Task 5); `renderer::Lighting`; `active_shadow_*()`.
- Produces:

```cpp
class MinorPass {
public:
    ~MinorPass();                       // deletes VAOs / instance VBO (GL alive)
    // Draws field.bins() into the bound target. `lookup` resolves a model handle.
    void render(const minors::MinorField& field, const scenegraph::Camera& cam,
                Pipeline& pipeline, const std::function<const assets::Model*(std::uint64_t)>& lookup,
                const Lighting& lighting, float ambient_scale, float rim_strength);
    void forget_models();               // drop VAOs keyed on model handles (mission swap)
    int last_draw_calls() const { return draw_calls_; }
};
```

`minor.vert`:

```glsl
#version 410 core
// Minor rocks (minor-rocks spec §2): opaque.vert with a per-instance model
// matrix. Linked with opaque.frag, so minors are lit exactly as majors are.
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
layout(location = 7) in vec4 a_row0;   // rows of [R*s | t], RENDER space
layout(location = 8) in vec4 a_row1;
layout(location = 9) in vec4 a_row2;

uniform mat4 u_view;
uniform mat4 u_proj;

out vec3 v_normal_ws;
out vec2 v_uv;
out vec3 v_position_ws;

void main() {
    mat4 model = transpose(mat4(a_row0, a_row1, a_row2, vec4(0.0, 0.0, 0.0, 1.0)));
    vec4 ws = model * vec4(a_position, 1.0);
    v_normal_ws = mat3(model) * a_normal;
    v_uv = a_uv;
    v_position_ws = ws.xyz;
    gl_Position = u_proj * u_view * ws;
}
```

`MinorPass::render` steps:
1. Return early when `field.bins()` is empty. Otherwise use
   `pipeline.minor_shader()` and set `u_view`, `u_proj` and `u_camera_pos_ws`.
2. Call `set_ambient_uniforms(s, lighting, ambient_scale)` and set
   `u_dir_light_count` / `_dir_ws` / `_color`, exactly as
   `submit_opaque_in_pass`'s `configure_common` does.
3. Set the per-pass "feature off" uniforms once:
   - `u_decal_count 0`, `u_glow_region_count 0`, `u_dyn_light_count 0`
   - `u_carve_enabled 0`, `u_carve_count 0`, `u_carve_invert 0`
   - `u_hull_field 6`, `u_hull_field_enabled 0`
   - `u_frame_enabled 0`, `u_damage_decal 3`
   - `u_hull_decal_count 0`, `u_decal_enabled_mask 0`
   - `u_node_rest_fix` identity
   - `u_emissive_scale 1`, `u_scuff_map_ok 0`
   - `u_nan_debug` from `dauntless_nan_debug::enabled()`
   - `u_rim_strength rim_strength`
   - shadows exactly as `draw_model` does (unit 5)
4. Upload every bin's items into one `GL_ARRAY_BUFFER` (`instance_vbo_`,
   `glBufferData` with `GL_STREAM_DRAW`, growing only).
5. For each bin:
   - Resolve `Fragment f = field.fragments(bin.family)[bin.slot]` and
     `model = lookup(bin.lod == 0 ? f.lod0 : f.lod1)`. Skip the bin if the
     model is null.
   - Take the model's first mesh node. Catalogue fragments are one node and
     one mesh, so assert that in a debug log once.
   - Get or create the VAO for `(model handle, mesh index)`:
     - bind the mesh's `vbo()` / `ebo()`, then set attribute pointers 0/1/2
       exactly as `mesh_upload.cc:54-72` does (read that file for the stride
       and offsets);
     - set attributes 7/8/9 from `instance_vbo_` with
       `glVertexAttribDivisor(…, 1)`;
     - the instance attribute offset is set per bin with
       `glVertexAttribPointer(7..9, …, (void*)(bin_offset + k·16))`.
   - Set material uniforms the way `draw_model`'s mesh loop does:
     - `u_diffuse_color`, `u_emissive_color`
     - `u_base_color` unit 0, from the material's base texture or white
     - `u_glow_map` unit 1, black
     - `u_specular_map` unit 2, black, and `u_specular_enabled 0`
     - `u_normal_map` unit 4, with `u_normal_enabled`, `u_normal_strength`
       and `u_normal_flip_g` from `dauntless_normal_map` as `draw_model` does
     - `u_model` identity (unused by `minor.vert`; set so nothing is stale)
   - `glDrawElementsInstanced(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr, items)`, and increment `draw_calls_`.
6. Unbind the VAO and restore the active texture unit to 0.

White and black fallbacks: create 1×1 textures lazily in `MinorPass`, the way
`FrameSubmitter::ensure_white_texture` does.

- [ ] **Step 1: Write the failing GL tests**

Follow `breach_pass_test.cc`'s fixture: a hidden `renderer::Window` with
`GTEST_SKIP` only when there is no GL context. Build a one-node, one-mesh
`assets::Model` by hand: a unit cube of radius about 57 model units, with
positions, normals and UVs, uploaded through the same `assets::Mesh` upload
the breach test uses.

```cpp
TEST_F(MinorPassGLTest, MatchesDrawModelPixelForPixel) {
    // 1. Render the cube through FrameSubmitter::submit_opaque_instance (or
    //    draw_model) with world = translate(0,0,-3) * scale(0.01*s) and a
    //    Lighting with one directional light + ambient; read back pixels A.
    // 2. Clear; add a MinorField cloud with ONE minor whose step produces the
    //    same world (count 1, shell 0, r = 0.01*s*57.142857, tumble 0:
    //    set dials tumble_min = tumble_max = 0 and give the minor phase 0
    //    by calling a test-only MinorField::debug_set_phase(id, 0, 0.0f));
    //    MinorPass::render with the same Lighting, ambient_scale 1, rim 0;
    //    read back pixels B.
    // 3. EXPECT every pixel of A == B (same fragment shader, same inputs).
}

TEST_F(MinorPassGLTest, OneInstancedDrawPerNonEmptyBin) {
    // Field with 2 fragments x both LODs populated -> last_draw_calls() == bins().size()
}

TEST_F(MinorPassGLTest, ModelVaoIsNotModified) {
    // glGetVertexAttribiv on mesh.vao() for attribute 7 ENABLED before and
    // after render(): both GL_FALSE.
}

TEST_F(MinorPassGLTest, EmptyFieldIssuesNoDraws) {
    // render() with no clouds -> last_draw_calls() == 0
}
```

Write these out in full in the test file, using the breach test's helpers as
the model for building the window, the model and the pixel readback. If
`MatchesDrawModelPixelForPixel` cannot get an exactly-equal pose because the
minor's rotation includes `phase`, add
`void debug_set_phase(std::uint32_t id, std::size_t i, float phase)` to
`MinorField` (documented as test-only) rather than loosening the comparison.
Rim strength: pass `rim_strength = 0` to both draws.

- [ ] **Step 2: Reconfigure (new shader), build and confirm the failure**

Run: `cmake -B build -S . -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 && cmake --build build -j 2>&1 | tail -5`
Expected: compile errors, because `MinorPass` does not exist.

- [ ] **Step 3: Implement** `minor.vert`, the `Pipeline::minor_shader()`
program (`std::make_unique<Shader>(shader_src::minor_vs, shader_src::opaque_fs)`,
then assign unit 7 to `u_scuff_map` as the opaque program does), the
`set_ambient_uniforms` exposure and `MinorPass`.

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='MinorPass*:Minor*'`
Expected: all PASS, none skipped (the Mac has GL).

- [ ] **Step 5: Run the existing frame and breach suites** (the
`set_ambient_uniforms` move must not change them)

Run: `build/native/tests/renderer/renderer_tests --gtest_filter='Frame*:Breach*:Pipeline*'`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/shaders/minor.vert native/src/renderer/include/renderer/minor_pass.h native/src/renderer/minor_pass.cc native/tests/renderer/minor_pass_test.cc native/src/renderer/CMakeLists.txt native/tests/renderer/CMakeLists.txt native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc native/src/renderer/frame.cc native/src/renderer/include/renderer/frame.h native/src/renderer/include/renderer/minor_field.h native/src/renderer/minor_field.cc
git commit -m "feat(minors): MinorPass -- instanced fragments through opaque.frag"
```

---

### Task 8: Host wiring: bindings, `frame()`, resets, profiler, Python façade

**Files:**
- Modify:
  - `native/src/host/host_bindings.cc`
  - `engine/renderer.py`
- Test:
  - `tests/host/test_minors_bindings.py` (create)
  - `tests/host/test_init_resets_frame_state.py` (extend)
  - `tests/unit/test_renderer_binding_manifest.py` (passes once the manifest is updated)

**Interfaces:**
- Consumes: Tasks 5–7.
- Produces. The Python façade in `engine/renderer.py`, all in
  `_REQUIRED_BINDINGS`:
  - `minors_add_cloud(desc: dict)`
  - `minors_remove_cloud(id: int)`
  - `minors_detach(id, p0, v, t0, debris: list)`
  - `minors_fade_out(id, seconds)`
  - `minors_set_fragments(family: int, entries: list[tuple[int, int, float]])`
  - `minors_set_player(iid_or_None)`
  - `minors_set_dials(d: dict)`
  - `minors_set_enabled(bool)`
  - `minors_enabled() -> bool`
  - `minors_drain_contacts() -> list[dict]` (`{"point": (x,y,z), "radius", "rel_speed"}`)
  - `minors_stats() -> dict` (`{"clouds", "minors", "drawn", "bins", "draw_calls"}`)
  - `minors_clear()`
- The desc dict keys are:
  - `id`, `anchor` (`"instance" | "point" | "free"`), `instance` (InstanceId or None)
  - `point` (view-space tuple), `velocity`, `t0`
  - `shell_inner`, `shell_outer`, `falloff`, `count`
  - `r_min`, `r_max`, `size_exponent`
  - `family`, `seed`, `orbit_rate`, `fade_in`
  - `debris` (a list of `{"offset", "v0", "radius", "seed"}`)
- Produces `_dauntless_host.MinorField`, a standalone pybind class for headless
  probes. Its methods are `add_cloud(desc, now)`, `remove_cloud`,
  `detach(id, p0, v, t0, debris)`, `fade_out(id, s, now)`,
  `set_fragments(family, entries)`, `set_dials(d)`, `dials() -> dict` and:

  ```
  step(game_time, view16, proj16, viewport_h, anchors: dict[int, tuple] = {},
       player: dict | None = None, render_origin=(0,0,0))
  ```

  where `player = {"world": 16 floats column-major, "center": (..), "half": (..)}`.
  It also has `drain_contacts()` and `stats()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/host/test_minors_bindings.py
import os
import math


def _identity16():
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _persp16(fovy=math.radians(60), aspect=16 / 9, n=0.1, f=1e6):
    t = 1.0 / math.tan(fovy / 2)
    return [t / aspect, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1,
            0, 0, 2 * f * n / (n - f), 0]


def _desc(**kw):
    d = dict(id=1, anchor="point", instance=None, point=(0.0, 0.0, -20.0),
             velocity=(0.0, 0.0, 0.0), t0=0.0, shell_inner=0.0, shell_outer=2.0,
             falloff=0.0, count=50, r_min=0.3, r_max=0.3, size_exponent=2.5,
             family=0, seed=1, orbit_rate=0.0, fade_in=False, debris=[])
    d.update(kw)
    return d


def test_standalone_minorfield_steps_without_init():
    import _dauntless_host as h
    f = h.MinorField()
    f.set_fragments(0, [(1, 2, 57.142857)])
    f.add_cloud(_desc(), 0.0)
    f.step(0.0, _identity16(), _persp16(), 1080.0)
    s = f.stats()
    assert s["clouds"] == 1 and s["minors"] == 50 and s["drawn"] == 50


def test_dials_defaults_match_python_defaults():
    import _dauntless_host as h
    from engine.rocks import minor_dials as md
    native = h.MinorField().dials()
    for k in md.NATIVE_KEYS:
        assert native[k] == md.DEFAULTS[k], k


def test_contacts_come_back_as_dicts():
    import _dauntless_host as h
    f = h.MinorField()
    f.set_fragments(0, [(1, 2, 57.142857)])
    f.add_cloud(_desc(count=1, shell_outer=0.0, r_min=0.2, r_max=0.2), 0.0)
    def player(y):
        w = [0.01, 0, 0, 0, 0, 0.01, 0, 0, 0, 0, 0.01, 0, 0.0, y, -20.0, 1.0]
        return {"world": w, "center": (0, 0, 0), "half": (50, 100, 30)}
    f.step(0.0, _identity16(), _persp16(), 1080.0, player=player(-5.0))
    f.step(0.1, _identity16(), _persp16(), 1080.0, player=player(0.0))
    c = f.drain_contacts()
    assert len(c) == 1 and set(c[0]) == {"point", "radius", "rel_speed"}


def test_global_minors_bindings_before_init_are_silent():
    import _dauntless_host as h
    h.minors_clear()
    h.minors_set_enabled(True)
    assert h.minors_drain_contacts() == []


def test_frame_with_a_cloud_draws_it():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    from engine.rocks import catalogue
    h.init(64, 64, "test_minors_frame")
    try:
        rock = catalogue.pick("x", kind="fragment", family="silicate")
        h0 = h.load_model(rock.lod_paths[0], [], None, decals=None, scale=1.0)
        h1 = h.load_model(rock.lod_paths[1], [], None, decals=None, scale=1.0)
        h.minors_set_fragments(0, [(h0, h1, rock.bound_radius_m / 1.75)])
        h.minors_add_cloud(_desc())
        h.set_camera(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, -1.0),
                     up=(0.0, 1.0, 0.0), fov_y_rad=1.0472)
        h.damage_decals_tick(1.0)
        h.frame()
        s = h.minors_stats()
        assert s["drawn"] > 0 and s["draw_calls"] >= 1
    finally:
        h.shutdown()
```

In `tests/host/test_init_resets_frame_state.py`, add
`test_minors_state_cleared_by_reset`. It adds a cloud and a player with the
global bindings, runs `shutdown()` then `init()`, and asserts that
`minors_stats()["clouds"] == 0`, that `minors_drain_contacts() == []`, and
that `minors_enabled()` is True. Follow that file's existing pattern.

Match the real `set_camera` / `load_model` keyword names: read the
signatures in `host_bindings.cc` (`load_model` around :2092) and adjust the
calls if they differ.

- [ ] **Step 2: Build and confirm the failure** (`AttributeError: MinorField`).

- [ ] **Step 3: Implement the native side in `host_bindings.cc`**
1. Globals (near `g_dust_pass`):
   - `renderer::minors::MinorField g_minor_field;`
   - `std::unique_ptr<renderer::MinorPass> g_minor_pass;`
   - `bool g_minors_enabled = true;`
   - `std::optional<scenegraph::InstanceId> g_minor_player;`
   - `int g_minor_draw_calls = 0;`
2. Pass lifetime:
   - `init()`: `g_minor_pass = std::make_unique<renderer::MinorPass>();`
   - `shutdown()`: reset it beside `g_dust_pass.reset()`, while GL is alive.
3. `reset_frame_state()`:
   - `g_minor_field.clear(); g_minor_field.reset_player(); g_minor_field.set_dials({});`
   - `g_minors_enabled = true; g_minor_player.reset(); g_minor_draw_calls = 0;`
   - `if (g_minor_pass) g_minor_pass->forget_models();`
   - Fragment tables are cleared by `clear()`: make `MinorField::clear()`
     also clear `fragments_`.
4. `frame()`, inside the `xform_sync` block right after
   `resolve_attached_dynamic_lights`:

   ```cpp
   if (g_minors_enabled) {
       DAUNTLESS_FRAME_SCOPE("space.minors.step");
       renderer::minors::StepInput in;
       in.game_time = g_decal_game_time;
       in.render_origin = g_world.render_origin();
       in.view = g_camera.view_matrix();
       in.proj = g_camera.proj_matrix();
       in.viewport_h = static_cast<float>(fh);
       in.anchor_of = [](std::uint64_t key, glm::vec3& out) {
           scenegraph::InstanceId id{static_cast<std::uint32_t>(key >> 32),
                                     static_cast<std::uint32_t>(key & 0xffffffffu)};
           const auto* inst = g_world.get(id);
           if (inst == nullptr) return false;
           out = glm::vec3(inst->world[3]);
           return true;
       };
       if (g_minor_player) {
           if (const auto* inst = g_world.get(*g_minor_player)) {
               if (const auto* m = resolve_model(inst->model_handle)) {
                   const auto box = renderer::compute_model_aabb(*m);
                   in.player = renderer::minors::PlayerBox{
                       inst->world, (box.min + box.max) * 0.5f,
                       (box.max - box.min) * 0.5f};
               }
           }
       }
       g_minor_field.step(in);
   }
   ```

   Check the `Aabb` field names in `renderer/aabb.h` and use them.
   `compute_model_aabb` walks every vertex, so cache it per model handle in a
   small `std::unordered_map<std::uint64_t, Aabb>` cleared in
   `reset_frame_state`. Never recompute it per frame.
5. In `render_space_geometry`, right after the `space.opaque` block:

   ```cpp
   if (g_minors_enabled && g_minor_pass) {
       DAUNTLESS_FRAME_SCOPE("space.minors.draw");
       const float rim = dauntless_rim::enabled() ? 0.1f * dauntless_rim::kStrengthScale : 0.0f;
       g_minor_pass->render(g_minor_field, cam, *g_pipeline,
           [](std::uint64_t h) { return resolve_model(h); },
           g_lighting, ambient_scale, rim);
       g_minor_draw_calls = g_minor_pass->last_draw_calls();
   }
   ```

   (0.1 is `Instance::rim_strength`'s default. If `dauntless_rim` is not
   visible in this TU, expose its `enabled()` / `kStrengthScale` the same way
   the other `dauntless_*` namespaces are declared at the top of the file.)
6. Bindings: one `m.def` per façade name. They convert the dict into a
   `CloudDesc`, where `instance` is an `InstanceId` and the key is
   `(index<<32)|generation`. `minors_add_cloud` passes `g_decal_game_time` as
   `now`, and so do `minors_fade_out` and `minors_detach`. `minors_set_dials`
   reads each key with `contains`, like `system_nebula_set_dials`, and
   `minors_stats` adds `draw_calls`.
7. `py::class_<renderer::minors::MinorField>(m, "MinorField")` with the
   standalone methods listed under **Interfaces**. `step` builds a
   `StepInput` from flat lists (`glm::make_mat4`); its `anchor_of` reads the
   `anchors` dict (keys are ints).

- [ ] **Step 4: Implement the Python façade** in `engine/renderer.py`: one
thin wrapper per name (`_h.minors_add_cloud(desc)` and so on), each with a
one-line docstring. Add all twelve names to `_REQUIRED_BINDINGS`.

- [ ] **Step 5: Build and run**

Run: `cmake --build build -j && uv run pytest tests/host/test_minors_bindings.py tests/host/test_init_resets_frame_state.py tests/unit/test_renderer_binding_manifest.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py tests/host/test_minors_bindings.py tests/host/test_init_resets_frame_state.py native/src/renderer/include/renderer/minor_field.h native/src/renderer/minor_field.cc
git commit -m "feat(minors): host wiring -- frame() step and draw, bindings, resets, profiler scopes"
```

---

### Task 9: Python cloud registry and host-loop wiring

**Files:**
- Create: `engine/rocks/minors.py`
- Modify:
  - `engine/host_loop.py`:
    - `_reconcile_scene`: call `minors.reconcile` after `_reconcile_runtime_instances`
    - `_drain_pending_swap`: add `minors.reset(self.renderer)` to the reset list
    - boot: `minor_dials.register()` beside `dev_nebula_dials.register(_h)`
  - `engine/ui/developer_options_panel.py` and `native/assets/ui-cef/js/developer_options.js`: a "Minor rocks" toggle on the Lighting tab
  - `tests/conftest.py`: autouse reset
- Test:
  - `tests/unit/test_minor_registry.py` (create)
  - `tests/integration/test_minor_clouds_e2e.py` (create)

**Interfaces:**
- Consumes:
  - `engine.renderer.minors_*` (Task 8)
  - `minor_dials` (Task 3)
  - `catalogue.load()`
  - `rocks.rock.is_rock`, `effective_radius`
  - `rocks.death.is_dying_rock`
  - `frames.viewing_set()`, `frames.offset_between`
- Produces, in `engine/rocks/minors.py`:
  - `CloudSpec` (a frozen dataclass whose fields equal the native desc keys
    minus `id`, plus `key: str`)
  - `halo_spec(rock, iid) -> CloudSpec | None`
  - `tile_spec(field, view_set, set_name: str, offset: tuple) -> CloudSpec | None`
  - `desired_clouds(view_set, rock_instances: dict, fields: list) -> dict[str, CloudSpec]`
  - `reconcile_with(r, view_set, rock_instances, fields, player_iid) -> None` (the testable core)
  - `reconcile(session, r) -> None`
  - `register_free_cloud(spec: FreeCloudSpec) -> None`
  - `reset(r=None) -> None`
  - `live_minor_count() -> int`
  - `native_ids() -> dict[str, int]`
- `FreeCloudSpec` is defined here and consumed by Task 10:

```python
@dataclass(frozen=True)
class FreeCloudSpec:
    rock_name: str
    pSet: object                 # the set the rock died in
    p0: tuple                    # pSet coordinates
    velocity: tuple              # GU/s
    t0: float                    # game time
    family: str
    debris: tuple                # tuple of dict(offset, v0, radius, seed)
    halo_radius_gu: float        # the parent's effective radius (halo rebuild)
```

Rules:
- **Halo**: rock `R = effective_radius(rock)`.
  - `count = clamp(round(halo_per_gu2·R²), halo_min, halo_max)`
  - shell `[halo_inner·R, halo_outer·R]`, `falloff = halo_falloff`
  - `r_min = halo_r_min_gu`, `r_max = min(halo_r_max_frac·R, halo_r_max_gu)`
  - `size_exponent = halo_size_exponent`, `orbit_rate = halo_orbit_rate`
  - family `rock.__dict__.get("_rock_family", "silicate")`
  - `seed = crc32("halo:" + name)`, `anchor = "instance"`
  - key `"halo:" + name`
  - Skip it when the rock is dying (`death.is_dying_rock`) or dead.
- **Tile**: `count = round(tiles³·per_tile·tile_count_mult)`.
  - shell `[0, field_radius]`, `falloff = 0`
  - `r_min = tile_r_min_gu`, `r_max = max(tile_r_min_gu, tile_r_per_size_factor·size_factor)`
  - `size_exponent = tile_size_exponent`, `orbit_rate = tile_orbit_rate`
  - silicate, `seed = crc32("tile:" + set_name + ":" + field_name)`
  - `anchor = "point"`, with `point` = the field's world location in view space
    (offset by `frames.offset_between(view_set, field_set)`; a field in the
    viewed set has offset 0)
  - key `"tile:<set>:<name>"`
  - Skip it when `count ≤ 0` or the radius is ≤ 0.
- **Free**: key `"free:<set>:<rock_name>"` (`<set>` is `""` when `pSet` is None, which means "the viewed set"); `point = p0 + offset(view_set, pSet)`; `anchor = "free"`; `t0`, `velocity` and `debris` come from the spec. The halo part is rebuilt from `halo_radius_gu` with the halo rules and `orbit_rate = 0`. Only sent when the free cloud's set offset to the view set is not None.
- **Fade-in**: a spec created after the registry's first reconcile of the
  current view set has `fade_in=True`. One present at the first reconcile has
  `fade_in=False`.
- **Reconcile** each frame, with `v = frames.viewing_set()`:
  1. If `catalogue.load()` is empty or `renderer.minors_enabled()` is False,
     remove every native cloud and return.
  2. Ensure fragment models are loaded for every family in use: for each
     family, call `minors_set_fragments(FAMILY_INDEX[f], [(h0, h1, bound_mu)…])`,
     loading `rock.lod_paths[0]` and `[1]` with `r.load_model(path, [], None,
     decals=None, scale=1.0)`. Memoise per family until `reset`.
  3. Drain pending free specs (Task 10 queues them):
     - Each becomes a free cloud.
     - If a native halo for that rock exists, call `minors_detach(id, p0_view,
       v, t0, debris)` and re-key the id from `"halo:"` to `"free:"` without
       removing it.
     - Otherwise `minors_add_cloud` the free spec.
  4. Compute the desired halo and tile specs. The free clouds of `v` stay
     desired until evicted.
  5. Diff by key:
     - Remove the native ids whose key is no longer desired.
     - Add the new keys with fresh ids from a counter.
     - A key whose spec changed (dial rebuild, or a view change moving a point)
       is removed and re-added.
  6. Budget: while `live_minor_count() > max_live_minors` and an un-faded free
     cloud exists, call `minors_fade_out(oldest_free_id,
     free_cloud_fade_seconds)` and schedule its removal after that time.
     Removing it also drops it from the per-set free list.
  7. Player: `minors_set_player(session.ship_instances.get(player))`.
  8. Dials: the first reconcile calls `minors_set_dials(minor_dials.native())`.
     `minor_dials.set_on_change` is wired so that a native key change pushes
     `native()` and any other change forces a full re-add.

- [ ] **Step 1: Write the failing unit tests** (pure functions with fakes)

```python
# tests/unit/test_minor_registry.py
import pytest

from engine.rocks import minor_dials as md
from engine.rocks import minors


class _Loc:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Rock:
    def __init__(self, name, r=4.0, family="icy"):
        self._name, self._r = name, r
        self.__dict__["_rock_family"] = family
    def GetName(self): return self._name
    def IsDead(self): return 0


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    md.reset()
    minors.reset(None)
    monkeypatch.setattr(minors, "_effective_radius", lambda rock: rock._r)
    monkeypatch.setattr(minors, "_is_dying", lambda rock: False)
    yield
    minors.reset(None)


def test_halo_spec_follows_the_dials():
    s = minors.halo_spec(_Rock("Asteroid 1", r=4.0), iid=object())
    assert s.key == "halo:Asteroid 1" and s.anchor == "instance"
    assert s.shell_inner == pytest.approx(4.4) and s.shell_outer == pytest.approx(12.0)
    assert s.count == 128                       # 8 x 16
    assert s.r_max == pytest.approx(0.6)        # min(0.15 x 4, 1.0)
    assert s.family == md.FAMILY_INDEX["icy"]


def test_halo_count_is_clamped():
    assert minors.halo_spec(_Rock("a", r=0.5), iid=1).count == 12
    assert minors.halo_spec(_Rock("b", r=50.0), iid=1).count == 400


def test_dying_rock_has_no_halo(monkeypatch):
    monkeypatch.setattr(minors, "_is_dying", lambda rock: True)
    assert minors.halo_spec(_Rock("a"), iid=1) is None


def test_tile_spec_beol4_is_405_minors():
    from engine.appc.asteroid_field import AsteroidField
    f = AsteroidField()
    f.SetName("Asteroid Field 1")
    f.SetFieldRadius(1000.0); f.SetNumTilesPerAxis(3)
    f.SetNumAsteroidsPerTile(15); f.SetAsteroidSizeFactor(7.0)
    s = minors.tile_spec(f, view_set=None, set_name="Beol4", offset=(0, 0, 0))
    assert s.count == 405 and s.shell_outer == 1000.0
    assert s.r_max == pytest.approx(0.7) and s.anchor == "point"


def test_no_catalogue_means_no_clouds(monkeypatch):
    from engine.rocks import catalogue
    monkeypatch.setattr(catalogue, "load", lambda: ())
    calls = []
    class _R:
        def __getattr__(self, n):
            return lambda *a, **k: calls.append(n)
        def minors_enabled(self): return True
    minors.reconcile_with(_R(), view_set=None, rock_instances={},
                          fields=[], player_iid=None)
    assert "minors_add_cloud" not in calls


def test_diff_adds_then_removes():
    added, removed = [], []
    class _R:
        def minors_enabled(self): return True
        def minors_add_cloud(self, d): added.append(d["id"])
        def minors_remove_cloud(self, i): removed.append(i)
        def minors_set_fragments(self, *a): pass
        def minors_set_player(self, *a): pass
        def minors_set_dials(self, *a): pass
        def load_model(self, *a, **k): return 7
    r = _R()
    rock = _Rock("A")
    minors.reconcile_with(r, view_set=None, rock_instances={rock: 11},
                          fields=[], player_iid=None)
    assert len(added) == 1
    minors.reconcile_with(r, view_set=None, rock_instances={rock: 11},
                          fields=[], player_iid=None)
    assert len(added) == 1                       # unchanged -> no re-add
    minors.reconcile_with(r, view_set=None, rock_instances={},
                          fields=[], player_iid=None)
    assert removed == added


def test_first_reconcile_does_not_fade_in_later_ones_do():
    descs = []
    class _R:
        def minors_enabled(self): return True
        def minors_add_cloud(self, d): descs.append(d)
        def __getattr__(self, n): return lambda *a, **k: 7
    r = _R()
    minors.reconcile_with(r, None, {_Rock("A"): 1}, [], None)
    minors.reconcile_with(r, None, {_Rock("A"): 1, _Rock("B"): 2}, [], None)
    assert descs[0]["fade_in"] is False and descs[1]["fade_in"] is True


def test_swap_reset_clears_registry():
    class _R:
        def minors_enabled(self): return True
        def __getattr__(self, n): return lambda *a, **k: 7
    minors.reconcile_with(_R(), None, {_Rock("A"): 1}, [], None)
    assert minors.native_ids()
    cleared = []
    class _C:
        def minors_clear(self): cleared.append(1)
    minors.reset(_C())
    assert minors.native_ids() == {} and cleared == [1]

def test_budget_evicts_oldest_free_cloud_first(monkeypatch):
    md._dials["max_live_minors"] = 100
    faded = []
    class _R:
        def minors_enabled(self): return True
        def minors_fade_out(self, i, s): faded.append(i)
        def __getattr__(self, n): return lambda *a, **k: 7
    r = _R()
    for name in ("old", "new"):
        minors.register_free_cloud(minors.FreeCloudSpec(
            name, None, (0, 0, 0), (0, 0, 0), 0.0, "silicate",
            tuple({"offset": (0, 0, 0), "v0": (0, 0, 0), "radius": 0.1, "seed": i}
                  for i in range(10)), 4.0))
        minors.reconcile_with(r, None, {}, [], None)
    big = _Rock("Big", r=50.0)                       # a 400-minor halo
    minors.reconcile_with(r, None, {big: 3}, [], None)
    ids = minors.native_ids()
    assert faded and faded[0] == ids["free::old"]
    assert "halo:Big" in ids                         # halos never evicted

```

`reconcile(session, r)` is a thin adapter over the testable core
`reconcile_with(r, view_set, rock_instances, fields, player_iid)`:
- `view_set = frames.viewing_set()`
- `rock_instances` = `{ship: iid for ship, iid in session.ship_instances.items() if is_rock(ship)}`
- `fields` = the `AsteroidField_Cast` of `view_set.GetClassObjectList(App.CT_ASTEROID_FIELD)`
- `player_iid` is the player's iid

`tile_spec(field, view_set, set_name, offset)` takes the precomputed offset so
it can be tested without frames. `_effective_radius` and `_is_dying` are module
seams wrapping `rocks.rock.effective_radius` and `rocks.death.is_dying_rock`
(plus `IsDead()`).

- [ ] **Step 2: Run the tests and confirm they fail** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `engine/rocks/minors.py`** to the rules above.
Module state:
- `_ids: dict[str, int]`
- `_specs: dict[str, CloudSpec]`
- `_next_id`
- `_free: dict[str, list[FreeCloudSpec-with-id]]`, keyed by set name
- `_pending_free: list`
- `_fragments_loaded: set[int]`
- `_seen_view`: the set name the first-reconcile rule tracks
- `_fading: dict[int, float]`, the game time at which to remove

`reset(r)` clears all of these and calls `r.minors_clear()` when `r` is not
None. Every read of `catalogue` or `paths` happens at use. Wrap each native
call in `try/except Exception as e: dev_mode.log_swallowed("minors <what>",
e)`, so that rendering can never break the frame.

- [ ] **Step 4: Wire the host loop**
- In `_reconcile_scene`, after `_reconcile_runtime_instances(...)`:

  ```python
  from engine.rocks import minors as _minors
  _minors.reconcile(session, renderer)
  ```

- In `_drain_pending_swap`, after `_debris_chunk.clear(self.renderer)`:

  ```python
  from engine.rocks import minors as _minors
  _minors.reset(self.renderer)
  ```

- Beside `dev_nebula_dials.register(_h)` (host_loop ~9776):

  ```python
  from engine.rocks import minor_dials as _minor_dials
  _minor_dials.register()
  ```

- Wire `minor_dials.set_on_change(minors.on_dials_changed)` inside
  `minors.reconcile`'s first call. Native keys push `native()`; others mark
  every spec dirty so the next diff re-adds them.

Add `tests/host/test_scene_reconcile_ordering.py`-style coverage only if that
test enumerates the calls inside `_reconcile_scene`. Read it, and if it pins
the exact sequence, add `minors.reconcile` to its expected order.

- [ ] **Step 5: Add the Developer Options "Minor rocks" toggle**

This mirrors the `rock_catalogue` row exactly:
- State: `self._minor_rocks = renderer.minors_enabled()` (read in `__init__`
  and `open()`).
- Snapshot and settings: `"minor_rocks"`.
- Action: `toggle:minor_rocks` → `renderer.minors_set_enabled(not
  self._minor_rocks)`, then flip the mirror.
- Focusable in the Lighting list.
- JS row: `_doToggleRow('Minor Rocks', 'minor_rocks', s.minor_rocks,
  isFoc('minor_rocks'))`.

The panel is constructed in headless tests where `renderer` may be
uninitialised. Guard the read with `try/except` and default to True.

- [ ] **Step 6: Add the conftest reset**

```python
    try:
        _mn = sys.modules.get("engine.rocks.minors")
        if _mn is not None:
            _mn.reset(None)
    except Exception:
        pass
```

- [ ] **Step 7: Write the E2E test**

```python
# tests/integration/test_minor_clouds_e2e.py
"""Minor clouds from REAL SDK content (minor-rocks spec §5 E2E)."""
import App
from engine.rocks import minors
from tests.integration.test_sdk_bridge_load import _fresh_world


def _fields(pSet):
    return [App.AsteroidField_Cast(o)
            for o in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD)]


def test_beol4_registers_a_405_minor_tile_cloud():
    _fresh_world()
    import Systems.Beol.Beol4 as beol4
    beol4.Initialize()
    pSet = beol4.GetSet()
    specs = minors.desired_clouds(pSet, rock_instances={}, fields=_fields(pSet))
    tiles = [s for k, s in specs.items() if k.startswith("tile:")]
    assert len(tiles) == 1 and tiles[0].count == 405


def test_multi1_registers_54_halos():
    from engine.rocks.rock import is_rock
    _fresh_world()
    import Systems.Multi1.Multi1 as m1
    m1.Initialize()
    pSet = m1.GetSet()
    rocks = {pSet.GetObject("Asteroid %d" % i): i for i in range(1, 55)}
    assert all(is_rock(r) for r in rocks)
    specs = minors.desired_clouds(pSet, rock_instances=rocks, fields=_fields(pSet))
    assert sum(1 for k in specs if k.startswith("halo:")) == 54


def test_vesuvi1_and_multi7_fields():
    _fresh_world()
    import Systems.Multi7.Multi7_S as m7
    m7.Initialize()
    pSet = m7.GetSet()
    specs = minors.desired_clouds(pSet, rock_instances={}, fields=_fields(pSet))
    assert sorted(s.count for k, s in specs.items() if k.startswith("tile:")) == [54, 54, 54]
```

Check each system module's real `Initialize` / `GetSet` names before running
(`Systems/Beol/Beol4.py`, `Multi7_S.py`). `desired_clouds(view_set,
rock_instances, fields)` is the pure core that `reconcile_with` uses.

- [ ] **Step 8: Run**

Run: `uv run pytest tests/unit/test_minor_registry.py tests/integration/test_minor_clouds_e2e.py tests/host -q -k "minor or reconcile"`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add engine/rocks/minors.py engine/host_loop.py engine/ui/developer_options_panel.py native/assets/ui-cef/js/developer_options.js tests/conftest.py tests/unit/test_minor_registry.py tests/integration/test_minor_clouds_e2e.py
git commit -m "feat(minors): cloud registry -- halos and tile fields for the viewed set"
```

---

### Task 10: Breakup debris becomes a free minor cloud; rock chunks retire

**Files:**
- Modify: `engine/rocks/death.py`, `engine/rocks/breakup.py`, `engine/host_loop.py` (the `sim.rock_breakup` scope)
- Delete: `engine/rocks/chunks.py`, `tests/unit/test_rock_chunks.py`
- Modify: `engine/appc/debris_chunk.py` (remove `spawn_body` and its ghost helpers if `rocks/chunks.py` was their only caller: grep first)
- Test:
  - `tests/unit/test_rock_breakup.py`, `tests/unit/test_rock_death.py`, `tests/integration/test_e1m2_rocks.py`, `tests/unit/test_mission_change.py` (update)
  - `tests/unit/test_rock_debris_minors.py` (create)

**Interfaces:**
- Consumes: `minors.FreeCloudSpec` and `minors.register_free_cloud` (Task 9),
  and `minor_dials`.
- Produces:
  - `breakup.plan` no longer demotes chunks past a cap. `kMaxChunksPerDeath`
    is deleted. A non-major piece is tier `"chunk"` (kept as the name for "a
    debris minor") or `"dust"`.
  - `death.debris_specs(name, pieces, at, loc, parent_v, vels, R) -> tuple[dict, ...]`

Rules (spec §4):
- Collect every plan piece whose tier is `"chunk"`. That includes a
  would-be major demoted by the generation cap, which `plan` already marks as
  a chunk.
  - Each entry: `{"offset": at − loc, "v0": vel − parent_v (after
    _strip_inward), "radius": p.radius_gu, "seed": crc32("%s#%d" % (name, i))}`.
- Add gravel: `n = round(debris_gravel_per_gu · R)` pieces, from
  `random.Random(crc32(name + "#gravel"))`.
  - radius uniform in `[debris_gravel_r_min_gu, debris_gravel_r_max_gu]`
  - offset = `unit·R·0.5·rng.random()`
  - v0 = `unit·kSeparationSpeedGU·rng.uniform(0.5, 1.0)`
  - seed `crc32("%s#g%d" % (name, j))`
- Keep the largest `max_debris_per_death` in total.
- Call `minors.register_free_cloud(FreeCloudSpec(name, pSet, (loc), (parent v),
  App.g_kUtopiaModule.GetGameTime(), family, debris, R))`.
- Delete `ChunkSpec`, `_chunk_specs`, `drain_chunk_specs` and the
  chunk-ghosting. The majors' `_ghost(ghosted)` call stays.
- Remove `rock_chunks.pump(r, session)` from the host loop's
  `sim.rock_breakup` scope, keeping `rock_vfx.pump()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_rock_debris_minors.py
import pytest

from engine.rocks import breakup, death, minors
from engine.rocks import minor_dials as md


def test_plan_has_no_per_death_chunk_cap():
    assert not hasattr(breakup, "kMaxChunksPerDeath")
    pieces = breakup.plan("Asteroid 9", 7.44, generation=1)   # every major demoted
    assert sum(1 for p in pieces if p.tier == "chunk") > 8


def test_debris_specs_follow_rules_and_cap():
    md.reset()
    pieces = breakup.plan("Asteroid 9", 7.44)
    at = [(0.1 * i, 0.0, 0.0) for i in range(len(pieces))]
    out = death.debris_specs("Asteroid 9", pieces, at,
                             loc=(0.0, 0.0, 0.0), parent_v=(0.0, 0.0, 0.0),
                             vels=[(0.8, 0.0, 0.0)] * len(pieces), R=7.44)
    assert 0 < len(out) <= md.get("max_debris_per_death")
    radii = [d["radius"] for d in out]
    assert radii == sorted(radii, reverse=True)
    assert all(set(d) == {"offset", "v0", "radius", "seed"} for d in out)
    again = death.debris_specs("Asteroid 9", pieces, at, (0.0, 0.0, 0.0),
                               (0.0, 0.0, 0.0), [(0.8, 0.0, 0.0)] * len(pieces), 7.44)
    assert out == again                                  # deterministic


def test_dying_rock_halo_is_detached_not_recreated(monkeypatch):
    md.reset(); minors.reset(None)
    calls = []
    class _R:
        def minors_enabled(self): return True
        def minors_add_cloud(self, d): calls.append(("add", d["id"], d["anchor"]))
        def minors_remove_cloud(self, i): calls.append(("remove", i))
        def minors_detach(self, i, *a): calls.append(("detach", i))
        def __getattr__(self, n): return lambda *a, **k: 7
    class _Rock:
        def GetName(self): return "A"
        def IsDead(self): return 0
    rock = _Rock()
    dying = {"v": False}
    monkeypatch.setattr(minors, "_effective_radius", lambda r: 3.0)
    monkeypatch.setattr(minors, "_is_dying", lambda r: dying["v"])
    minors.reconcile_with(_R(), None, {rock: 1}, [], None)
    halo_id = calls[0][1]
    dying["v"] = True
    minors.register_free_cloud(minors.FreeCloudSpec(
        "A", None, (0, 0, 0), (0, 0, 0), 0.0, "silicate", (), 3.0))
    minors.reconcile_with(_R(), None, {rock: 1}, [], None)   # rock still in set
    assert ("detach", halo_id) in calls
    assert ("remove", halo_id) not in calls
    assert sum(1 for c in calls if c[0] == "add") == 1          # no new halo
```

`death.debris_specs(name, pieces, at, loc, parent_v, vels, R)` is the pure
helper `_break_up` calls. `at[i]` and `vels[i]` are the world position and
velocity `_break_up` already computes per piece; it is aligned with `pieces`.

`pSet=None` in the free spec means "the viewed set": `reconcile_with` with
`view_set=None` treats an offset between None and None as zero. Implement it
that way so the unit test needs no frames.

Update the existing tests:
- `test_rock_breakup.py`: delete the chunk-cap assertions and keep everything
  else.
- `test_rock_death.py`: replace every `drain_chunk_specs` expectation with
  `minors._pending_free` (or a monkeypatched `register_free_cloud` collector)
  holding one `FreeCloudSpec` for the rock, whose debris count follows the
  rule.
- `test_e1m2_rocks.py`: "destroying an E1M2 debris rock leaves a free cloud
  and zero rock chunks". Assert `debris_chunk._live` gains nothing from the
  kill and that one `FreeCloudSpec` was registered.
- `test_mission_change.py`: drop the chunk reference it holds (read it first).

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement** the death and breakup changes and remove
`chunks.py`. Grep for leftovers:

Run: `grep -rn "chunk_specs\|ChunkSpec\|kMaxChunksPerDeath\|rocks import chunks\|rocks.chunks" engine tests`
Expected: no matches.

Run: `grep -rn "spawn_body" engine tests`
If the only remaining hits are inside `debris_chunk.py` itself, delete
`spawn_body` and any helper only it used (do not leave orphans); otherwise keep
them.

- [ ] **Step 4: Run the rock and mission suites**

Run: `uv run pytest tests/unit/test_rock_debris_minors.py tests/unit/test_rock_breakup.py tests/unit/test_rock_death.py tests/unit/test_mission_change.py tests/integration/test_e1m2_rocks.py tests/integration/test_e1m2_asteroid_crash.py tests/integration/test_multi1_rocks.py tests/integration/test_e2m1_rocks.py -q`
Expected: PASS.

- [ ] **Step 5: Update the CLAUDE.md "Rock class" row**

Replace `(<1.0 GU → debris_chunk)` with `(<1.0 GU → debris minors in a free
cloud)`, and replace `engine/rocks/{rock,motion,death,breakup,chunks,vfx}.py`
with `…{rock,motion,death,breakup,vfx,minors}.py`.

- [ ] **Step 6: Commit**

```bash
git add engine/rocks/death.py engine/rocks/breakup.py engine/host_loop.py engine/appc/debris_chunk.py tests/unit/test_rock_debris_minors.py tests/unit/test_rock_breakup.py tests/unit/test_rock_death.py tests/unit/test_mission_change.py tests/integration/test_e1m2_rocks.py CLAUDE.md
git rm engine/rocks/chunks.py tests/unit/test_rock_chunks.py
git commit -m "feat(minors): breakup debris becomes a free minor cloud; rock chunks retired"
```

---

### Task 11: Fly-through responses

**Files:**
- Create: `engine/rocks/minor_contact.py`
- Modify: `engine/host_loop.py`, to call `minor_contact.pump(player)` in the `sim.rock_breakup` scope after `rock_vfx.pump()`
- Test: `tests/unit/test_minor_contact.py` (create)

**Interfaces:**
- Consumes: `renderer.minors_drain_contacts()`, `hit_vfx.spawn`,
  `hit_feedback.SPARK_KIND_ROCK`, `combat.shields_block`,
  `host_io.shield_hit`, `hit_feedback._mesh_xyz`, `dash.is_dashing`,
  `App.g_kSoundManager`, `frames.viewing_set()`, and `minor_dials`.
- Produces:
  - `pump(player, contacts=None, now=None, session=None) -> dict`, which
    returns `{"puffs", "grits", "flickers"}` for the frame
  - `reset()`
- Rate limits: one token bucket per response, refilled at `X_max_per_s`
  tokens/s, with capacity `X_max_per_s`. The game clock is
  `App.g_kUtopiaModule.GetGameTime()`.
- Muted while `dash.is_dashing(player)` or while the player's containing set
  is named `"warp"`. Contacts are drained and discarded either way.
- **Puff:** only for `radius ≥ puff_min_radius_gu`:

  ```python
  hit_vfx.spawn(TGPoint3(*point), severity=hit_vfx.Severity.CRITICAL,
                instance_id=None, weapon_kind=SPARK_KIND_ROCK,
                spark_count=puff_spark_count, pSet=frames.viewing_set())
  ```

  `CRITICAL` also registers an explosion light. If that light reads wrong
  live, it becomes a dial; for now record it in the commit message.
- **Grit:**
  - `name = "Collision %d" % random.randint(1, 8)`, then
    `snd = App.g_kSoundManager.GetSound(name)`; if it is None, skip.
  - `old = snd.GetVolume()`, then
    `snd.SetVolume(old * grit_volume * min(1.0, radius / 0.5))`, then
    `snd.Play(position=point)`, then `snd.SetVolume(old)`. `TGSound.Play`
    snapshots the gain at play time (`tg_sound.py:256`), so restoring at once
    is safe.
- **Flicker:** only when `combat.shields_block(player)`. Look up `iid` in
  `session.ship_instances`, then call
  `host_io.shield_hit(iid, point, (0,0,0,0), flicker_intensity, flicker_radius)`.
  `point` is already in view (mesh) coordinates, the frame
  `hit_feedback._mesh_xyz` produces, so pass it straight through.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_minor_contact.py
import pytest

from engine.rocks import minor_contact as mc
from engine.rocks import minor_dials as md


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    md.reset(); mc.reset()
    monkeypatch.setattr(mc, "_spawn_puff", lambda p: None)
    monkeypatch.setattr(mc, "_play_grit", lambda p, r: True)
    monkeypatch.setattr(mc, "_flicker", lambda player, p, session: True)
    monkeypatch.setattr(mc, "_shields_up", lambda player: True)
    monkeypatch.setattr(mc, "_muted", lambda player: False)
    yield
    mc.reset()


def _c(r=0.3):
    return {"point": (0.0, 0.0, 0.0), "radius": r, "rel_speed": 5.0}


def test_rate_limits_hold_over_ten_seconds():
    totals = {"puffs": 0, "grits": 0, "flickers": 0}
    for i in range(600):                             # 10 s at 60 Hz, 20 contacts/frame
        out = mc.pump(object(), contacts=[_c()] * 20, now=i / 60.0)
        for k in totals:
            totals[k] += out[k]
    assert totals["puffs"] <= 6 * 10 + 6
    assert totals["grits"] <= 4 * 10 + 4
    assert totals["flickers"] <= 2 * 10 + 2


def test_small_minors_make_no_puff():
    out = mc.pump(object(), contacts=[_c(r=0.05)], now=0.0)
    assert out["puffs"] == 0 and out["grits"] == 1


def test_no_flicker_with_shields_down(monkeypatch):
    monkeypatch.setattr(mc, "_shields_up", lambda player: False)
    assert mc.pump(object(), contacts=[_c()], now=0.0)["flickers"] == 0


def test_muted_while_dashing_or_in_warp(monkeypatch):
    monkeypatch.setattr(mc, "_muted", lambda player: True)
    assert mc.pump(object(), contacts=[_c()] * 5, now=0.0) == \
        {"puffs": 0, "grits": 0, "flickers": 0}


def test_no_player_drains_and_does_nothing():
    assert mc.pump(None, contacts=[_c()], now=0.0) == \
        {"puffs": 0, "grits": 0, "flickers": 0}
```

The module seams are `_spawn_puff`, `_play_grit`, `_flicker`, `_shields_up`
and `_muted`. When `contacts is None`, `pump` drains
`renderer.minors_drain_contacts()` (guarded: an uninitialised renderer gives
`[]`).

- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** `minor_contact.py` and wire `pump(player,
session=session)` into the host loop's `sim.rock_breakup` scope.
- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_minor_contact.py -q`
Expected: PASS.

- [ ] **Step 5: Add the conftest reset** (`mc.reset()` in
`_reset_leakable_engine_globals`, using the same `sys.modules.get` pattern),
then commit:

```bash
git add engine/rocks/minor_contact.py engine/host_loop.py tests/unit/test_minor_contact.py tests/conftest.py
git commit -m "feat(minors): fly-through responses -- rate-limited puff, grit, shield flicker"
```

---

### Task 12: Headless VFX probe and step benchmark

**Files:**
- Create:
  - `tests/integration/test_minor_flythrough_probe.py`
  - `native/tests/renderer/minor_field_bench_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt` (add the bench file to `renderer_tests`)

**Interfaces:**
- Consumes: `_dauntless_host.MinorField` (Task 8), `minors.desired_clouds`
  (Task 9), `minor_contact.pump` (Task 11) and real SDK systems.

- [ ] **Step 1: Write the probe** (it should pass straight away if Tasks 4–11
are right; if it fails, that is a real bug to fix in the owning task's code)

```python
# tests/integration/test_minor_flythrough_probe.py
"""Headless VFX probe (minor-rocks spec §3/§5): fly the player box through
real clouds for 10 s at full impulse and 10 s dashing, driving the REAL
native MinorField step, and count every response the frame would fire."""
import math

import pytest

import App
from engine.rocks import minor_contact as mc
from engine.rocks import minor_dials as md
from engine.rocks import minors
from tests.integration.test_sdk_bridge_load import _fresh_world


def _persp16():
    t = 1.0 / math.tan(math.radians(30))
    n, f, a = 0.1, 1e6, 16 / 9
    return [t / a, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1,
            0, 0, 2 * f * n / (n - f), 0]


def _view16_at(y):
    # Camera 30 GU behind the player along -y, looking +y.
    return [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, -(y - 30), 1]


def _desc(spec, cid):
    d = {k: getattr(spec, k) for k in (
        "anchor", "point", "velocity", "t0", "shell_inner", "shell_outer",
        "falloff", "count", "r_min", "r_max", "size_exponent", "family",
        "seed", "orbit_rate", "fade_in", "debris")}
    d["id"], d["instance"] = cid, None
    return d


def _fly(field, speed_gups, start, seconds=10.0, muted=False, monkeypatch=None):
    totals = {"puffs": 0, "grits": 0, "flickers": 0}
    calls = {"puff": 0, "grit": 0, "flicker": 0}
    monkeypatch.setattr(mc, "_spawn_puff", lambda p: calls.__setitem__("puff", calls["puff"] + 1))
    monkeypatch.setattr(mc, "_play_grit", lambda p, r: calls.__setitem__("grit", calls["grit"] + 1) or True)
    monkeypatch.setattr(mc, "_flicker", lambda pl, p, s: calls.__setitem__("flicker", calls["flicker"] + 1) or True)
    monkeypatch.setattr(mc, "_shields_up", lambda pl: True)
    monkeypatch.setattr(mc, "_muted", lambda pl: muted)
    dt = 1.0 / 60.0
    for i in range(int(seconds * 60)):
        t = i * dt
        y = start[1] + speed_gups * t
        w = [0.01, 0, 0, 0, 0, 0.01, 0, 0, 0, 0, 0.01, 0, start[0], y, start[2], 1]
        field.step(t, _view16_at(y), _persp16(), 1080.0,
                   player={"world": w, "center": (0, 0, 0), "half": (60, 320, 40)})
        out = mc.pump(object(), contacts=field.drain_contacts(), now=t)
        for k in totals:
            totals[k] += out[k]
    return totals, calls


def _beol4_field():
    import _dauntless_host as h
    _fresh_world()
    import Systems.Beol.Beol4 as beol4
    beol4.Initialize()
    pSet = beol4.GetSet()
    fields = [App.AsteroidField_Cast(o) for o in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD)]
    md.reset()
    # Dense enough that a straight flight really meets minors.
    md._dials["tile_count_mult"] = 20.0
    specs = minors.desired_clouds(pSet, rock_instances={}, fields=fields)
    f = h.MinorField()
    f.set_fragments(0, [(1, 2, 57.142857)])
    for i, (k, s) in enumerate(specs.items(), start=1):
        f.add_cloud(_desc(s, i), 0.0)
    centre = specs[next(iter(specs))].point
    return f, centre


@pytest.mark.parametrize("speed,muted", [(6.3, False), (2000.0, True)])
def test_beol4_flythrough_stays_within_caps(speed, muted, monkeypatch):
    mc.reset()
    f, c = _beol4_field()
    start = (c[0], c[1] - speed * 5.0, c[2])          # crosses the centre at t = 5 s
    totals, calls = _fly(f, speed, start, muted=muted, monkeypatch=monkeypatch)
    assert totals["puffs"] <= 6 * 10 + 6
    assert totals["grits"] <= 4 * 10 + 4
    assert totals["flickers"] <= 2 * 10 + 2
    if muted:
        assert calls == {"puff": 0, "grit": 0, "flicker": 0}
    else:
        assert calls["grit"] > 0                       # it really met minors


def test_flythrough_changes_no_game_state(monkeypatch):
    """No damage, no events: the probe never touches a ship object."""
    posted = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", lambda e: posted.append(e))
    mc.reset()
    f, c = _beol4_field()
    _fly(f, 6.3, (c[0], c[1] - 31.5, c[2]), seconds=10.0, monkeypatch=monkeypatch)
    assert posted == []
```

Add a Multi1-halo case in the same style: 54 halos with Point anchors at each
rock's location (`anchor="point"`, `point` = the rock's world location), and a
flight through the densest one. Assert the same caps.

- [ ] **Step 2: Write the benchmark (it reports and asserts nothing)**

```cpp
// native/tests/renderer/minor_field_bench_test.cc
#include <chrono>
#include <cstdio>
#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include <renderer/minor_field.h>

using namespace renderer::minors;

TEST(MinorFieldBench, ReportsStepTimeAt20kMinors) {
    MinorField f;
    f.set_fragments(0, {Fragment{1, 2, 57.142857f}, Fragment{3, 4, 57.142857f}});
    for (std::uint32_t i = 0; i < 50; ++i) {
        CloudDesc d; d.id = i + 1; d.anchor = Anchor::Point;
        d.point = {double(i % 10) * 40.0, double(i / 10) * 40.0, -200.0};
        d.shell_inner = 4; d.shell_outer = 12; d.count = 400;
        d.r_min = 0.03f; d.r_max = 0.6f; d.seed = i; d.orbit_rate = 0.02f;
        f.add_cloud(d, 0.0);
    }
    StepInput in;
    in.view = glm::lookAt(glm::vec3(200, 200, 100), glm::vec3(200, 200, -200), glm::vec3(0, 1, 0));
    in.proj = glm::perspective(glm::radians(60.0f), 16.0f / 9.0f, 0.1f, 1e6f);
    in.viewport_h = 1080.0f;
    PlayerBox p; p.world = glm::translate(glm::mat4(1.0f), {200, 200, -200}) *
                           glm::scale(glm::mat4(1.0f), glm::vec3(0.01f));
    p.half_mu = {60, 320, 40};
    in.player = p;
    const int frames = 120;
    const auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < frames; ++i) { in.game_time = i / 60.0; f.step(in); f.drain_contacts(); }
    const double ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - t0).count() / frames;
    std::printf("[minor bench] 20,000 minors: %.3f ms/step (drawn %d, bins %d)\n",
                ms, f.stats().drawn, f.stats().bins);
    EXPECT_EQ(f.stats().minors, 20000);
}
```

- [ ] **Step 3: Build and run both**

Run: `cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='MinorFieldBench.*' && uv run pytest tests/integration/test_minor_flythrough_probe.py -q -s`
Expected: PASS. Record the printed ms/step in the commit message.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_minor_flythrough_probe.py native/tests/renderer/minor_field_bench_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "test(minors): headless fly-through VFX probe and 20k step benchmark"
```

---

### Task 13: Docs and the gate

**Files:**
- Modify:
  - `CLAUDE.md`: a new "Minor rocks" row after "Rock class"
  - `docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md`: sub-project 3 status
  - `docs/superpowers/specs/2026-10-01-minor-rocks-design.md`: Status line

- [ ] **Step 1: Add the CLAUDE.md row**

Write it in the table's existing style:

| Minor rocks — instanced scenery around rocks | `engine/rocks/{minors,minor_dials,minor_contact}.py`, `native/src/renderer/{minor_field,minor_pass}.cc`, `shaders/minor.vert`, `engine/dev_dial_groups.py`, `docs/superpowers/specs/2026-10-01-minor-rocks-design.md` | Non-simulated catalogue fragments in **clouds**: a halo per `RockClass` (anchored on its renderer instance, translation only), one per `AsteroidField` (tiles³ × per-tile, sizes 0.1 × size factor GU), and a **free** debris cloud per breakup (the halo detaches; pieces < 1 GU + gravel join; analytic decay). C++ `MinorField` owns instances, cull, LOD bins, shove and the swept player contact; `MinorPass` draws them instanced with `minor.vert` + **`opaque.frag`** (lit like majors by construction). Python owns which clouds exist (viewed set only, reconciled in `_reconcile_scene`), responses (rate-limited puff / BC "Collision N" grit / cosmetic `shield_hit`, muted while dashing) and every number (`minor_dials`). ⚠️ No damage, no events, never in `render_payload`. ⚠️ `/ L O` are SHARED: Developer Options → Lighting → "Dial keys" picks nebula or minors. ⚠️ Tile-field count is a standing decision, not RE'd BC behaviour (stbc-reference was down). Rock chunks are retired. |

- [ ] **Step 2: Update the roadmap's sub-project table row 3** to "built,
awaiting live check — spec `2026-10-01-minor-rocks-design.md`, branch
`feat/minor-rocks`".

- [ ] **Step 3: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. If a test outside this plan fails, run it in isolation
first: if it passes alone, it is order pollution, so add the missing reset to
`tests/conftest.py`. Never call a failure pre-existing by eyeball.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md docs/superpowers/specs/2026-10-01-minor-rocks-design.md
git commit -m "docs(minors): CLAUDE.md row, roadmap status"
```

---

## Live check for Mark (after the gate)

From the worktree:

```bash
./build/dauntless --developer
```

Then follow the spec's "Live check (Mark)" list. To tune: Developer Options →
Lighting → "Dial keys: minors", then `/` to pick a dial and `L` / `O` to step
it. Each press prints `[minors dials] …`.
