"""NPC torpedo evasion only dodges torpedoes that would hit within 20 s.

Decision: Mark, 2026-10-29. A deliberate BC departure.

BC's `AI/PlainAI/EvadeTorps` asks `AIScriptAssist_GetIncomingTorpIDsInSet`
for every torpedo closing within `fDangerTimeThreshold = 3600.0` s ("a very
generous estimate. VERY generous."). The stock trees gate it behind
`ConditionIncomingTorps` at 18 s, but once evasion is on, every torpedo
closing within the hour shapes the dodge: `PickRandomVector` subtracts the
same `fTime / 20` from every candidate vector, so time to impact never
changes which direction wins, and `UpdateHeading` drops to 0.2 impulse when
facing ANY listed torpedo. In a battle with thousands of torpedoes in flight
a minute-away miss pulled the dodge as hard as one about to hit.

20 s sits just above the 18 s trigger, so a torpedo that switches evasion on
is always one it dodges. The SDK file is never edited: `install()` sets the
class attribute (instances read it through `self`). Mod AIs that build
EvadeTorps get the cap too.
"""
import logging

_log = logging.getLogger(__name__)

EVADE_HORIZON_S = 20.0


def install(module=None) -> bool:
    """Cap `AI.PlainAI.EvadeTorps.EvadeTorps.fDangerTimeThreshold` once.
    True if it capped now; False if already capped or unavailable. BC's value
    is kept on the class as `_dauntless_bc_danger_time`."""
    if module is None:
        try:
            import AI.PlainAI.EvadeTorps as module
        except Exception as e:
            _log.warning("evade horizon: AI.PlainAI.EvadeTorps unavailable: %s", e)
            return False
    cls = getattr(module, "EvadeTorps", None)
    if cls is None or "_dauntless_bc_danger_time" in cls.__dict__:
        return False
    cls._dauntless_bc_danger_time = getattr(cls, "fDangerTimeThreshold", None)
    cls.fDangerTimeThreshold = EVADE_HORIZON_S
    return True
