"""_advance_combat must refresh deform eligibility once per tick, with the
tick's ship list, BEFORE hits are processed. Collaborators are stubbed so the
test exercises only the eligibility seam."""
import engine.host_loop as host_loop
from engine.appc import deform_eligibility as de
from engine.appc import projectiles, hit_vfx, particles, ship_death
from engine.appc import subsystem_emitters, camera_shake


class _Ship:
    def GetPhaserSystem(self):
        return None  # skip the phaser damage loop


def test_advance_combat_updates_eligibility(monkeypatch):
    calls = []
    monkeypatch.setattr(de, "update", lambda ships: calls.append(list(ships)))

    # Stub everything else _advance_combat touches so an empty/None world is safe.
    monkeypatch.setattr(projectiles, "update_all", lambda *a, **k: [])
    monkeypatch.setattr(hit_vfx, "update_ages", lambda *a, **k: None)
    monkeypatch.setattr(particles, "advance", lambda *a, **k: None)
    monkeypatch.setattr(ship_death, "advance", lambda *a, **k: None)
    monkeypatch.setattr(subsystem_emitters, "pump", lambda *a, **k: None)
    monkeypatch.setattr(camera_shake, "update", lambda *a, **k: None)
    monkeypatch.setattr(host_loop, "_camera_world_pos", lambda host: None)

    s1, s2 = _Ship(), _Ship()
    host_loop._advance_combat([s1, s2], 0.016, host=None, ship_instances={})

    assert calls == [[s1, s2]]
