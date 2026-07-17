"""AIScriptAssist torpedo-detection surface: the linchpin that lets NPCs
evade torpedoes.

Chain (all six links were dead before this change, see the design report):
  ConditionIncomingTorps / PlainAI.EvadeTorps  ->  App.AIScriptAssist_*
      AIScriptAssist_GetIncomingTorpIDsInSet(pShip, pSet, thresh, srcID, match)
      AIScriptAssist_TorpIsIncoming(pTarget, pTorp, thresh, srcID, match)
      App.Torpedo_Cast(obj)              # real torp -> torp; else None
      App.Torpedo_GetObjectByID(pSet, id)
      Torpedo.GetVelocityTG()            # must return a COPY (SDK mutates it)

Evidence tiers:
  tier1 (RE'd binary, ../STBC-Reverse-Engineering-1) gives the SIGNATURES:
    0x006063d0  TorpIsIncoming(PyObject*, float, long, int)   argfmt 'OOfli'
    0x00473830  GetIncomingTorpIDsInSet(PyObject*, float, int, int)  'OOfii'
    -> five args; param4 = a torp SOURCE id (long), param5 = a bool.
  tier3 (SDK) fixes the PARAMETER MEANINGS:
    - param4 is a firing-object match filter, not an ignore filter: the module
      is "True if a given object has incoming torps FROM the specified firing
      object" (ConditionIncomingTorps.py:3-5), seeded from the named source
      (:148-151), and Defense.py:34 passes the ship's attack target as it.
    - param5 = (self.sFiringObject is not None): "is the source filter armed".
    - the metric is a closing-TIME threshold in seconds (18.0 here, 3600.0 in
      PlainAI/EvadeTorps): SDK EvadeTorps.UpdateTorpInfo:113-120 computes
      distance / closing-speed downstream.
    - armed-but-unresolved source (id == NULL_ID, match == 1) reports NOTHING:
      SetupInitialState:162 declines to count torps in exactly that case.
"""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem
from engine.appc import projectiles


NULL_ID = App.NULL_ID


@pytest.fixture(autouse=True)
def _clear_active_torps():
    projectiles._active.clear()
    yield
    projectiles._active.clear()


def _ship(x=0.0, y=0.0, z=0.0):
    s = ShipClass()
    s._hull = HullSubsystem("H")
    s._hull.SetMaxCondition(1000.0)
    s.SetWorldLocation(TGPoint3(x, y, z))
    return s


def _torp(pos, vel, source=None):
    """A registered in-flight torpedo at `pos` travelling `vel`."""
    t = projectiles.Torpedo()
    t._position = TGPoint3(*pos)
    t._velocity = TGPoint3(*vel)
    t._source_ship = source
    projectiles.register(t)
    return t


# ── The headline bug: five-arg arity + a real answer ─────────────────────────

def test_torp_is_incoming_accepts_five_args_and_reports_a_closing_torp():
    ship = _ship(0, 0, 0)
    # 100 GU dead ahead on +Y, closing at 50 GU/s -> ETA 2s, well under 18.
    torp = _torp((0, 100, 0), (0, -50, 0))
    # The exact call ConditionIncomingTorps.CheckTorpedo makes (5 args).
    result = App.AIScriptAssist_TorpIsIncoming(ship, torp, 18.0, NULL_ID, 0)
    assert result == 1


def test_torp_is_incoming_receding_torp_reports_zero():
    ship = _ship(0, 0, 0)
    torp = _torp((0, 100, 0), (0, 50, 0))  # moving AWAY on +Y
    assert App.AIScriptAssist_TorpIsIncoming(ship, torp, 18.0, NULL_ID, 0) == 0


def test_torp_is_incoming_closing_but_beyond_time_threshold_reports_zero():
    ship = _ship(0, 0, 0)
    # Closing at 10 GU/s from 1000 GU out -> ETA 100s, over the 18s threshold.
    torp = _torp((0, 1000, 0), (0, -10, 0))
    assert App.AIScriptAssist_TorpIsIncoming(ship, torp, 18.0, NULL_ID, 0) == 0


def test_torp_is_incoming_rejects_non_torpedo():
    ship = _ship(0, 0, 0)
    other = _ship(0, 100, 0)  # a ship, not a torpedo
    assert App.AIScriptAssist_TorpIsIncoming(ship, other, 18.0, NULL_ID, 0) == 0


