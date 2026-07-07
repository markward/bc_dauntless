"""Dev-mode [cloak] transition prints (print(), not logging — the host has no
logging handler). Off in production."""
from engine import dev_mode
from engine.appc.subsystems import CloakingSubsystem
from engine.appc.ships import ShipClass


def _cloak_on_ship(name="Warbird 1"):
    ship = ShipClass()
    ship.SetName(name)
    cloak = CloakingSubsystem("Cloaking Device")
    ship.SetCloakingSubsystem(cloak)   # _attach_subsystem sets _parent_ship
    return ship, cloak


def test_cloak_prints_when_dev_mode_on(monkeypatch, capsys):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    ship, cloak = _cloak_on_ship()
    cloak.StartCloaking()
    out = capsys.readouterr().out
    assert "[cloak]" in out
    assert "Warbird 1" in out
    assert "cloaking" in out


def test_decloak_prints_when_dev_mode_on(monkeypatch, capsys):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    ship, cloak = _cloak_on_ship()
    cloak.InstantCloak()               # -> CLOAKED so StopCloaking is not a no-op
    capsys.readouterr()                # drain
    cloak.StopCloaking()
    out = capsys.readouterr().out
    assert "[cloak]" in out
    assert "decloaking" in out


def test_cloak_silent_when_dev_mode_off(monkeypatch, capsys):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    ship, cloak = _cloak_on_ship()
    cloak.StartCloaking()
    out = capsys.readouterr().out
    assert "[cloak]" not in out
