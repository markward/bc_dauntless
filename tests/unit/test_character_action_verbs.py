from engine import bridge_character_anim
from engine.appc import bridge_placement
from engine.appc.characters import CharacterClass


def _character_with(key, module_path, location="DBTactical"):
    ch = CharacterClass("body.nif", "head.nif")
    ch.SetLocation(location)
    ch.AddAnimation(key, module_path)
    return ch


def test_registered_module_path_uses_the_literal_key():
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    # literal — NOT prefixed with the location
    assert bridge_placement.registered_module_path(ch, "PushingButtons") == \
        "Some.Module.DBTConsoleInteraction"
    assert bridge_placement.registered_module_path(ch, "DBTacticalPushingButtons") is None


def test_push_buttons_misspelling_is_aliased():
    # BC ships a bug: MissionLib.PushButtons and 40 other sites ask for
    # "PushButtons", but all 14 character registrations spell it "PushingButtons", so those
    # calls are silent no-ops in the original. We deliberately FIX the typo.
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    assert bridge_placement.registered_module_path(ch, "PushButtons") == \
        "Some.Module.DBTConsoleInteraction"


def test_unregistered_key_resolves_to_none():
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    assert bridge_placement.registered_module_path(ch, "Nonexistent") is None
    assert bridge_placement.resolve_builder(ch, "Nonexistent") is None


def test_scripted_priority_outranks_idle_and_reactions():
    assert bridge_character_anim._SCRIPTED > bridge_character_anim._REACTION
    assert bridge_character_anim._SCRIPTED > bridge_character_anim._IDLE


def test_request_default_clears_the_active_action():
    ctrl = bridge_character_anim.BridgeCharacterAnimController()
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    # submit() keys off the render-instance id and refuses a hidden character
    # (bridge_character_anim.py:70-73), so a bare CharacterClass would be dropped.
    ch._render_instance = 7
    ch.SetHidden(0)
    assert ctrl.submit(ch, [("some/clip.nif", 1.0)],
                       priority=bridge_character_anim._SCRIPTED) is True
    assert ctrl.is_busy(ch) is True
    ctrl.request_default(ch)
    assert ctrl.is_busy(ch) is False