# ── GetIncomingTorpIDsInSet: the path PlainAI.EvadeTorps actually flies ───────

def test_get_incoming_ids_lists_only_closing_torps_by_objid():
    ship = _ship(0, 0, 0)
    incoming = _torp((0, 100, 0), (0, -50, 0))     # ETA 2s -> incoming
    receding = _torp((0, 100, 0), (0, 50, 0))      # away -> not
    far = _torp((0, 1000, 0), (0, -10, 0))         # ETA 100s -> not

    ids = App.AIScriptAssist_GetIncomingTorpIDsInSet(
        ship, ship.GetContainingSet(), 18.0, NULL_ID, 0)

    assert incoming.GetObjID() in ids
    assert receding.GetObjID() not in ids
    assert far.GetObjID() not in ids


def test_get_incoming_ids_returns_iterable_of_ints():
    # SDK does `for idTorp in lIncomingTorpIDs` and dict-keys them, so the
    # result must be a concrete iterable of ints (a _Stub loops forever).
    ship = _ship(0, 0, 0)
    _torp((0, 100, 0), (0, -50, 0))
    ids = App.AIScriptAssist_GetIncomingTorpIDsInSet(ship, None, 18.0, NULL_ID, 0)
    assert list(ids) == [i for i in ids]
    assert all(isinstance(i, int) for i in ids)


# ── The firing-object match filter (param 4 / param 5) ───────────────────────

def test_source_filter_matches_only_the_named_firing_object():
    ship = _ship(0, 0, 0)
    attacker = _ship(0, 500, 0)
    bystander = _ship(500, 0, 0)
    from_attacker = _torp((0, 100, 0), (0, -50, 0), source=attacker)
    from_bystander = _torp((50, 0, 0), (-50, 0, 0), source=bystander)

    ids = App.AIScriptAssist_GetIncomingTorpIDsInSet(
        ship, None, 18.0, attacker.GetObjID(), 1)

    assert from_attacker.GetObjID() in ids
    assert from_bystander.GetObjID() not in ids


def test_source_filter_armed_but_unresolved_id_matches_nothing():
    # Named source that has not spawned yet: iFiringObjectID stays NULL_ID
    # while the filter is armed. SetupInitialState:162 declines to count in
    # exactly this case, so we report nothing.
    ship = _ship(0, 0, 0)
    attacker = _ship(0, 500, 0)
    _torp((0, 100, 0), (0, -50, 0), source=attacker)  # a real, closing torp
    ids = App.AIScriptAssist_GetIncomingTorpIDsInSet(ship, None, 18.0, NULL_ID, 1)
    assert list(ids) == []


# ── Torpedo_Cast: real torps in, ships/None out ──────────────────────────────

def test_torpedo_cast_recognizes_real_torpedo():
    torp = _torp((0, 0, 0), (0, 0, 0))
    assert App.Torpedo_Cast(torp) is torp


def test_torpedo_cast_rejects_ship_and_none():
    ship = _ship(0, 0, 0)
    assert App.Torpedo_Cast(ship) is None
    assert App.Torpedo_Cast(None) is None


# ── Torpedo_GetObjectByID ────────────────────────────────────────────────────

def test_torpedo_get_object_by_id_finds_registered_torp():
    torp = _torp((0, 0, 0), (0, 0, 0))
    assert App.Torpedo_GetObjectByID(None, torp.GetObjID()) is torp


def test_torpedo_get_object_by_id_unknown_and_none_return_none():
    assert App.Torpedo_GetObjectByID(None, 9999999) is None
    assert App.Torpedo_GetObjectByID(None, None) is None


# ── GetVelocityTG must hand back a COPY (SDK mutates it in place) ─────────────

def test_torpedo_get_velocity_tg_returns_a_copy():
    # SDK EvadeTorps.UpdateTorpInfo:114-115 does
    #   vVelocity = pTorp.GetVelocityTG(); vVelocity.Subtract(pShip...)
    # If GetVelocityTG returned the live vector, that Subtract would corrupt
    # the torpedo's real velocity.
    torp = _torp((0, 0, 0), (1.0, 2.0, 3.0))
    v = torp.GetVelocityTG()
    v.Subtract(TGPoint3(1.0, 2.0, 3.0))
    assert (torp._velocity.x, torp._velocity.y, torp._velocity.z) == (1.0, 2.0, 3.0)
