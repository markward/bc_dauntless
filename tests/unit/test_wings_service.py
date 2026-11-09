"""Wing service: switch, arming with phase stagger, 1 Hz cadence, reset."""
import pytest

from engine.wings import brain, roster, service


class _Group:
    def GetNameTuple(self):
        return ()


@pytest.fixture(autouse=True)
def _clean():
    service.reset_all()
    service.reset_dev()
    yield
    service.reset_all()
    service.reset_dev()


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


def test_dev_switch():
    service.set_dev_enabled(False)
    assert not service.enabled()
    service.reset()
    assert not service.enabled()      # mission reset leaves it
    service.reset_dev()
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


def test_disabled_tick_is_noop(monkeypatch):
    seen = []
    monkeypatch.setattr(brain, "arm_chain", lambda w: None)
    monkeypatch.setattr(brain, "tick_safely", lambda w: seen.append(1))
    service.arm(_wing("A"))
    service.set_dev_enabled(False)
    service.tick(5.0)
    assert seen == []
