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
