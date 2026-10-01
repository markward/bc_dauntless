"""Validate one ShipDef `dauntless` dict (already merged across layers).

Pure: no paths, no mods, no Foundation. An invalid value is treated exactly
like an absent one (it lands in `missing`), plus a readable line in `errors`
so the mod metadata gate can say WHY. An invalid variant is dropped with an
error; variants are optional, so that never makes an entry incomplete.

Spec: docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md §1
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from engine.ship_catalog.tables import (
    ALL_ERAS, ERA_IDS, MANDATORY, ROLE_IDS, STOCK_SPECIES)


@dataclass(frozen=True)
class Variant:
    """A named ship. `script` spawns a separate ships/<script>.py instead of
    the definition's own; `registry` is the hull-name decal registry
    (Masks/<registry>/). The class default (variants[0]) may set neither: it
    spawns the entry's own script. `playable` is set on a variant that is a
    class member ship (it has its own flag); None means "the entry's"."""
    name: str
    script: Optional[str] = None
    registry: Optional[str] = None
    playable: Optional[bool] = None


@dataclass(frozen=True)
class Parsed:
    values: dict
    variants: tuple
    missing: tuple
    errors: tuple
    variant_of: Optional[str] = None     # class name, trimmed; None = own class
    class_default: bool = False


def _text(value) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _era(value) -> Optional[tuple]:
    if isinstance(value, str):
        if value.strip().lower() == ALL_ERAS:
            return (ALL_ERAS,)
        value = (value, value)
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    if not all(isinstance(v, str) for v in value):
        return None
    lo, hi = (v.strip().upper() for v in value)
    if lo not in ERA_IDS or hi not in ERA_IDS:
        return None
    if ERA_IDS.index(lo) > ERA_IDS.index(hi):
        return None
    return (lo, hi)


def _role(value) -> Optional[str]:
    if isinstance(value, str) and value.strip().lower() in ROLE_IDS:
        return value.strip().lower()
    return None


def _playable(value) -> Optional[bool]:
    # bool first: bool is an int subclass, and True/False must stay accepted.
    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    return None


def _species(value) -> Optional[str]:
    text = _text(value)
    if text is None:
        return None
    for s in STOCK_SPECIES:
        if s.name.lower() == text.lower():
            return s.name
    return text


_PARSERS = {"era": _era, "role": _role, "playable": _playable,
            "title": _text, "species": _species}


def parse_dauntless(raw) -> Parsed:
    errors: list = []
    if raw is None:
        raw = {}
    elif not isinstance(raw, dict):
        errors.append("dauntless: must be a dict (got %r)" % (raw,))
        raw = {}

    values: dict = {}
    missing: list = []
    for key in MANDATORY:
        if key not in raw:
            missing.append(key)
            continue
        got = _PARSERS[key](raw[key])
        if got is None:
            missing.append(key)
            errors.append("%s: invalid value %r" % (key, raw[key]))
        else:
            values[key] = got

    variants = _variants(raw.get("variants"), errors)
    variant_of = None
    if "variant_of" in raw and raw["variant_of"] is not None:
        if isinstance(raw["variant_of"], str):
            variant_of = raw["variant_of"].strip() or None
        else:
            errors.append("variant_of: invalid value %r" % (raw["variant_of"],))
    class_default = False
    if "class_default" in raw:
        got = _playable(raw["class_default"])      # same 0/1/bool rule
        if got is None:
            errors.append("class_default: invalid value %r" % (raw["class_default"],))
        else:
            class_default = got
    return Parsed(values, variants, tuple(missing), tuple(errors),
                  variant_of, class_default)


def _variants(raw, errors: list) -> tuple:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        errors.append("variants: must be a list (got %r)" % (raw,))
        return ()
    kept: list = []
    seen: set = set()
    for i, v in enumerate(raw):
        where = "variants[%d]" % i
        if not isinstance(v, dict):
            errors.append("%s: must be a dict (got %r)" % (where, v))
            continue
        name = _text(v.get("name"))
        if name is None:
            errors.append("%s: needs a non-empty 'name'" % where)
            continue
        script = _text(v.get("script"))
        registry = _text(v.get("registry"))
        if script is None and registry is None and kept:
            # Only the class default (the first kept variant) may be
            # name-only: it spawns the entry's own script.
            errors.append("%s %r: needs a 'script' or a 'registry'" % (where, name))
            continue
        if name in seen:
            errors.append("%s %r: duplicate name" % (where, name))
            continue
        if not kept and script is not None:
            # The first KEPT variant is the class default, which spawns the
            # definition's own script (spec §1).
            errors.append("%s %r: the class default must not have a 'script'"
                          % (where, name))
            continue
        seen.add(name)
        kept.append(Variant(name, script, registry))
    return tuple(kept)
