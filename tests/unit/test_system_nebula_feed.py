from engine import dev_mode, host_loop
from engine.systems import profile as P
from engine.systems.map import Body, Region, SystemMap


class _R:
    def __init__(self, volumetric=True):
        self.profiles = []
        self.stars = []
        self._volumetric = volumetric

    def set_system_nebula_profile(self, d):
        self.profiles.append(d)

    def set_system_nebula_star(self, pos):
        self.stars.append(pos)

    def volumetric_nebulae_enabled(self):
        return self._volumetric


def _map(name="Vesuvi"):
    return SystemMap(system=name,
                     bodies=[Body("Star", "Star", 2000.0, (0.0, 0.0, 0.0))],
                     regions=[Region("R", (100000.0, 0.0, 0.0), 1000.0)],
                     profile=P.Profile(rows=[P.ProfileRow(0.0, nebula=1.0),
                                             P.ProfileRow(200000.0, nebula=1.0)],
                                       color=(0.6, 0.35, 0.72)))


def _patch(monkeypatch, m):
    from engine.systems import frames, resolve
    monkeypatch.setattr(frames, "system_position",
                        lambda obj: (("system", m.system), 1.0, 2.0, 3.0))
    monkeypatch.setattr(resolve, "map_of", lambda name: m if name == m.system else None)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", None)
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)


def test_profile_repushed_only_on_system_change(monkeypatch):
    m = _map()
    _patch(monkeypatch, m)
    r = _R()
    suns = [{"position": (5.0, 6.0, 7.0)}]
    host_loop._push_system_nebula(r, object(), suns, False)
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 1
    d = r.profiles[0]
    assert d["r"] == [0.0, 200000.0] and d["nebula"] == [1.0, 1.0]
    assert d["k_sys"] == P.k_sys(m) and d["star_radius"] == 2000.0
    assert r.stars[-1] == (5.0, 6.0, 7.0)
    m2 = _map("Belaruz")
    _patch(monkeypatch, m2)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", "Vesuvi")
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 2


def test_unmapped_set_clears_profile(monkeypatch):
    from engine.systems import frames
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(frames, "system_position", lambda obj: None)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", "Vesuvi")
    r = _R()
    host_loop._push_system_nebula(r, object(), [], False)
    assert r.profiles == [None]


def test_warp_tunnel_clears_profile(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", "Vesuvi")
    r = _R()
    host_loop._push_system_nebula(r, object(), [], True)
    assert r.profiles == [None]


def test_star_position_pushed_every_frame_even_without_a_profile(monkeypatch):
    """Clump-only lighting keys off the star position, so it must go out
    even when there's no mapped-system profile to build a table from."""
    from engine.systems import frames
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(frames, "system_position", lambda obj: None)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", None)
    r = _R()
    suns = [{"position": (9.0, 8.0, 7.0)}]
    host_loop._push_system_nebula(r, object(), suns, False)
    assert r.profiles == []
    assert r.stars == [(9.0, 8.0, 7.0)]


def test_gate_closed_dev_mode_off_never_touches_frames_or_pushes(monkeypatch):
    from engine.systems import frames
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", None)
    touched = []
    monkeypatch.setattr(frames, "system_position", lambda obj: touched.append(1))
    r = _R()
    suns = [{"position": (5.0, 6.0, 7.0)}]
    host_loop._push_system_nebula(r, object(), suns, False)
    assert r.profiles == []
    assert r.stars == []
    assert touched == [], "gate closed must never build a table in production"


def test_gate_closed_when_volumetric_toggle_off(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", None)
    r = _R(volumetric=False)
    suns = [{"position": (1.0, 2.0, 3.0)}]
    host_loop._push_system_nebula(r, object(), suns, False)
    assert r.profiles == []
    assert r.stars == []


def test_gate_closing_pushes_one_none_then_reopening_repushes(monkeypatch):
    m = _map()
    _patch(monkeypatch, m)
    r = _R()
    suns = [{"position": (5.0, 6.0, 7.0)}]
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 1

    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 2 and r.profiles[-1] is None
    assert host_loop._system_nebula_pushed_for is None

    # Gate stays closed: no repeated None pushes.
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 2

    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 3 and r.profiles[-1] is not None


# ── _reset_sensor_state's UNKNOWN sentinel (mission-swap clear bug) ─────────
#
# _reset_sensor_state forgets the latch to _SYSTEM_NEBULA_UNKNOWN, not None,
# because the native pass keeps its old far-field table across a mission swap.
# Forgetting to plain None would make the very next unmapped/gate-closed
# frame's `if _system_nebula_pushed_for is not None` guard false already, so
# the clear push would never fire and the previous system's haze would keep
# drawing. The sentinel is `is not None` (forces exactly one clear) and never
# `==` any system name (forces a fresh push into the SAME system too).

def _guard_latch_restore(monkeypatch):
    """Make monkeypatch restore the real module global on teardown even
    though the code under test reassigns it directly (not through
    monkeypatch), so these tests can't leak _system_nebula_pushed_for."""
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for",
                        host_loop._system_nebula_pushed_for)


def test_reset_sensor_state_marks_the_nebula_latch_unknown(monkeypatch):
    _guard_latch_restore(monkeypatch)
    host_loop._system_nebula_pushed_for = "Vesuvi"
    host_loop._reset_sensor_state()
    assert host_loop._system_nebula_pushed_for is host_loop._SYSTEM_NEBULA_UNKNOWN


def test_unmapped_frame_after_reset_pushes_exactly_one_none(monkeypatch):
    from engine.systems import frames
    _guard_latch_restore(monkeypatch)
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(frames, "system_position", lambda obj: None)
    host_loop._system_nebula_pushed_for = "Vesuvi"
    host_loop._reset_sensor_state()
    r = _R()
    host_loop._push_system_nebula(r, object(), [], False)
    assert r.profiles == [None]
    assert host_loop._system_nebula_pushed_for is None
    # A second unmapped frame must not repeat the clear.
    host_loop._push_system_nebula(r, object(), [], False)
    assert r.profiles == [None]


def test_mapped_frame_with_the_same_system_name_repushes_after_reset(monkeypatch):
    _guard_latch_restore(monkeypatch)
    m = _map()
    _patch(monkeypatch, m)
    r = _R()
    suns = [{"position": (5.0, 6.0, 7.0)}]
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 1
    assert host_loop._system_nebula_pushed_for == "Vesuvi"

    host_loop._reset_sensor_state()
    assert host_loop._system_nebula_pushed_for is host_loop._SYSTEM_NEBULA_UNKNOWN

    # frames/resolve still resolve to the SAME system as before the swap.
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 2, (
        "the sentinel must force a fresh push even into the same system name")
    assert host_loop._system_nebula_pushed_for == "Vesuvi"
