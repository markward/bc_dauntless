"""engine.renderer hologram + subsystem-pin wrappers forward to the host module."""
from unittest.mock import MagicMock

import engine.renderer as renderer


def test_set_hologram_ship_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    iid = object()
    renderer.set_hologram_ship(iid, color=(0.1, 0.2, 0.3),
                               opacity_facing=0.1, opacity_grazing=0.6)
    fake.set_hologram_ship.assert_called_once_with(iid, (0.1, 0.2, 0.3),
                                                   0.1, 0.6)


def test_set_hologram_ship_default_color(monkeypatch):
    """Default color and opacities are forwarded correctly."""
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    iid = object()
    renderer.set_hologram_ship(iid)
    fake.set_hologram_ship.assert_called_once_with(iid, (0.30, 0.62, 1.0),
                                                   0.20, 0.70)


def test_set_hologram_ship_coerces_list_color(monkeypatch):
    """A list color is coerced to a tuple before forwarding."""
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    iid = object()
    renderer.set_hologram_ship(iid, color=[0.5, 0.5, 0.5])
    args = fake.set_hologram_ship.call_args[0]
    assert isinstance(args[1], tuple)


def test_clear_hologram_ship_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.clear_hologram_ship()
    fake.clear_hologram_ship.assert_called_once_with()


def test_set_subsystem_pins_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    pins = [((1.0, 2.0, 3.0), 0, True), ((4.0, 5.0, 6.0), 1, False)]
    renderer.set_subsystem_pins(pins)
    fake.set_subsystem_pins.assert_called_once_with(pins)


def test_clear_subsystem_pins_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.clear_subsystem_pins()
    fake.clear_subsystem_pins.assert_called_once_with()
