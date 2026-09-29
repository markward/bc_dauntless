import pytest

from engine import dev_mode, host_loop
from engine import dev_nebula_dials as D
from engine.systems import profile as P
from engine.systems.map import Body, Region, SystemMap


class _R:
    def __init__(self, volumetric=True):
        self.profiles = []
        self.stars = []
        self._volumetric = volumetric
        self.volumetric_queries = 0
        self.flashes = []
        self.godrays = []
        self._lightning = True

    def set_system_nebula_profile(self, d):
        self.profiles.append(d)

    def set_system_nebula_star(self, pos):
        self.stars.append(pos)

    def volumetric_nebulae_enabled(self):
        self.volumetric_queries += 1
        return self._volumetric

    def set_system_nebula_flashes(self, flashes):
        self.flashes.append(list(flashes))

    def set_nebula_godrays(self, godrays):
        self.godrays.append(list(godrays))

    def nebula_lightning_enabled(self):
        return self._lightning

    def system_nebula_set_dials(self, dials):
        # Task 7 dev-tuning surface: _push_system_nebula never touches this,
        # but the double mirrors the real renderer facade's shape (see
        # tests/unit/test_dev_nebula_dials.py for the dial-stepping tests).
        self.dials = dict(dials)


def _map(name="Vesuvi"):
    return SystemMap(system=name,
                     bodies=[Body("Star", "Star", 2000.0, (0.0, 0.0, 0.0))],
                     regions=[Region("R", (100000.0, 0.0, 0.0), 1000.0)],
                     profile=P.Profile(rows=[P.ProfileRow(0.0, nebula=1.0),
                                             P.ProfileRow(200000.0, nebula=1.0)],
                                       color=(0.6, 0.35, 0.72)))


@pytest.fixture(autouse=True)
def _isolate_dials_and_latches(monkeypatch):
    """The dev dials and the veil latch are module state: restore them."""
    monkeypatch.setattr(D, "_dials", dict(D.DEFAULTS))
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_veil",
                        host_loop._system_nebula_pushed_veil)


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

    # Developer mode is fixed for a process; the SETTING is what toggles.
    r._volumetric = False
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 2 and r.profiles[-1] is None
    assert host_loop._system_nebula_pushed_for is None

    # Gate stays closed: no repeated None pushes.
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 2

    r._volumetric = True
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


# ── Final-review fixes ──────────────────────────────────────────────────────

def test_profile_push_carries_the_current_dev_dials_g_and_floor(monkeypatch):
    """set_profile syncs the native dials from the pushed LookParams, so a
    push WITHOUT g/floor would silently revert tuned values to defaults."""
    m = _map()
    _patch(monkeypatch, m)
    D._dials = dict(D.DEFAULTS, g=0.3, floor=0.05)
    r = _R()
    host_loop._push_system_nebula(r, object(), [{"position": (0.0, 0.0, 0.0)}], False)
    assert r.profiles[-1]["g"] == 0.3
    assert r.profiles[-1]["floor"] == 0.05


def test_veil_dial_resolves_k_sys_and_forces_a_repush(monkeypatch):
    m = _map()
    _patch(monkeypatch, m)
    r = _R()
    suns = [{"position": (0.0, 0.0, 0.0)}]
    host_loop._push_system_nebula(r, object(), suns, False)
    assert r.profiles[-1]["k_sys"] == pytest.approx(P.k_sys(m, D.DEFAULTS["veil"]))
    D._dials = dict(D._dials, veil=0.4)
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 2, "a veil change must re-push the profile"
    assert r.profiles[-1]["k_sys"] == pytest.approx(P.k_sys(m, 0.4))
    host_loop._push_system_nebula(r, object(), suns, False)
    assert len(r.profiles) == 2, "an unchanged veil must not rebuild again"


def test_sunless_frame_clears_the_star(monkeypatch):
    """No sun in the viewed set: tell the pass there is no star, every
    frame, so it never lights from the previous set's sun."""
    from engine.systems import frames
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(frames, "system_position", lambda obj: None)
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", None)
    r = _R()
    host_loop._push_system_nebula(r, object(), [{"position": (1.0, 2.0, 3.0)}], False)
    host_loop._push_system_nebula(r, object(), [], False)
    assert r.stars == [(1.0, 2.0, 3.0), None]


def test_profile_map_without_a_star_does_not_raise(monkeypatch):
    m = _map()
    m.bodies = [Body("Planet", "Planet", 500.0, (1.0, 0.0, 0.0), orbits="Star")]
    _patch(monkeypatch, m)   # latch None: nothing held yet
    r = _R()
    host_loop._push_system_nebula(r, object(), [], False)   # must not raise
    assert r.profiles == []
    # A held profile with no star to centre it on is cleared.
    monkeypatch.setattr(host_loop, "_system_nebula_pushed_for", "Belaruz")
    host_loop._push_system_nebula(r, object(), [], False)
    assert r.profiles == [None], "no star to centre the haze on: clear it"


def test_production_makes_no_native_call_after_a_mission_swap(monkeypatch):
    """Without --developer the pass never runs and was never fed, so even
    the UNKNOWN latch a mission swap leaves must not reach the renderer."""
    _guard_latch_restore(monkeypatch)
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    host_loop._reset_sensor_state()
    r = _R()
    host_loop._push_system_nebula(r, object(), [{"position": (1.0, 2.0, 3.0)}], False)
    assert r.profiles == [] and r.stars == []
    assert r.volumetric_queries == 0


