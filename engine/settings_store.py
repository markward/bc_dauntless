"""Dauntless settings persistence — JSON, loaded at boot, written on change.

Deliberately NOT BC's Options.cfg. TGConfigMapping.SaveConfigFile dumps the
entire in-memory map, and SDK code saves that global at times we don't control
(QuickBattle.py:1202, host_loop.py:5055) — sharing it means our settings get
written by code we don't own.

SettingsStore is section/key addressed and knows nothing about which settings
exist; the SETTINGS table (added alongside it) supplies that.

The "paths" section holds the bootstrap tier — where the player's BC install
lives. engine/paths.py owns it; see
docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md. Unknown-section
preservation means an older build cannot destroy it.

Spec: docs/superpowers/specs/2026-09-05-settings-persistence-design.md
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from engine import dev_mode
from engine.cameras import EXTERIOR_FOV_Y_RAD
from engine.ui.configuration_panel import (
    AA_MODE_SAMPLES, AA_MSAA_8X, AA_OFF, AA_SMAA,
    FOV_MAX, FOV_MIN, SettingsSnapshot,
)

# 2: graphics.smaa_on (bool) became graphics.aa_mode (index) when SMAA and
#    MSAA merged into one mutually-exclusive selector. See _migrate.
SCHEMA_VERSION = 2

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
        self._migrate()

    def _migrate(self) -> None:
        """Bring an older document up to SCHEMA_VERSION, in place.

        Migrate UP ONLY. A file stamped newer than us belongs to a build that
        knows things we do not; rewriting its keys would corrupt them. This
        mirrors the setdefault-not-assignment rule in _save().

        Migrations do NOT save. The next set() writes the whole document
        anyway, and a load that silently rewrote the file would turn a
        read-only install into a boot failure rather than a first-change one.
        """
        try:
            stamped = int(self._doc.get("version", 1))
        except (TypeError, ValueError):
            stamped = 1
        if stamped >= SCHEMA_VERSION:
            return

        # v1 -> v2: the independent `smaa_on` bool became one mutually
        # exclusive `aa_mode` index shared with MSAA. An ABSENT smaa_on stays
        # absent — apply_all never applies an unstored key, so inventing an
        # aa_mode here would override the engine default on first launch.
        graphics = self._doc.get("graphics")
        if isinstance(graphics, dict) and "smaa_on" in graphics:
            graphics["aa_mode"] = AA_SMAA if graphics.pop("smaa_on") else AA_OFF

        self._doc["version"] = SCHEMA_VERSION

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

        NOTE: "version" is a reserved top-level key (the schema stamp, not a
        section) — a SETTINGS row with section="version" would silently
        collide with it. Unreachable today: every section comes from the
        SETTINGS table, and test_every_setting_key_is_unique_and_in_a_known_section
        pins the section set to {"graphics", "gameplay"}.
        """
        self._doc.setdefault("version", SCHEMA_VERSION)
        tmp = self._path.parent / (self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._doc, indent=2) + "\n",
                           encoding="utf-8")
            os.replace(tmp, self._path)
        except (OSError, TypeError, ValueError) as exc:
            # TypeError/ValueError: json.dumps on a non-serialisable value
            # (e.g. a stray Mock reaching store.set in a test double). Widened
            # alongside OSError so a bad value can't raise out through
            # store.set -> on_change -> the panel toggle, which would
            # contradict "a failed write does not raise" above.
            dev_mode.log_swallowed("SettingsStore.save", exc)
            try:
                tmp.unlink()
            except OSError:
                pass


