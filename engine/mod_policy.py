"""Which mod files Dauntless refuses, and which mods it blocks outright.

Spec: docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md §5

Pure -- no I/O. engine/mods.build_index consults decide() per mod BEFORE any of
that mod's files enter the index, so every consumer (both _SDKFinders, the
asset overlay, the C++ override map) skips a refused file with no second
filter, and a refused file can never displace an earlier mod's copy.

Rule A -- NanoFX. Dauntless provides NanoFX's API itself (Custom.NanoFXv2,
engine/compat/fx_api). A mod that is nothing but NanoFX's distribution is
blocked whole; NanoFX bundled inside a bigger pack has only its own files
skipped.

Rule B -- Foundation infrastructure. Dauntless provides Foundation
(engine/foundation). Foundation's own modules are refused in any mod; three
engine-owned SDK modules are refused only when the mod's copy is Foundation's
rewrite (it imports Foundation/FoundationMenu), so a pre-Foundation mod that
edits LoadTacticalSounds.py directly keeps working.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

SDK = "sdk"    # paths-guard: kind label, mirrors engine/mods._TARGET_FOR
GAME = "game"  # paths-guard: kind label, mirrors engine/mods._TARGET_FOR

REASON_NANOFX_BLOCKED = "incompatible: NanoFX (Dauntless provides its API)"
REASON_NANOFX_BUNDLED = "bundled NanoFX skipped (Dauntless provides its API)"
REASON_FOUNDATION = "Foundation infrastructure (Dauntless provides Foundation)"

_NANOFX_MARKERS = frozenset({
    "custom/nanofxv2/nanofx_lib.py",
    "custom/autoload/loadnanofx.py",
})
_NANOFX_OWN_PREFIX = "custom/nanofxv2/"
_NANOFX_OWN_FILES = frozenset({"custom/autoload/loadnanofx.py"})

_FOUNDATION_ALWAYS = frozenset({
    "foundation.py", "foundationmenu.py", "foundationtriggers.py",
})
_FOUNDATION_ALWAYS_RE = re.compile(
    r"^(fixes2003[^/]*\.py"
    r"|custom/autoload/000-fixes[^/]*\.py"
    r"|custom/autoload/000-utilities-[^/]*\.py)$")
_FOUNDATION_CONDITIONAL = frozenset({
    "loadtacticalsounds.py", "quickbattle/quickbattle.py", "mainmenu/mainmenu.py",
})
_FOUNDATION_IMPORTS = frozenset({"Foundation", "FoundationMenu"})

# Everything else NanoFX 2.0's installer ships (tests/fixtures/mod_layouts/
# nanofx_2_0_beta.txt): Foundation's bundled QB/menu support, its 000-*
# autoload add-ons, ATP, the movies and its Damage.tga.
_NANOFX_DIST_SDK_FILES = frozenset({
    "mainmenu/mutatormenu.py", "quickbattle/quickbattlegame.py",
})
_NANOFX_DIST_SDK_PREFIXES = ("custom/advancedtechnologies/",)
_NANOFX_DIST_SDK_RE = re.compile(r"^custom/autoload/000-[^/]*\.py$")
_NANOFX_DIST_GAME_PREFIXES = ("data/movies/",)
_NANOFX_DIST_GAME_FILES = frozenset({"data/textures/effects/damage.tga"})


@dataclass(frozen=True)
class PolicyFile:
    target: str   # SDK or GAME
    rel: str      # folded index key; sdk keys carry no "scripts/" prefix


@dataclass
class PolicyDecision:
    blocked: Optional[str] = None
    refused: dict = field(default_factory=dict)   # rel -> reason


def _is_nanofx_own(f: PolicyFile) -> bool:
    return f.target == SDK and (f.rel.startswith(_NANOFX_OWN_PREFIX)
                                or f.rel in _NANOFX_OWN_FILES)


def _is_foundation_file(f: PolicyFile) -> bool:
    return f.target == SDK and (f.rel in _FOUNDATION_ALWAYS
                                or bool(_FOUNDATION_ALWAYS_RE.match(f.rel))
                                or f.rel in _FOUNDATION_CONDITIONAL)


def _in_nanofx_distribution(f: PolicyFile) -> bool:
    if f.target == SDK:
        return (_is_nanofx_own(f) or _is_foundation_file(f)
                or f.rel in _NANOFX_DIST_SDK_FILES
                or f.rel.startswith(_NANOFX_DIST_SDK_PREFIXES)
                or bool(_NANOFX_DIST_SDK_RE.match(f.rel)))
    return (f.rel.startswith(_NANOFX_DIST_GAME_PREFIXES)
            or f.rel in _NANOFX_DIST_GAME_FILES)


def needs_imports(f: PolicyFile) -> bool:
    """True for the files whose verdict depends on what they import."""
    return f.target == SDK and f.rel in _FOUNDATION_CONDITIONAL


def _foundation_reason(f: PolicyFile, imports: dict) -> Optional[str]:
    if f.target != SDK:
        return None
    if f.rel in _FOUNDATION_ALWAYS or _FOUNDATION_ALWAYS_RE.match(f.rel):
        return REASON_FOUNDATION
    if f.rel in _FOUNDATION_CONDITIONAL and (set(imports.get(f.rel, ())) & _FOUNDATION_IMPORTS):
        return REASON_FOUNDATION
    return None


def decide(files: list, imports: dict) -> PolicyDecision:
    decision = PolicyDecision()
    has_nanofx = any(f.target == SDK and f.rel in _NANOFX_MARKERS for f in files)
    if has_nanofx and all(_in_nanofx_distribution(f) for f in files):
        decision.blocked = REASON_NANOFX_BLOCKED
        return decision
    for f in files:
        if has_nanofx and _is_nanofx_own(f):
            decision.refused[f.rel] = REASON_NANOFX_BUNDLED
            continue
        reason = _foundation_reason(f, imports)
        if reason is not None:
            decision.refused[f.rel] = reason
    return decision
