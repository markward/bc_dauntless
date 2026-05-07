import math
from engine.appc.events import (
    TGEvent, TGEvent_Create,
    TGEventHandlerObject, TGEventManager,
)
from engine.appc.timers import TGTimer, TGTimer_Create, TGTimerManager
from engine.core.game import Game, Episode, Mission, Game_GetCurrentGame, _set_current_game

# ── Numeric constants ──────────────────────────────────────────────────────────
NULL_ID = 0
PI = math.pi
HALF_PI = math.pi / 2.0
TWO_PI = math.pi * 2.0

# ── Singletons ─────────────────────────────────────────────────────────────────
g_kEventManager = TGEventManager()
g_kTimerManager = TGTimerManager(g_kEventManager)
g_kRealtimeTimerManager = TGTimerManager(g_kEventManager)

# ── Event-type constants (integers; values are arbitrary but stable) ───────────
# Only the subset needed for Phase 1.  Add more as SDK scripts demand them.
ET_AI_TIMER = 100
ET_ACTION_COMPLETED = 101
ET_MISSION_START = 102
ET_EPISODE_START = 103
ET_OBJECT_DELETED = 104


# ── Fallback stub ──────────────────────────────────────────────────────────────
class _Stub:
    """Returned for any App attribute not yet implemented.

    Falsy so that `if pShip:` guards behave correctly when the object
    hasn't been set up — surfaces missing implementations rather than
    silently proceeding with stub data.
    """
    def __getattr__(self, name):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return _Stub()

    def __bool__(self):
        return False

    def __repr__(self):
        return "<App._Stub>"


def __getattr__(name):
    return _Stub()
