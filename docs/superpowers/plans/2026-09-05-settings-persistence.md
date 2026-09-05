# Settings Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configuration panel settings survive a launch — turn off camera shake or subtitles once and they stay off next session.

**Architecture:** A new `engine/settings_store.py` holds JSON file I/O (`SettingsStore`, section/key addressed and table-agnostic) plus a declarative `SETTINGS` table naming each persisted setting's section, default, coercion and applier fan-out. At boot the host loop loads the store, applies every *stored* key through the same appliers the panel uses, then hands the panel a snapshot built from stored values. The panel gains two callbacks (`on_change`, `on_reset`) and never imports the store.

**Tech Stack:** Python 3 (stdlib `json`, `pathlib`, `os.replace`), pytest, CEF-rendered JS panel (`native/assets/ui-cef/js/configuration_panel.js`).

**Spec:** `docs/superpowers/specs/2026-09-05-settings-persistence-design.md`

## Global Constraints

- **Absent key ⇒ applier is never called.** A missing or empty `settings.json` leaves the engine on its native defaults and boot must be byte-identical to today. The table's `default` populates the panel's display snapshot only — it never drives an applier.
- **Persistence is third.** In every panel toggle branch the order is: appliers first, local `setattr` second, `on_change` third. A raising applier must never persist a value the engine isn't on.
- **No new required constructor params.** `on_change` and `on_reset` default to no-ops so every existing `ConfigurationPanel` construction and test keeps working.
- **Never run destructive git.** No `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, or `git add .`. Stage with explicit pathspecs only. This tree is shared with concurrent sessions and holds deliberately-uncommitted work.
- **Never launch the game.** Mark does all live testing. Verify with pytest only.
- **Test gate is `scripts/check_tests.sh`**, not `scripts/run_tests.sh` (the latter is pytest-only and cannot see C++ regressions). A failure not in `tests/known_failures.txt` is a regression this work introduced.
- **Settings keys and their exact spellings** (used verbatim across all tasks):
  `smaa`, `dust`, `fov_deg`, `improved_space`, `camera_realism`, `realistic_lighting`, `camera_shake` (section `graphics`); `subtitles`, `disable_annoying_dialogue`, `ai_difficulty` (section `gameplay`).
- **`SettingsSnapshot` field names** (they are NOT all `<key>_on` — `fov_deg` and `ai_difficulty` have no suffix): `smaa_on`, `dust_on`, `fov_deg`, `improved_space_on`, `camera_realism_on`, `realistic_lighting_on`, `camera_shake_on`, `subtitles_on`, `disable_annoying_dialogue_on`, `ai_difficulty`.
- **FOV bounds are `FOV_MIN = 25`, `FOV_MAX = 55`**, imported from `engine.ui.configuration_panel`. `ai_difficulty` bounds are 0–2.

## File Structure

| File | Responsibility |
|---|---|
| `engine/settings_store.py` (new) | `SettingsStore` (JSON I/O) + `SETTINGS` table + `SettingsContext` + the four module functions. One file: the table and the store change together, and the table is what makes the store meaningful. |
| `engine/ui/configuration_panel.py` (modify) | Two new callbacks, the `reset:<section>` action, two new focusables. No knowledge of the store. |
| `native/assets/ui-cef/js/configuration_panel.js` (modify) | Reset rows for the Graphics and Gameplay tabs, mirroring the Python focusable list. |
| `engine/host_loop.py` (modify, ~line 7236) | Wire the store: load, `apply_all`, pass callbacks and snapshot to the panel. |
| `.gitignore` (modify) | Ignore the runtime files. |
| `tests/unit/test_settings_store.py` (new) | Store I/O and the table (Tasks 1–2). |
| `tests/unit/test_settings_swap_survival.py` (new) | `reset_sdk_globals()` must not clear persisted state (Task 4). |
| `tests/unit/test_configuration_panel.py` (modify) | Panel callback and reset behaviour (Task 3). |

---

### Task 1: `SettingsStore` — JSON file I/O

The dumb half: section/key addressed, knows nothing about which settings exist.

**Files:**
- Create: `engine/settings_store.py`
- Test: `tests/unit/test_settings_store.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `SCHEMA_VERSION: int = 1`
  - `default_settings_path() -> pathlib.Path` — `<project root>/settings.json`
  - `class SettingsStore:`
    - `__init__(self, path: str | Path | None = None)`
    - `load(self) -> None`
    - `has(self, section: str, key: str) -> bool`
    - `get(self, section: str, key: str, default=None)`
    - `set(self, section: str, key: str, value) -> None` — writes through immediately
    - `reset_section(self, section: str) -> None` — deletes the section, writes through

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_settings_store.py`:

```python
"""SettingsStore — JSON persistence for Dauntless settings.

Section/key addressed and table-agnostic; the SETTINGS table lives in the
same module but these tests exercise only the file I/O half.

Spec: docs/superpowers/specs/2026-09-05-settings-persistence-design.md
"""
import json
import stat

import pytest

from engine.settings_store import SCHEMA_VERSION, SettingsStore


def _store(tmp_path):
    return SettingsStore(path=tmp_path / "settings.json")


def test_round_trip_through_a_fresh_store(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "camera_shake", False)

    reloaded = _store(tmp_path)
    reloaded.load()
    assert reloaded.get("graphics", "camera_shake") is False


def test_missing_file_loads_clean(tmp_path):
    s = _store(tmp_path)
    s.load()                          # file does not exist
    assert s.has("graphics", "smaa") is False
    assert s.get("graphics", "smaa") is None


def test_corrupt_file_is_quarantined_and_load_does_not_raise(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json at all")
    s = SettingsStore(path=path)
    s.load()

    assert s.has("graphics", "smaa") is False
    assert (tmp_path / "settings.json.corrupt").exists()
    assert (tmp_path / "settings.json.corrupt").read_text() == "{not json at all"


def test_non_object_json_is_also_treated_as_corrupt(tmp_path):
    # Valid JSON, wrong shape — a bare list would explode on .get() later.
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]")
    s = SettingsStore(path=path)
    s.load()

    assert s.has("graphics", "smaa") is False
    assert (tmp_path / "settings.json.corrupt").exists()


