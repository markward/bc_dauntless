from engine.appc import passive_state as ps


class Obj:
    x = ps.WakeField()

    def __init__(self):
        self.wakes = 0

    def _passive_on_wake(self):
        self.wakes += 1


def test_configure_reads_the_switches():
    ps.configure({})
    assert ps.enabled() and not ps.audit_enabled()
    ps.configure({"DAUNTLESS_PASSIVE_STATE": "0", "DAUNTLESS_PASSIVE_AUDIT": "1"})
    assert not ps.enabled() and ps.audit_enabled()


def test_wakefield_write_wakes_a_sleeper_and_reads_stay_plain():
    o = Obj()
    o.x = 1
    assert o.wakes == 0
    ps.put_to_sleep(o)
    assert ps.is_asleep(o)
    o.x = 1
    assert not ps.is_asleep(o)
    assert o.wakes == 1
    assert not hasattr(type(o).__dict__["x"], "__get__")
    assert o.__dict__["x"] == 1 and o.x == 1
    assert ps.counts() == {"slept": 1, "woke": 1}


def test_audit_records_a_changing_step_and_restores_in_place():
    o = Obj()
    o.v = [1, 2]
    keep = o.v
    ps.audit_step(o, lambda: None)
    assert ps.audit_failures() == []
    ps.audit_step(o, lambda: o.v.append(3))
    assert ps.audit_failures() == [("Obj", "v")]
    assert o.v == [1, 2]
    assert o.v is keep


def test_game_loop_configures_on_construction(monkeypatch):
    from engine.core.loop import GameLoop
    monkeypatch.setenv("DAUNTLESS_PASSIVE_STATE", "0")
    GameLoop()
    assert not ps.enabled()
