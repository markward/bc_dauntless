"""The host's combat step answers repeated sensor questions once.

_advance_combat runs inside an engine.core.step_memo block, so torpedo
guidance and the held-weapon and phaser pumps share one answer per
(observer, target) and per mount; the block is closed when the step
returns. The memos: tests/unit/test_sensor_step_answers.py and
tests/unit/test_mount_position_step_answers.py.
"""
from engine.core import step_memo


def test_the_combat_step_answers_guidance_and_the_weapon_pumps(monkeypatch):
    from engine import host_loop
    from engine.appc import projectiles
    active = {}

    def spy(name, real):
        def wrapped(*a, **k):
            active[name] = step_memo.active()
            return real(*a, **k)
        return wrapped
    monkeypatch.setattr(projectiles, "update_all",
                        spy("guidance", projectiles.update_all))
    monkeypatch.setattr(host_loop, "_pump_held_weapons",
                        spy("held", host_loop._pump_held_weapons))
    host_loop._advance_combat([], 1.0 / 60.0, push_render_data=False)
    assert active == {"guidance": True, "held": True}
    assert not step_memo.active()
