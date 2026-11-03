"""combat_k2_scan_ships' object cache (native damage perf fix; Task 4's
report concern 1: the per-step scan probes every phaser system's and
bank's instance dict, four more names each since Task 4).

Each system's and bank's "holds a stood-in name" answer is kept with what
it was computed on -- its type, its dict at the dict's ma_version_tag --
by its position in the scan, so an unchanged one is never probed again;
the class checks and the bank's target-class check are read live. A patch
made after the cache was filled is obeyed at the next scan
(test_native_k2_dispatch's test_binding_scan_matches_the_python_clean_check
walks every way a ship stops being clean, after a first scan).
"""
import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import native_combat as nc
from tests.unit.test_native_k2_dispatch import GALAXY_VORCHA, World

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k2_scan_ships"),
    reason="native combat bindings not built")


def _scan(w):
    return _h.combat_k2_scan_ships(
        w.order, nc._kind("Object"), nc._KIND_SHIFT, nc._k2_seen_set,
        nc._k2_stock_system, nc._k2_stock_bank, nc._K2_SHIP_PATCHES,
        nc._K2_SYSTEM_PATCHES, nc._K2_BANK_PATCHES)


def _probed(w):
    _h.combat_k2_scan_reset_counts()
    out = _scan(w)
    return out, _h.combat_k2_scan_counts()


def test_unchanged_systems_and_banks_are_answered_from_the_cache(
        monkeypatch):
    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k2_scan_cache")
        try:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            g.GetPhaserSystem().StartFiring(v)
            w.tick()
            assert _scan(w)[1] == []
            (handles, bad), counts = _probed(w)
            assert bad == []
            assert counts["probed"] == 0, counts
            assert counts["cached"] > 0, counts
            # A bank written since is probed again; nothing else is.
            bank = g.GetPhaserSystem().GetWeapon(0)
            bank.__dict__["_scan_cache_probe"] = 1
            (handles, bad), counts = _probed(w)
            assert bad == []
            assert counts["probed"] == 1, counts
        finally:
            w.close()


def test_a_bank_target_class_is_read_live(monkeypatch):
    """The bank's target is cached with its dict; whether the target's
    class is one K2 has seen is asked at every scan."""
    class Unseen:
        pass

    with monkeypatch.context() as mp:
        w = World(mp, True, GALAXY_VORCHA, "k2_scan_target")
        try:
            g, v = w.ships["Galaxy"], w.ships["Vorcha"]
            g.GetPhaserSystem().StartFiring(v)
            w.tick()
            bank = g.GetPhaserSystem().GetWeapon(1)
            mp.setitem(bank.__dict__, "_target", Unseen())
            assert [s for s, _h_ in _scan(w)[1]] == [g]
            mp.setattr(nc, "_k2_seen_set",
                       set(nc._k2_seen_set) | {Unseen})
            assert _scan(w)[1] == []        # the same dict, now seen
        finally:
            w.close()