def test_unknown_sections_and_keys_survive_a_save(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "version": SCHEMA_VERSION,
        "graphics": {"smaa": True, "future_knob": 7},
        "paths": {"game_dir": "/somewhere"},
    }))
    s = SettingsStore(path=path)
    s.load()
    s.set("graphics", "smaa", False)

    on_disk = json.loads(path.read_text())
    assert on_disk["graphics"]["future_knob"] == 7
    assert on_disk["paths"] == {"game_dir": "/somewhere"}
    assert on_disk["graphics"]["smaa"] is False


def test_a_newer_schema_version_is_not_downgraded(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"version": SCHEMA_VERSION + 5,
                                "graphics": {"smaa": True}}))
    s = SettingsStore(path=path)
    s.load()
    assert s.get("graphics", "smaa") is True     # known keys still read
    s.set("graphics", "dust", False)

    assert json.loads(path.read_text())["version"] == SCHEMA_VERSION + 5


def test_reset_section_deletes_it(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    s.set("gameplay", "subtitles", False)

    s.reset_section("graphics")

    assert s.has("graphics", "smaa") is False
    assert s.has("gameplay", "subtitles") is True
    assert "graphics" not in json.loads((tmp_path / "settings.json").read_text())


def test_set_leaves_no_temp_file_behind(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]


def test_unwritable_location_does_not_raise(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    s = SettingsStore(path=ro / "settings.json")
    s.load()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)          # read + execute, no write
    try:
        s.set("graphics", "smaa", False)            # must not raise
        assert s.get("graphics", "smaa") is False   # in-memory value still holds
    finally:
        ro.chmod(stat.S_IRWXU)                      # restore so tmp_path cleans up
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_settings_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.settings_store'`

- [ ] **Step 3: Write the store**

Create `engine/settings_store.py`:

```python
"""Dauntless settings persistence — JSON, loaded at boot, written on change.

Deliberately NOT BC's Options.cfg. TGConfigMapping.SaveConfigFile dumps the
entire in-memory map, and SDK code saves that global at times we don't control
(QuickBattle.py:1202, host_loop.py:5055) — sharing it means our settings get
written by code we don't own.

SettingsStore is section/key addressed and knows nothing about which settings
exist; the SETTINGS table (added alongside it) supplies that.

The "paths" section is RESERVED for the bootstrap tier — where the player's BC
install lives, which has to be readable before anything boots. Nothing writes
or reads it yet; game/ and sdk/ are still hardcoded to PROJECT_ROOT in
host_loop. It is reserved here so the schema never has to change when that
lands, and unknown-section preservation means an older build cannot destroy it.

Spec: docs/superpowers/specs/2026-09-05-settings-persistence-design.md
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from engine import dev_mode

SCHEMA_VERSION = 1

# engine/settings_store.py -> engine/ -> <project root>, matching
# host_loop.PROJECT_ROOT. Kept local rather than imported so the store has no
# dependency on the host loop.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_settings_path() -> Path:
    """Where settings.json lives. A function, not a constant, because this is
    the single seam that has to move if the file ever needs a per-user OS
    config directory — an installed game's own directory may be read-only."""
    return PROJECT_ROOT / "settings.json"


class SettingsStore:
    """INI-shaped JSON: {"version": N, "<section>": {"<key>": value}}.

    The loaded document is retained whole, so unknown sections and unknown
    keys survive a save — an older build cannot silently eat a newer build's
    settings.
    """

    def __init__(self, path=None):
        self._path = Path(path) if path is not None else default_settings_path()
        self._doc: dict = {"version": SCHEMA_VERSION}

    # ── Load ────────────────────────────────────────────────────────────────
    def load(self) -> None:
        """Read the file. Missing is normal; corrupt is quarantined.

        A corrupt file is renamed to <name>.corrupt rather than deleted, so it
        survives for inspection AND the next save isn't blocked by it.
        """
        self._doc = {"version": SCHEMA_VERSION}
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            dev_mode.log_swallowed("SettingsStore.load read", exc)
            return
        try:
            doc = json.loads(raw)
            if not isinstance(doc, dict):
                raise ValueError("settings root is %s, not an object"
                                 % type(doc).__name__)
        except (ValueError, TypeError) as exc:
            dev_mode.log_swallowed("SettingsStore.load parse", exc)
            self._quarantine()
            return
        self._doc = doc

    def _quarantine(self) -> None:
        try:
            os.replace(self._path,
                       self._path.parent / (self._path.name + ".corrupt"))
        except OSError as exc:
            dev_mode.log_swallowed("SettingsStore quarantine", exc)

    # ── Access ──────────────────────────────────────────────────────────────
    def _section(self, section: str) -> dict:
        got = self._doc.get(section)
        return got if isinstance(got, dict) else {}

    def has(self, section: str, key: str) -> bool:
        return key in self._section(section)

    def get(self, section: str, key: str, default=None):
        return self._section(section).get(key, default)

    # ── Mutation (write-through) ────────────────────────────────────────────
    def set(self, section: str, key: str, value) -> None:
        got = self._doc.get(section)
        if not isinstance(got, dict):
            got = {}
            self._doc[section] = got
        got[key] = value
        self._save()

    def reset_section(self, section: str) -> None:
        self._doc.pop(section, None)
        self._save()

    # ── Write ───────────────────────────────────────────────────────────────
    def _save(self) -> None:
        """Temp file + os.replace, so a crash mid-write can't truncate it.

        setdefault (not assignment) on version: a file stamped NEWER than us
        keeps its stamp, so a downgrade doesn't relabel a newer document.
        A failed write is logged and swallowed — the in-memory settings stay
        live and the game keeps running.
        """
        self._doc.setdefault("version", SCHEMA_VERSION)
        tmp = self._path.parent / (self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._doc, indent=2) + "\n",
                           encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            dev_mode.log_swallowed("SettingsStore.save", exc)
            try:
                tmp.unlink()
            except OSError:
                pass
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_settings_store.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/settings_store.py tests/unit/test_settings_store.py
git commit -m "feat(settings): add SettingsStore — atomic JSON with corrupt quarantine

Section/key addressed and table-agnostic. The loaded document is retained
whole so unknown sections and keys survive a save, which is what stops an
older build eating a newer one's settings — and what makes the reserved
paths section safe to add later.

A corrupt file is renamed to .corrupt rather than deleted: it survives for
inspection and the next save is not blocked by it. Version uses setdefault,
so a file stamped newer than us keeps its stamp.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The `SETTINGS` table, context, and apply/snapshot/reset functions

The half that knows what a setting *is*: its section, default, coercion, and which appliers it drives.

**Files:**
- Modify: `engine/settings_store.py` (append)
- Test: `tests/unit/test_settings_store.py` (append)

**Interfaces:**
- Consumes: `SettingsStore` from Task 1.
- Produces:
  - `@dataclass class SettingsContext:` fields `r`, `director`, `crew_speech`, `light_emitters`, `camera_shake`, `App`
  - `@dataclass(frozen=True) class Setting:` fields `key: str`, `section: str`, `field: str`, `kind: type`, `default`, `apply`, `lo=None`, `hi=None`
  - `SETTINGS: tuple[Setting, ...]` — ten rows
  - `setting_for(key: str) -> Setting`
  - `resolve_default(setting: Setting, ctx) -> object`
  - `apply_all(store: SettingsStore, ctx) -> None`
  - `snapshot_for_panel(store: SettingsStore, ctx) -> SettingsSnapshot`
  - `set_setting(store: SettingsStore, key: str, value) -> None`
  - `reset_and_apply_section(store: SettingsStore, ctx, section: str) -> dict` — field-keyed

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_settings_store.py`:

```python
# ── The SETTINGS table ──────────────────────────────────────────────────────

from dataclasses import fields as dataclass_fields
from unittest.mock import Mock

from engine.settings_store import (
    SETTINGS, SettingsContext, apply_all, reset_and_apply_section,
    resolve_default, set_setting, setting_for, snapshot_for_panel,
)
from engine.ui.configuration_panel import (
    FOV_MAX, MASTER_TOGGLES, SettingsSnapshot,
)


def _ctx():
    """Context of Mocks. director.fov_y_rad is a real float so the fov
    default (degrees(fov_y_rad)) resolves to a number, not a Mock."""
    import math
    ctx = SettingsContext(r=Mock(), director=Mock(), crew_speech=Mock(),
                          light_emitters=Mock(), camera_shake=Mock(), App=Mock())
    ctx.director.fov_y_rad = math.radians(45)
    ctx.camera_shake.enabled.return_value = True
    return ctx


def _calls(mock):
    """Names of the methods called on a Mock, e.g. {'set_smaa_enabled'}."""
    return {name for name, _args, _kwargs in mock.mock_calls}


# The applier each MASTER_TOGGLES member name is expected to reach:
# (SettingsContext attribute, method name).
_MEMBER_CALL = {
    "procedural_sky":      ("r", "set_procedural_sky_enabled"),
    "volumetric_nebulae":  ("r", "set_volumetric_nebulae_enabled"),
    "hdr":                 ("r", "set_hdr_enabled"),
    "filmic":              ("r", "set_filmic_enabled"),
    "motion_blur":         ("r", "set_motion_blur_enabled"),
    "hdr_lens_flare":      ("r", "set_hdr_lens_flare_enabled"),
    "rim":                 ("r", "set_rim_enabled"),
    "shadows":             ("r", "set_shadows_enabled"),
    "nebula_lightning":    ("r", "set_nebula_lightning_enabled"),
    "ship_light_emitters": ("light_emitters", "set_enabled"),
}


def test_missing_file_calls_zero_appliers(tmp_path):
    """THE guarantee: no settings.json means boot is byte-identical to today.
    An absent key must never reach its applier — the table's default exists
    only to populate the panel's display snapshot."""
    s = _store(tmp_path)
    s.load()
    ctx = _ctx()

    apply_all(s, ctx)

    for attr in ("r", "director", "crew_speech", "light_emitters",
                 "camera_shake", "App"):
        assert getattr(ctx, attr).mock_calls == [], \
            "%s was touched with no stored settings" % attr


def test_stored_keys_reach_their_appliers(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    s.set("gameplay", "ai_difficulty", 2)
    ctx = _ctx()

    apply_all(s, ctx)

    ctx.r.set_smaa_enabled.assert_called_once_with(False)
    ctx.App.Game_SetDifficulty.assert_called_once_with(2)
    ctx.crew_speech.set_subtitles_enabled.assert_not_called()   # not stored


def test_fov_applies_in_radians(tmp_path):
    import math
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "fov_deg", 30)
    ctx = _ctx()

    apply_all(s, ctx)

    (called_rad,), _kwargs = ctx.director.set_fov.call_args
    assert called_rad == pytest.approx(math.radians(30))


def test_out_of_range_int_is_clamped(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "fov_deg", 999)
    ctx = _ctx()

    apply_all(s, ctx)

    (called_rad,), _kwargs = ctx.director.set_fov.call_args
    import math
    assert called_rad == pytest.approx(math.radians(FOV_MAX))


def test_uncoercible_value_is_treated_as_absent(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("gameplay", "ai_difficulty", "banana")
    ctx = _ctx()

    apply_all(s, ctx)

    ctx.App.Game_SetDifficulty.assert_not_called()


def test_every_snapshot_field_has_exactly_one_setting_row():
    """Adding a toggle to SettingsSnapshot without a SETTINGS row ships a
    control that silently forgets. Same bug class the JS focusables test
    guards on the other side."""
    snapshot_fields = {f.name for f in dataclass_fields(SettingsSnapshot)}
    table_fields = [s.field for s in SETTINGS]
    assert sorted(table_fields) == sorted(snapshot_fields)
    assert len(table_fields) == len(set(table_fields))


def test_every_setting_key_is_unique_and_in_a_known_section():
    keys = [s.key for s in SETTINGS]
    assert len(keys) == len(set(keys))
    assert {s.section for s in SETTINGS} == {"graphics", "gameplay"}


def test_master_fan_out_matches_the_panel_master_table():
    """MASTER_TOGGLES is the panel's own grouping. If the store's fan-out
    drifts from it, a master row toggles a different set of effects than the
    one the player sees described."""
    for key, _label, members in MASTER_TOGGLES:
        ctx = _ctx()
        setting_for(key).apply(ctx, True)
        expected = {}
        for m in members:
            attr, method = _MEMBER_CALL[m]
            expected.setdefault(attr, set()).add(method)
        for attr in ("r", "light_emitters"):
            assert _calls(getattr(ctx, attr)) == expected.get(attr, set()), \
                "master %r fan-out drifted on ctx.%s" % (key, attr)


def test_snapshot_uses_stored_value_where_present_and_default_where_absent(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    ctx = _ctx()
    ctx.camera_shake.enabled.return_value = False   # live getter default

    snap = snapshot_for_panel(s, ctx)

    assert snap.smaa_on is False        # stored
    assert snap.dust_on is True         # static default
    assert snap.camera_shake_on is False  # callable default, read live
    assert snap.fov_deg == 45           # callable default from director


def test_snapshot_does_not_call_any_applier(tmp_path):
    """Building the panel's display state must not mutate the engine."""
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    ctx = _ctx()

    snapshot_for_panel(s, ctx)

    assert ctx.r.mock_calls == []
    assert ctx.director.set_fov.called is False


def test_set_setting_writes_to_the_right_section(tmp_path):
    s = _store(tmp_path)
    s.load()
    set_setting(s, "subtitles", False)
    assert s.get("gameplay", "subtitles") is False


def test_reset_and_apply_section_deletes_reapplies_and_returns_fields(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    s.set("gameplay", "subtitles", False)
    ctx = _ctx()

    out = reset_and_apply_section(s, ctx, "graphics")

    assert s.has("graphics", "smaa") is False         # section gone
    assert s.has("gameplay", "subtitles") is True     # other section untouched
    assert out["smaa_on"] is True                     # field-keyed, default value
    assert "subtitles_on" not in out
    ctx.r.set_smaa_enabled.assert_called_once_with(True)   # engine re-applied


def test_resolve_default_handles_values_and_callables():
    ctx = _ctx()
    assert resolve_default(setting_for("dust"), ctx) is True
    assert resolve_default(setting_for("fov_deg"), ctx) == 45
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_settings_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'SETTINGS' from 'engine.settings_store'`

- [ ] **Step 3: Append the table and functions**

Append to `engine/settings_store.py`:

```python
# ── The settings table ──────────────────────────────────────────────────────
import math
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class SettingsContext:
    """The live objects the appliers act on, bundled so the table's lambdas
    close over no globals and the module is testable headless."""
    r: Any                # renderer binding module
    director: Any         # engine.cameras director
    crew_speech: Any      # engine.appc.crew_speech
    light_emitters: Any   # engine.appc.light_emitters
    camera_shake: Any     # engine.appc.camera_shake
    App: Any              # the App shim


@dataclass(frozen=True)
class Setting:
    """One persisted setting. The row is the whole spec for that setting.

    `field` is the SettingsSnapshot attribute name, which is NOT derivable
    from `key` — fov_deg and ai_difficulty carry no `_on` suffix.
    `default` is a value or a callable(ctx); it feeds the panel's display
    snapshot only, never an applier.
    """
    key: str
    section: str
    field: str
    kind: type                       # bool or int
    default: Any
    apply: Callable[[Any, Any], None]
    lo: Optional[int] = None
    hi: Optional[int] = None


def _fan(*appliers):
    """Compose several appliers into the single `apply` a master row needs."""
    def _apply(ctx, value):
        for fn in appliers:
            fn(ctx, value)
    return _apply


SETTINGS: tuple = (
    Setting("smaa", "graphics", "smaa_on", bool, True,
            lambda c, v: c.r.set_smaa_enabled(v)),
    Setting("dust", "graphics", "dust_on", bool, True,
            lambda c, v: c.r.set_dust_enabled(v)),
    Setting("fov_deg", "graphics", "fov_deg", int,
            lambda c: int(round(math.degrees(c.director.fov_y_rad))),
            lambda c, v: c.director.set_fov(math.radians(v)),
            lo=25, hi=55),
    Setting("improved_space", "graphics", "improved_space_on", bool, True,
            _fan(lambda c, v: c.r.set_procedural_sky_enabled(v),
                 lambda c, v: c.r.set_volumetric_nebulae_enabled(v))),
    Setting("camera_realism", "graphics", "camera_realism_on", bool, True,
            _fan(lambda c, v: c.r.set_hdr_enabled(v),
                 lambda c, v: c.r.set_filmic_enabled(v),
                 lambda c, v: c.r.set_motion_blur_enabled(v),
                 lambda c, v: c.r.set_hdr_lens_flare_enabled(v))),
    Setting("realistic_lighting", "graphics", "realistic_lighting_on", bool, True,
            _fan(lambda c, v: c.r.set_rim_enabled(v),
                 lambda c, v: c.r.set_shadows_enabled(v),
                 lambda c, v: c.r.set_nebula_lightning_enabled(v),
                 lambda c, v: c.light_emitters.set_enabled(v))),
    Setting("camera_shake", "graphics", "camera_shake_on", bool,
            lambda c: c.camera_shake.enabled(),
            lambda c, v: c.camera_shake.set_enabled(v)),
    Setting("subtitles", "gameplay", "subtitles_on", bool, True,
            lambda c, v: c.crew_speech.set_subtitles_enabled(v)),
    Setting("disable_annoying_dialogue", "gameplay",
            "disable_annoying_dialogue_on", bool, True,
            lambda c, v: c.crew_speech.set_annoying_dialogue_disabled(v)),
    Setting("ai_difficulty", "gameplay", "ai_difficulty", int, 1,
            lambda c, v: c.App.Game_SetDifficulty(v),
            lo=0, hi=2),
)

_BY_KEY = {s.key: s for s in SETTINGS}


def setting_for(key: str) -> Setting:
    return _BY_KEY[key]


def resolve_default(setting: Setting, ctx) -> Any:
    return setting.default(ctx) if callable(setting.default) else setting.default


def _coerce(setting: Setting, raw):
    """Stored value -> usable value. Raises ValueError if unusable, which
    callers treat as 'key absent' rather than substituting a default."""
    if setting.kind is bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int):        # tolerate 0/1 from a hand-edited file
            return bool(raw)
        raise ValueError("not a boolean: %r" % (raw,))
    if setting.kind is int:
        if isinstance(raw, bool):       # bool is an int subclass; reject it here
            raise ValueError("boolean where int expected: %r" % (raw,))
        value = int(raw)                # raises ValueError/TypeError on junk
        if setting.lo is not None:
            value = max(setting.lo, value)
        if setting.hi is not None:
            value = min(setting.hi, value)
        return value
    raise ValueError("unhandled kind %r" % (setting.kind,))


def _stored(store: SettingsStore, setting: Setting):
    """(present, value). Absent, or present but uncoercible, -> (False, None)."""
    if not store.has(setting.section, setting.key):
        return False, None
    try:
        return True, _coerce(setting, store.get(setting.section, setting.key))
    except (ValueError, TypeError) as exc:
        dev_mode.log_swallowed("settings coerce %r" % (setting.key,), exc)
        return False, None


def apply_all(store: SettingsStore, ctx) -> None:
    """Apply every STORED setting. An absent key never reaches its applier —
    that is what makes a first launch byte-identical to today."""
    for setting in SETTINGS:
        present, value = _stored(store, setting)
        if present:
            setting.apply(ctx, value)


def snapshot_for_panel(store: SettingsStore, ctx):
    """Build the panel's display state. Reads only — touches no applier."""
    from engine.ui.configuration_panel import SettingsSnapshot
    values = {}
    for setting in SETTINGS:
        present, value = _stored(store, setting)
        values[setting.field] = value if present else resolve_default(setting, ctx)
    return SettingsSnapshot(**values)


def set_setting(store: SettingsStore, key: str, value) -> None:
    """Key-addressed write. The store is section/key addressed and only the
    table knows a key's section, so the panel's on_change binds to this."""
    setting = setting_for(key)
    store.set(setting.section, setting.key, value)


def reset_and_apply_section(store: SettingsStore, ctx, section: str) -> dict:
    """Drop a section, re-apply its defaults to the engine, and return
    {SettingsSnapshot field: value} so the panel can setattr the result.

    Deleting rather than writing defaults is deliberate: it returns the player
    to genuine first-launch behaviour rather than to our transcription of it.
    """
    store.reset_section(section)
    out = {}
    for setting in SETTINGS:
        if setting.section != section:
            continue
        value = resolve_default(setting, ctx)
        setting.apply(ctx, value)
        out[setting.field] = value
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_settings_store.py -v`
Expected: PASS (22 tests total)

- [ ] **Step 5: Commit**

```bash
git add engine/settings_store.py tests/unit/test_settings_store.py
git commit -m "feat(settings): add the SETTINGS table, apply_all, and snapshot

One row per persisted setting carrying its section, snapshot field, default,
bounds and applier fan-out. `field` is explicit because it is not derivable
from `key` — fov_deg and ai_difficulty carry no _on suffix.

The load-time rule is enforced in apply_all: an absent key never reaches its
applier, so a missing settings.json leaves boot byte-identical to today. A
present-but-uncoercible value is treated as absent rather than silently
substituted, and an out-of-range int clamps.

Two drift guards: every SettingsSnapshot field must have exactly one row, and
each master's fan-out is pinned against the panel's own MASTER_TOGGLES.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Panel callbacks, the reset action, and the JS rows

**Files:**
- Modify: `engine/ui/configuration_panel.py`
- Modify: `native/assets/ui-cef/js/configuration_panel.js`
- Test: `tests/unit/test_configuration_panel.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–2 (the panel never imports the store).
- Produces:
  - `ConfigurationPanel.__init__` gains `on_change: Callable[[str, Any], None] = None` and `on_reset: Callable[[str], dict] = None`, both defaulting to no-ops.
  - Action `reset:<section>` for `section in ("graphics", "gameplay")`.
  - Focusables `("ctrl", "reset_graphics")` and `("ctrl", "reset_gameplay")`, last in their tab.
  - JS const `CP_RESET_TARGETS = {graphics: 'reset_graphics', gameplay: 'reset_gameplay'}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_configuration_panel.py`:

```python
# ── persistence callbacks + per-tab reset ───────────────────────────────────

def test_toggle_reports_the_change_once_with_key_and_value():
    on_change = Mock()
    p, _ = _make(on_change=on_change)
    p.dispatch_event("toggle:smaa")
    on_change.assert_called_once_with("smaa", False)


def test_fov_reports_the_change_with_the_clamped_degree_value():
    on_change = Mock()
    p, _ = _make(on_change=on_change)
    p.dispatch_event("fov:999")
    on_change.assert_called_once_with("fov_deg", 55)


def test_ai_difficulty_reports_the_change():
    on_change = Mock()
    p, _ = _make(tabs=[("gameplay", "Gameplay")], on_change=on_change)
    p.dispatch_event("ai_difficulty:2")
    on_change.assert_called_once_with("ai_difficulty", 2)


def test_master_toggle_reports_the_master_key_not_its_members():
    on_change = Mock()
    p, _ = _make(on_change=on_change)
    p.dispatch_event("toggle:improved_space")
    on_change.assert_called_once_with("improved_space", False)


def test_every_toggleable_row_reports_a_change():
    """A branch that flips state but never calls on_change is a control that
    silently forgets. Cover them all rather than the two that were easy."""
    cases = [
        ("toggle:smaa", "smaa"),
        ("toggle:dust", "dust"),
        ("toggle:camera_shake", "camera_shake"),
        ("toggle:subtitles", "subtitles"),
        ("toggle:disable_annoying_dialogue", "disable_annoying_dialogue"),
    ] + [("toggle:" + k, k) for k in MASTER_KEYS]
    for action, key in cases:
        on_change = Mock()
        p, _ = _make(on_change=on_change)
        p.dispatch_event(action)
        assert on_change.call_count == 1, "%s did not report" % action
        assert on_change.call_args[0][0] == key


def test_a_raising_applier_does_not_report_a_change():
    """Ordering is load-bearing: appliers first, setattr second, persistence
    third. If an applier throws, nothing may be written — otherwise the file
    records a value the engine is not on."""
    boom = Mock(side_effect=RuntimeError("renderer said no"))
    on_change = Mock()
    p, _ = _make(set_smaa=boom, on_change=on_change)
    with pytest.raises(RuntimeError):
        p.dispatch_event("toggle:smaa")
    on_change.assert_not_called()


def test_reset_graphics_writes_returned_fields_into_settings():
    on_reset = Mock(return_value={"smaa_on": False, "fov_deg": 30})
    p, _ = _make(on_reset=on_reset)
    assert p.dispatch_event("reset:graphics") is True
    on_reset.assert_called_once_with("graphics")
    assert p._settings.smaa_on is False
    assert p._settings.fov_deg == 30


def test_reset_unknown_section_returns_false():
    on_reset = Mock(return_value={})
    p, _ = _make(on_reset=on_reset)
    assert p.dispatch_event("reset:nonsense") is False
    on_reset.assert_not_called()


def test_reset_row_is_last_focusable_on_graphics():
    p, _ = _make()
    assert p._focusables()[-1] == ("ctrl", "reset_graphics")


def test_reset_row_is_last_focusable_on_gameplay():
    p, _ = _make(tabs=[("gameplay", "Gameplay")])
    assert p._focusables()[-1] == ("ctrl", "reset_gameplay")


def test_space_on_the_graphics_reset_row_dispatches_reset():
    on_reset = Mock(return_value={})
    p, _ = _make(on_reset=on_reset)
    p.open()
    r = _FakeReader()
    p._focused = p._focusables().index(("ctrl", "reset_graphics"))
    r.press(r.keys.KEY_SPACE)
    p.handle_input(r)
    on_reset.assert_called_once_with("graphics")


def test_panel_constructs_without_the_persistence_callbacks():
    """Existing construction sites and tests must keep working."""
    p, _ = _make()
    assert p.dispatch_event("toggle:smaa") is True     # no-op on_change
    assert p.dispatch_event("reset:graphics") is True  # no-op on_reset


def test_js_gameplay_reset_row_exists():
    assert "reset_gameplay" in _js_source()
```

Then update the existing JS parity test in the same file so it accounts for the new trailing reset row — replace the body of `test_js_graphics_focusables_match_python` with:

```python
def test_js_graphics_focusables_match_python():
    """configuration_panel.js composes its focusable list the same way Python
    does — standalones, masters, trailing rows, then the reset row — but by
    hand. If the two drift, keyboard focus highlights one row while Space
    toggles another."""
    import re
    standalone = re.search(r"CP_GRAPHICS_STANDALONE = \[(.*?)\];", _js_source(), re.S)
    assert standalone, "CP_GRAPHICS_STANDALONE not found"
    trailing = re.search(r"CP_GRAPHICS_TRAILING = \[(.*?)\];", _js_source(), re.S)
    assert trailing, "CP_GRAPHICS_TRAILING not found"
    resets = re.search(r"CP_RESET_TARGETS = \{(.*?)\};", _js_source(), re.S)
    assert resets, "CP_RESET_TARGETS not found"
    graphics_reset = re.search(r"graphics:\s*'(\w+)'", resets.group(1))
    assert graphics_reset, "CP_RESET_TARGETS has no graphics entry"
    js_targets = (re.findall(r"'(\w+)'", standalone.group(1))
                  + _js_master_keys()
                  + re.findall(r"\['(\w+)',", trailing.group(1))
                  + [graphics_reset.group(1)])
    p, _ = _make()
    assert js_targets == [t for kind, t in p._focusables() if kind == "ctrl"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_configuration_panel.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'on_change'`, plus the parity test failing on the missing `CP_RESET_TARGETS`.

- [ ] **Step 3a: Wire the panel**

In `engine/ui/configuration_panel.py`, add the two params to `__init__` (after `input_map=None`):

```python
                 input_map=None,
                 on_change: Optional[Callable[[str, object], None]] = None,
                 on_reset: Optional[Callable[[str], dict]] = None):
```

and, beside the other assignments in `__init__`:

```python
        # Persistence seam. Defaults are no-ops so the panel works standalone
        # and every existing construction site keeps compiling. The panel never
        # imports the settings store — the host loop binds these.
        self._on_change = on_change or (lambda key, value: None)
        self._on_reset = on_reset or (lambda section: {})
```

Add `self._on_change(...)` as the LAST statement of each mutation branch in `dispatch_event`, keeping the existing applier-then-setattr order:

- master loop, after `setattr(self._settings, key + "_on", new_val)`: `self._on_change(key, new_val)`
- `toggle:camera_shake`: `self._on_change("camera_shake", new_val)`
- `toggle:dust`: `self._on_change("dust", new_val)`
- `toggle:smaa`: `self._on_change("smaa", new_val)`
- `toggle:subtitles`: `self._on_change("subtitles", new_val)`
- `toggle:disable_annoying_dialogue`: `self._on_change("disable_annoying_dialogue", new_val)`
- `ai_difficulty:` branch, after `self._settings.ai_difficulty = level`: `self._on_change("ai_difficulty", level)`
- `fov:` branch, after `self._settings.fov_deg = deg`: `self._on_change("fov_deg", deg)`

Add the reset branch to `dispatch_event`, immediately before the `tab:` branch:

```python
        if action.startswith("reset:"):
            # Per-tab reset. Scoped rather than global so a fat-finger can't
            # wipe keybindings, which the Controls tab resets on its own.
            section = action[len("reset:"):]
            if section not in ("graphics", "gameplay"):
                return False
            for field, value in self._on_reset(section).items():
                setattr(self._settings, field, value)
            return True
```

Add the focusables in `_focusables()` — as the final entry of each branch:

```python
        if self._selected_tab == "graphics":
            out += [("ctrl", "smaa"), ("ctrl", "dust"), ("ctrl", "fov")]
            out += [("ctrl", k) for k in MASTER_KEYS]
            out += [("ctrl", "camera_shake")]
            out += [("ctrl", "reset_graphics")]
        elif self._selected_tab == "gameplay":
            out += [("ctrl", "subtitles"),
                    ("ctrl", "disable_annoying_dialogue"),
                    ("ctrl", "ai_difficulty"),
                    ("ctrl", "reset_gameplay")]
```

And handle activation in `handle_input`, beside the existing `controls_reset` branch:

```python
        elif activate and kind == "ctrl" and target == "reset_graphics":
            self.dispatch_event("reset:graphics")
        elif activate and kind == "ctrl" and target == "reset_gameplay":
            self.dispatch_event("reset:gameplay")
```

Finally update the module docstring — the line "Settings are not persisted across launches." is now false. Replace that sentence with:

```
Settings persist across launches via engine.settings_store: the host loop
loads the store, applies stored values, and binds on_change/on_reset. The
panel itself never imports the store.
```

- [ ] **Step 3b: Wire the JS**

In `native/assets/ui-cef/js/configuration_panel.js`, after `CP_GRAPHICS_TRAILING`:

```js
// Per-tab "Reset to Defaults" rows. Scoped, not global: the Controls tab
// resets its own bindings, so a fat-finger here can't wipe them.
const CP_RESET_TARGETS = {graphics: 'reset_graphics', gameplay: 'reset_gameplay'};
```

Extend `CP_GRAPHICS_CTRLS` with the reset target:

```js
const CP_GRAPHICS_CTRLS = CP_GRAPHICS_STANDALONE
    .concat(CP_MASTERS.map(m => m[0]))
    .concat(CP_GRAPHICS_TRAILING.map(t => t[0]))
    .concat([CP_RESET_TARGETS.graphics]);
```

Add the shared row renderer beside `_cpToggleRow`:

```js
// One "Reset to Defaults" row, dispatching configuration/reset:<section>.
function _cpResetRow(section, isFocused) {
    return '<hr class="cp-divider">'
         + '<div class="cp-row' + (isFocused ? ' cp-focused' : '') + '">'
         +   '<span class="cp-label">Reset to Defaults</span>'
         +   '<button class="cp-toggle"'
         +      ' onclick="dauntlessEvent(\'configuration/reset:' + section + '\')">Reset</button>'
         + '</div>';
}
```

In `_cpFocusableList`, push the gameplay reset last in its branch:

```js
    } else if (state.selected_tab === 'gameplay') {
        out.push({kind: 'ctrl', target: 'subtitles'});
        out.push({kind: 'ctrl', target: 'disable_annoying_dialogue'});
        out.push({kind: 'ctrl', target: 'ai_difficulty'});
        out.push({kind: 'ctrl', target: CP_RESET_TARGETS.gameplay});
    } else if (state.selected_tab === 'controls') {
```

Append the row at the end of `_cpRenderGraphicsBody`, after the `CP_GRAPHICS_TRAILING.forEach` block and before its `return html;`:

```js
    html += _cpResetRow('graphics',
                        focused.kind === 'ctrl'
                        && focused.target === CP_RESET_TARGETS.graphics);
```

and at the end of `_cpRenderGameplayBody` (before its `return html;`):

```js
    html += _cpResetRow('gameplay',
                        focused.kind === 'ctrl'
                        && focused.target === CP_RESET_TARGETS.gameplay);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_configuration_panel.py -v`
Expected: PASS — all existing tests plus the 13 new ones.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/configuration_panel.py native/assets/ui-cef/js/configuration_panel.js tests/unit/test_configuration_panel.py
git commit -m "feat(config-panel): report changes and add per-tab Reset to Defaults

Two callbacks, both defaulting to no-ops so existing construction sites and
tests are untouched. on_change fires LAST in each branch — appliers, then
setattr, then persistence — so a raising applier can never write a value the
engine is not on; a test pins that ordering.

Reset is per-tab rather than global: the Controls tab already resets its own
bindings, and a single global row would let a fat-finger wipe keybindings
someone spent time on. Both the Python focusable list and the JS one gain the
row, kept in lockstep by the existing parity test.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Host-loop wiring, swap-survival guard, gitignore

**Files:**
- Modify: `engine/host_loop.py:7233-7290` (the `ConfigurationPanel` construction block)
- Modify: `.gitignore:327-332`
- Create: `tests/unit/test_settings_swap_survival.py`

**Interfaces:**
- Consumes: `SettingsStore`, `SettingsContext`, `apply_all`, `snapshot_for_panel`, `set_setting`, `reset_and_apply_section` from Tasks 1–2; `on_change` / `on_reset` from Task 3.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_settings_swap_survival.py`:

```python
"""Persisted settings must survive an in-process mission swap.

reset_sdk_globals() runs on every swap and its docstring asks that the list
be kept "in lockstep with what the SDK actually mutates" — so a future entry
could clear one of these and silently turn persistence back into session-only
state. Nothing else in the suite would catch that.

Covers the Python-side state only. The four pure-renderer flags (smaa, dust,
and the improved_space / camera_realism members) live in C++ with no headless
getter; their survival rests on reset_sdk_globals touching only
render_instances, plus a live check.

Spec: docs/superpowers/specs/2026-09-05-settings-persistence-design.md
"""
import math

from engine.appc import camera_shake, crew_speech, light_emitters
from engine.cameras.director import _CameraDirector
from engine.core import game as game_mod
from engine.host_loop import reset_sdk_globals


def test_reset_sdk_globals_preserves_persisted_settings():
    saved = (game_mod._difficulty,
             crew_speech._subtitles_enabled,
             crew_speech._annoying_dialogue_disabled,
             camera_shake.enabled(),
             light_emitters.enabled())
    director = _CameraDirector()
    try:
        # Dirty every piece of persisted Python-side state.
        game_mod.Game_SetDifficulty(2)
        crew_speech.set_subtitles_enabled(False)
        crew_speech.set_annoying_dialogue_disabled(False)
        camera_shake.set_enabled(False)
        light_emitters.set_enabled(False)
        director.set_fov(math.radians(25))

        reset_sdk_globals()

        assert game_mod.Game_GetDifficulty() == 2
        assert crew_speech.subtitles_enabled() is False
        assert crew_speech.annoying_dialogue_disabled() is False
        assert camera_shake.enabled() is False
        assert light_emitters.enabled() is False
        assert director.fov_y_rad == math.radians(25)
    finally:
        # These are module globals; the conftest autouse reset does not cover
        # them, so leaving them dirty would pollute every later test.
        game_mod.Game_SetDifficulty(saved[0])
        crew_speech.set_subtitles_enabled(saved[1])
        crew_speech.set_annoying_dialogue_disabled(saved[2])
        camera_shake.set_enabled(saved[3])
        light_emitters.set_enabled(saved[4])
```

- [ ] **Step 2: Run the test to verify it passes or fails honestly**

Run: `uv run pytest tests/unit/test_settings_swap_survival.py -v`
Expected: PASS on the first run. This test characterises behaviour that already holds — it is a regression guard, not a red-green cycle. If it FAILS, stop: the spec's survival analysis is wrong and the design needs revisiting before wiring anything.

- [ ] **Step 3: Wire the host loop**

In `engine/host_loop.py`, replace the comment block and `initial_settings=` argument at the `ConfigurationPanel` construction (currently lines ~7233-7270). The comment currently claims "Settings apply live; no persistence" and the snapshot is reconstructed from renderer getters, several of which do not exist. Replace with:

```python
        # Configuration panel — production-visible pause-menu modal.
        # Settings persist across launches via engine.settings_store: the
        # store loads, apply_all pushes every STORED value through the same
        # appliers the panel uses (an absent key is never applied, so a
        # missing settings.json leaves boot on the engine's own defaults),
        # and snapshot_for_panel builds the panel's display state. This
        # replaces reconstructing the snapshot from renderer getters —
        # several of those do not exist, so the old snapshot asserted
        # smaa_on/dust_on were True without reading anything.
        from engine.ui.configuration_panel import ConfigurationPanel
        from engine.appc import crew_speech as _crew_speech
        from engine.appc import light_emitters as _light_emitters
        from engine.appc import camera_shake as _camera_shake
        from engine import settings_store as _settings
        _store = _settings.SettingsStore()
        _store.load()
        _settings_ctx = _settings.SettingsContext(
            r=r, director=director, crew_speech=_crew_speech,
            light_emitters=_light_emitters, camera_shake=_camera_shake, App=App,
        )
        _settings.apply_all(_store, _settings_ctx)
        configuration_panel = ConfigurationPanel(
            tabs=[("graphics", "Graphics"), ("gameplay", "Gameplay"),
                  ("controls", "Controls")],
            initial_settings=_settings.snapshot_for_panel(_store, _settings_ctx),
            on_change=lambda key, value: _settings.set_setting(_store, key, value),
            on_reset=lambda section: _settings.reset_and_apply_section(
                _store, _settings_ctx, section),
            set_dust=r.set_dust_enabled,
            set_hdr=r.set_hdr_enabled,
            set_rim=r.set_rim_enabled,
            set_smaa=r.set_smaa_enabled,
            set_subtitles=_crew_speech.set_subtitles_enabled,
            set_disable_annoying_dialogue=_crew_speech.set_annoying_dialogue_disabled,
            set_ai_difficulty=App.Game_SetDifficulty,
            set_fov_rad=director.set_fov,
            set_shadows=r.set_shadows_enabled,
            set_procedural_sky=r.set_procedural_sky_enabled,
            set_filmic=r.set_filmic_enabled,
            set_motion_blur=r.set_motion_blur_enabled,
            set_volumetric_nebulae=r.set_volumetric_nebulae_enabled,
            set_nebula_lightning=r.set_nebula_lightning_enabled,
            set_hdr_lens_flare=r.set_hdr_lens_flare_enabled,
            set_ship_light_emitters=_light_emitters.set_enabled,
            set_camera_shake=_camera_shake.set_enabled,
            input_map=input_map,
        )
```

The `SettingsSnapshot` import at this site becomes unused — drop it from the import line, but only if nothing else in the block references it (grep first).

- [ ] **Step 4: Ignore the runtime files**

In `.gitignore`, beside the existing `/Options.cfg`, `/BCTickLog.cfg`, `/Keybindings.cfg` entries (around line 330), add:

```
/settings.json
/settings.json.corrupt
```

- [ ] **Step 5: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: PASS, or failures matching `tests/known_failures.txt` exactly. As of the last update that ledger holds zero ctest entries and one pytest entry (`test_engineer_emitters.py::test_shield_level_change_announces`, order-dependent). Any other failure is a regression from this work — do not label it pre-existing without checking the ledger. Confirm no `settings.json` was written into the repo by the test run: `git status --short` should show only the intended files.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py .gitignore tests/unit/test_settings_swap_survival.py
git commit -m "feat(settings): load, apply and persist settings at boot

Wires the store where every applier first exists at once — renderer, director,
crew_speech, light_emitters, camera_shake and App — on the production path,
not behind --developer. Settings therefore apply whether or not the player
ever opens the panel, which is why persistence could not live in the panel
itself.

This also retires the boot snapshot's guesswork: it used to hardcode
smaa_on and dust_on to True because no getter exists, so the panel reported
state it had never read.

The swap-survival test guards the Python-side values against a future
addition to reset_sdk_globals' list quietly turning persistence back into
session-only state.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Live verification (Mark only — never launch the game yourself)

Report these to Mark as the checklist once the gate is green. A green suite cannot see any of them.

1. No `settings.json` present → everything reads exactly as today.
2. Turn camera shake and subtitles off, quit, relaunch → both still off **before** opening the panel (take a hit; trigger a crew line).
3. FOV to 25, relaunch → 25 on the first frame.
4. Reset Graphics → back to stock; relaunch → still stock.
5. Hand-corrupt `settings.json` → boots on defaults, `settings.json.corrupt` appears.
6. Change difficulty, subtitles **and a renderer toggle**, then swap missions → all three still applied. This is the only check that covers the renderer flags at all, since no headless test can read them.
