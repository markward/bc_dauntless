"""Smoke: existing TorpedoSystem ammo surface is sufficient for Slice C.

Spec for Slice C is "Pragmatic mid-scope" — `bChooseTorpsWisely` paths
are deferred. FireScript.__init__ defaults bChooseTorpsWisely=0 (SDK
Preprocessors.py:68), so the default path never enters ChooseTorpType.

These tests pin two things:
  1. Fresh TorpedoSystem has no ammo types (existing engine contract).
  2. The SDK's ChooseTorpType handles an empty-ammo TorpedoSystem
     without crashing (early-return at Preprocessors.py:541).

When Slice D/E ports the smart-selection path, this file expands to
exercise real ammo iteration."""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.subsystems import TorpedoSystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_fresh_torpedo_system_has_no_ammo_types():
    """SDK ChooseTorpType iterates range(GetNumAmmoTypes()); the existing
    engine returns 0 for an unconfigured torp system, which the SDK loop
    handles gracefully (skips immediately)."""
    t = TorpedoSystem("T")
    assert t.GetNumAmmoTypes() == 0


def test_sdk_choose_torp_type_does_not_crash_on_empty_ammo():
    """SDK Preprocessors.py:541 — `if not lTorpTypes: return`. Verify a
    real FireScript.ChooseTorpType call against a fresh TorpedoSystem
    runs to completion without crashing.

    This is the actual contract Slice C relies on: the default
    bChooseTorpsWisely=0 path doesn't reach ChooseTorpType at all, but
    the smart path (deferred to Slice D/E) needs to gracefully handle
    a torp system with no configured ammo. Pin that today."""
    from AI.Preprocessors import FireScript
    fs = FireScript("Target")
    fs.pCodeAI = PreprocessingAI_Create(None, "FirePP")
    torp = TorpedoSystem("T")
    target_loc = App.TGPoint3()
    target_loc.SetXYZ(0.0, 100.0, 0.0)
    # ChooseTorpType returns without raising even with no ammo loaded.
    fs.ChooseTorpType(torp, target_loc, 0.0)
