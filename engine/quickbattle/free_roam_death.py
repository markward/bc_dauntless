"""A player's death in free roam is final (spec 2026-10-26-station-self-defence
§5.5). Mark's ruling: "trigger a death sequence, then leave the player's ship
destroyed. When we implement a save game mechanism they will have to reload
recent save."

BC's `ShipDestroyed` answers the player's death outside a battle with
`RecreatePlayer()`, a forced bridge view and a reset cinematic window: a free
respawn. The wrapper skips all of that for the player when no battle is
running, so the ship stays destroyed and the death sequence has already played;
the pause menu is untouched. In a battle, and for every other ship, BC's own
runs (the battle ends one second after the player dies).

`install(qb)` replaces the module attribute, which is what the event manager
finds: the handler is registered by qualified name. The wrapper carries
`_dauntless_free_roam_death_orig`; install walks every `_dauntless_*_orig`
link, so another module's wrapper over ours is still found.
"""
from __future__ import annotations

_MARK = "_dauntless_free_roam_death_orig"


def _chain(fn):
    """`fn`, then each function it wraps, following any `_dauntless_*_orig`
    link (ours or another module's)."""
    seen = set()
    while fn is not None and id(fn) not in seen:
        seen.add(id(fn))
        yield fn
        links = getattr(fn, "__dict__", {})
        fn = next((v for k, v in links.items()
                   if k.startswith("_dauntless_") and k.endswith("_orig")),
                  None)


def _is_the_players(event) -> bool:
    """The destroyed ship is the current player's (BC compares names)."""
    import App
    player = App.Game_GetCurrentGame().GetPlayer()
    ship = App.ShipClass_Cast(event.GetDestination())
    return (player is not None and ship is not None
            and ship.GetName() == player.GetName())


def _make(qb, orig):
    def ShipDestroyed(pObject, pEvent):
        if not qb.__dict__.get("bInSimulation") and _is_the_players(pEvent):
            return None
        return orig(pObject, pEvent)
    return ShipDestroyed


def install(qb) -> bool:
    """Wrap `qb.ShipDestroyed`; True when this call installed the wrapper."""
    current = qb.__dict__.get("ShipDestroyed")
    if current is None or any(_MARK in getattr(f, "__dict__", {})
                              for f in _chain(current)):
        return False
    wrapper = _make(qb, current)
    setattr(wrapper, _MARK, current)
    qb.ShipDestroyed = wrapper
    return True
