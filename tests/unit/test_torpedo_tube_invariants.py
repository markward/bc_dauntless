"""Invariants that must hold no matter what an SDK mission does to a tube.

All three regressions here were found by the post-implementation code review and
proven by execution, not by reading. They share one root cause: in this codebase
a wrong value does NOT raise. TGObject.__getattr__ (engine/core/ids.py:125)
hands back a truthy, callable _Stub for any missing attribute, and _Stub's
comparisons return False while its coercions return 0/0.0. So a broken guard
silently inverts instead of blowing up.
"""
import pytest

import App
from engine.appc.subsystems import TorpedoSystem, TorpedoTube
from engine.core.ids import _Stub


@pytest.fixture
def clock():
    App.g_kTimerManager._time = 0.0

    def _set(t: float) -> None:
        App.g_kTimerManager._time = float(t)

    yield _set
    App.g_kTimerManager._time = 0.0


def _tube(max_ready: int = 1, reload_delay: float = 40.0,
          immediate_delay: float = 0.0) -> TorpedoTube:
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = reload_delay
    tube._immediate_delay = immediate_delay
    tube._max_ready = max_ready
    tube._num_ready = max_ready
    tube._resize_slots()
    system.AddChildSubsystem(tube)
    return tube


# ── 1. SetNumReady/IncNumReady must not overshoot MaxReady ──────────────────
# SetNumReady/IncNumReady/DecNumReady are real SDK surface (App.py:6018-6020) —
# a mission can call them directly. Unclamped, _num_ready ran ahead of the slot
# array: Fire() kept decrementing and spawning torpedoes while
# _start_slot_cooldown found no loaded slot and silently no-op'd (free
# torpedoes), and UpdateReload's `num_ready >= max_ready` guard then held
# forever, so the tube never reloaded again.

def test_set_num_ready_cannot_exceed_max_ready(clock):
    tube = _tube(max_ready=1)
    tube.SetNumReady(5)
    assert tube.GetNumReady() == 1


def test_inc_num_ready_cannot_exceed_max_ready(clock):
    tube = _tube(max_ready=1)
    tube.IncNumReady()          # already full
    assert tube.GetNumReady() == 1


def test_set_num_ready_cannot_go_negative(clock):
    tube = _tube(max_ready=1)
    tube.SetNumReady(-3)
    assert tube.GetNumReady() == 0


def test_overshoot_cannot_conjure_torpedoes_or_brick_the_tube(clock):
    """The proven failure: SetNumReady(5) on a 1-slot tube fired FOUR torpedoes
    from one physical slot, then never reloaded again."""
    tube = _tube(max_ready=1, reload_delay=40.0)
    clock(100.0)
    tube.SetNumReady(5)

    fired = 0
    for _ in range(4):
        before = tube.GetNumReady()
        tube.Fire()
        if tube.GetNumReady() < before:
            fired += 1
    assert fired == 1, "a 1-slot tube must not launch more than its one round"

    # And it must still reload — the old code deadlocked on num_ready >= max_ready.
    clock(141.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1


# ── 2. The power guard must not invert under a _Stub ────────────────────────
# `if factor <= 0.0: return` meant "no power => no reload". But _Stub.__le__ is
# False, so the guard did not fire; execution reached
# `delay = self._reload_delay / factor`, and `40.0 / _Stub` is 0.0 — so
# `now - slot >= 0.0` held for every slot and the tube reloaded EVERY FRAME.
# The guard's intent was inverted into infinite ammo.

def test_stub_semantics_that_caused_the_inversion():
    """Guard-rail documenting WHY an isinstance check is required here."""
    s = _Stub("GetNormalPowerPercentage", "TorpedoSystem")
    assert (s <= 0.0) is False      # !!! the guard cannot see it
    assert 40.0 / s == 0.0          # !!! and the division yields a zero delay


def test_non_numeric_power_factor_blocks_reload_instead_of_instant_reload(clock):
    class _StubPowerParent(TorpedoSystem):
        def GetNormalPowerPercentage(self):
            return _Stub("GetNormalPowerPercentage", "TorpedoSystem")

    parent = _StubPowerParent("Torpedoes")
    parent.TurnOn()
    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = 40.0
    tube._immediate_delay = 0.0
    tube._max_ready = 1
    tube._num_ready = 1
    tube._resize_slots()
    parent.AddChildSubsystem(tube)

    clock(100.0)
    tube.Fire()
    assert tube.GetNumReady() == 0

    clock(100.5)                    # only 0.5s — nowhere near the 40s ReloadDelay
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 0, "an unusable power factor must NOT reload instantly"


# ── 3. FireDumb: "not ready" no-ops; "not implemented" still shouts ─────────
# AI/Preprocessors.py:458 calls pTube.FireDumb(0, 1) WITHOUT checking CanFire
# first, so FireDumb must be a silent no-op when the weapon is NOT READY. That
# contract is met by TorpedoTube.Fire's own early return.
#
# It is NOT met by gating FireDumb on CanFire() — the base Weapon.CanFire()
# returns 0, so a subclass that forgot to implement Fire() would then silently
# do nothing forever instead of raising. That trades a loud programming error
# for the exact silent-failure pattern this engine is riddled with. A missing
# implementation must stay loud; only a runtime not-ready state may no-op.

def test_firedumb_on_a_not_ready_tube_is_a_silent_no_op(clock):
    """The real SDK contract: an empty tube ignores FireDumb without raising."""
    tube = _tube(max_ready=1)
    clock(100.0)
    tube.Fire()
    assert tube.GetNumReady() == 0
    tube.FireDumb(0, 1)             # must not raise, must not fire
    assert tube.GetNumReady() == 0


def test_firedumb_on_an_unimplemented_weapon_still_raises():
    """A subclass that never implemented Fire() is a BUG, and must shout.
    Silently no-opping here is how this codebase loses whole features."""
    from engine.appc.subsystems import Weapon

    class _UnfinishedWeapon(Weapon):
        pass                        # deliberately does NOT override Fire

    with pytest.raises(NotImplementedError):
        _UnfinishedWeapon("Experimental").FireDumb(0, 1)


def test_torpedo_tube_does_not_shadow_the_weapon_firedumb():
    """TorpedoTube's FireDumb override was a byte-identical duplicate. Keeping it
    would have silently skipped any future change to the base contract."""
    from engine.appc.subsystems import Weapon
    assert "FireDumb" not in TorpedoTube.__dict__
    assert "FireDumb" in Weapon.__dict__
