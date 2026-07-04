"""InputMap — action → physical-key map with conflict checks and persistence.

The Controls remap UI edits this; _PlayerControl and the fire/function pollers
read their keys from it.  Remapping happens at the physical-key layer (which GLFW
key drives each action), so the BC WC→ET binding table is never touched.
"""
import pytest

from engine.appc.config_mapping import TGConfigMapping
from engine.input_map import (
    InputMap, GLFW_KEYS, RESERVED, ACTIONS, ACTION_IDS,
)


def test_defaults_present_and_resolvable():
    im = InputMap()
    assert set(ACTION_IDS) == {a[0] for a in ACTIONS}
    for aid, _label, _cat, default in ACTIONS:
        assert im.name(aid) == default
        # Every default key resolves to a real GLFW code.
        assert im.code(aid) == GLFW_KEYS[default]
    # Stock weapon/flight keys.
    assert im.name("fire_primary") == "F"
    assert im.code("fire_primary") == GLFW_KEYS["F"]
    assert im.name("pitch_down") == "W"


def test_set_changes_binding():
    im = InputMap()
    im.set("fire_primary", "J")
    assert im.name("fire_primary") == "J"
    assert im.code("fire_primary") == GLFW_KEYS["J"]


def test_set_rejects_unknown():
    im = InputMap()
    with pytest.raises(ValueError):
        im.set("fire_primary", "NOPE")       # not a bindable key
    with pytest.raises(KeyError):
        im.set("not_an_action", "J")


def test_action_for_detects_conflict():
    im = InputMap()
    # F is the stock primary-fire key.
    assert im.action_for("F") == "fire_primary"
    # An unbound key has no owner.
    assert im.action_for("J") is None
    im.set("fire_secondary", "J")
    assert im.action_for("J") == "fire_secondary"


def test_reserved_keys_not_bindable():
    # Reserved display names are deliberately absent from the bindable universe.
    for name in RESERVED:
        assert name not in GLFW_KEYS


def test_reset_restores_defaults():
    im = InputMap()
    im.set("fire_primary", "J")
    im.set("pitch_down", "U")
    im.reset()
    assert im.name("fire_primary") == "F"
    assert im.name("pitch_down") == "W"


def test_save_load_round_trip(tmp_path):
    path = str(tmp_path / "Keybindings.cfg")
    cfg = TGConfigMapping()
    im = InputMap(config_mapping=cfg, filename=path)
    im.set("fire_primary", "J")
    im.set("camera_cycle", "B")
    assert im.save() == 1

    cfg2 = TGConfigMapping()
    im2 = InputMap(config_mapping=cfg2, filename=path)
    im2.load()
    assert im2.name("fire_primary") == "J"
    assert im2.name("camera_cycle") == "B"
    # Untouched actions keep their defaults.
    assert im2.name("pitch_down") == "W"


def test_load_unknown_value_falls_back(tmp_path):
    path = str(tmp_path / "Keybindings.cfg")
    cfg = TGConfigMapping()
    cfg.SetStringValue("Controls", "fire_primary", "BOGUS")
    cfg.SaveConfigFile(path)
    im = InputMap(config_mapping=TGConfigMapping(), filename=path)
    im.load()
    assert im.name("fire_primary") == "F"   # bad value → default


def test_load_missing_file_uses_defaults(tmp_path):
    path = str(tmp_path / "does_not_exist.cfg")
    im = InputMap(config_mapping=TGConfigMapping(), filename=path)
    im.load()
    assert im.name("fire_primary") == "F"


def test_skip_dialogue_default_backspace():
    im = InputMap()
    assert im.name("skip_dialogue") == "Backspace"
    assert im.code("skip_dialogue") == GLFW_KEYS["Backspace"]