# ── The settings table ──────────────────────────────────────────────────────

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

    `default` and `reset_default` answer two different questions that happen
    to coincide for most rows, which is why this table has both:
      - `default` is the panel's DISPLAY FALLBACK for an absent key — for a
        row whose live value can drift from any fixed constant (fov_deg,
        camera_shake, and the three Modern VFX masters) it is a callable(ctx)
        that reads current engine state, so the panel never reports a value
        it hasn't actually read. It feeds snapshot_for_panel only, never an
        applier.
      - `reset_default` is what "Reset to Defaults" restores — the engine's
        native, constant default. `reset_and_apply_section` uses this,
        falling back to `default` when unset (correct for every row whose
        `default` is already a plain constant).
    A row with a *callable* `default` MUST set `reset_default` explicitly:
    otherwise Reset re-resolves `default(ctx)`, which reads back whatever the
    player just set — Reset becomes a no-op that also deletes the stored
    section, so the live session and the next launch disagree about what
    Reset did. This is exactly the bug that shipped for fov_deg and
    camera_shake before `reset_default` existed.
    """
    key: str
    section: str
    field: str
    kind: type                       # bool or int
    default: Any
    apply: Callable[[Any, Any], None]
    lo: Optional[int] = None
    hi: Optional[int] = None
    reset_default: Any = None        # None means "use `default`" — see above


def _fan(*appliers):
    """Compose several appliers into the single `apply` a master row needs."""
    def _apply(ctx, value):
        for fn in appliers:
            fn(ctx, value)
    return _apply


SETTINGS: tuple = (
    # One row drives BOTH anti-aliasing engines, which is what makes them
    # mutually exclusive by construction rather than by a rule someone has to
    # remember. The fan-out lives here, not at the panel's call site.
    Setting("aa_mode", "graphics", "aa_mode", int, AA_SMAA,
            _fan(lambda c, v: c.r.set_smaa_enabled(v == AA_SMAA),
                 lambda c, v: c.r.set_msaa_samples(AA_MODE_SAMPLES[v])),
            lo=AA_OFF, hi=AA_MSAA_8X, reset_default=AA_SMAA),
    Setting("dust", "graphics", "dust_on", bool, True,
            lambda c, v: c.r.set_dust_enabled(v)),
    Setting("fov_deg", "graphics", "fov_deg", int,
            lambda c: int(round(math.degrees(c.director.fov_y_rad))),
            lambda c, v: c.director.set_fov(math.radians(v)),
            lo=FOV_MIN, hi=FOV_MAX,
            reset_default=int(round(math.degrees(EXTERIOR_FOV_Y_RAD)))),
    # The three masters' `default` reads the real getters (ANDed, matching the
    # pre-persistence host_loop code) so the panel doesn't report state it
    # hasn't read — see the Setting docstring. `reset_default` stays the
    # static True: "Reset to Defaults" restores stock BC (everything on),
    # not whatever combination the live getters currently report.
    Setting("improved_space", "graphics", "improved_space_on", bool,
            lambda c: (c.r.procedural_sky_enabled()
                       and c.r.volumetric_nebulae_enabled()),
            _fan(lambda c, v: c.r.set_procedural_sky_enabled(v),
                 lambda c, v: c.r.set_volumetric_nebulae_enabled(v)),
            reset_default=True),
    Setting("camera_realism", "graphics", "camera_realism_on", bool,
            lambda c: (c.r.filmic_enabled()
                       and c.r.motion_blur_enabled()
                       and c.r.hdr_lens_flare_enabled()),
            _fan(lambda c, v: c.r.set_hdr_enabled(v),
                 lambda c, v: c.r.set_filmic_enabled(v),
                 lambda c, v: c.r.set_motion_blur_enabled(v),
                 lambda c, v: c.r.set_hdr_lens_flare_enabled(v),
                 lambda c, v: c.r.set_dof_enabled(v)),
            reset_default=True),
    Setting("realistic_lighting", "graphics", "realistic_lighting_on", bool,
            lambda c: (c.r.nebula_lightning_enabled()
                       and c.light_emitters.enabled()),
            _fan(lambda c, v: c.r.set_rim_enabled(v),
                 lambda c, v: c.r.set_shadows_enabled(v),
                 lambda c, v: c.r.set_nebula_lightning_enabled(v),
                 lambda c, v: c.light_emitters.set_enabled(v),
                 lambda c, v: c.r.set_ambient_gradient_enabled(v)),
            reset_default=True),
    Setting("camera_shake", "graphics", "camera_shake_on", bool,
            lambda c: c.camera_shake.enabled(),
            lambda c, v: c.camera_shake.set_enabled(v),
            reset_default=True),
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
    """Panel display fallback for an absent key — see the Setting docstring.
    NOT what "Reset to Defaults" restores; use resolve_reset_default for that."""
    return setting.default(ctx) if callable(setting.default) else setting.default


def resolve_reset_default(setting: Setting, ctx) -> Any:
    """The value "Reset to Defaults" restores — the engine's native, constant
    default. Falls back to `default` when `reset_default` is unset, which is
    correct exactly when `default` is already a plain constant; a row with a
    callable `default` must set `reset_default` (see the Setting docstring)."""
    target = setting.reset_default if setting.reset_default is not None else setting.default
    return target(ctx) if callable(target) else target


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
        # int(raw) also tolerates a numeric STRING ("2" -> 2) alongside a
        # hand-edited file's actual ints — the same hand-editing leniency as
        # the bool tolerance above, just via int()'s own coercion rather than
        # an explicit isinstance branch. "banana" still raises ValueError.
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


def apply_setting(ctx, key: str, value) -> None:
    """Run one SETTINGS row's applier without touching the store.

    The panel binds its `set_*` callbacks to this rather than to a renderer
    function directly wherever one player-facing row drives more than one
    engine call — aa_mode is one index that sets BOTH the SMAA flag and the
    MSAA sample count. Keeping that fan-out in the table is what makes the two
    engines mutually exclusive by construction instead of by a rule someone
    has to remember at every call site.
    """
    setting_for(key).apply(ctx, value)


def reset_and_apply_section(store: SettingsStore, ctx, section: str) -> dict:
    """Drop a section, re-apply its NATIVE defaults to the engine, and return
    {SettingsSnapshot field: value} so the panel can setattr the result.

    Deleting rather than writing defaults is deliberate: it returns the player
    to genuine first-launch behaviour rather than to our transcription of it.

    Uses resolve_reset_default, not resolve_default: for a row whose display
    default reads live state (fov_deg, camera_shake, the three Modern VFX
    masters), resolve_default(ctx) would just read back the value the player
    is resetting AWAY from, making Reset a silent no-op. See the Setting
    docstring.
    """
    store.reset_section(section)
    out = {}
    for setting in SETTINGS:
        if setting.section != section:
            continue
        value = resolve_reset_default(setting, ctx)
        setting.apply(ctx, value)
        out[setting.field] = value
    return out
