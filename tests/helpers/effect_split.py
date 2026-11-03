"""The queued kinds, split out of a differential's event log (combat fire
events, Task 2; spec docs/superpowers/specs/2026-11-02-combat-fire-events-
design.md §4.2, §6).

With native combat on, the tick's scope (host_loop._combat_effect_scope)
delivers weapon events and weapon sounds at the tick boundary, while the
Python reference (switch off) posts them mid-step. So a differential keeps
two logs: every other event stays in its ordered event log, and the queued
kinds go to a per-tick ordered list of their own, compared on its own (both
arms emit them in the same order). A row carries its tick, so equal lists
mean equal per-tick order.

The queued kinds: ET_WEAPON_FIRED, ET_WEAPON_FIRE_FAILED, ET_TORPEDO_FIRED
with a source (a launch; an unload has none and is not queued),
ET_TORPEDO_AMMO_CONSUMED, ET_TORPEDO_RELOAD, ET_TORPEDO_ENTERED_SET (posted
by the spawn, which a K1 launch defers to the boundary: launch deferral,
ruling L2), every event a weapon's charge
watcher fires, and the bank sounds: `_play_fire_sfx` ("play") and a loop
actually stopped by `_stop_loop_sound` ("stop"). Headless, no sound plays
(Play returns no handle), so the play spy gives a bank that got none a
stand-in loop handle, in both arms: its stops are then real stops, and
compared.
"""
import App

from engine.appc import weapon_subsystems as ws


class StandInLoop:
    """A loop handle for a bank whose fire sound played none (headless)."""

    def Stop(self):
        pass
from engine.appc.float_range_watcher import FloatRangeWatcher


def _queued_types():
    return {App.ET_WEAPON_FIRED, App.ET_WEAPON_FIRE_FAILED,
            App.ET_TORPEDO_FIRED, App.ET_TORPEDO_AMMO_CONSUMED,
            App.ET_TORPEDO_RELOAD, App.ET_TORPEDO_ENTERED_SET}


class Queued:
    """One arm's per-tick ordered list of queued kinds (`rows`).

    `label(obj)` names an object as the arm's event log does; `tick()` is
    the arm's current tick. The sound and watcher spies are installed on
    `mp`; the arm's AddEvent spy asks `takes(evt)` and appends its row to
    `rows` instead of its event log when it does."""

    def __init__(self, mp, label, tick):
        self.rows = []
        self.label = label
        self.tick = tick
        self.types = _queued_types()
        self._watching = [0]
        play = ws._EnergyWeaponFireMixin._play_fire_sfx
        stop = ws._EnergyWeaponFireMixin._stop_loop_sound
        fire = FloatRangeWatcher._fire

        def play_spy(bank, _orig=play):
            self.rows.append(("sound", "play", self.label(bank), self.tick()))
            result = _orig(bank)
            if bank.__dict__.get("_loop_handle") is None:
                bank._loop_handle = StandInLoop()
            return result

        def stop_spy(bank, _orig=stop):
            if bank.__dict__.get("_loop_handle") is not None:
                self.rows.append(("sound", "stop", self.label(bank),
                                  self.tick()))
            return _orig(bank)

        def fire_spy(watcher, pEvent, value, _orig=fire):
            owned = watcher._owner is not None
            self._watching[0] += owned
            try:
                return _orig(watcher, pEvent, value)
            finally:
                self._watching[0] -= owned

        mp.setattr(ws._EnergyWeaponFireMixin, "_play_fire_sfx", play_spy)
        mp.setattr(ws._EnergyWeaponFireMixin, "_stop_loop_sound", stop_spy)
        mp.setattr(FloatRangeWatcher, "_fire", fire_spy)

    def takes(self, evt) -> bool:
        """Whether `evt` is a queued kind (see the module docstring)."""
        if self._watching[0]:
            return True
        t = evt.GetEventType()
        if t not in self.types:
            return False
        return t != App.ET_TORPEDO_FIRED or evt.GetSource() is not None


def stops(q) -> int:
    """The loop stops an arm recorded."""
    return sum(1 for r in q.rows if r[:2] == ("sound", "stop"))


def compare(ref, nat, what="queued"):
    """The two arms' queued lists, row by row (then their lengths)."""
    for i, (x, y) in enumerate(zip(ref.rows, nat.rows)):
        assert x == y, "%s %d differs:\n python %r\n native %r" % (
            what, i, x, y)
    assert len(ref.rows) == len(nat.rows), (len(ref.rows), len(nat.rows))


class Scopes:
    """Counts the tick's effect scopes an arm opened (`opened`).

    Fire control is native in both arms of a differential (fire control
    native only, M9), so a reference arm (DAUNTLESS_NATIVE_COMBAT=0) also
    queues: each K1 session defers what it produces and delivers it at its
    own end (effect_queue.session). What still tells the reference apart is
    that it never opens the tick's scope (host_loop._combat_effect_scope):
    its K0, K2 and K3 producers act at once."""

    def __init__(self, mp):
        from engine.appc import effect_queue
        self.opened = 0
        orig = effect_queue.scope

        def scope_spy(*args, _orig=orig, **kwargs):
            self.opened += 1
            return _orig(*args, **kwargs)

        mp.setattr(effect_queue, "scope", scope_spy)
