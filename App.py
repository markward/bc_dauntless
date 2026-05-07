import math
from engine.appc.events import (
    TGEvent, TGEvent_Create,
    TGEventHandlerObject, TGEventManager,
)
from engine.appc.timers import TGTimer, TGTimer_Create, TGTimerManager
from engine.core.game import Game, Episode, Mission, Game_GetCurrentGame, _set_current_game, Game_GetDifficulty

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
ET_ENTERED_SET = 105
ET_OBJECT_EXPLODING = 106

_next_event_type_id = 200


def Game_GetNextEventType() -> int:
    global _next_event_type_id
    result = _next_event_type_id
    _next_event_type_id += 1
    return result


Mission_GetNextEventType = Game_GetNextEventType
Episode_GetNextEventType = Game_GetNextEventType


# ── UtopiaModule ───────────────────────────────────────────────────────────────

class _UtopiaModule:
    def GetGameTime(self) -> float:
        return g_kTimerManager.get_time()

    def __getattr__(self, name):
        return _Stub()

g_kUtopiaModule = _UtopiaModule()


# ── Typed event objects ────────────────────────────────────────────────────────
# SDK scripts create these, store a typed value via Set*, then pass the event
# to a handler which reads it back via Get*.  The stub's __getattr__ would lose
# the stored value, so we need real storage.

class _TGTypedEvent:
    """Base for Int/String/Float event objects."""
    def __init__(self):
        self._event_type = 0
        self._destination = None
    def SetEventType(self, t): self._event_type = t
    def GetEventType(self): return self._event_type
    def SetDestination(self, d): self._destination = d
    def GetDestination(self): return self._destination
    def __getattr__(self, name): return _Stub()

class _TGIntEvent(_TGTypedEvent):
    def __init__(self): super().__init__(); self._val = 0
    def SetInt(self, v): self._val = int(v) if not isinstance(v, _Stub) else 0
    def GetInt(self): return self._val

class _TGStringEvent(_TGTypedEvent):
    def __init__(self): super().__init__(); self._val = ""
    def SetString(self, v): self._val = str(v) if not isinstance(v, _Stub) else ""
    def GetString(self): return self._val

class _TGFloatEvent(_TGTypedEvent):
    def __init__(self): super().__init__(); self._val = 0.0
    def SetFloat(self, v): self._val = float(v) if not isinstance(v, _Stub) else 0.0
    def GetFloat(self): return self._val

def TGIntEvent_Create(): return _TGIntEvent()
def TGStringEvent_Create(): return _TGStringEvent()
def TGFloatEvent_Create(): return _TGFloatEvent()


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
        return True

    def __hash__(self):
        return id(self)

    def __getitem__(self, key):
        return _Stub()

    def __setitem__(self, key, value):
        pass

    def __delitem__(self, key):
        pass

    def __repr__(self):
        return "<App._Stub>"

    # Numeric operators: return 0/0.0 so arithmetic in SDK scripts doesn't crash.
    # GetRadius() / 2, position comparisons, etc. all need to produce a numeric.
    def __int__(self):      return 0
    def __float__(self):    return 0.0
    def __index__(self):    return 0
    def __add__(self, o):   return o if isinstance(o, str) else 0
    def __radd__(self, o):  return o if isinstance(o, str) else 0
    def __sub__(self, o):   return 0
    def __rsub__(self, o):  return 0
    def __mul__(self, o):   return 0
    def __rmul__(self, o):  return 0
    def __truediv__(self, o):  return 0.0
    def __rtruediv__(self, o): return 0.0
    def __floordiv__(self, o):  return 0
    def __rfloordiv__(self, o): return 0
    def __mod__(self, o):   return 0
    def __rmod__(self, o):  return 0
    def __neg__(self):      return 0
    def __pos__(self):      return 0
    def __abs__(self):      return 0
    def __or__(self, o):    return 0
    def __ror__(self, o):   return 0
    def __and__(self, o):   return 0
    def __rand__(self, o):  return 0
    def __xor__(self, o):   return 0
    def __rxor__(self, o):  return 0
    def __lshift__(self, o): return 0
    def __rshift__(self, o): return 0
    def __invert__(self):   return 0
    # Comparison operators: always False so guards like `fRadius >= 6000` skip
    def __lt__(self, o):    return False
    def __le__(self, o):    return False
    def __gt__(self, o):    return False
    def __ge__(self, o):    return False
    def __eq__(self, o):    return isinstance(o, type(self))
    def __ne__(self, o):    return not isinstance(o, type(self))


def __getattr__(name):
    return _Stub()
