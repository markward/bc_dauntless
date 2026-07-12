"""ET_CHARACTER_ANIMATION_DONE applies the carried character state.

Every SDK move builder ends with one, e.g. PicardAnimations.MoveFromPToL1:

    pEvent = App.TGIntEvent_Create()   # "Add event to hide character after it
    pEvent.SetEventType(App.ET_CHARACTER_ANIMATION_DONE)   #  gets into the turbolift"
    pEvent.SetDestination(pCharacter)
    pEvent.SetInt(App.CharacterClass.CS_HIDDEN)
    pSequence.AddCompletedEvent(pEvent)

BC's native engine consumes it and applies the state. Without it a walking-off
officer never hides.
"""
import App
from engine.appc.characters import CharacterClass


def _event(character, state):
    ev = App.TGIntEvent_Create()
    ev.SetEventType(App.ET_CHARACTER_ANIMATION_DONE)
    ev.SetDestination(character)
    ev.SetInt(state)
    return ev


def test_cs_hidden_hides_the_character():
    ch = CharacterClass()
    ch.SetHidden(0)
    ch.ProcessEvent(_event(ch, CharacterClass.CS_HIDDEN))
    assert ch.IsHidden() == 1


def test_cs_standing_reveals_and_stands():
    ch = CharacterClass()
    ch.SetHidden(1)
    ch.ProcessEvent(_event(ch, CharacterClass.CS_STANDING))
    assert ch.IsHidden() == 0
    assert ch.IsStanding() == 1


def test_cs_seated_reveals_and_seats():
    ch = CharacterClass()
    ch.SetHidden(1)
    ch.ProcessEvent(_event(ch, CharacterClass.CS_SEATED))
    assert ch.IsHidden() == 0
    assert ch.IsStanding() == 0


def test_the_constant_is_a_real_int_not_a_stub():
    """An undefined App constant collapses to a _NamedStub whose int() is 0, which
    would silently alias every other event type. Guard against that."""
    assert isinstance(App.ET_CHARACTER_ANIMATION_DONE, int)
    assert App.ET_CHARACTER_ANIMATION_DONE != 0
