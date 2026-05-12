"""Emission recording for shuttle / probe / decoy launches.

When enabled, captures launch events including emitter location, forward/up
directions, and metadata. Off by default; tests and the harness opt in.
"""
import App


def _reset_recorder():
    App._emission_recorder.disable()
    App._emission_recorder.reset_mission()
    App._emission_recorder.clear()


def test_recorder_disabled_by_default():
    _reset_recorder()
    assert App._emission_recorder.is_enabled() is False


def test_record_is_noop_when_disabled():
    _reset_recorder()
    from engine.appc.math import TGPoint3
    p = TGPoint3(1.0, 2.0, 3.0)
    fwd = TGPoint3(0.0, 1.0, 0.0)
    up = TGPoint3(0.0, 0.0, 1.0)
    App._emission_recorder.record(123, "Shuttle Bay", 1, p, fwd, up)
    assert App._emission_recorder.events() == []


def test_record_when_enabled_captures_event():
    _reset_recorder()
    App._emission_recorder.enable()
    App._emission_recorder.set_mission("mission.M1")
    from engine.appc.math import TGPoint3
    p = TGPoint3(1.0, 2.0, 3.0)
    fwd = TGPoint3(0.0, 1.0, 0.0)
    up = TGPoint3(0.0, 0.0, 1.0)
    App._emission_recorder.record(123, "Shuttle Bay", 1, p, fwd, up)
    events = App._emission_recorder.events()
    assert len(events) == 1
    e = events[0]
    assert e["mission"] == "mission.M1"
    assert e["ship_id"] == 123
    assert e["emitter_name"] == "Shuttle Bay"
    assert e["emitter_type"] == 1
    assert e["world_position"] == (1.0, 2.0, 3.0)
    assert e["world_forward"] == (0.0, 1.0, 0.0)
    assert e["world_up"] == (0.0, 0.0, 1.0)
    _reset_recorder()


def test_events_returns_a_copy():
    _reset_recorder()
    App._emission_recorder.enable()
    from engine.appc.math import TGPoint3
    App._emission_recorder.record(1, "n", 1, TGPoint3(), TGPoint3(), TGPoint3())
    snapshot = App._emission_recorder.events()
    App._emission_recorder.record(2, "n2", 2, TGPoint3(), TGPoint3(), TGPoint3())
    # Original snapshot must not have grown
    assert len(snapshot) == 1
    _reset_recorder()


def test_clear_empties_events():
    _reset_recorder()
    App._emission_recorder.enable()
    from engine.appc.math import TGPoint3
    App._emission_recorder.record(1, "n", 1, TGPoint3(), TGPoint3(), TGPoint3())
    assert len(App._emission_recorder.events()) == 1
    App._emission_recorder.clear()
    assert App._emission_recorder.events() == []
    _reset_recorder()
