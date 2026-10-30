"""The host's combat step answers repeated sensor questions once.

_advance_combat runs inside sensor_detection.step_answers(), so torpedo
guidance and the held-weapon and phaser pumps share one answer per
(observer, target); the block is closed when the step returns. The
memo itself: tests/unit/test_sensor_step_answers.py.
"""
from engine.appc import sensor_detection as sd


def test_the_combat_step_answers_guidance_and_the_weapon_pumps(monkeypatch):
    from engine import host_loop
    from engine.appc import projectiles
    active = {}

    def spy(name, real):
        def wrapped(*a, **k):
            active[name] = sd._step_answers is not None
            return real(*a, **k)
        return wrapped
    monkeypatch.setattr(projectiles, "update_all",
                        spy("guidance", projectiles.update_all))
    monkeypatch.setattr(host_loop, "_pump_held_weapons",
                        spy("held", host_loop._pump_held_weapons))
    host_loop._advance_combat([], 1.0 / 60.0, push_render_data=False)
    assert active == {"guidance": True, "held": True}
    assert sd._step_answers is None
