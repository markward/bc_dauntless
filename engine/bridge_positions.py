"""Officers on a bridge pack's bridge stand where the pack says.

BC places each officer with Bridge/Characters/CommonAnimations.SetPosition,
a chain of `if pCharacter.GetLocation() == "DBHelm": ...` branches that
knows only the stock bridges' location names. A bridge pack names its own
locations ('DFHelm', 'DFL1S', ...) in its Foundation.BridgeDef, and
Foundation's replacement SetPosition asked the current bridge's BridgeDef
first (Foundation.BridgeSetLocation) before falling back to the stock
locations.

`install()` wraps SetPosition to do the same, without editing the SDK file:
when the loaded bridge has a BridgeDef that declares this officer's
location, the BridgeDef places them; anything else goes to BC's own
SetPosition unchanged. Dauntless reads officer placement only through
SetPosition (engine/appc/bridge_placement.capture_placement), which installs
the wrap before its first call.

Spec: docs/superpowers/specs/2026-11-11-foundation-bridge-starbase-defs-design.md
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def _place_by_bridgedef(pCharacter):
    """The TGSequence placing `pCharacter`, or None when the current bridge
    has no BridgeDef declaring its location."""
    from engine.foundation import bridge
    current = bridge.current_bridge()
    if current is None or not current.locations:
        return None
    location = pCharacter.GetLocation()
    if location not in current.locations:
        return None
    import App
    sequence = App.TGSequence_Create()
    if current.SetLocation(location, App.g_kAnimationManager, sequence,
                           pCharacter.GetAnimNode(), pCharacter=pCharacter):
        return sequence
    return None


def install(module=None) -> bool:
    """Wrap `Bridge.Characters.CommonAnimations.SetPosition` (or
    `module.SetPosition`) once. True if it wrapped now; False if already
    wrapped or unavailable."""
    if module is None:
        try:
            import Bridge.Characters.CommonAnimations as module
        except Exception as e:
            _log.warning("bridge positions: CommonAnimations unavailable: %s", e)
            return False
    current = getattr(module, "SetPosition", None)
    if current is None or getattr(
            current, "_dauntless_bridge_positions_orig", None) is not None:
        return False
    orig = current

    def SetPosition(pCharacter):
        sequence = _place_by_bridgedef(pCharacter)
        if sequence is not None:
            return sequence
        return orig(pCharacter)

    SetPosition._dauntless_bridge_positions_orig = orig
    module.SetPosition = SetPosition
    return True
