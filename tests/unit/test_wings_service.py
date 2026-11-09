"""Wing service: switch, arming with phase stagger, 1 Hz cadence, reset."""
import pytest

from engine.wings import brain, roster, service


class _Group:
    def GetNameTuple(self):
        return ()


@pytest.fixture(autouse=True)
def _clean():
    service.reset_all()
    yield
    service.reset_all()


def _wing(wid):
    return roster.create_wing(wid, _Group())


def _recorder(monkeypatch):
    calls = []
    monkeypatch.setattr(brain, "arm_chain", lambda w: None)
    monkeypatch.setattr(brain, "tick_wing",
                        lambda w: calls.append((w.wing_id, round(clock[0], 4))))
    return calls


clock = [0.0]


def test_disabled_by_env(monkeypatch):
    assert service.enabled()
    monkeypatch.setenv("DAUNTLESS_WINGS", "0")
    assert not service.enabled()


def test_env_is_the_only_switch():
    """The developer toggles are gone (Mark, 2026-11-09): wings are switched
    per battle by the Quick Battle setup screen (plan.wings), and globally
    only by DAUNTLESS_WINGS."""
    for gone in ("set_dev_enabled", "_dev_enabled", "reset_dev",
                 "set_show_markers", "show_markers", "_show_markers"):
        assert not hasattr(service, gone), gone
    assert service.enabled()


def test_tick_runs_on_cadence_and_stagger(monkeypatch):
    calls = _recorder(monkeypatch)
    a, b = _wing("A"), _wing("B")
    service.arm(a)
    service.arm(b)
    assert (a.phase_s, b.phase_s) == (0.0, 0.5)
    clock[0] = 0.0
    for _ in range(120):
        clock[0] += 1 / 60
        service.tick(1 / 60)
    ids = [c[0] for c in calls]
    first = {}
    for wid, t in calls:
        first.setdefault(wid, t)
    assert first["A"] != first["B"]
    assert ids.count("A") == 2
    assert ids.count("B") == 2


def test_tick_noop_when_nothing_armed(monkeypatch):
    calls = _recorder(monkeypatch)
    _wing("A")
    service.tick(5.0)
    assert calls == []


def test_reset_clears(monkeypatch):
    calls = _recorder(monkeypatch)
    w = _wing("A")
    service.arm(w)
    service.reset()
    assert roster.wings() == []
    service.tick(5.0)
    assert calls == []


def test_tick_uses_tick_safely(monkeypatch):
    seen = []
    monkeypatch.setattr(brain, "arm_chain", lambda w: None)
    monkeypatch.setattr(brain, "tick_safely", lambda w: seen.append(w.wing_id))
    service.arm(_wing("A"))
    service.tick(1.0)
    assert seen == ["A"]


def test_env_off_tick_does_no_work(monkeypatch):
    """DAUNTLESS_WINGS=0: no brain work runs, even for an armed wing."""
    seen = []
    monkeypatch.setattr(brain, "arm_chain", lambda w: None)
    monkeypatch.setattr(brain, "tick_safely", lambda w: seen.append(1))
    service.arm(_wing("A"))
    monkeypatch.setenv("DAUNTLESS_WINGS", "0")
    service.tick(5.0)
    assert seen == []


def test_nothing_armed_tick_does_no_work(monkeypatch):
    seen = []
    monkeypatch.setattr(brain, "tick_safely", lambda w: seen.append(1))
    _wing("A")                                  # created, never armed
    service.tick(5.0)
    assert seen == []


def test_is_commander():
    from engine.wings import roster
    import App
    g = App.ObjectGroup()
    w = roster.create_wing("wx", g)
    roster.add_member(w, "A")
    roster.add_member(w, "B")
    w.commander = "A"
    assert service.is_commander("A") and not service.is_commander("B")
    assert not service.is_commander("nobody")
    w.leaderless = True
    assert not service.is_commander("A")
    service.reset_all()


def _player_wing():
    import App
    w = roster.create_wing("qb:g", App.ObjectGroup())
    roster.add_member(w, "A")
    w.commander = "A"
    w.primary = "Foe"
    return w


def test_player_focus_none_without_a_player_wing():
    _player_wing()
    assert service.player_focus() is None
    service.set_player_wing("missing")
    assert service.player_focus() is None


def test_player_focus_is_the_primary():
    _player_wing()
    service.set_player_wing("qb:g")
    assert service.player_focus() == "Foe"


def test_player_focus_none_when_leaderless_away_or_no_primary():
    w = _player_wing()
    service.set_player_wing("qb:g")
    w.leaderless = True
    assert service.player_focus() is None
    w.leaderless = False
    w.away = True
    assert service.player_focus() is None
    w.away = False
    w.primary = None
    assert service.player_focus() is None


def test_reset_clears_player_wing():
    _player_wing()
    service.set_player_wing("qb:g")
    service.reset()
    assert service.player_focus() is None
