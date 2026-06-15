"""Dev keybinding handlers (engine/dev_keybindings.py).

Handlers are pulled straight from the dev_mode registry after
register_for_frame(), bypassing is_enabled() — dispatch gating is covered
by test_dev_mode.py; here we test the handler behaviour itself.
"""
import pytest

import engine.dev_mode as dev_mode
from engine.dev_keybindings import register_for_frame
from engine.appc import ship_death


@pytest.fixture(autouse=True)
def _isolate_registries():
    """Snapshot/restore the shared dev-keybinding registry and the death
    registry so register_for_frame() here never leaks into other tests."""
    saved = dict(dev_mode._dev_keybindings)
    ship_death.reset()
    yield
    dev_mode._dev_keybindings.clear()
    dev_mode._dev_keybindings.update(saved)
    ship_death.reset()


class _Keys:
    KEY_F7 = 296
    KEY_F10 = 299
    KEY_LEFT_BRACKET = 91
    KEY_RIGHT_BRACKET = 93


class _FakeHost:
    keys = _Keys()


class _Hull:
    def __init__(self):
        self._cond = 100.0
        self._destroyed = False
    def GetCondition(self):     return self._cond
    def SetCondition(self, v):  self._cond = max(0.0, float(v))
    def IsCritical(self):       return 1
    def SetDestroyed(self, v):  self._destroyed = bool(v)
    def IsDestroyed(self):      return 1 if self._destroyed else 0


class _Ship:
    def __init__(self, name):
        self._name = name
        self._hull = _Hull()
        self._dying = False
        self._dead = False
        self._target = None
    def GetName(self):           return self._name
    def GetRadius(self):         return 1.0
    def GetContainingSet(self):  return None
    def GetHull(self):           return self._hull
    def GetTarget(self):         return self._target
    def IsDying(self):           return 1 if self._dying else 0
    def IsDead(self):            return 1 if self._dead else 0
    def SetDying(self, v):       self._dying = bool(v)
    def SetDead(self, v=True):   self._dead = bool(v) if v is not True else True
    def DestroySystem(self, sub):
        if sub is None:
            return
        sub.SetCondition(0.0)
        sub.SetDestroyed(True)
        if sub.IsCritical() and not self._dying and not self._dead:
            ship_death.begin(self)


def _handler_for(key):
    return dev_mode._dev_keybindings[key][0]


def test_right_bracket_destroys_current_target():
    ship_death.reset()
    player = _Ship("Player")
    target = _Ship("Victim")
    player._target = target
    register_for_frame(_FakeHost(), session=None, player=player)
    _handler_for(_Keys.KEY_RIGHT_BRACKET)()
    assert target.GetHull().GetCondition() == 0.0
    assert target.IsDying() == 1          # real death path engaged
    assert player.IsDying() == 0          # player untouched
    ship_death.reset()


def test_right_bracket_noop_without_target_or_on_self():
    ship_death.reset()
    player = _Ship("Player")
    register_for_frame(_FakeHost(), session=None, player=player)
    _handler_for(_Keys.KEY_RIGHT_BRACKET)()   # no target: must not raise
    player._target = player                   # self-target: ignored
    _handler_for(_Keys.KEY_RIGHT_BRACKET)()
    assert player.IsDying() == 0
    ship_death.reset()
