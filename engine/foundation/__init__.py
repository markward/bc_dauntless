"""Foundation compatibility -- the surface real BC ship mods call.

Ours is intended to always win over a mod-supplied Foundation.py: it will be
shadowed by a `Foundation.py` at the project root (Task 5), checked by
_SDKFinder BEFORE the mod index, an ordering the mod overlay is meant to
choose deliberately so our own replacements cannot be overridden. That shim
does not exist yet -- this module is the surface it will forward to.

Spec: docs/superpowers/specs/2026-09-09-foundation-compatibility-design.md
"""
from __future__ import annotations

import re

from engine.foundation.shipdef import ShipDefinition, ShipList, _ShipDefNamespace

ShipDef = _ShipDefNamespace()
shipList = ShipList()

_RACE_FACTORY = re.compile(r"^([A-Z][A-Za-z0-9]*)ShipDef$")
_synthesised: set = set()
_sound_failures: list = []


def synthesised_races():
    """Race factories a mod asked for that we had not anticipated."""
    return set(_synthesised)


def __getattr__(attr):
    """Synthesise `<Race>ShipDef` on demand.

    Foundation has race variants we have never seen in a mod -- Klingon,
    Romulan, Cardassian and more. Hardcoding only the two our corpus uses
    would make an unseen one an AttributeError at import, taking the whole
    mod down for a name we could have handled. The race is only a label
    plus a default side/AI, so synthesising is safe.

    Deliberately narrow: anything not matching <Race>ShipDef still raises,
    so a genuine typo is not swallowed.
    """
    m = _RACE_FACTORY.match(attr)
    if not m:
        raise AttributeError(attr)
    race = m.group(1)
    _synthesised.add(attr)

    def factory(abbrev, species, details=None, dict=None):
        return ShipDefinition(race, abbrev, species, details, dict)

    factory.__name__ = attr
    return factory


def load_plugins():
    from engine.foundation.loader import load_plugins as _lp
    return _lp()


def describe(report) -> str:
    """The boot report. Empty when nothing loaded, like mods.describe()."""
    if not (report.ships or report.autoload or report.failures):
        return ""

    lines = ["foundation:"]
    if report.ships:
        lines.append("  %d ship script(s), %d registered"
                     % (len(report.ships), len(_registered_names())))
    if report.autoload:
        lines.append("  %d plugin(s) run" % len(report.autoload))

    # Every tech any definition declares is "not installed" while
    # FoundationTech is out of scope. FTech itself logs and continues in
    # this exact case, so this reports the ecosystem's own behaviour
    # rather than announcing a fault of ours.
    from engine.foundation.shipdef import all_definitions
    techs = sorted({t for d in all_definitions() for t in (d.dTechs or {})})
    if techs:
        lines.append("  techs declared but not installed: %s"
                     % ", ".join(techs))

    races = sorted(synthesised_races() - {"FedShipDef", "BorgShipDef"})
    if races:
        lines.append("  unanticipated race factories used: %s"
                     % ", ".join(races))

    for name, err in _sound_failures_as_pairs():
        lines.append("  WARNING sound %s: %s" % (name, err))
    for script, err in report.failures:
        lines.append("  WARNING %s failed: %s" % (script, err))
    return "\n".join(lines)


def _registered_names():
    from engine.foundation import quickbattle
    return [n for n, _sid in quickbattle.registered()]


def _sound_failures_as_pairs():
    return [(s.split(" ", 1)[0], s) for s in _sound_failures]


def sound_failures() -> list:
    return list(_sound_failures)


def _sound_manager():
    """The live TGSoundManager. Indirected so tests can substitute one."""
    import App
    return App.g_kSoundManager


def SoundDef(file, name, volume=1.0, dict=None):
    """Register a named sound, as LoadTacticalSounds.py does.

    `file` is install-relative (e.g. "sfx/Weapons/X.wav") and resolves
    through paths.game_asset, so a mod-supplied wav is found -- which is
    why sfx/ had to become placeable content first.

    `volume` is applied via the returned TGSound's own SetVolume -- the same
    mechanism LoadBridge.py already uses unconditionally on a LoadSound
    result -- so a mod authoring e.g. 0.3 is no longer silently promoted to
    full volume. Guarded with hasattr rather than an `is not None` check: a
    caller (test or otherwise) that hands back something other than a real
    TGSound is left alone rather than crashing on a method it never had.

    A failure is recorded, never raised: an unplayable sound must not abort
    the Autoload script that declares it.
    """
    from engine import paths
    try:
        path = str(paths.game_asset(file))
        snd = _sound_manager().LoadSound(path, name, 0)
        if hasattr(snd, "SetVolume"):
            snd.SetVolume(volume)
    except Exception as exc:
        _sound_failures.append("%s (%s): %s: %s"
                               % (name, file, type(exc).__name__, exc))


def reset():
    """Drop all registered state. Tests only."""
    for k in [k for k in ShipDef.__dict__ if not k.startswith("_")]:
        delattr(ShipDef, k)
    shipList._items.clear()
    _synthesised.clear()
    _sound_failures.clear()
    # Definitions accumulate on construction, so this must be cleared too
    # or they leak between tests and inflate describe()'s tech list.
    from engine.foundation.shipdef import _ALL_DEFINITIONS
    _ALL_DEFINITIONS.clear()