def test_flare_veil_and_profile_push_share_one_gate():
    import inspect
    for fn in (host_loop._push_system_nebula, host_loop._veil_flares):
        assert "_system_nebula_gate(" in inspect.getsource(fn), fn.__name__


# ── Lightning flashes light the system nebula (Part B, 2026-09-30) ─────────

class _Flash:
    def __init__(self, d=(0.0, 1.0, 0.0), intensity=2.0, color=(0.8, 0.9, 1.0)):
        self.dir, self.intensity, self.color = d, intensity, color


class _Thunder:
    def __init__(self, flashes):
        self._f = flashes

    def active_flashes(self):
        return list(self._f)


_FLASH_DICT = {"dir": (0.0, 1.0, 0.0), "intensity": 2.0, "color": (0.8, 0.9, 1.0)}


def test_thunder_flashes_go_to_the_system_nebula_under_the_gate(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(host_loop, "_nebula_thunder", _Thunder([_Flash()]))
    r = _R()
    host_loop._push_nebula_godrays(r, None, [], False)
    assert r.flashes == [[_FLASH_DICT]]
    assert r.godrays == [[_FLASH_DICT]]


def test_gate_closed_in_developer_mode_pushes_no_flashes(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(host_loop, "_nebula_thunder", _Thunder([_Flash()]))
    r = _R(volumetric=False)
    host_loop._push_nebula_godrays(r, None, [], False)
    assert r.flashes == [[]]
    assert r.godrays == [[_FLASH_DICT]]


def test_warp_streaking_pushes_no_flashes(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(host_loop, "_nebula_thunder", _Thunder([_Flash()]))
    r = _R()
    host_loop._push_nebula_godrays(r, None, [], True)
    assert r.flashes == [[]]
    assert r.godrays == [[]]


def test_production_never_pushes_system_nebula_flashes(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    monkeypatch.setattr(host_loop, "_nebula_thunder", _Thunder([_Flash()]))
    r = _R()
    host_loop._push_nebula_godrays(r, None, [{"position": (1.0, 0.0, 0.0)}], False)
    assert r.flashes == []
    assert r.godrays == [[_FLASH_DICT]]
    assert r.volumetric_queries == 0, "production must not even ask the gate"



# ── The star as a steady godray source (Part C, 2026-09-30) ────────────────

def _star_feed(monkeypatch, nebula=0.6, transmittance=0.5):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(host_loop, "_nebula_thunder", _Thunder([_Flash()]))
    monkeypatch.setattr(P, "sample_for_object", lambda obj: P.Sample(nebula=nebula))
    monkeypatch.setattr(P, "star_transmittance", lambda obj, veil: transmittance)
    m = _map()
    m.bodies[0].appearance.color = (1.0, 0.9, 0.7)
    _patch(monkeypatch, m)


def test_the_star_is_a_godray_source_under_the_gate(monkeypatch):
    _star_feed(monkeypatch)
    r = _R()
    host_loop._push_nebula_godrays(r, object(), [{"position": (0.0, 0.0, 300.0)}], False)
    (godrays,) = r.godrays
    assert godrays[0] == _FLASH_DICT, "the lightning flashes stay in the list"
    star = godrays[1]
    assert star["dir"] == pytest.approx((0.0, 0.0, 1.0))
    assert star["intensity"] == pytest.approx(1.0 * 0.6 * 0.5)
    assert star["color"] == (1.0, 0.9, 0.7)
    assert r.flashes == [[_FLASH_DICT]], "the star never lights the cloud as a flash"


def test_the_star_godray_follows_the_gain_dial(monkeypatch):
    _star_feed(monkeypatch)
    monkeypatch.setattr(D, "_dials", dict(D.DEFAULTS, godray_gain=2.0))
    r = _R()
    host_loop._push_nebula_godrays(r, object(), [{"position": (0.0, 5.0, 0.0)}], False)
    assert r.godrays[0][1]["intensity"] == pytest.approx(2.0 * 0.6 * 0.5)


def test_no_star_godray_without_suns_player_gas_or_gate(monkeypatch):
    _star_feed(monkeypatch)
    suns = [{"position": (0.0, 0.0, 300.0)}]
    for args, expected in (((object(), [], False), [_FLASH_DICT]),   # no sun
                           ((None, suns, False), [_FLASH_DICT]),     # no player
                           ((object(), suns, True), [])):            # warp streak
        r = _R()
        host_loop._push_nebula_godrays(r, *args)
        assert r.godrays == [expected], args
    r = _R(volumetric=False)
    host_loop._push_nebula_godrays(r, object(), suns, False)
    assert r.godrays == [[_FLASH_DICT]]
    _star_feed(monkeypatch, nebula=0.0)
    r = _R()
    host_loop._push_nebula_godrays(r, object(), suns, False)
    assert r.godrays == [[_FLASH_DICT]], "clear space: intensity 0, no entry"


def test_the_star_godray_defaults_to_white_without_a_map_colour(monkeypatch):
    _star_feed(monkeypatch)
    m = _map()
    m.bodies[0].appearance.color = None
    _patch(monkeypatch, m)
    r = _R()
    host_loop._push_nebula_godrays(r, object(), [{"position": (3.0, 0.0, 0.0)}], False)
    assert r.godrays[0][1]["color"] == (1.0, 1.0, 1.0)


def test_production_godray_list_is_exactly_the_flashes(monkeypatch):
    _star_feed(monkeypatch)
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    r = _R()
    host_loop._push_nebula_godrays(r, object(), [{"position": (0.0, 0.0, 300.0)}], False)
    assert r.godrays == [[_FLASH_DICT]]
    assert r.flashes == []
